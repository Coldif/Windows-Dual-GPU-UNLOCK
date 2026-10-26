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
import json
import re
import struct
import sys
from pathlib import Path

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
    """Return (rva, virtual_size) of .text from an in-memory PE image."""
    if dump[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", dump, 0x3C)[0]
    if dump[pe:pe + 4] == b"PE\0\0":
        count = struct.unpack_from("<H", dump, pe + 6)[0]
        opt = struct.unpack_from("<H", dump, pe + 20)[0]
        sections = pe + 24 + opt
    elif dump[pe:pe + 2] == b"VZ":  # TE image (PI spec)
        count = dump[pe + 5]
        sections = pe + 40
    else:
        return None
    for i in range(count):
        s = sections + 40 * i
        if dump[s:s + 8].rstrip(b"\0") == b".text":
            vsize, rva = struct.unpack_from("<II", dump, s + 8)
            return rva, vsize
    return None


def parse(capture: Path):
    lines = capture.read_text(encoding="ascii", errors="replace").splitlines()
    out = {"capture": capture.name, "sha256": hashlib.sha256(capture.read_bytes()).hexdigest()}
    simple = {
        "subsystem": r"^subsystem=0x([0-9a-f]+)",
        "bar0": r"^probe-bar0 base=0x([0-9a-f]+)",
        "prom_sha256": r"^prom sha256=([0-9a-f]{64})",
        "probe_status": r"^probe status=0x([0-9a-f]+)",
        "result": r"^diagnostic-result status=0x([0-9a-f]+)",
        "gops": r"^gops=([0-9a-f]+)",
    }
    for key, pat in simple.items():
        for line in lines:
            m = re.match(pat, line)
            if m:
                out[key] = m.group(1)
                break
    for line in lines:
        m = re.match(r"^probe-target seg=0x([0-9a-f]+) bus=0x([0-9a-f]+) dev=0x([0-9a-f]+) fun=0x([0-9a-f]+)", line)
        if m:
            out["bdf"] = "%04x:%02x:%02x.%x" % tuple(int(x, 16) for x in m.groups())
        m = re.match(r"^cfg dwords=(.*)", line)
        if m and "board_id" not in out:
            words = [int(w, 16) for w in m.group(1).split()]
            out["board_id"] = f"{words[0]:08x}"
    mmio = {}
    for line in lines:
        m = re.match(r"^mmio off=0x([0-9a-f]+) status=0x([0-9a-f]+) value=0x([0-9a-f]+)", line)
        if m and int(m.group(2), 16) == 0:
            mmio[int(m.group(1), 16)] = int(m.group(3), 16)
    out["chip"] = f"{mmio.get(0, 0):08x}"
    out["memory_mib"] = f"{mmio.get(0x1183a4, 0):x}"
    out["cold"] = {
        "plm": f"{mmio.get(0x823804, 0):08x}",
        "gfw": f"{mmio.get(0x118128, 0):x}/{mmio.get(0x118234, 0):x}/{mmio.get(0x110100, 0):x}",
        "wpr2_hi": f"{mmio.get(0x1fa828, 0):x}",
        "ss0": f"{mmio.get(0x82381c, 0):08x}",
        "ss1": f"{mmio.get(0x823820, 0):x}",
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
            path = root / ("IMG%02d.BIN" % (d["dump"] % 100))
            if d["dump"] >= 100:
                row["text_note"] = "dump index >= 100 wraps in probe.c; IMG file unreliable"
            elif path.exists():
                dump = path.read_bytes()
                sec = text_section(dump)
                if dump and len(dump) == d.get("size"):
                    row["text_section"] = None if not sec else {"rva": f"{sec[0]:x}", "bytes": f"{sec[1]:x}"}
                    rva = TEXT_RVA[kind]
                    if sec and sec[0] == rva:
                        row["text_sha256"] = hashlib.sha256(dump[rva:rva + sec[1]]).hexdigest()
                    else:
                        row["text_note"] = f".text not at the RVA full-release.c hashes (0x{rva:x})"
                else:
                    row["text_note"] = "dump size differs from loaded image size"
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
