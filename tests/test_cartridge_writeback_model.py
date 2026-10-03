"""Native-derived synthetic observations, not a device writer or reset test."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import model_cartridge_reconciliation as model


class WritebackTests(unittest.TestCase):
    def test_exact_readback_matches(self):
        self.assertTrue(model.check_readback(b'A'*16, b'A'*16)['helper_success'])

    def test_write_error_prevents_readback_success(self):
        self.assertEqual(model.check_readback(b'A'*16, b'A'*16, write_error=True)['stage'], 'write_error')

    def test_read_error_even_when_bytes_match(self):
        self.assertEqual(model.check_readback(b'A'*16, b'A'*16, read_error=True)['stage'], 'read_error')

    def test_corrupt_and_truncated_readback(self):
        for value in (b'B'*16, b'A'*8, b'', b'A'*17):
            self.assertFalse(model.check_readback(b'A'*16, value)['helper_success'])

    def test_readback_bounds_and_types(self):
        for args in ((b'', b''), (b'A'*16, b'A'*33), ('x', b''), (b'A'*16, b'A'*16, 1)):
            with self.assertRaises(ValueError):
                model.check_readback(*args)

    def test_file_then_B_then_A(self):
        self.assertEqual(model.simulate_flush()['events'],
                         ['file_attempt', 'read_A', 'read_B', 'write_B', 'readback_B', 'write_A', 'readback_A'])

    def test_already_equal_copies_skip_chip_writes(self):
        value = model.simulate_flush(a_equal=True, b_equal=True)
        self.assertEqual(value['events'], ['file_attempt', 'read_A', 'read_B'])
        self.assertEqual(value['native_result_code'], 3)

    def test_single_changed_copy(self):
        for args, copy in (({'a_equal': True}, 'B'), ({'b_equal': True}, 'A')):
            self.assertEqual(model.simulate_flush(**args)['events'][3:], ['write_'+copy, 'readback_'+copy])

    def test_invalid_A_changes_order(self):
        for b_valid in (False, True):
            self.assertEqual(model.simulate_flush(a_valid=False, b_valid=b_valid)['events'][3:],
                             ['write_A', 'readback_A', 'write_B', 'readback_B'])

    def test_invalid_B_preserves_B_first(self):
        self.assertEqual(model.simulate_flush(b_valid=False)['events'][3], 'write_B')

    def test_first_failure_does_not_touch_other_copy(self):
        value = model.simulate_flush(fail_copy='B')
        self.assertEqual(value['events'][3:], ['write_B', 'write_B'])
        self.assertTrue(value['native_error_returned'])
        self.assertEqual(value['native_result_code'], 5)

    def test_second_failure_leaves_partial_progress(self):
        value = model.simulate_flush(fail_copy='A')
        self.assertEqual(value['events'][3:], ['write_B', 'readback_B', 'write_A'])
        self.assertEqual(value['modeled_copies_current'], {'A': False, 'B': True})
        self.assertTrue(value['native_error_returned'])

    def test_only_copy_failure_retries_within_observed_budget(self):
        self.assertEqual(model.simulate_flush(b_equal=True, fail_copy='A')['events'][3:], ['write_A', 'write_A'])

    def test_file_failure_is_not_an_owner_commit(self):
        value = model.simulate_flush(file_error=True)
        self.assertFalse(value['native_error_returned'])
        self.assertEqual(value['owner_review'], 'blocked_file_error')
        self.assertFalse(value['all_store_commit_proven'])
        self.assertFalse(value['native_write_authorized'])

    def test_unknown_or_inconsistent_state_rejected(self):
        for args in ({'a_valid': None}, {'b_equal': 1}, {'fail_copy': 'C'},
                     {'a_valid': False, 'a_equal': True}):
            with self.assertRaises(ValueError):
                model.simulate_flush(**args)

    def test_no_synthetic_success_grants_dispensing(self):
        value = model.simulate_flush()
        self.assertFalse(value['native_write_authorized'])
        self.assertFalse(value['dispensing_authorized'])


if __name__ == '__main__':
    unittest.main()
