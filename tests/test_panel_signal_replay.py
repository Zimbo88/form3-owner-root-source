"""Sealed synthetic capture replay; no private capture or printer dependency."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from replay_panel_signals import PanelReplay, replay
import test_post_print_review as print_fixture
from test_post_print_review import signal


class ReplayTests(unittest.TestCase):
    def test_counts_without_identifiers_or_raw_values(self):
        r=PanelReplay();r.boot('synthetic-private-boot')
        r.signal(signal('statesChanged',' string "synthetic-job"\n array [\n string "PRINT_IDLE"\n string "synthetic-private.flx"\n ]'))
        result=r.result()[0]
        self.assertEqual(result['counts']['states_frames'],1)
        self.assertEqual(result['counts']['states_value_available'],1)
        self.assertEqual(result['counts']['states_incomplete_projection'],1)
        self.assertNotIn('synthetic',json.dumps(result))
        self.assertNotIn('PRINT_IDLE',json.dumps(result))

    def test_each_frame_is_independent_and_truncation_stays_unavailable(self):
        r=PanelReplay();r.boot('one')
        r.signal(signal('currentlyPrintingLayerChanged',' string ""\n int32 8'))
        r.signal(signal('currentlyPrintingLayerChanged',' string ""\n int32'))
        self.assertEqual(r.result()[0]['counts'],{'layers_frames':2,'layers_value_available':1})

    def test_stream_hash_and_undelimited_tail_are_not_bypassed(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);stream=print_fixture.ProgressTests().fixture(root)
            result=replay(root)
            self.assertEqual(result['observations']['counts']['layers_value_available'],1)
            self.assertEqual(result['observations']['unique_boots'],1)
            self.assertEqual(result['undelimited_tail_frames_omitted'],1)
            self.assertFalse(result['hardware_contact'])
            self.assertNotIn('private',json.dumps(result))
            stream.write_bytes(stream.read_bytes()+b'\n')
            with self.assertRaises(ValueError):replay(root)

    def test_repeated_boot_identity_and_budget(self):
        r=PanelReplay()
        for i in range(64):r.boot(str(i));r.boot(str(i))
        self.assertEqual(r.result()[0]['unique_boots'],64)
        with self.assertRaises(ValueError):r.boot('overflow')
