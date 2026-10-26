"""Synthetic format fixtures; no firmware, GPU or headless boot evidence."""
import unittest

from analyze_capture import analyze, MARKER, GOP, TEXT, INPUT


def fixture(amd=False):
    pci = '02010c00d041030a00000000\n010106000101\n010106000000'
    def path(nodes):
        return ''.join('path-node raw=' + node + '\n' for node in nodes.splitlines())
    end = '7fff0400'
    cfg = [0x220410de] + [0]*10 + [0x145410de] + [0]*4
    text = MARKER + '\nconsole out=0x1 error=0x1 input=0x1\n'
    text += f'handles status=0x0 count=0x{5 if amd else 3:x}\n'
    text += 'handle id=0x1\nprotocol guid=' + TEXT + '\nprotocol guid=' + INPUT + '\n'
    text += 'handle id=0x2\npci config-status=0x0000000000000000\npci config-dwords=' + ' '.join(f'{w:08x}' for w in cfg) + '\n' + path(pci + '\n' + end)
    text += 'handle id=0x3\nprotocol guid=' + GOP + '\ngop framebuffer=0x1000 bytes=0x4000\n' + path(pci + '\n0203080040030180\n' + end)
    if amd:
        cfg[0], cfg[11] = 0x164e1002, 0x88771043
        p2 = pci.replace('010106000101', '010106000108')
        text += 'handle id=0x4\npci config-status=0x0000000000000000\npci config-dwords=' + ' '.join(f'{w:08x}' for w in cfg) + '\n' + path(p2 + '\n' + end)
        text += 'handle id=0x5\nprotocol guid=' + GOP + '\ngop framebuffer=0x5000 bytes=0x4000\n' + path(p2 + '\n0203080000030180\n' + end)
    return (text + 'capture-complete=1\n').encode()


