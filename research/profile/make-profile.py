"""Turn read-only generic probe captures into this machine's local profile.

Offline only: reads the DIAGnn.TXT logs, IMGnn.BIN driver dumps and PROM.BIN
that a GU_PROBE_GENERIC probe wrote, and runs fwsec-locate (the production
VBIOS parser built for the host) on that PROM. Writes, never for commit:

  internal-boot/unlock/profile-local.h   constants for -DGU_PROFILE_LOCAL
  research/profile/local/profile.json    what was derived, and from which files
  research/profile/local/fixtures/       host-test fixtures (probe/, cold/, console/, PROM.BIN)

Driver roles come from the capture's own ownership graph, mirroring what
prepare-console.c / full-release.c check at boot:

  OutAgent  opens SimpleTextOut BY_DRIVER on the RTX GOP handle
  GfxAgent  opens GOP           BY_DRIVER on the RTX GOP handle
  EdidAgent opens EdidDiscovered BY_DRIVER on the RTX GOP handle (AMI mouse/EDID file)
  NvAgent   opens PciIo         BY_DRIVER on the RTX PCI handle (nvgop-ga1xx)

Anything outside research/profile/proven.json, or any disagreement between
captures, is refused: there is no override. Widening the envelope is a
reviewed change backed by hardware evidence (docs/NEW-MACHINE.en.md).

Usage: python -I make-profile.py CAPTURE_DIR FWSEC_LOCATE_EXE
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import uuid
from pathlib import Path

GENERATOR_VERSION = 1
REPO = Path(__file__).resolve().parents[2]
TEXT_OUT = '387477c2-69c7-11d2-8e39-00a0c969723b'
GOP = '9042a9de-23dc-4a38-96fb-7aded080516a'
EDID_DISCOVERED = '1c0c34f6-d380-41fa-a049-8ad06c1a66aa'
PCI_IO = '4cf5b200-68b8-4ca5-9eec-b23e3f50029a'
BY_DRIVER = 0x10
OUT_FILE = '628a497d-2bf6-4264-8741-069dbd3399d6'
GFX_FILE = '43e7abdd-e352-4cfb-a230-4cdc1d350e5c'
MOUSE_FILE = 'c7a7030c-c3d8-45ee-bed9-5d9e76762953'
NVGOP_NAME = 'nvgop-ga1xx'
# full-release.c Profile(): hashed code ranges start at these RVAs.
EDID_TEXT_RVA = 0x1000
NVGOP_TEXT_RVA = 0x280
EFI_BOOT_SERVICES_CODE = 3
EFI_RUNTIME_SERVICES_CODE = 5
# app.c ColdCheck / full-release.c ColdRead registers.
COLD = [0x0, 0x823804, 0x118128, 0x118234, 0x110100, 0x1fa828, 0x82381c, 0x823820, 0x1183a4]
# Test expected-image buffer in test_efi_transaction.c.
FWSEC_IMAGE_MAX = 0x10000


class Refused(ValueError):
    pass


def fail(message):
    raise Refused(message)


def node_file(nodes):
    """Return ('guid', str) for a PIWG firmware-file node, ('name', str) for a file path."""
    if len(nodes) != 2 or nodes[1] != b'\x7f\xff\x04\x00':
        return None
    node = nodes[0]
    if node[0] == 4 and node[1] == 6 and len(node) == 20:
        return ('guid', str(uuid.UUID(bytes_le=node[4:20])))
    if node[0] == 4 and node[1] == 4:
        return ('name', node[4:].decode('utf-16-le').rstrip('\0'))
    return None


def parse_bindings(lines):
    out = []
    pattern = re.compile(r'binding handle=0x([0-9a-f]+) image=0x([0-9a-f]+) version=0x([0-9a-f]+) stop=0x([0-9a-f]+)$')
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        rec = {'handle': int(m[1], 16), 'image': int(m[2], 16), 'version': int(m[3], 16), 'stop': int(m[4], 16), 'nodes': []}
        for follow in lines[i + 1:]:
            if follow.startswith('binding handle=') or follow.startswith('handles status='):
                break
            for key in ('base', 'size', 'code-type'):
                v = re.match(rf'img {key}=0x([0-9a-f]+)$', follow)
                if v:
                    rec[key] = int(v[1], 16)
            v = re.match(r'img-path-node raw=([0-9a-f]+)$', follow)
            if v:
                rec['nodes'].append(bytes.fromhex(v[1]))
            v = re.match(r'img dump index=([0-9a-f]+)$', follow)
            if v:
                rec['dump'] = int(v[1], 16)
        rec['file'] = node_file(rec['nodes'])
        out.append(rec)
    return out


def parse_handles(text):
    blocks = {}
    for m in re.finditer(r'^handle id=0x([0-9a-f]+)\n(.*?)(?=^handle id=|^capture-complete=|\Z)', text, re.M | re.S):
        h = int(m[1], 16)
        if h in blocks:
            fail(f'duplicate handle record {h:#x}')
        edges, protocols, protocol = [], set(), None
        for line in m[2].splitlines():
            if line.startswith('protocol guid='):
                protocol = line.removeprefix('protocol guid=')
                protocols.add(protocol)
            e = re.fullmatch(r'open agent=0x([0-9a-f]+) controller=0x([0-9a-f]+) attributes=0x([0-9a-f]+) count=0x([0-9a-f]+)', line)
            if e:
                edges.append((protocol, int(e[1], 16), int(e[2], 16), int(e[3], 16), int(e[4], 16)))
        blocks[h] = {'raw': m[2], 'edges': edges, 'protocols': protocols}
    return blocks


def path_of(block):
    rows = re.findall(r'^path-node raw=([0-9a-f]+)$', block, re.M)
    return b''.join(bytes.fromhex(r) for r in rows) if rows else None


def pci_config(block):
    m = re.search(r'^pci config-dwords=([^\n]+)$', block, re.M)
    return [int(w, 16) for w in m[1].split()] if m else None


def sole_driver(blocks, handle, protocol):
    agents = [a for p, a, c, attrs, n in blocks[handle]['edges'] if p == protocol and attrs == BY_DRIVER and c == handle]
    if len(agents) != 1:
        fail(f'expected one BY_DRIVER opener of {protocol} on {handle:#x}, found {len(agents)}')
    return agents[0]


def binding_for(bindings, agent):
    recs = [b for b in bindings if b['handle'] == agent]
    if len(recs) != 1:
        fail(f'expected one binding record for agent {agent:#x}, found {len(recs)}')
    b = recs[0]
    if 'base' not in b or 'size' not in b or not b['base'] <= b['stop'] < b['base'] + b['size']:
        fail(f'binding {agent:#x} stop is outside its image')
    return b


def pe_sections(image):
    off = struct.unpack_from('<I', image, 0x3c)[0]
    if image[off:off + 4] != b'PE\0\0':
        fail('no PE header in dump')
    count, opt_size = struct.unpack_from('<H', image, off + 6)[0], struct.unpack_from('<H', image, off + 20)[0]
    opt = off + 24
    if struct.unpack_from('<H', image, opt)[0] != 0x20b:
        fail('dump is not PE32+')
    reloc_rva, reloc_size = struct.unpack_from('<II', image, opt + 112 + 5 * 8)
    table = opt + opt_size
    sections = []
    for i in range(count):
        name, vsize, rva = struct.unpack_from('<8sII', image, table + 40 * i)
        sections.append((name.rstrip(b'\0').decode('ascii', 'replace'), rva, vsize))
    return sections, reloc_rva, reloc_size


def relocations(image, rva, size):
    out, at, end = [], rva, rva + size
    while at < end:
        page, block = struct.unpack_from('<II', image, at)
        if block < 8:
            break
        for k in range(8, block, 2):
            entry = struct.unpack_from('<H', image, at + k)[0]
            if entry >> 12:
                out.append(page + (entry & 0xfff))
        at += block
    return out


def code_hash(image_dir, rec, rva):
    if 'dump' not in rec:
        fail(f'binding {rec["handle"]:#x} has no image dump')
    dump = image_dir / f'IMG{rec["dump"]:02d}.BIN'
    image = dump.read_bytes()
    if len(image) != rec['size']:
        fail(f'{dump.name} is {len(image):#x} bytes, image size is {rec["size"]:#x}')
    sections, reloc_rva, reloc_size = pe_sections(image)
    text = [s for s in sections if s[1] == rva]
    if len(text) != 1:
        fail(f'{dump.name}: no section at expected code RVA {rva:#x}: {sections}')
    name, start, length = text[0]
    inside = [r for r in relocations(image, reloc_rva, reloc_size) if start <= r < start + length]
    if inside:
        fail(f'{dump.name}: {len(inside)} relocations inside {name}; loaded-code hash would vary by load address')
    return {'dump': dump.name, 'bytes': length, 'sha256': hashlib.sha256(image[start:start + length]).hexdigest()}


def gu_hex(v):
    """GuFormat %#x."""
    return '0' if v == 0 else f'{v:#x}'


