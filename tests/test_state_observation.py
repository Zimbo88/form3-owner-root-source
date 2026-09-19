import json,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from state_observation_model import StateObservation,replay
class StateObservationTests(unittest.TestCase):
 def seeded(self):
  m=StateObservation();m.event({'kind':'owner','time':0,'owner':':1.1'})
  m.event({'kind':'states','time':1,'owner':':1.1','states':['SAURON_IDLE','HIGH_LEVEL_IDLE']});return m
 def test_idle_labels_never_authorize_power(self):
  r=self.seeded().snapshot(2);self.assertFalse(r['safe_idle_proven']);self.assertEqual(r['quality'],'RECENT_RECEIPT')
 def test_disconnect_and_new_owner_invalidate(self):
  for event in [{'kind':'disconnect','time':2},{'kind':'owner','time':2,'owner':':1.2'}]:
   m=self.seeded();r=m.event(event);self.assertEqual(r['quality'],'UNAVAILABLE')
 def test_old_owner_event_cannot_replace_current_state(self):
  m=self.seeded();r=m.event({'kind':'states','time':2,'owner':':1.2','states':['SAURON_NONE']})
  self.assertEqual(r['ignored_event_reason'],'WRONG_OR_MISSING_OWNER');self.assertIn('SAURON_IDLE',r['labels'])
 def test_silence_and_empty_states_are_not_idle(self):
  m=self.seeded();self.assertEqual(m.snapshot(12)['quality'],'STALE')
  self.assertEqual(m.event({'kind':'states','time':13,'owner':':1.1','states':[]})['quality'],'UNAVAILABLE')
 def test_unknown_label_drops_whole_claim_and_redacts(self):
  m=self.seeded();r=m.event({'kind':'states','time':2,'owner':':1.1','states':['SAURON_IDLE','synthetic-private-value']})
  self.assertIsNone(r['labels']);self.assertNotIn('synthetic-private-value',json.dumps(r))
 def test_clock_reset_clears_identity_and_state(self):
  m=self.seeded()
  with self.assertRaises(ValueError):m.snapshot(0)
  self.assertIsNone(m.owner);self.assertIsNone(m.labels)
 def test_bad_shape_and_size_refused(self):
  for raw in [b'{',b'{}',b'['+b'{} '*600000+b']',json.dumps([{}]*4097).encode(),b'[{"kind":"snapshot","kind":"states","time":0}]']:
   with self.assertRaises(ValueError):replay(raw)
 def test_reconnect_requires_a_new_observation(self):
  m=self.seeded();m.event({'kind':'disconnect','time':2});m.event({'kind':'owner','time':3,'owner':':1.3'})
  self.assertEqual(m.snapshot(4)['quality'],'UNAVAILABLE')
