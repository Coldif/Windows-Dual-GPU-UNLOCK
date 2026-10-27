"""Synthetic capture admission regressions. No private captures or hardware."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('profile_records', Path(__file__).with_name('make-profile.py'))
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)


class ProbeRecordTests(unittest.TestCase):
    def test_zero_and_failed_reads_stay_distinct(self):
        values, statuses = mp.probe_mmio(
            'mmio off=0x001fa828 status=0x0 value=0x0\n'
            'mmio off=0x0082381c status=0x8000000000000007 value=0x0\n')
        self.assertEqual(values, {0x1fa828: 0})
        self.assertNotEqual(statuses[0x82381c], 0)

    def test_duplicate_reads_refused_in_either_status_order(self):
        for first, second in ((0, 0), (0, 7), (7, 0), (7, 7)):
            with self.subTest(first=first, second=second):
                text = ''.join(f'mmio off=0x0 status=0x{s:x} value=0x0\n' for s in (first, second))
                with self.assertRaisesRegex(mp.Refused, 'duplicate MMIO'):
                    mp.probe_mmio(text)

    def test_malformed_or_wide_values_refused(self):
        for text in ('mmio off=0x0 status=0x0 value=garbage',
                     'mmio off=0x0 status=0x0 value=0x100000000',
                     'mmio off=0x0 status=0x0 value=0x0 trailing',
                     'mmio off=0x0 status=0x10000000000000000 value=0x0'):
            with self.subTest(text=text), self.assertRaisesRegex(mp.Refused, 'malformed MMIO'):
                mp.probe_mmio(text)

    def test_ambiguous_completion_or_result_rejected_before_profile(self):
        good = 'capture-complete=1\ndiagnostic-result status=0x0000000000000000\n'
        for extra in ('capture-complete=0\n', 'capture-complete=1\n',
                      'diagnostic-result status=0x8000000000000007\n',
                      'diagnostic-result status=0x0000000000000000\n'):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'DIAG00.TXT'
                path.write_text(good + extra, encoding='ascii')
                with self.assertRaisesRegex(mp.Refused, 'complete, successful'):
                    mp.analyze(path, None, {})

    def test_each_required_cold_read_must_be_present_and_successful(self):
        cfg = [0x220410de, 3, 0x030000a1, 0, 0xf5000000] + [0] * 59
        prefix = ('capture-complete=1\ndiagnostic-result status=0x0000000000000000\n'
                  'probe-target seg=0x0000 bus=0x0001 dev=0x0000 fun=0x0000\n'
                  'probe targets=0001 cfg-incomplete=0000\ncfg dwords=' +
                  ' '.join(f'{word:08x}' for word in cfg) + '\n' +
                  # PciIo attribute cache matching command 0x3 (IO|MEM, no BME), as the probe records it.
                  'pci-attributes status=0x0000000000000000 value=0x0000000000000300\n')
        envelope = {'probe_device_ids': ['220410de'], 'class_revision': '030000a1'}
        for missing in mp.COLD:
            for failed in (False, True):
                rows = ''.join(f'mmio off=0x{offset:08x} status=0x{7 if offset == missing and failed else 0:x} value=0x0\n'
                               for offset in mp.COLD if offset != missing or failed)
                with self.subTest(offset=missing, failed=failed), tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / 'DIAG00.TXT'
                    path.write_text(prefix + rows, encoding='ascii')
                    with self.assertRaisesRegex(mp.Refused, 'missing a cold-state'):
                        mp.analyze(path, None, envelope)

    def test_pci_attribute_cache_must_match_the_command_register(self):
        """full-release.c CapturePermit stops the release on a mismatch, after the console detach."""
        envelope = {'probe_device_ids': ['220410de'], 'class_revision': '030000a1'}
        record = 'pci-attributes status=0x{:016x} value=0x{:016x}\n'
        cases = [
            # command dword, attribute record or None, expected refusal (None: the attribute gate passes)
            (3, None, 'no PciIo attribute record'),
            (3, record.format(0x8000000000000003, 0), 'reading the PciIo attributes failed'),
            (3, record.format(0, 0x700), 'disagree with the PCI command register'),  # BME in the cache
            (3, record.format(0, 0x100), 'disagree with the PCI command register'),  # MEM missing
            (2, record.format(0, 0x300), 'disagree with the PCI command register'),  # IO not in command
            (3, record.format(0, 0x300) * 2, 'ambiguous PciIo attribute records'),
            (3, record.format(0, 0x300) + record.format(7, 0), 'ambiguous PciIo attribute records'),
            (3, record.format(7, 0x300), 'reading the PciIo attributes failed'),
            (3, record.format(0, 0x300), None),
            (2, record.format(0, 0x200), None),
            (3, record.format(0, 0x300 | 0x4000), None),  # other cached attributes are not compared
        ]
        for command, attributes, refusal in cases:
            cfg = [0x220410de, command, 0x030000a1, 0, 0xf5000000] + [0] * 59
            text = ('capture-complete=1\ndiagnostic-result status=0x0000000000000000\n'
                    'probe-target seg=0x0000 bus=0x0001 dev=0x0000 fun=0x0000\n'
                    'probe targets=0001 cfg-incomplete=0000\ncfg dwords=' +
                    ' '.join(f'{word:08x}' for word in cfg) + '\n' + (attributes or ''))
            with self.subTest(command=command, attributes=attributes), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'DIAG00.TXT'
                path.write_text(text, encoding='ascii')
                # With no cold-state reads in the text, a passing attribute gate reaches the next gate.
                with self.assertRaisesRegex(mp.Refused, refusal or 'missing a cold-state'):
                    mp.analyze(path, None, envelope)

    def test_malformed_attribute_records_are_never_ignored(self):
        cfg = [0x220410de, 3, 0x030000a1, 0, 0xf5000000] + [0] * 59
        prefix = ('capture-complete=1\ndiagnostic-result status=0x0000000000000000\n'
                  'probe-target seg=0x0000 bus=0x0001 dev=0x0000 fun=0x0000\n'
                  'probe targets=0001 cfg-incomplete=0000\ncfg dwords=' +
                  ' '.join(f'{word:08x}' for word in cfg) + '\n')
        good = 'pci-attributes status=0x0000000000000000 value=0x0000000000000300\n'
        malformed = [
            'pci-attributes',
            'pci-attributes\tstatus=0x0000000000000000 value=0x0000000000000300',
            'pci-attributes status=0x',
            'pci-attributes status=0x0000000000000000',
            'pci-attributes status=0x0000000000000000 value=0x10000000000000300',
            'pci-attributes status=0x10000000000000000 value=0x0000000000000300',
            'pci-attributes status=0x0000000000000000 value=0x-000000000000300',
            'pci-attributes status=0x0000000000000000 value=0x0000000000000xyz',
            'pci-attributes status=0x8000000000000003 value=0x0000000000000000 trailing',
        ]
        envelope = {'probe_device_ids': ['220410de'], 'class_revision': '030000a1'}
        for bad in malformed:
            for rows in (bad + '\n', good + bad + '\n', bad + '\n' + good):
                expected = 'ambiguous' if good in rows else 'malformed'
                with self.subTest(rows=rows), tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / 'DIAG00.TXT'
                    path.write_text(prefix + rows, encoding='ascii')
                    with self.assertRaisesRegex(mp.Refused, expected + ' PciIo attribute'):
                        mp.analyze(path, None, envelope)


if __name__ == '__main__':
    unittest.main()
