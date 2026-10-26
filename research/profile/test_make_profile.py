"""Refusal tests for make-profile.py, run on this machine's own probe captures.

Each case copies the captures to a temporary folder, changes one fact and
requires the generator to refuse. Offline only; writes nothing in the repo.

Usage: python -I test_make_profile.py CAPTURE_DIR FWSEC_LOCATE_EXE
"""
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('make_profile', HERE / 'make-profile.py')
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)
ENVELOPE = json.loads((HERE / 'proven.json').read_text())
failures = 0


def sub(path, pattern, replace):
    """Rewrite the first match of pattern in a capture; the case is void if it does not occur."""
    text = path.read_bytes().decode('utf-8-sig').replace('\r\n', '\n')
    new, n = re.subn(pattern, replace, text, count=1, flags=re.M)
    if n != 1:
        raise AssertionError(f'{path.name}: pattern {pattern!r} not found')
    path.write_bytes(new.encode())


def case(name, expect, mutate=None, envelope=ENVELOPE):
    global failures
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / 'capture'
        shutil.copytree(CAPTURES, work)
        diags = sorted(work.glob('DIAG[0-9][0-9].TXT'))
        if mutate:
            mutate(work, diags)
        try:
            mp.generate(work, LOCATOR, envelope)
            outcome = None
        except mp.Refused as error:
            outcome = str(error)
    ok = outcome is None if expect is None else outcome is not None and expect in outcome
    failures += not ok
    print(f'{"PASS" if ok else "FAIL"} {name}: {outcome or "accepted"}')


def hexword(value):
    return lambda m: m[1] + f'{value:08x}'


def main():
    global CAPTURES, LOCATOR
    CAPTURES, LOCATOR = Path(sys.argv[1]), Path(sys.argv[2])
    case('real captures accepted', None)
    case('single capture', 'at least', lambda w, d: [p.unlink() for p in d[:-1]])
    case('captures disagree', 'disagree on GU_PROM_SHA256',
         lambda w, d: sub(d[0], r'^(prom sha256=)[0-9a-f]{64}', lambda m: m[1] + '0' * 64))
    case('unproven chip', 'no hardware-proven profile',
         lambda w, d: sub(d[-1], r'^(mmio off=0x00000000 status=0x0+ value=0x)[0-9a-f]{8}', hexword(0xb74000a1)))
    case('unproven memory size', 'not hardware-proven',
         lambda w, d: sub(d[-1], r'^(mmio off=0x001183a4 status=0x0+ value=0x)[0-9a-f]{8}', hexword(0x2800)))
    case('already unlocked', 'power-on state',
         lambda w, d: sub(d[-1], r'^(mmio off=0x0082381c status=0x0+ value=0x)[0-9a-f]{8}', hexword(0x88888888)))
    case('WPR2 already set', 'power-on state',
         lambda w, d: sub(d[-1], r'^(mmio off=0x001fa828 status=0x0+ value=0x)[0-9a-f]{8}', hexword(0x10)))
    case('second NVIDIA GPU', 'exactly one NVIDIA', lambda w, d: sub(d[-1], r'^probe targets=0001(?: cfg-incomplete=0000)?$', 'probe targets=0002 cfg-incomplete=0000'))
    case('RTX not at 01:00.0', '0000:01:00.0',
         lambda w, d: sub(d[-1], r'^(probe-target seg=0x0000 bus=0x)0001', lambda m: m[1] + '0002'))
    case('no integrated GPU', 'non-NVIDIA display controller',
         lambda w, d: sub(d[-1], r'^(pci config-dwords=(?!....10de)[0-9a-f]{8} [0-9a-f]{8} )03', lambda m: m[1] + '04'))
    case('aggregate console', 'ConOut',
         lambda w, d: sub(d[-1], r'^(variable name=ConOut .*\n(?:.*\n)*?path-node raw=0101060000)00', lambda m: m[1] + '1f'))
    case('incomplete capture', 'complete, successful',
         lambda w, d: sub(d[-1], r'^diagnostic-result status=0x0+$', 'diagnostic-result status=0x8000000000000006'))
    case('PROM.BIN from another card', 'PROM.BIN is not',
         lambda w, d: (w / 'PROM.BIN').write_bytes(b'\0' + (w / 'PROM.BIN').read_bytes()[1:]))
    case('nvgop never released on proven hardware', 'has not released cleanly',
         envelope={**ENVELOPE, 'nvgop': []})
    case('chip family without proof', 'no hardware-proven profile', envelope={**ENVELOPE, 'chips': []})
    print(f'{failures} generator refusal case(s) failed' if failures else 'All generator refusal cases passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
