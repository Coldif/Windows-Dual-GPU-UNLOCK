"""Offline machine-profile candidates from a read-only probe capture.

GPL-2.0-only. Reads one DIAGnn.TXT written by the GU_DIAGNOSTIC_PROBE build and
the IMGnn.BIN dumps next to it. Prints the values machine-profile.h pins: PCI
identity, BAR0, chip, VRAM, PROM digest, the RTX display path and the driver
fingerprints that prepare-console.c and full-release.c check. No hardware,
firmware variable or boot entry is touched. A candidate is not a reviewed
profile: identical results from several cold boots are still required.

    python research/headless/fingerprint_probe.py --capture X:/RTX3090-UNLOCK/DIAG00.TXT
"""
import argparse
import hashlib
import importlib.util
import json
import re
import struct
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'gu_profile_pe', Path(__file__).resolve().parents[1] / 'profile' / 'make-profile.py')
_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_profile)

# EFI file GUIDs the console release code matches (prepare-console.c / full-release.c).
KNOWN_FILES = {
    "628a497d-2bf6-4264-8741-069dbd3399d6": "console-text (GU_CONSOLE_TEXT_*)",
    "43e7abdd-e352-4cfb-a230-4cdc1d350e5c": "console-gfx (GU_CONSOLE_GFX_*)",
    "c7a7030c-c3d8-45ee-bed9-5d9e76762953": "edid-mouse (GU_EDID_*)",
    "55987e62-1df6-41d1-9062-334fcac3e54d": "gop-combo (GU_COMBO_*)",
}
NVGOP_NAME = "nvgop-ga1xx"
TEXT_RVA = {"nvgop": 0x280, "edid": 0x1000}  # full-release.c Profile()


def guid(raw: bytes) -> str:
    a, b, c = struct.unpack_from("<IHH", raw)
    d = raw[8:16]
    return f"{a:08x}-{b:04x}-{c:04x}-{d[:2].hex()}-{d[2:].hex()}"


def node_value(line: str) -> bytes:
    return bytes.fromhex(line.split("raw=", 1)[1].strip())


def describe_file(nodes):
    for n in nodes:
        if n[0] == 4 and n[1] == 6 and len(n) == 20:  # MEDIA / PIWG firmware file
            g = guid(n[4:20])
            return g, KNOWN_FILES.get(g, "")
        if n[0] == 4 and n[1] == 4:  # MEDIA / file path
            name = n[4:].decode("utf-16-le").rstrip("\0")
            return name, "nvgop (GU_NVGOP_*)" if name == NVGOP_NAME else ""
    return "", ""


def text_section(dump: bytes):
    """Use the same bounded AMD64 loaded-PE policy as local-profile generation."""
    sections, _, _ = _profile.pe_sections(dump)
    text = [s for s in sections if s[0] == ".text"]
    if len(text) != 1 or not text[0][2] or not text[0][3] & 0x20000000:
        raise ValueError("missing, ambiguous or non-executable .text")
    return text[0][1], text[0][2]


