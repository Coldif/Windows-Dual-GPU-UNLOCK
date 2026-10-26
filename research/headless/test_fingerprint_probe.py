"""Synthetic tests for fingerprint_probe.py. GPL-2.0-only. No real capture is used."""
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

import fingerprint_probe as fp


def pe_image(size: int, text_rva: int, text_bytes: int) -> bytes:
    """Minimal in-memory PE image with one .text section."""
    img = bytearray(size)
    img[0:2] = b"MZ"
    pe = 0x80
    struct.pack_into("<I", img, 0x3C, pe)
    img[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<H", img, pe + 4, 0x8664)
    struct.pack_into("<H", img, pe + 6, 1)       # one section
    struct.pack_into("<H", img, pe + 20, 0xF0)   # optional header size
    struct.pack_into("<H", img, pe + 24, 0x20b)
    struct.pack_into("<II", img, pe + 24 + 56, size, 0x200)
    struct.pack_into("<I", img, pe + 24 + 108, 16)
    sec = pe + 24 + 0xF0
    img[sec:sec + 8] = b".text\0\0\0"
    struct.pack_into("<II", img, sec + 8, text_bytes, text_rva)
    struct.pack_into("<I", img, sec + 36, 0x60000020)
    for i in range(text_bytes):
        img[text_rva + i] = (i * 7) & 0xFF
    return bytes(img)


NVGOP_PATH = "0404" + "1c00" + "nvgop-ga1xx".encode("utf-16-le").hex() + "0000"
EDID_PATH = "04061400" + "0c03a7c7d8c3ee45bed95d9e76762953"


def capture(nvgop_size: int, edid_size: int) -> str:
    return "\n".join([
        "probe-target seg=0x0000 bus=0x0001 dev=0x0000 fun=0x0000",
        "cfg dwords=" + " ".join(["250410de"] + ["00000000"] * 63),
        "subsystem=0x0000000040961458",
        "probe-bar0 base=0x0000000042000000",
        "mmio off=0x00000000 status=0x0000000000000000 value=0xb76000a1",
        "mmio off=0x001183a4 status=0x0000000000000000 value=0x00003000",
        "mmio off=0x00823804 status=0x0000000000000000 value=0xffffff8f",
        "mmio off=0x0082381c status=0x8000000000000007 value=0xdeadbeef",
        "prom sha256=" + "ab" * 32,
        "gops=0001",
        "gop handle=0x0000000000000010 path-status=0x0000000000000000 has-path=1",
        "img-path-node raw=02010c00d041030a00000000",
        "img-path-node raw=7fff0400",
        "binding handle=0x0000000000000100 image=0x0000000000000100 version=0x00060010 stop=0x0000000000010678",
        "img base=0x0000000000010000",
        "img size=0x%016x" % nvgop_size,
        "img code-type=0x0000000000000003",
        "img-path-node raw=" + NVGOP_PATH,
        "img-path-node raw=7fff0400",
        "img dump index=0000",
        "binding handle=0x0000000000000200 image=0x0000000000000200 version=0x00000001 stop=0x00000000000214d4",
        "img base=0x0000000000020000",
        "img size=0x%016x" % edid_size,
        "img code-type=0x0000000000000005",
        "img-path-node raw=" + EDID_PATH,
        "img-path-node raw=7fff0400",
        "img dump index=0001",
        "console-out=0x0000000000000001 stderr=0x0000000000000001 conin=0x0000000000000001",
        "probe status=0x0000000000000000",
    ]) + "\n"


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.nvgop = pe_image(0x1000, 0x280, 0x500)
        self.edid = pe_image(0x2000, 0x1000, 0x800)
        (self.root / "IMG00.BIN").write_bytes(self.nvgop)
        (self.root / "IMG01.BIN").write_bytes(self.edid)
        self.cap = self.root / "DIAG00.TXT"
        self.cap.write_text(capture(len(self.nvgop), len(self.edid)), encoding="ascii")

    def tearDown(self):
        self.dir.cleanup()

    def test_identity_and_failed_reads(self):
        info = fp.parse(self.cap)
        self.assertEqual(info["board_id"], "250410de")
        self.assertEqual(info["bdf"], "0000:01:00.0")
        self.assertEqual(info["chip"], "b76000a1")
        self.assertEqual(info["memory_mib"], "3000")
        # A failed MMIO read is not reported as a value.
        self.assertIsNone(info["cold"]["ss0"])
        self.assertIn('0x82381c', info['missing_mmio'])
        self.assertEqual(info["gop_paths"], ["02010c00d041030a000000007fff0400"])

    def test_text_hashes_and_stop_offsets(self):
        rows = {r["role"].split()[0]: r for r in fp.fingerprint(fp.parse(self.cap), self.root)}
        self.assertEqual(rows["nvgop"]["stop_offset"], "678")
        self.assertEqual(rows["nvgop"]["text_section"], {"rva": "280", "bytes": "500"})
        self.assertEqual(rows["nvgop"]["text_sha256"], hashlib.sha256(self.nvgop[0x280:0x780]).hexdigest())
        self.assertEqual(rows["edid-mouse"]["stop_offset"], "14d4")
        self.assertEqual(rows["edid-mouse"]["text_sha256"], hashlib.sha256(self.edid[0x1000:0x1800]).hexdigest())

    def test_mismatched_dump_is_not_hashed(self):
        (self.root / "IMG00.BIN").write_bytes(self.nvgop[:-16])
        row = next(r for r in fp.fingerprint(fp.parse(self.cap), self.root) if r["role"].startswith("nvgop"))
        self.assertNotIn("text_sha256", row)
        self.assertIn("differs", row["text_note"])

    def test_text_at_unexpected_rva_is_not_hashed(self):
        (self.root / "IMG00.BIN").write_bytes(pe_image(0x1000, 0x400, 0x300))
        row = next(r for r in fp.fingerprint(fp.parse(self.cap), self.root) if r["role"].startswith("nvgop"))
        self.assertNotIn("text_sha256", row)

    def test_truncated_headers_sections_and_stop_are_not_hashed(self):
        for at, fmt, value in ((0x3c, '<I', 0xffffffff), (0x84, '<H', 0x14c),
                               (0x188 + 8, '<I', 0x2000), (0x188 + 36, '<I', 0)):
            with self.subTest(at=at):
                data = bytearray(self.nvgop)
                struct.pack_into(fmt, data, at, value)
                (self.root / 'IMG00.BIN').write_bytes(data)
                row = next(r for r in fp.fingerprint(fp.parse(self.cap), self.root) if r['role'].startswith('nvgop'))
                self.assertNotIn('text_sha256', row)
                self.assertIn('refused', row['text_note'])

    def test_relocations_touching_code_are_not_hashed(self):
        data = bytearray(self.nvgop)
        struct.pack_into('<II', data, 0x98 + 112 + 40, 0x900, 12)
        struct.pack_into('<IIHH', data, 0x900, 0, 12, 0xa280, 0)
        (self.root / 'IMG00.BIN').write_bytes(data)
        row = next(r for r in fp.fingerprint(fp.parse(self.cap), self.root) if r['role'].startswith('nvgop'))
        self.assertNotIn('text_sha256', row)

    def test_failed_and_missing_mmio_are_distinct_from_zero(self):
        info = fp.parse(self.cap)
        self.assertIsNone(info['cold']['wpr2_hi'])
        with self.cap.open('a', encoding='ascii') as output:
            output.write('mmio off=0x001fa828 status=0x0000000000000000 value=0x00000000\n')
        info = fp.parse(self.cap)
        self.assertEqual(info['cold']['wpr2_hi'], '0')
        self.assertNotIn('0x1fa828', info['missing_mmio'])

    def test_duplicate_success_or_failed_read_cannot_hide_a_previous_read(self):
        for status in ('0000000000000000', '8000000000000007'):
            with self.subTest(status=status):
                self.cap.write_text(capture(len(self.nvgop), len(self.edid)) +
                    f'mmio off=0x00000000 status=0x{status} value=0xb76000a1\n', encoding='ascii')
                with self.assertRaisesRegex(ValueError, 'duplicate MMIO'):
                    fp.parse(self.cap)

    def test_marker_does_not_verify_file_close_or_hardware_provenance(self):
        with self.cap.open('a', encoding='ascii') as output:
            output.write('capture-complete=1\n')
        info = fp.parse(self.cap)
        self.assertTrue(info['capture_complete'])
        self.assertFalse(info['file_close_verified'])
        self.assertFalse(info['hardware_provenance_verified'])
        self.assertIn('0x82381c', info['failed_mmio'])

    def test_ambiguous_target_config_and_markers_refused(self):
        base = capture(len(self.nvgop), len(self.edid))
        config = next(line for line in base.splitlines() if line.startswith('cfg dwords='))
        target = base.splitlines()[0]
        for extra in (config + '\n', target + '\n', 'capture-complete=1\ncapture-complete=0\n'):
            self.cap.write_text(base + extra, encoding='ascii')
            with self.assertRaises(ValueError):
                fp.parse(self.cap)
        for words in ([], ['00000000'] * 63, ['00000000'] * 65,
                      ['100000000'] + ['00000000'] * 63):
            self.cap.write_text(base.replace(config, 'cfg dwords=' + ' '.join(words)), encoding='ascii')
            with self.assertRaisesRegex(ValueError, '64 config DWORDs'):
                fp.parse(self.cap)

    def test_mem_off_is_observed_without_claiming_safety(self):
        info = fp.parse(self.cap)
        self.assertFalse(info['pci_memory_enabled'])
        self.assertFalse(info['pci_bus_master_enabled'])
        self.assertFalse(info['capture_complete'])

    def test_oversize_capture_refused(self):
        self.cap.write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, 'format limit'):
            fp.parse(self.cap)

    def test_malformed_status_cannot_be_reported_as_success(self):
        base = capture(len(self.nvgop), len(self.edid))
        records = ['probe status=0x0000000000000000', 'subsystem=0x0000000040961458',
                   'probe-bar0 base=0x0000000042000000', 'prom sha256=' + 'ab' * 32]
        for record in records:
            for replacement in (record + 'truncated', record.split('=')[0] + '=',
                                record + record[-1] * 64):
                self.cap.write_text(base.replace(record, replacement), encoding='ascii')
                with self.subTest(record=record, replacement=replacement), self.assertRaises(ValueError):
                    fp.parse(self.cap)


if __name__ == "__main__":
    unittest.main()
