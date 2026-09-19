"""Authored Git-source packaging policy; no private/runtime blobs are fixtures."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from package_developer_source import validate_member

class SourcePolicy(unittest.TestCase):
    def test_regular_authored_source_is_accepted(self):
        self.assertEqual(len(validate_member('owner-ui/example.py','100644',b'print("fixture")\n')),64)
    def test_symlink_device_traversal_and_private_paths_refused(self):
        for n,m in [('../escape','100644'),('research-private/data.json','100644'),('build/file','100644'),('link','120000'),('sub','160000')]:
            with self.assertRaises(ValueError):validate_member(n,m,b'fixture')
    def test_binary_and_actual_key_material_refused(self):
        for n,d in [('program',b'\x7fELFfixture'),('image.img',b'fixture'),('key.txt',b'-----BEGIN PRIVATE KEY-----\n'+b'A'*80+b'\n')]:
            with self.assertRaises(ValueError):validate_member(n,'100644',d)
    def test_vendor_resources_rejected_even_under_harmless_names(self):
        for data in (b'qresfixture',b'\xd0\x0d\xfe\xedfixture',b'PK\x03\x04fixture',b'\xfd7zXZ\x00fixture',b'!<arch>\nfixture'):
            with self.subTest(data=data[:4]):
                with self.assertRaises(ValueError):validate_member('example.txt','100644',data)
        for name in ('clock.rcc','chip.raw','image.rgba','archive.formlogs','state.sqlite3'):
            with self.assertRaises(ValueError):validate_member(name,'100644',b'fixture')
    def test_binary_patch_payload_rejected_but_authored_recipe_allowed(self):
        for data in (b'BSDIFF40fixture',b'\xd6\xc3\xc4fixture',b'diff --git a/example b/example\nGIT binary patch\nliteral 8\nfixture\n'):
            with self.assertRaises(ValueError):validate_member('change.patch','100644',data)
        self.assertEqual(len(validate_member('recipe.py','100644',b'# Read and hash the owner-supplied file; write a new local derivative.\n')),64)

class RuntimeListPolicy(unittest.TestCase):
    def test_checksums_are_sorted_and_only_metadata(self):
        import json
        from package_developer_source import runtime_checksums
        raw=json.dumps({'files':[{'path':'usr/bin/python3.5','bytes':5,'sha256':'a'*64},{'path':'lib/ld.so','bytes':7,'sha256':'b'*64}]}).encode()
        self.assertEqual(runtime_checksums(raw),('b'*64+'  lib/ld.so\n'+'a'*64+'  usr/bin/python3.5\n').encode())
    def test_corrupt_runtime_lists_refused(self):
        import json
        from package_developer_source import runtime_checksums
        good={'path':'lib/ld.so','bytes':7,'sha256':'b'*64}
        cases=[{'files':[]},{'files':[good,good]},{'files':[dict(good,path='../escape')]},{'files':[dict(good,path='lib/name\nsecret')]},{'files':[dict(good,sha256='bad')]},{'files':[dict(good,bytes=True)]}]
        for obj in cases:
            with self.assertRaises(ValueError):runtime_checksums(json.dumps(obj).encode())
