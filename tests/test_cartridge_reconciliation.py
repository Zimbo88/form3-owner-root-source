"""Authored state-model fixtures; no vendor code, keys, chip data or device I/O."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import model_cartridge_reconciliation as model


def usage(volume=100.0, seconds=200, count=30, writes=40):
    return dict(zip(model.FIELDS, (volume, seconds, count, writes)))


class ReconciliationTests(unittest.TestCase):
    def test_zeroing_only_incoming_mirror_does_not_lower_usage(self):
        result = model.merge_usage(usage(), usage(0, 0, 0, 0))
        self.assertEqual(result['usage'], usage())

    def test_old_incoming_usage_returns_to_zero_receiver(self):
        result = model.merge_usage(usage(0, 0, 0, 0), usage())
        self.assertEqual(result['usage'], usage(writes=0))

    def test_crossing_maxima(self):
        self.assertEqual(model.merge_usage(usage(30, 20, 10, 3), usage(10, 40, 30, 8))['usage'],
                         usage(30, 40, 30, 3))

    def test_incoming_write_count_does_not_replace_receiver(self):
        for incoming in (0, 1, 0xffffffff):
            self.assertEqual(model.merge_usage(usage(writes=7), usage(writes=incoming))['usage']['WriteCount'], 7)

    def test_fractional_quantization_does_not_invent_precision(self):
        result = model.merge_usage(usage(0), usage(0.05))
        self.assertEqual(result['usage']['EstimatedVolumeDispensed_ml'], 0.05)
        self.assertEqual(result['quantized_volume_if_recomputed_100uL'], 0)

    def test_known_representable_boundaries(self):
        maximum = usage(6553.5, 65535, 0xffffff, 0xffffffff)
        self.assertEqual(model.merge_usage(maximum, maximum)['usage'], maximum)

    def test_unknown_nonfinite_and_out_of_range_rejected(self):
        for field in model.FIELDS:
            for value in (None, True, -1, float('nan'), float('inf'), 1e20):
                bad = usage()
                bad[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    model.merge_usage(bad, usage())
        with self.assertRaises(ValueError):
            model.merge_usage({}, usage())

    def test_counter_floats_rejected(self):
        with self.assertRaises(ValueError):
            model.merge_usage(usage(count=3.0), usage())

    def test_both_valid_prefer_A(self):
        result = model.load_decision(True, True)
        self.assertEqual(result['selected_copy'], 'A')
        self.assertFalse(result['write_count_used_for_selection'])

    def test_only_one_valid_copy(self):
        for va, vb, expected in ((True, False, 'A'), (False, True, 'B')):
            result = model.load_decision(va, vb)
            self.assertEqual(result['selected_copy'], expected)
            self.assertEqual(result['owner_review'], 'blocked_invalid_copy')

    def test_blank_other_copy_does_not_override_valid_copy(self):
        self.assertEqual(model.load_decision(True, False, b_blank=True)['selected_copy'], 'A')
        self.assertEqual(model.load_decision(False, True, a_blank=True)['selected_copy'], 'B')

    def test_invalid_records_never_get_owner_authorization(self):
        for ba, bb in ((False, False), (True, False), (False, True), (True, True)):
            result = model.load_decision(False, False, ba, bb)
            self.assertIsNone(result['selected_copy'])
            self.assertFalse(result['native_write_authorized'])
            self.assertFalse(result['dispensing_authorized'])
            self.assertEqual(result['owner_review'], 'blocked_invalid_copy')

    def test_native_initialization_is_not_implemented(self):
        result = model.load_decision(False, False, a_blank=True)
        self.assertEqual(result['modeled_native_path'], 'native_initialization_path_not_reproduced')
        self.assertNotIn('usage', result)

    def test_ambiguous_classification_rejected(self):
        for args in ((1, True), (None, False), (True, False, True), (False, True, False, True)):
            with self.assertRaises(ValueError):
                model.load_decision(*args)

    def test_unknown_sensitive_fields_not_exported(self):
        value = usage()
        value['SECRET-IN-FIELD-NAME'] = 'private'
        value['SecretKey'] = 'also-private'
        result = json.dumps(model.merge_usage(value, usage()))
        self.assertNotIn('SECRET-IN-FIELD-NAME', result)
        self.assertNotIn('private', result)

    def test_demo_is_explicit_and_never_authorizes_changes(self):
        report = model.demo()
        self.assertEqual(report['data_class'], 'SYNTHETIC')
        self.assertFalse(report['hardware_contact'])
        for result in report['scenarios'].values():
            self.assertFalse(result['native_write_authorized'])


if __name__ == '__main__':
    unittest.main()