class CaptureTests(unittest.TestCase):
    def test_single_topology_does_not_authorize_execution(self):
        report = analyze(fixture())
        self.assertTrue(report['single_rtx_display_topology_observed'])
        for flag in ['hardware_access', 'authorizes_driver_detach', 'authorizes_unlock', 'headless_handoff_verified']:
            self.assertFalse(report[flag])
        self.assertNotIn('0x1', str(report))

    def test_two_display_baseline_is_not_single_gpu_evidence(self):
        r = analyze(fixture(amd=True))
        self.assertEqual(r['physical_gop_count'], 2)
        self.assertFalse(r['single_rtx_display_topology_observed'])

    def test_multi_capture_requires_explicit_index(self):
        raw = fixture() + fixture(amd=True)
        with self.assertRaises(ValueError):
            analyze(raw)
        self.assertEqual(analyze(raw, 1)['physical_gop_count'], 2)

    def test_incomplete_capture_rejected(self):
        with self.assertRaises(ValueError):
            analyze(fixture().replace(b'capture-complete=1', b'capture-complete=0'))

    def test_duplicate_handle_rejected(self):
        with self.assertRaises(ValueError):
            analyze(fixture().replace(b'handle id=0x3', b'handle id=0x2'))

    def test_wrong_subsystem_not_candidate(self):
        r = analyze(fixture().replace(b'145410de', b'123410de'))
        self.assertFalse(r['single_rtx_display_topology_observed'])

    def test_unresolved_ancestry_rejected(self):
        raw = fixture()
        # Change only the GOP ancestry, leaving the parent PCI record intact.
        before, after = raw.split(('protocol guid=' + GOP).encode())
        after = after.replace(b'010106000101', b'010106000102')
        with self.assertRaises(ValueError):
            analyze(before + ('protocol guid=' + GOP).encode() + after)

    def test_console_protocol_missing_not_candidate(self):
        r = analyze(fixture().replace(('protocol guid=' + INPUT).encode(), b'protocol guid=00000000-0000-0000-0000-000000000000'))
        self.assertFalse(r['single_rtx_display_topology_observed'])

    def test_invalid_capture_index_rejected(self):
        for index in (-1, 1):
            with self.assertRaises(ValueError):
                analyze(fixture(), index)

    def test_bridge_prefix_uses_nearest_endpoint(self):
        bridge = ('handle id=0x9\npci config-status=0x0000000000000000\npci config-dwords=' +
                  ' '.join(['00011022'] + ['0']*15) +
                  '\npath-node raw=02010c00d041030a00000000\npath-node raw=7fff0400\n')
        raw = fixture().replace(b'capture-complete=1', bridge.encode() + b'capture-complete=1')
        raw = raw.replace(b'handles status=0x0 count=0x3', b'handles status=0x0 count=0x4')
        self.assertTrue(analyze(raw)['single_rtx_display_topology_observed'])

    def test_duplicate_nearest_parent_is_ambiguous(self):
        text = fixture().decode()
        parent = text.split('handle id=0x2\n')[1].split('handle id=0x3\n')[0]
        text = text.replace('capture-complete=1', 'handle id=0x9\n' + parent + 'capture-complete=1')
        text = text.replace('handles status=0x0 count=0x3', 'handles status=0x0 count=0x4')
        with self.assertRaises(ValueError):
            analyze(text.encode())

    def test_declared_handle_count_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            analyze(fixture().replace(b'count=0x3', b'count=0x4'))

    def test_oversize_rejected(self):
        with self.assertRaises(ValueError):
            analyze(b'x' * (8 * 1024 * 1024 + 1))

    def test_mem_and_bme_are_observations_not_topology_or_authority(self):
        for command in (0, 2, 6):
            with self.subTest(command=command):
                raw = fixture().replace(b'220410de 00000000', f'220410de {command:08x}'.encode())
                report = analyze(raw)
                row = report['pci_command_observations'][0]
                self.assertEqual(row['memory_enabled'], bool(command & 2))
                self.assertEqual(row['bus_master_enabled'], bool(command & 4))
                self.assertTrue(report['single_rtx_display_topology_observed'])
                self.assertFalse(report['authorizes_unlock'])
                self.assertFalse(report['file_close_verified'])

    def test_duplicate_pci_config_and_status_rejected(self):
        base = fixture()
        config = next(line for line in base.splitlines() if line.startswith(b'pci config-dwords='))
        for extra in (config, b'pci config-status=0x0000000000000000',
                      b'pci config-status=0x8000000000000007'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                analyze(base.replace(config, config + b'\n' + extra))

    def test_unknown_completion_and_duplicate_console_rejected(self):
        base = fixture()
        for raw in (base + b'capture-complete=2\n',
                    base.replace(b'console out=0x1 error=0x1 input=0x1',
                                 b'console out=0x1 error=0x1 input=0x1\nconsole out=0x1 error=0x1 input=0x1')):
            with self.assertRaises(ValueError):
                analyze(raw)

    def test_literal_open_attributes_do_not_invent_detach_roles(self):
        # No owner, GET_PROTOCOL, child-like 0x8, BY_DRIVER and multi-count
        # exclusive opens are independent observations, never new authority.
        for attributes, count in ((None, 0), (2, 1), (8, 1), (0x10, 1), (0x30, 3)):
            snapshot = b'opens status=0x0 count=0x0\n'
            if attributes is not None:
                snapshot = (f'opens status=0x0 count=0x1\nopen agent=0x1 controller=0x3 attributes=0x{attributes:x} count=0x{count:x}\n').encode()
            needle = ('protocol guid=' + GOP + '\n').encode()
            raw = fixture().replace(needle, needle + snapshot)
            report = analyze(raw)
            observed = report['ownership_observations']
            self.assertEqual(observed['snapshot_count'], 1)
            self.assertFalse(observed['role_interpretation_performed'])
            self.assertEqual(len(observed['attributes']), int(attributes is not None))
            if attributes is not None:
                self.assertEqual(observed['attributes'][0]['attributes'], f'{attributes:x}')
                self.assertEqual(observed['attributes'][0]['reported_open_count'], count)
            self.assertFalse(report['authorizes_driver_detach'])

    def test_partial_ownership_cannot_be_summarized_as_complete(self):
        needle = ('protocol guid=' + GOP + '\n').encode()
        for snapshot in (b'opens status=0x0 count=0x1\n',
                         b'opens status=0x7 count=0x0\n',
                         b'opens status=0x0 count=0x0\nopens status=0x0 count=0x0\n',
                         b'opens status=0x0 count=0x1\nopen agent=0x1 controller=0x3 attributes=0x8 count=0x1truncated\n'):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                analyze(fixture().replace(needle, needle + snapshot))

    def test_duplicate_or_malformed_protocol_snapshot_rejected(self):
        needle = ('protocol guid=' + GOP + '\n').encode()
        for replacement in (needle + needle, b'protocol guid=invalid\n'):
            with self.assertRaises(ValueError):
                analyze(fixture().replace(needle, replacement))

    def test_orphan_open_records_rejected(self):
        for row in (b'opens status=0x7 count=0x0\n',
                    b'open agent=0x1 controller=0x3 attributes=0x8 count=0x1\n'):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'no protocol'):
                analyze(fixture().replace(b'handle id=0x3\n', b'handle id=0x3\n' + row))

    def test_same_agent_driver_and_shared_console_child_are_distinct_records(self):
        # Abstract the #20 relationship, using only synthetic handles/identity:
        # one agent opens a physical child as driver and names the shared
        # console as its child controller. This is not two alternate agents.
        snapshot = (('protocol guid=' + TEXT + '\n').encode() +
                    b'opens status=0x0 count=0x2\n'
                    b'open agent=0x4 controller=0x3 attributes=0x10 count=0x1\n'
                    b'open agent=0x4 controller=0x1 attributes=0x8 count=0x1\n'
                    b'handle id=0x4\n'
                    b'protocol guid=18a031ab-b443-4d1a-a5c0-0c09261e9f71\n')
        raw = fixture().replace(b'capture-complete=1\n', snapshot + b'capture-complete=1\n')
        raw = raw.replace(b'handles status=0x0 count=0x3', b'handles status=0x0 count=0x4')
        report = analyze(raw)
        summary = report['ownership_observations']
        self.assertEqual({row['attributes'] for row in summary['attributes']}, {'8', '10'})
        self.assertEqual({row['protocol'] for row in summary['attributes']}, {TEXT})
        self.assertEqual(sum(row['records'] for row in summary['attributes']), 2)
        self.assertFalse(summary['role_interpretation_performed'])
        self.assertFalse(report['authorizes_driver_detach'])


if __name__ == '__main__':
    unittest.main()
