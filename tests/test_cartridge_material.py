"""Synthetic material records and interrupted-transaction fixtures, no hardware."""
import ast
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'owner-maintenance'))
import cartridge_codec as codec
import cartridge_material as module
from test_cartridge_decode import IMAGE, NAME, record


def fixture():
    rec = record()
    rec.update(ResinID='FLGPCL02', OriginalVolume_mL=1000, UnknownPrivateField='preserve')
    plain = bytes(range(21)) + b'FLGPCL02' + b'\x10\x20\x30\x40'
    image = bytearray(IMAGE)
    image[6:10] = struct.pack('<I', codec.checksum(plain))
    image[10:43] = codec._decrypt(codec.derive_key(rec['SecretKey'], NAME), image[2:6]*2, plain, 10)
    return bytes(image), rec


class Memory(object):
    def __init__(self, fail=None):
        self.before, self.rec = fixture()
        self.target, revised, changes = module.candidate(self.before, self.rec, NAME)
        self.image, self.file = self.before, b'old'
        self.fail, self.failed = fail, False
        self.events, self.calls = {}, []

    def guard(self):
        pass

    def exclusion(self):
        pass

    def read_image(self):
        return self.image

    def read_mirror(self):
        return self.file

    def write_mirror(self, data):
        self.calls.append(('file', data))
        self.file = data
        self.inject('file')

    def write_material_rows(self, offset, data):
        self.calls.append(('row', offset))
        end = offset + len(data)
        self.image = self.image[:offset] + data + self.image[end:]
        self.inject(offset)

    def inject(self, where):
        if where == self.fail and not self.failed:
            self.failed = True
            raise IOError('Synthetic interrupted write')

    def run(self):
        module.commit_material(self, self.before, self.target, b'old', b'new',
                               lambda k, v: self.events.update({k: v}))


class MaterialTests(unittest.TestCase):
    def test_only_material_and_checksum_change(self):
        image, rec = fixture()
        target, revised, changes = module.candidate(image, rec, NAME)
        self.assertEqual(module.material(target, revised, NAME), 'FLGPCL04')
        self.assertEqual({k for k in rec if rec[k] != revised[k]}, {'ResinID'})
        self.assertEqual(target[64:], image[64:])
        self.assertEqual(codec.decode(target, revised, NAME), codec.decode(image, rec, NAME))
        self.assertEqual(set(changes), {6, 8, 38})

    def test_bad_source_rejected(self):
        image, rec = fixture()
        for field, value in [('ResinID', 'FLGPCL04'), ('OriginalVolume_mL', 2000),
                             ('WriteCount', 1), ('SecretKey', 'wrong')]:
            revised = dict(rec)
            revised[field] = value
            with self.assertRaises(ValueError):
                module.candidate(image, revised, NAME)

    def test_ro_mirror_mismatch(self):
        image, rec = fixture()
        target, revised, changes = module.candidate(image, rec, NAME)
        with self.assertRaises(ValueError):
            module.candidate(target, rec, NAME)

    def test_success_order(self):
        memory = Memory()
        memory.run()
        self.assertEqual(memory.calls, [('file', b'new'), ('row', 24), ('row', 0)])
        self.assertEqual(memory.image, memory.target)
        self.assertEqual(memory.events['full_target'], 'PASS')

    def test_rollback_each_write(self):
        for failure in ('file', 24, 0):
            with self.subTest(failure=failure):
                memory = Memory(failure)
                with self.assertRaises(IOError):
                    memory.run()
                self.assertEqual(memory.image, memory.before)
                self.assertEqual(memory.file, b'old')
                self.assertEqual(memory.events['rollback'], 'PASS')

    def test_readback_mismatch_rollback(self):
        class Corrupt(Memory):
            def write_material_rows(self, offset, data):
                super().write_material_rows(offset, data)
                if not self.failed:
                    self.failed = True
                    image = bytearray(self.image)
                    image[offset] ^= 1
                    self.image = bytes(image)
        memory = Corrupt()
        with self.assertRaises(ValueError):
            memory.run()
        self.assertEqual(memory.image, memory.before)
        self.assertEqual(memory.events['rollback'], 'PASS')

    def test_unexpected_identity_or_usage_edit_refused(self):
        for offset in (0, 5, 20, 64, 96, 127):
            memory = Memory()
            target = bytearray(memory.target)
            target[offset] ^= 1
            memory.target = bytes(target)
            with self.assertRaises(ValueError):
                memory.run()
            self.assertEqual(memory.calls, [])

    def test_python35_grammar(self):
        ast.parse((ROOT / 'owner-maintenance/cartridge_material.py').read_text(), feature_version=(3, 5))


if __name__ == '__main__':
    unittest.main()