def analyze(diag, image_dir, envelope):
    """Everything one capture yields. image_dir=None skips the driver code hashes."""
    raw = diag.read_bytes()
    text = raw.decode('utf-8-sig').replace('\r\n', '\n')
    if text.count('capture-complete=1\n') != 1 or 'diagnostic-result status=0x0000000000000000' not in text:
        fail(f'{diag.name}: need exactly one complete, successful capture')
    if text.count('\nprobe-target ') != 1 or 'probe targets=0001\n' not in text:
        fail(f'{diag.name}: need exactly one NVIDIA display controller (single-RTX topology only)')
    target = re.search(r'^probe-target seg=0x([0-9a-f]+) bus=0x([0-9a-f]+) dev=0x([0-9a-f]+) fun=0x([0-9a-f]+)$', text, re.M)
    if not target or [int(x, 16) for x in target.groups()] != [0, 1, 0, 0]:
        fail(f'{diag.name}: the RTX must be 0000:01:00.0 (checks.c GuCheckConfig)')
    rows = re.findall(r'^cfg dwords=([0-9a-f ]+)$', text, re.M)
    words = rows[0].split() if len(rows) == 1 else []
    if len(words) != 64:
        fail(f'{diag.name}: expected one 64-dword probe config snapshot')
    cfg = [int(w, 16) for w in words]
    board, subsystem = cfg[0], cfg[11]
    if cfg[2] != int(envelope['class_revision'], 16):
        fail(f'class/revision {cfg[2]:08x} is not the proven {envelope["class_revision"]}')
    if not cfg[1] & 2 or cfg[1] & 4:
        fail('RTX memory decode must be on and bus mastering off at capture (checks.c)')
    bar0 = cfg[4]
    if bar0 & 0xf or bar0 & 0xffffff or not bar0:
        fail(f'BAR0 {bar0:#x} is not a 16 MiB aligned 32-bit non-prefetchable window')

    mmio = {int(o, 16): int(v, 16) for o, v in
            re.findall(r'^mmio off=0x([0-9a-f]+) status=0x0+ value=0x([0-9a-f]+)$', text, re.M)}
    if any(o not in mmio for o in COLD):
        fail(f'{diag.name}: missing a cold-state register read')
    chip, plm, g1, g2, g3, wpr2, ss0, ss1, memory = (mmio[o] for o in COLD)
    proven = [c for c in envelope['chips'] if int(c['chip'], 16) == chip]
    if len(proven) != 1:
        fail(f'chip {chip:#010x} has no hardware-proven profile')
    if memory not in [int(m, 16) for m in proven[0]['memory']]:
        fail(f'{proven[0]["family"]} with {memory:#x} MiB is not hardware-proven')
    # full-release.c ColdRead: power-on state; the unlock never runs from anything else.
    if (g1, g2, g3, wpr2, plm) != (0x8b8f, 0x3ff, 0x10, 0, 0xffffff8f) or ss1 > 15 or \
            ss0 in (0xffffffff, 0x88888888) or ss0 & 0xffff0000 == 0xbadf0000:
        fail(f'{diag.name}: GPU was not in its power-on state; capture after a full shutdown')
    prom = re.search(r'^prom sha256=([0-9a-f]{64})$', text, re.M)
    if not prom:
        fail(f'{diag.name}: no PROM hash')

    lines = text.split('\n')
    bindings = parse_bindings(lines)
    blocks = parse_handles(text)
    nvidia = [h for h, b in blocks.items() if (c := pci_config(b['raw'])) and c[0] & 0xffff == 0x10de and c[2] >> 24 == 3]
    if len(nvidia) != 1 or pci_config(blocks[nvidia[0]]['raw'])[0] != board:
        fail('the graph must hold exactly one NVIDIA display controller, the probe target')
    rtx_pci = nvidia[0]
    if pci_config(blocks[rtx_pci]['raw'])[11] != subsystem:
        fail('graph and probe disagree on the RTX subsystem')
    other = [h for h, b in blocks.items() if (c := pci_config(b['raw'])) and c[0] & 0xffff != 0x10de and c[2] >> 24 == 3]
    if len(other) != 1:
        fail(f'expected one non-NVIDIA display controller (integrated GPU), found {len(other)}; '
             'the reviewed single-RTX console replay has no design without one')
    igpu = pci_config(blocks[other[0]]['raw'])[0]
    pci_path = path_of(blocks[rtx_pci]['raw'])
    if not pci_path:
        fail('RTX PCI handle has no device path')
    pci_path = pci_path[:-4]
    gops = [h for h, b in blocks.items() if GOP in b['protocols'] and (path_of(b['raw']) or b'').startswith(pci_path)]
    if len(gops) != 1:
        fail(f'expected one RTX GOP child, found {len(gops)}')
    rtx = gops[0]
    rtx_path = path_of(blocks[rtx]['raw'])
    # ACPI PNP0A03 UID 0 / Pci(root port) / Pci(0,0) / ACPI ADR / End: 36 bytes.
    if len(rtx_path) != 36 or rtx_path[0:12] != bytes.fromhex('02010c00d041030a00000000') or \
            rtx_path[12:16] != b'\x01\x01\x06\x00' or rtx_path[18:24] != bytes.fromhex('010106000000') or \
            rtx_path[24:28] != b'\x02\x03\x08\x00' or rtx_path[32:36] != b'\x7f\xff\x04\x00':
        fail('RTX GOP path is not PciRoot(0)/root port/Pci(0,0)/ADR; other topologies are unreviewed')
    root_function, root_device = rtx_path[16], rtx_path[17]
    fb = re.search(r'^gop framebuffer=0x([0-9a-f]+) ', blocks[rtx]['raw'], re.M)
    if not fb:
        fail('RTX GOP has no framebuffer record')
    # Non-aggregate console: ConOut names the RTX GOP itself, not a splitter or a second device.
    conout = re.search(r'^variable name=ConOut .*\n((?:(?!variable name=).*\n)*)', text, re.M)
    rows = re.findall(r'^path-node raw=([0-9a-f]+)$', conout[1], re.M) if conout else []
    if b''.join(bytes.fromhex(r) for r in rows) != rtx_path:
        fail('ConOut is not exactly the RTX GOP path; aggregate or multi-device consoles are not generated')

    roles = {
        'out': binding_for(bindings, sole_driver(blocks, rtx, TEXT_OUT)),
        'gfx': binding_for(bindings, sole_driver(blocks, rtx, GOP)),
        'edid': binding_for(bindings, sole_driver(blocks, rtx, EDID_DISCOVERED)),
        'nvgop': binding_for(bindings, sole_driver(blocks, rtx_pci, PCI_IO)),
    }
    expect = {'out': ('guid', OUT_FILE), 'gfx': ('guid', GFX_FILE), 'edid': ('guid', MOUSE_FILE), 'nvgop': ('name', NVGOP_NAME)}
    for role, rec in roles.items():
        if rec['file'] != expect[role]:
            fail(f'{role}: image file {rec["file"]} is not the reviewed AMI/NVIDIA driver {expect[role]}')
    for role in ('out', 'gfx'):
        if roles[role]['code-type'] != EFI_BOOT_SERVICES_CODE:
            fail(f'{role}: not boot-services code')
    edid, nv = roles['edid'], roles['nvgop']
    if edid['image'] != edid['handle'] or edid['version'] != 1 or edid['code-type'] != EFI_RUNTIME_SERVICES_CODE:
        fail('EDID driver does not match full-release.c Profile(mouse) shape')
    if nv['image'] != nv['handle'] or nv['code-type'] != EFI_BOOT_SERVICES_CODE:
        fail('nvgop driver does not match full-release.c Profile() shape')

    off = lambda r: r['stop'] - r['base']
    defines = [
        ('GU_BOARD_ID', f'0x{board:08x}U'),
        ('GU_BOARD_SUBSYSTEM', f'0x{subsystem:08x}U'),
        ('GU_BAR0_BASE', f'0x{bar0:08x}ULL'),
        ('GU_BAR0_END', f'0x{bar0 + 0xffffff:08x}ULL'),
        ('GU_DEVICE_MEMORY_SIZE', f'0x{memory:x}U'),
        ('GU_CHIP_ID', f'0x{chip:08x}U'),
        ('GU_PROM_SHA256', f'"{prom[1]}"'),
        ('GU_ROOT_PORT_DEVICE', f'{root_device}U'),
        ('GU_ROOT_PORT_FUNCTION', f'{root_function}U'),
        ('GU_RTX_PATH_BYTES', '\\\n  ' + ','.join(str(b) for b in rtx_path)),
        ('GU_CONSOLE_TEXT_SIZE', f'0x{roles["out"]["size"]:x}U'),
        ('GU_CONSOLE_TEXT_STOP', f'0x{off(roles["out"]):x}U'),
        ('GU_CONSOLE_TEXT_VERSION', f'0x{roles["out"]["version"]:x}U'),
        ('GU_CONSOLE_GFX_SIZE', f'0x{roles["gfx"]["size"]:x}U'),
        ('GU_CONSOLE_GFX_STOP', f'0x{off(roles["gfx"]):x}U'),
        ('GU_CONSOLE_GFX_VERSION', f'0x{roles["gfx"]["version"]:x}U'),
        ('GU_EDID_IMAGE_SIZE', f'0x{edid["size"]:x}U'),
        ('GU_EDID_STOP', f'0x{off(edid):x}U'),
        ('GU_NVGOP_VERSION', f'0x{nv["version"]:x}U'),
        ('GU_NVGOP_IMAGE_SIZE', f'0x{nv["size"]:x}U'),
        ('GU_NVGOP_STOP', f'0x{off(nv):x}U'),
    ]
    result = {
        'capture': diag.name, 'capture_sha256': hashlib.sha256(raw).hexdigest(),
        'config': words, 'prom_sha256': prom[1], 'igpu_id': f'{igpu:08x}', 'rtx_fb': f'0x{fb[1]}',
        'cold_line': f'cold state: chip={gu_hex(chip)} plm={gu_hex(plm)} gfw={gu_hex(g1)}/{gu_hex(g2)}/{gu_hex(g3)} '
                     f'WPR2_HI={gu_hex(wpr2)} SS0={gu_hex(ss0)} SS1={gu_hex(ss1)}',
        'observed_line': f'cold observed: chip={gu_hex(chip)} memory={gu_hex(memory)} SS0={gu_hex(ss0)} SS1={gu_hex(ss1)}',
        'defines': defines,
    }
    if image_dir is not None:
        edid_code = code_hash(image_dir, edid, EDID_TEXT_RVA)
        nv_code = code_hash(image_dir, nv, NVGOP_TEXT_RVA)
        known = [g for g in envelope['nvgop'] if int(g['version'], 16) == nv['version'] and g['text_sha256'] == nv_code['sha256']]
        if len(known) != 1:
            fail(f'nvgop {nv["version"]:#x} with .text {nv_code["sha256"][:16]}... has not released cleanly on proven hardware')
        result['code'] = {'edid': edid_code, 'nvgop': nv_code}
        defines += [
            ('GU_EDID_TEXT_BYTES', f'0x{edid_code["bytes"]:x}U'),
            ('GU_EDID_TEXT_SHA256', f'"{edid_code["sha256"]}"'),
            ('GU_NVGOP_TEXT_BYTES', f'0x{nv_code["bytes"]:x}U'),
            ('GU_NVGOP_TEXT_SHA256', f'"{nv_code["sha256"]}"'),
        ]
    return result


