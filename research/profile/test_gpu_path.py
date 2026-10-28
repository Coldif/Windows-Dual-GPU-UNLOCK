"""Exact capture paths and pinned ancestry; synthetic inputs only."""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


contract=load('gpu_path_test_subject','gpu_path.py')
vectors=load('gpu_path_test_vectors','test_gpu_path_contract.py')
data=load('gpu_path_test_captures','test_local_topology.py')


class GpuPathTests(unittest.TestCase):
    def test_capture_path_is_exact_while_read_bound_may_extend(self):
        for nodes in (1,2,16):
            for hid,uid in ((3,0),(8,0xffffffff)):
                path=vectors.path(nodes,hid,uid)
                info=contract.decode_gpu_display_path(path)
                self.assertEqual(info['controller_bytes'],12+nodes*6)
                self.assertEqual(info['path_bytes'],len(path))
                self.assertEqual(info['root_uid'],uid)
                self.assertEqual(len(info['pci_nodes']),nodes)
                with self.assertRaises(ValueError):contract.decode_gpu_display_path(path+b'\0')
                self.assertEqual(contract.decode_gpu_display_path(path+bytes(256-len(path)),allow_trailing=True),info)

    def test_every_bridge_and_root_is_pinned_but_output_adr_is_discovered(self):
        path=vectors.path(3,3,42)
        for offset in (6,8,16,17,22,23):
            changed=bytearray(path);changed[offset]^=11 if offset==6 else 1
            contract.decode_gpu_display_path(bytes(changed))  # Still a legal, different route.
            self.assertFalse(contract.same_gpu_display_route(path,bytes(changed)))
        changed=bytearray(path);changed[-8]^=1
        self.assertTrue(contract.same_gpu_display_route(path,bytes(changed)))
        self.assertFalse(contract.same_gpu_display_route(path,vectors.path(4,3,42)))

    def test_invalid_endpoints_adrs_and_nodes_are_refused(self):
        good=vectors.path(2)
        variants=[vectors.path(0),vectors.path(17),good[:-4],good[:-4]+bytes.fromhex('7f010400'),
                  good[:-4]+good[-12:],good[:-4]+bytes.fromhex('0101060000007fff0400'),
                  good[:12]+good[:12]+good[12:]]
        for offset,value in ((16,8),(17,32),(22,1),(23,1),(26,12),(26,4),(26,7)):
            changed=bytearray(good);changed[offset]=value;variants.append(bytes(changed))
        for changed in variants:
            with self.subTest(changed=changed),self.assertRaises(ValueError):contract.decode_gpu_display_path(changed)

    def test_generator_refuses_illegal_root_node_values(self):
        for bad in ('010106000803','010106000120'):
            text=data.synthetic_capture().replace('010106000103',bad)
            with self.assertRaisesRegex(data.mp.Refused,'bounded ACPI/PCI/ADR'):
                data.analyze(text)

    def test_longer_route_stays_closed_until_backend_length_integration(self):
        text=data.synthetic_capture().replace('path-node raw=010106000103',
            'path-node raw=010106000103\npath-node raw=010106000004')
        with self.assertRaisesRegex(data.mp.Refused,'other topologies are unreviewed'):
            data.analyze(text)


if __name__=='__main__':unittest.main()
