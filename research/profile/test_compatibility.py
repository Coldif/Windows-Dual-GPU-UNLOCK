"""Offline compatibility behavior on synthetic data; never hardware evidence."""
import copy
import contextlib
import hashlib
import importlib.util
import json
import io
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load('compatibility_test_subject', 'check-compatibility.py')
topology = load('compatibility_synthetic_topology', 'test_local_topology.py')


def driver_image(size, rva, length):
    data = bytearray(size)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x8664, 1)
    struct.pack_into('<H', data, 0x94, 0xf0)
    struct.pack_into('<H', data, 0x98, 0x20b)
    struct.pack_into('<II', data, 0x98 + 56, size, 0x200)
    struct.pack_into('<I', data, 0x98 + 108, 16)
    struct.pack_into('<8sII', data, 0x188, b'.text', length, rva)
    struct.pack_into('<I', data, 0x188 + 36, 0x60000020)
    return data


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.envelope = copy.deepcopy(topology.ENVELOPE)
        self.envelope.update(min_captures=2, nvgop=[{
            'version': '60009', 'text_sha256': hashlib.sha256(bytes(0x500)).hexdigest()}])
        self.envelope['chips'][0]['nvgop'] = copy.deepcopy(self.envelope['nvgop'])

    def populate(self, *, no_edid=True, count=2, **options):
        text = topology.synthetic_capture(no_edid=no_edid, **options)
        first_binding = text.index('binding handle=')
        text = text[:first_binding] + f'driver-bindings={3 if no_edid else 4:08x}\n' + text[first_binding:]
        for agent, index in ((3, 0), (9, 1)):
            if agent == 9 and no_edid:
                continue
            pattern = rf'(^binding handle=0x{agent:x} .*?)(?=^binding handle=|^handles status=)'
            text, hits = re.subn(pattern, lambda m: m[1] + f'img dump index={index:02x}\n', text, flags=re.M | re.S)
            self.assertEqual(hits, 1)
        for index in range(count):
            (self.folder / f'DIAG{index:02d}.TXT').write_text(text, encoding='ascii')
        (self.folder / 'IMG00.BIN').write_bytes(driver_image(0x2be40, 0x280, 0x500))
        if not no_edid:
            (self.folder / 'IMG01.BIN').write_bytes(driver_image(0x9000, 0x1000, 0x800))
        (self.folder / 'PROM.BIN').write_bytes(bytes(1048576))
        return text

    def result(self):
        return checker.check(self.folder, self.envelope)

    def assert_reason(self, status, code):
        result = self.result()
        self.assertEqual(result['status'], status, result)
        self.assertIn(code, [entry['code'] for entry in result['checks']])
        self.assertIs(result['write_eligible'], False)
        self.assertIs(result['hardware_tested'], False)

    def test_complete_candidate_matrix_is_not_hardware_approval(self):
        for bus in (1, 0x2b):
            for igpu in (False, True):
                for no_edid in (False, True):
                    for children in (1, 2):
                        with self.subTest(bus=bus, igpu=igpu, no_edid=no_edid, children=children):
                            self.populate(bus=bus, igpu=igpu, no_edid=no_edid, children=children)
                            self.assert_reason('candidate', 'images_pass')

    def test_missing_and_single_capture(self):
        self.assert_reason('needs_data', 'no_captures')
        self.populate(count=1)
        self.assert_reason('needs_data', 'capture_count')

    def test_missing_assets_are_not_candidate(self):
        self.populate()
        (self.folder / 'IMG00.BIN').unlink()
        (self.folder / 'PROM.BIN').unlink()
        self.assert_reason('needs_data', 'missing_images')
        self.assert_reason('needs_data', 'missing_prom')

    def test_dump_reference_required(self):
        text = self.populate().replace('img dump index=00\n', '')
        (self.folder / 'DIAG01.TXT').write_text(text, encoding='ascii')
        self.assert_reason('needs_data', 'missing_images')

    def test_unknown_gpu_does_not_mean_globally_unsupported(self):
        for board in ('248210de', '250410de', 'ffffffff'):
            text = self.populate().replace('220410de', board)
            for index in (0, 1):
                (self.folder / f'DIAG{index:02d}.TXT').write_text(text, encoding='ascii')
            self.assert_reason('outside_scope', 'gpu_scope')

    def test_damaged_graph_is_not_missing_gpu_or_edid(self):
        good = self.populate()
        for text in (good.replace('capture-complete=1', 'capture-complete=0'),
                     good + 'diagnostic-result status=0x0000000000000000\n',
                     good.replace('pci config-status=0x0000000000000000\n', '', 1),
                     good.replace('open agent=0x3 controller=0x2 attributes=0x8 count=0x1', 'open broken')):
            with self.subTest(text=text[-40:]):
                (self.folder / 'DIAG01.TXT').write_text(text, encoding='ascii')
                self.assert_reason('invalid_data', 'invalid_graph')

    def test_attributes_have_actionable_reasons(self):
        good = self.populate()
        record = 'pci-attributes status=0x0000000000000000 value=0x0000000000000300\n'
        for change, status, code in (('', 'needs_data', 'attributes_missing'),
                                    (record.replace('0300', '0700'), 'invalid_data', 'attributes_mismatch')):
            (self.folder / 'DIAG01.TXT').write_text(good.replace(record, change), encoding='ascii')
            self.assert_reason(status, code)

    def test_cold_state_and_missing_registers(self):
        good = self.populate()
        for change, status, code in ((good.replace('value=0xffffff8f', 'value=0x0'), 'invalid_data', 'cold_state'),
                                    (re.sub(r'^mmio off=0x00823804 .*\n', '', good, flags=re.M), 'needs_data', 'deep_capture_missing')):
            (self.folder / 'DIAG01.TXT').write_text(change, encoding='ascii')
            self.assert_reason(status, code)

    def test_individually_valid_captures_must_agree(self):
        self.populate(bus=1)
        (self.folder / 'DIAG01.TXT').write_text(topology.synthetic_capture(bus=0x2b), encoding='ascii')
        self.assert_reason('invalid_data', 'captures_disagree')

    def test_unknown_nvgop_code_is_not_candidate(self):
        self.populate()
        image = bytearray((self.folder / 'IMG00.BIN').read_bytes())
        image[0x280] = 1
        (self.folder / 'IMG00.BIN').write_bytes(image)
        self.assert_reason('outside_scope', 'driver_scope')

    def test_malformed_image_and_prom_mismatch(self):
        self.populate()
        (self.folder / 'IMG00.BIN').write_bytes(b'not executable and must never be executed')
        self.assert_reason('invalid_data', 'images_invalid')
        self.populate()
        (self.folder / 'PROM.BIN').write_bytes(bytes(100))
        self.assert_reason('invalid_data', 'prom_invalid')

    def test_bounded_input_and_unreadable_folder(self):
        self.populate()
        with patch.object(checker, 'DIAG_LIMIT', 32):
            self.assert_reason('invalid_data', 'input_limit')
        with patch.object(checker, 'TOTAL_LIMIT', 32):
            self.assert_reason('invalid_data', 'input_limit')
        self.assertEqual(checker.check(self.folder / 'absent', self.envelope)['status'], 'invalid_data')
        for index in range(33):
            (self.folder / f'DIAG{index:02d}.TXT').write_bytes(b'')
        self.assert_reason('invalid_data', 'input_limit')

    def test_no_writes_or_subprocess_even_for_complete_candidate(self):
        self.populate()
        def manifest():
            return {path.name: path.read_bytes() for path in self.folder.iterdir()}
        before = manifest()
        with patch.object(Path, 'write_bytes', side_effect=AssertionError('write forbidden')), \
             patch.object(Path, 'write_text', side_effect=AssertionError('write forbidden')), \
             patch.object(checker.mp, 'generate', side_effect=AssertionError('generate forbidden')), \
             patch.object(checker.mp, 'locate_fwsec', side_effect=AssertionError('subprocess forbidden')), \
             patch.object(subprocess, 'run', side_effect=AssertionError('subprocess forbidden')):
            self.assert_reason('candidate', 'prom_pass')
        self.assertEqual(manifest(), before)

    def test_installed_envelope_errors_are_not_capture_failures(self):
        self.populate()
        for field, value in (('min_captures', 0), ('min_captures', True), ('min_captures', 33),
                             ('probe_device_ids', []), ('chips', [{}]), ('nvgop', [{}])):
            with self.subTest(field=field, value=value):
                envelope = copy.deepcopy(self.envelope)
                envelope[field] = value
                result = checker.check(self.folder, envelope)
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['checks'][0]['code'], 'tool_error')
        self.assertEqual(checker.check(self.folder, {})['status'], 'error')

    def test_cli_candidate_and_installation_error_exit_codes(self):
        self.populate()
        installed = checker.HERE / 'proven.json'
        original = Path.read_text
        for content, code, status in ((json.dumps(self.envelope), 0, 'candidate'), ('{}', 3, 'error')):
            def read(path, *args, **kwargs):
                return content if path == installed else original(path, *args, **kwargs)
            out = io.StringIO()
            with patch.object(Path, 'read_text', read), contextlib.redirect_stdout(out):
                self.assertEqual(checker.main([str(self.folder), '--json']), code)
            report = json.loads(out.getvalue())
            self.assertEqual(report['status'], status)
            self.assertIs(report['write_eligible'], False)

    def test_cli_json_languages_exit_codes_and_privacy(self):
        self.populate()
        private = 'PRIVATE-SERIAL-DO-NOT-REPORT'
        for path in self.folder.glob('DIAG*.TXT'):
            path.write_text(path.read_text() + private + '\n', encoding='ascii')
        # The real envelope intentionally does not know our synthetic code hash.
        for lang in ('en', 'ko'):
            done = subprocess.run([sys.executable, '-I', str(HERE / 'check-compatibility.py'),
                                   str(self.folder), '--json', '--lang', lang], capture_output=True, text=True)
            self.assertEqual(done.returncode, 2, done.stderr)
            report = json.loads(done.stdout)
            self.assertEqual(report['status'], 'outside_scope')
            self.assertIs(report['write_eligible'], False)
            self.assertNotIn(str(self.folder), done.stdout)
            self.assertNotIn(private, done.stdout)
            self.assertNotIn(topology.PROM_HASH, done.stdout)
            self.assertEqual(report['summary'], checker.MESSAGES['outside_scope'][lang == 'ko'])
            self.assertEqual(done.stderr, '')

    def test_direct_cli_leaves_source_and_input_files_unchanged(self):
        self.populate()
        def manifest():
            paths = list(HERE.rglob('*')) + list(self.folder.rglob('*'))
            return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in paths if path.is_file()}
        before = manifest()
        # No -B/-I: the entry point itself must suppress local bytecode writes.
        done = subprocess.run([sys.executable, str(HERE / 'check-compatibility.py'),
                               str(self.folder)], cwd=self.folder, capture_output=True, text=True)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn('Outside the current automatic local-profile route', done.stdout)
        self.assertEqual(manifest(), before)

    def test_shareable_observations_preserve_out_of_scope_inventory(self):
        self.populate()
        for path in self.folder.glob('DIAG*.TXT'):
            path.write_text(path.read_text().replace('220410de', '248210de'), encoding='ascii')
        report = self.result()
        self.assertEqual(report['format'], 2)
        self.assertEqual(report['status'], 'outside_scope')
        observation = report['observations'][0]
        self.assertTrue(observation['available'])
        self.assertEqual(observation['nvidia_display_count'], 1)
        self.assertEqual(observation['other_display_count'], 0)
        self.assertEqual(observation['display_controllers'][0]['pci_id'], '248210de')
        self.assertEqual(observation['display_controllers'][0]['location']['bus'], 0x2b)
        self.assertEqual(observation['edid_active_open_count'], 0)

    def test_unobserved_is_not_zero_and_malformed_graph_is_not_absence(self):
        text = self.populate()
        path = self.folder / 'DIAG00.TXT'
        path.write_text(re.sub(r'^mmio .*\n', '', text, flags=re.M), encoding='ascii')
        observation = self.result()['observations'][0]
        self.assertIsNone(observation['chip_id'])
        self.assertIsNone(observation['device_memory_size_mib'])
        self.assertEqual(observation['register_snapshot'], 'not_recorded')
        path.write_text(text.replace('value=0x00006000', 'value=0x00000000'), encoding='ascii')
        self.assertEqual(self.result()['observations'][0]['device_memory_size_mib'], 0)
        path.write_text(text.replace('capture-complete=1', 'capture-complete=0'), encoding='ascii')
        self.assertEqual(self.result()['observations'][0], {'capture': 'DIAG00.TXT', 'available': False})

    def test_missing_or_incomplete_driver_inventory_is_unknown(self):
        text = self.populate()
        path = self.folder / 'DIAG00.TXT'
        for change in (text.replace('driver-bindings=00000003\n', ''),
                       text.replace('driver-bindings=00000003', 'driver-bindings=00000004'),
                       text.replace('binding handle=0x4', 'binding broken=0x4')):
            path.write_text(change, encoding='ascii')
            observation = self.result()['observations'][0]
            self.assertIsNone(observation['firmware_bindings'])
            self.assertIsNone(observation['firmware_bindings_truncated'])


if __name__ == '__main__':
    unittest.main()
