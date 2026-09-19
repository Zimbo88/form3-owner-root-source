import json
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from sensor_event_model import HeaterEvidence, replay


class SensorEvents(unittest.TestCase):
    def test_error_flag_excludes_sample_and_retains_invalid_old_property(self):
        m=HeaterEvidence();m.sample(0,False,30);m.timer(1)
        m.sample(2,True,900);self.assertFalse(m.timer(3))
        s=m.snapshot(3);self.assertEqual(s['value'],30)
        self.assertEqual(s['quality'],'INVALID');self.assertFalse(s['safe_for_actuation'])

    def test_average_and_change_suppression_do_not_mean_missing_measurement(self):
        m=HeaterEvidence();m.sample(0,False,20);m.sample(1,False,40)
        self.assertTrue(m.timer(2));self.assertEqual(m.snapshot(2)['value'],30)
        m.sample(3,False,30.005);self.assertFalse(m.timer(4))
        s=m.snapshot(4);self.assertEqual(s['sample_time'],3)
        self.assertEqual(s['property_change_time'],2);self.assertEqual(s['quality'],'FRESH_SAMPLE_EVIDENCE')

    def test_timer_without_samples_does_not_refresh(self):
        m=HeaterEvidence();m.sample(0,False,30);m.timer(1);m.timer(20)
        self.assertEqual(m.snapshot(20)['quality'],'STALE')

    def test_owner_change_and_clock_regression_invalidate_cache(self):
        m=HeaterEvidence();m.sample(5,False,30);m.timer(6)
        with self.assertRaises(ValueError):m.snapshot(4)
        self.assertEqual(m.snapshot(7)['quality'],'UNAVAILABLE')
        result=replay(json.dumps([{'event':'sample','time':0,'error':False,'value':30},
                                  {'event':'timer','time':1},{'event':'owner_changed','time':2}]).encode())
        self.assertIsNone(result['samples'][-1]['value'])

    def test_malformed_and_resource_bounds(self):
        for value in (float('nan'),float('inf'),True,1e20):
            with self.assertRaises(ValueError):HeaterEvidence().sample(0,False,value)
        for raw in (b'[',b'[{}]',b'[{"event":"timer","time":0,"time":1}]',
                    b'[{"event":"timer","time":0,"secret-key":"private"}]',b' '*1048577):
            with self.assertRaises(ValueError):replay(raw)
        m=HeaterEvidence()
        for _ in range(4096):m.sample(0,False,1)
        with self.assertRaises(ValueError):m.sample(0,False,1)

    def test_error_recovery_does_not_invent_property_update(self):
        m=HeaterEvidence();m.sample(0,False,30);m.timer(1);m.sample(2,True,50)
        m.sample(3,False,30);self.assertFalse(m.timer(4))
        self.assertEqual(m.snapshot(4)['property_change_time'],1)
        self.assertEqual(m.snapshot(4)['provenance'],'OFFLINE_MODEL')