def parse(capture: Path):
    with capture.open('rb') as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Capture exceeds the diagnostic format limit')
    text = raw.decode('utf-8-sig').replace('\r\n', '\n')
    lines = text.splitlines()
    out = {"capture": capture.name, "sha256": hashlib.sha256(raw).hexdigest()}
    complete = [line for line in lines if line.startswith('capture-complete=')]
    if len(complete) > 1 or any(line not in ('capture-complete=0', 'capture-complete=1') for line in complete):
        raise ValueError('Ambiguous capture completion markers')
    out['capture_complete'] = complete == ['capture-complete=1']
    out['file_close_verified'] = False
    out['hardware_provenance_verified'] = False
    simple = {
        "subsystem": r"^subsystem=0x([0-9a-f]+)",
        "bar0": r"^probe-bar0 base=0x([0-9a-f]+)",
        "prom_sha256": r"^prom sha256=([0-9a-f]{64})",
        "probe_status": r"^probe status=0x([0-9a-f]+)",
        "result": r"^diagnostic-result status=0x([0-9a-f]+)",
        "gops": r"^gops=([0-9a-f]+)",
    }
    prefixes = {'subsystem': 'subsystem=', 'bar0': 'probe-bar0 ',
                'prom_sha256': 'prom sha256=', 'probe_status': 'probe status=',
                'result': 'diagnostic-result ', 'gops': 'gops='}
    for key, pat in simple.items():
        records = [line for line in lines if line.startswith(prefixes[key])]
        if len(records) > 1:
            raise ValueError('Duplicate probe field: ' + key)
        if records:
            m = re.fullmatch(pat, records[0])
            if not m:
                raise ValueError('Malformed probe field: ' + key)
            if key != 'prom_sha256':
                limit = 4096 if key == 'gops' else 0xffffffff if key == 'subsystem' else 0xffffffffffffffff
                if len(m.group(1)) > 16 or int(m.group(1), 16) > limit:
                    raise ValueError('Out-of-range probe field: ' + key)
            out[key] = m.group(1)
    targets = [line for line in lines if line.startswith('probe-target ')]
    configs = [line for line in lines if line.startswith('cfg dwords=')]
    if len(targets) != 1 or len(configs) != 1:
        raise ValueError('Expected one probe target and one config snapshot')
    words = configs[0].removeprefix('cfg dwords=').split()
    if len(words) != 64 or any(not re.fullmatch('[0-9a-f]{8}', word) for word in words):
        raise ValueError('Expected exactly 64 config DWORDs')
    out['board_id'] = words[0]
    command = int(words[1], 16) & 0xffff
    out['pci_command'] = f'{command:04x}'
    out['pci_memory_enabled'] = bool(command & 2)
    out['pci_bus_master_enabled'] = bool(command & 4)
    for line in targets:
        m = re.match(r"^probe-target seg=0x([0-9a-f]+) bus=0x([0-9a-f]+) dev=0x([0-9a-f]+) fun=0x([0-9a-f]+)", line)
        if not m or m.end() != len(line):
            raise ValueError('Malformed probe target')
        location = tuple(int(x, 16) for x in m.groups())
        if any(value > limit for value, limit in zip(location, (65535, 255, 31, 7))):
            raise ValueError('Probe PCI location out of range')
        out["bdf"] = "%04x:%02x:%02x.%x" % location
    mmio, statuses = _profile.probe_mmio(text)
    out['failed_mmio'] = [f'{offset:#x}' for offset, status in statuses.items() if status != 0]
    def observed(offset, fmt='x'):
        return format(mmio[offset], fmt) if offset in mmio else None
    out["chip"] = observed(0, '08x')
    out["memory_mib"] = observed(0x1183a4)
    out["missing_mmio"] = [f'{offset:#x}' for offset in _profile.COLD if offset not in mmio]
    gfw = [observed(offset) for offset in (0x118128, 0x118234, 0x110100)]
    out["cold"] = {
        "plm": observed(0x823804, '08x'),
        "gfw": '/'.join(gfw) if all(v is not None for v in gfw) else None,
        "wpr2_hi": observed(0x1fa828),
        "ss0": observed(0x82381c, '08x'),
        "ss1": observed(0x823820),
    }
    # The probe's GOP list: path nodes follow each "gop handle" line.
    gop_paths = []
    for i, line in enumerate(lines):
        if line.startswith("gop handle="):
            nodes = []
            for nxt in lines[i + 1:]:
                if not nxt.startswith("img-path-node raw="):
                    break
                nodes.append(node_value(nxt))
            gop_paths.append(b"".join(nodes))
    out["gop_paths"] = [p.hex() for p in gop_paths]
    # Driver bindings and their loaded images.
    drivers = []
    i = 0
    while i < len(lines):
        m = re.match(r"^binding handle=0x([0-9a-f]+) image=0x([0-9a-f]+) version=0x([0-9a-f]+) stop=0x([0-9a-f]+)", lines[i])
        if not m:
            i += 1
            continue
        d = {"handle": m.group(1), "image": m.group(2), "version": int(m.group(3), 16), "stop": int(m.group(4), 16), "nodes": []}
        i += 1
        while i < len(lines) and not lines[i].startswith("binding handle="):
            line = lines[i]
            for key in ("base", "size", "code-type"):
                mm = re.match(rf"^img {key}=0x([0-9a-f]+)", line)
                if mm:
                    d[key] = int(mm.group(1), 16)
            if line.startswith("img-path-node raw="):
                d["nodes"].append(node_value(line))
            mm = re.match(r"^img dump index=([0-9a-f]+)", line)
            if mm:
                d["dump"] = int(mm.group(1), 16)
            if line.startswith(("console-out=", "probe ", "handles ")):
                break
            i += 1
        drivers.append(d)
    out["drivers"] = drivers
    return out


def fingerprint(info, root: Path):
    rows = []
    for d in info["drivers"]:
        name, role = describe_file(d["nodes"])
        row = {
            "file": name, "role": role, "version": f"{d['version']:x}",
            "image_size": f"{d.get('size', 0):x}", "code_type": d.get("code-type"),
            "stop_offset": f"{d['stop'] - d['base']:x}" if "base" in d else None,
            "binding_is_image": d["handle"] == d["image"],
        }
        kind = "nvgop" if role.startswith("nvgop") else "edid" if role.startswith("edid") else None
        if kind and "dump" in d:
            if not 0 <= d["dump"] < 100:
                row["text_note"] = "invalid dump index"
            else:
                path = root / ("IMG%02d.BIN" % d["dump"])
                if not path.exists():
                    row["text_note"] = "image dump missing"
                elif path.stat().st_size != d.get("size"):
                    row["text_note"] = "dump size differs from loaded image size"
                else:
                    try:
                        sec = text_section(path.read_bytes())
                        rva = TEXT_RVA[kind]
                        if sec[0] != rva:
                            raise ValueError(f".text not at expected RVA {rva:#x}")
                        rec = dict(d, handle=int(d["handle"], 16))
                        code = _profile.code_hash(root, rec, rva)
                        row["text_section"] = {"rva": f"{sec[0]:x}", "bytes": f"{sec[1]:x}"}
                        row["text_sha256"] = code["sha256"]
                    except (ValueError, KeyError, TypeError, struct.error) as error:
                        row["text_note"] = "image refused: " + str(error)

        if role or kind:
            rows.append(row)
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--capture", required=True, type=Path)
    p.add_argument("--images", type=Path, help="directory with IMGnn.BIN (default: capture's directory)")
    a = p.parse_args(argv)
    info = parse(a.capture)
    report = {k: v for k, v in info.items() if k != "drivers"}
    report["fingerprints"] = fingerprint(info, a.images or a.capture.parent)
    report["authorizes_unlock"] = False
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
