"""Synthetic host-only fixtures: no proprietary profiles, credentials or devices."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('profiles', Path(__file__).resolve().parents[1] / 'tools/compare_material_profiles.py')
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'profiles'
        self.root.mkdir()
        self.value = {'Material_Scene': {'identifier_materialCode': 'FLTEST01'},
                      'Material_Daguerre_Print': {'energyDensity_fill_mJpcm2': 10,
                                                 'earlyLayerExposures_mJpcm2': [30, 20]},
                      'Daguerre_Print': {'wipe_speed_mmps': 2},
                      'Material_Form2_Print': {}}

    def add(self, name='a', value=None, job=None):
        d = self.root / name
        d.mkdir()
        (d / 'all_knobs_settings.json').write_text(json.dumps(self.value if value is None else value))
        (d / 'overridden_knobs_settings.json').write_text('{}')
        if job is not None:
            (d / 'Job.json').write_text(json.dumps(job))
        return d

    def test_constant_arrays_count_once(self):
        self.add(); self.add('b')
        r = profiles.inspect(self.root)
        self.assertEqual(r['groups']['Material_Daguerre_Print'],
                         {'union': 2, 'constant': 2, 'varying_or_absent': 0, 'absent_in_some': 0})
        self.assertFalse(r['safe_to_apply'])

    def test_variation_missing_and_null_are_distinct(self):
        self.add()
        v = copy.deepcopy(self.value)
        v['Material_Daguerre_Print']['energyDensity_fill_mJpcm2'] = None
        del v['Material_Daguerre_Print']['earlyLayerExposures_mJpcm2']
        self.add('b', v)
        self.assertEqual(profiles.inspect(self.root)['groups']['Material_Daguerre_Print']['varying_or_absent'], 2)

    def test_identity_conflict_visible(self):
        self.add(job={'MaterialCode': 'FLTEST02'})
        self.assertFalse(profiles.inspect(self.root)['profiles'][0]['job']['material_match'])

    def test_missing_identity_unknown(self):
        self.add(job={'MaterialCode': 'private-device-label'})
        r = profiles.inspect(self.root)['profiles'][0]['job']
        self.assertIsNone(r['material_match'])
        self.assertIsNone(r['material_code'])

    def test_unknown_keys_and_values_never_emitted(self):
        v = copy.deepcopy(self.value)
        v['private-opaque-key'] = {'private-token': 'do-not-emit'}
        v['Material_Daguerre_Print']['energyDensity_fill_mJpcm2'] = 'do-not-emit'
        self.add(value=v, job={'MaterialCode': 'secret'} )
        text = json.dumps(profiles.inspect(self.root, True))
        for secret in ('private-opaque-key', 'private-token', 'do-not-emit', 'secret'):
            self.assertNotIn(secret, text)

    def test_selected_values_explicit(self):
        self.add()
        self.assertNotIn('selected_numeric_values', profiles.inspect(self.root)['profiles'][0])
        r = profiles.inspect(self.root, True)['profiles'][0]
        self.assertEqual(r['selected_numeric_values']['Material_Daguerre_Print.energyDensity_fill_mJpcm2'], 10)

    def test_duplicate_json_rejected(self):
        d = self.add(); (d / 'all_knobs_settings.json').write_text('{"a":1,"a":2}')
        with self.assertRaises(ValueError): profiles.inspect(self.root)

    def test_truncated_json_rejected(self):
        d = self.add(); (d / 'all_knobs_settings.json').write_text('{"a":')
        with self.assertRaises(ValueError): profiles.inspect(self.root)

    def test_nonfinite_and_nested_bounds(self):
        d = self.add()
        for text in ('{"a":NaN}', '{"a":1e999}', '{"a":' + '[' * 40 + '0' + ']' * 40 + '}'):
            (d / 'all_knobs_settings.json').write_text(text)
            with self.assertRaises(ValueError): profiles.inspect(self.root)

    def test_oversize_rejected(self):
        d = self.add(); (d / 'all_knobs_settings.json').write_bytes(b' ' * (profiles.MAX_BYTES + 1))
        with self.assertRaises(ValueError): profiles.inspect(self.root)

    def test_symlink_profile_directory_rejected(self):
        self.add(); (self.root / 'b').symlink_to(self.root / 'a', target_is_directory=True)
        with self.assertRaises(ValueError): profiles.inspect(self.root)

    def test_symlink_input_file_rejected(self):
        d = self.add(); (d / 'Job.json').symlink_to(d / 'all_knobs_settings.json')
        with self.assertRaises(ValueError): profiles.inspect(self.root)

    def test_excess_profiles_rejected(self):
        for i in range(profiles.MAX_PROFILES + 1): (self.root / str(i)).mkdir()
        with self.assertRaises(ValueError): profiles.inspect(self.root)

    def test_empty_collection_rejected(self):
        with self.assertRaises(ValueError): profiles.inspect(self.root)

    def test_output_new_private_no_overwrite(self):
        target = Path(self.tmp.name) / 'out.json'
        profiles.write_report(target, {'safe': True})
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError): profiles.write_report(target, {})
        self.assertEqual(json.loads(target.read_text()), {'safe': True})

    def test_output_symlink_escape_rejected(self):
        link = Path(self.tmp.name) / 'link'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): profiles.write_report(link / 'out.json', {})
        self.assertFalse((self.root / 'out.json').exists())

    def test_read_preserves_inputs(self):
        d = self.add(); before = {p.name:p.read_bytes() for p in d.iterdir()}
        profiles.inspect(self.root)
        self.assertEqual(before, {p.name:p.read_bytes() for p in d.iterdir()})


if __name__ == '__main__':
    unittest.main()
