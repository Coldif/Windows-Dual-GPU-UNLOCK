"""Synthetic loaded-PE range tests; no firmware, captures or hardware access."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('make_profile', Path(__file__).with_name('make-profile.py'))
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)


def image(code=0x280, reloc=False):
    b = bytearray(0x3000)
    b[:2] = b'MZ'
    struct.pack_into('<I', b, 0x3c, 0x80)
    b[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', b, 0x84, 0x8664, 3)
    struct.pack_into('<H', b, 0x94, 0xf0)
    struct.pack_into('<H', b, 0x98, 0x20b)
    struct.pack_into('<II', b, 0x98 + 56, len(b), 0x200)
    struct.pack_into('<I', b, 0x98 + 108, 16)
    for i, (name, rva, size, flags) in enumerate([
        (b'.text', code, 0x400, 0x60000020),
        (b'.data', 0x2000, 0x800, 0xc0000040),
        (b'.reloc', 0x2800, 0x100, 0x42000040)]):
        at = 0x188 + i * 40
        struct.pack_into('<8sII', b, at, name, size, rva)
        struct.pack_into('<I', b, at + 36, flags)
    b[code:code + 0x400] = bytes(range(256)) * 4
    if reloc:
        struct.pack_into('<II', b, 0x98 + 112 + 40, 0x2800, 12)
        struct.pack_into('<IIHH', b, 0x2800, 0x2000, 12, 0xa000, 0)
    return b


class PeTests(unittest.TestCase):
    def digest(self, b, code=0x280, **changes):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'IMG00.BIN').write_bytes(b)
            rec = dict(dump=0, size=len(b), handle=1, base=0x100000, stop=0x100000 + code + 0x10)
            rec.update(changes)
            return mp.code_hash(path, rec, code)

    def test_compact_and_normal_loaded_images(self):
        for code in (0x280, 0x1000):
            with self.subTest(code=code):
                b = image(code)
                result = self.digest(b, code)
                self.assertEqual(result['bytes'], 0x400)
                self.assertEqual(result['sha256'], hashlib.sha256(b[code:code + 0x400]).hexdigest())

    def test_valid_noncode_relocations(self):
        self.digest(image(reloc=True))

    def test_malformed_headers_and_sections(self):
        cases = [(0x3c, '<I', 0xffffffff), (0x3c, '<I', 0),
                 (0x84, '<H', 0x14c), (0x86, '<H', 0), (0x86, '<H', 97),
                 (0x94, '<H', 111), (0x94, '<H', 0xffff), (0x98, '<H', 0x10b),
                 (0x98 + 56, '<I', 0x2000), (0x98 + 60, '<I', 0x180),
                 (0x98 + 108, '<I', 17), (0x188 + 8, '<I', 0x100000),
                 (0x188 + 12, '<I', 0x1ff), (0x188 + 40 + 12, '<I', 0x300),
                 (0x188 + 40 + 12, '<I', 0x280), (0x188 + 36, '<I', 0x40000040)]
        for at, fmt, value in cases:
            with self.subTest(at=at, value=value):
                b = image()
                struct.pack_into(fmt, b, at, value)
                with self.assertRaises(mp.Refused):
                    self.digest(b)
        for b in (b'', b'MZ', bytes(image()[:63]), b'NO' + bytes(image()[2:]), bytes(image()) + b'x'):
            with self.subTest(size=len(b)):
                with self.assertRaises(mp.Refused):
                    self.digest(b)

    def test_empty_code_and_bad_stop(self):
        b = image()
        struct.pack_into('<I', b, 0x188 + 8, 0)
        with self.assertRaises(mp.Refused):
            self.digest(b)
        for stop in (0, 0x100000 + 0x27f, 0x100000 + 0x680, 0x100000 + 0x3000):
            with self.subTest(stop=stop):
                with self.assertRaises(mp.Refused):
                    self.digest(image(), stop=stop)
        with self.assertRaises(mp.Refused):
            self.digest(image(), base=(1 << 64) - 1)

    def test_bad_relocation_directories(self):
        for rva, size in ((0, 12), (0x2800, 0), (0x2fff, 12), (0x2800, 0xffffffff)):
            b = image(reloc=True)
            struct.pack_into('<II', b, 0x98 + 112 + 40, rva, size)
            with self.assertRaises(mp.Refused):
                self.digest(b)
        for block in (0, 7, 9, 13, 100):
            b = image(reloc=True)
            struct.pack_into('<I', b, 0x2804, block)
            with self.subTest(block=block):
                with self.assertRaises(mp.Refused):
                    self.digest(b)
        b = image(reloc=True)
        struct.pack_into('<I', b, 0x98 + 112 + 44, 13)
        with self.assertRaises(mp.Refused):
            self.digest(b)

    def test_bad_fixup_targets_and_types(self):
        for page, entry in ((0x2001, 0xa000), (0x3000, 0xa000),
                            (0x2000, 0xaffc), (0x2000, 0x3000),
                            (0, 0xa280), (0, 0xa27c)):
            with self.subTest(page=page, entry=entry):
                b = image(reloc=True)
                struct.pack_into('<I', b, 0x2800, page)
                struct.pack_into('<H', b, 0x2808, entry)
                with self.assertRaises(mp.Refused):
                    self.digest(b)

    def test_summary_old_and_new_format(self):
        for text in ('probe targets=0001\n', 'probe targets=0001 cfg-incomplete=0000\n'):
            self.assertTrue(mp.single_probe_summary(text))
        for text in ('probe targets=0002\n', 'probe targets=0001 cfg-incomplete=0001\n',
                     'probe targets=0001\nprobe targets=0001\n', 'probe targets=0001 extra\n'):
            self.assertFalse(mp.single_probe_summary(text))


if __name__ == '__main__':
    unittest.main()