def locate_fwsec(locator, prom_path, prom_bytes):
    """Run the production VBIOS parser (fwsec-locate) on exactly these PROM bytes."""
    done = subprocess.run([str(locator), str(prom_path)], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        fail(f'FWSEC-FRTS not found in PROM.BIN: {done.stderr.strip()}')
    if hashlib.sha256(prom_path.read_bytes()).digest() != hashlib.sha256(prom_bytes).digest():
        fail('PROM.BIN changed while it was parsed')
    fw = json.loads(done.stdout)
    if not 0 < fw['image_size'] <= FWSEC_IMAGE_MAX or fw['image_off'] + fw['image_size'] > len(prom_bytes):
        fail(f'FWSEC-FRTS image {fw["image_off"]:#x}+{fw["image_size"]:#x} is outside the tested bounds')
    return fw


def generate(capture_dir, locator, envelope):
    """Validate captures; return (header text, profile.json dict, fixture files {relative path: bytes})."""
    capture_dir = Path(capture_dir)
    diags = sorted(capture_dir.glob('DIAG[0-9][0-9].TXT'))
    if len(diags) < envelope['min_captures']:
        fail(f'need at least {envelope["min_captures"]} probe captures from separate full shutdowns, found {len(diags)}')
    latest = analyze(diags[-1], capture_dir, envelope)
    for earlier in diags[:-1]:
        other = analyze(earlier, None, envelope)
        mine = dict(latest['defines'])
        for name, value in other['defines']:
            if mine[name] != value:
                fail(f'{earlier.name} and {diags[-1].name} disagree on {name}; values must not vary between boots')
        if other['config'] != latest['config']:
            fail(f'{earlier.name} and {diags[-1].name} disagree on the RTX PCI config space')
    prom_path = capture_dir / 'PROM.BIN'
    prom = prom_path.read_bytes()
    if len(prom) != 0x100000 or hashlib.sha256(prom).hexdigest() != latest['prom_sha256']:
        fail('PROM.BIN is not the 1 MiB image the captures hashed')
    fw = locate_fwsec(locator, prom_path, prom)

    board = dict(latest['defines'])['GU_BOARD_ID'][2:10]
    subsystem = dict(latest['defines'])['GU_BOARD_SUBSYSTEM'][2:10]
    name = f'LOCAL-{board}-{subsystem}-{latest["prom_sha256"][:8]}'
    sources = [{'name': d.name, 'sha256': hashlib.sha256(d.read_bytes()).hexdigest()} for d in diags]
    header = [
        '/* GENERATED by research/profile/make-profile.py; local only, never commit.',
        ' * Regenerate from new probe captures instead of editing: build scripts bind',
        ' * write builds to this file\'s exact bytes and its host-test results. */',
        f'#define GU_LOCAL_PROFILE_GENERATOR {GENERATOR_VERSION}',
        f'/* Captures: ' + ', '.join(f'{s["name"]} {s["sha256"][:16]}' for s in sources) + ' */',
        f'#define GU_PROFILE_NAME "{name}"',
    ]
    header += [f'#define {k} {v}' for k, v in latest['defines']]
    header += [
        '/* Host-test pins: this capture\'s authenticated cold line and its PROM\'s FWSEC-FRTS image. */',
        f'#define GU_LOCAL_TEST_COLD_LINE "{latest["cold_line"]}"',
        f'#define GU_LOCAL_FWSEC_IMAGE_OFF 0x{fw["image_off"]:x}U',
        f'#define GU_LOCAL_FWSEC_IMAGE_SIZE 0x{fw["image_size"]:x}U',
    ]
    text = '\n'.join(header) + '\n'
    words = latest['config']
    probe = ''.join(f'config_offset=0x{i * 4:x}\nvalue=0x{w}\n' for i, w in enumerate(words))
    cold = ''.join(f'config[{i * 4:x}]={" ".join(words[i:i + 4])}\n' for i in range(0, 64, 4))
    cold += latest['cold_line'] + '\n' + latest['observed_line'] + '\n'
    fixtures = {'probe/REPORT.TXT': probe.encode(), 'cold/REPORT.TXT': cold.encode(), 'PROM.BIN': prom,
                'console/DIAG.TXT': (capture_dir / latest['capture']).read_bytes()}
    report = {
        'Format': 1, 'GeneratorVersion': GENERATOR_VERSION, 'ProfileName': name,
        'HeaderSha256': hashlib.sha256(text.encode()).hexdigest(), 'PromSha256': latest['prom_sha256'],
        'Captures': sources, 'Replay': {'Capture': latest['capture'], 'RtxId': board, 'IgpuId': latest['igpu_id'], 'RtxFramebuffer': latest['rtx_fb']},
        'Fwsec': fw, 'Code': latest['code'], 'HardwareTested': False,
        'Fixtures': {k: hashlib.sha256(v).hexdigest() for k, v in fixtures.items()},
    }
    return text, report, fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('captures', type=Path, help='folder with DIAGnn.TXT, IMGnn.BIN and PROM.BIN from the probe stick')
    parser.add_argument('locator', type=Path, help='fwsec-locate executable built from research/profile/fwsec-locate.c')
    args = parser.parse_args()
    envelope = json.loads((REPO / 'research/profile/proven.json').read_text())
    try:
        header, report, fixtures = generate(args.captures, args.locator, envelope)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, struct.error, subprocess.SubprocessError) as error:
        parser.exit(2, f'Profile refused: {error}\n')
    local = REPO / 'research/profile/local'
    for rel, data in fixtures.items():
        target = local / 'fixtures' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (local / 'profile.json').write_text(json.dumps(report, indent=2) + '\n', newline='\n')
    # Any earlier test evidence was for other bytes.
    (local / 'test-results.json').unlink(missing_ok=True)
    (REPO / 'internal-boot/unlock/profile-local.h').write_bytes(header.encode())
    print(f'Wrote internal-boot/unlock/profile-local.h ({report["ProfileName"]}, sha256 {report["HeaderSha256"]})')
    print('Not write-eligible until research/profile/test-profile.ps1 passes against it.')


if __name__ == '__main__':
    sys.exit(main())
