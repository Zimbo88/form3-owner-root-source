"""Synthetic counter deltas; no workload, process controls or device contact."""
import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'owner-ui'))
from panel_data import CpuUsage
class CpuUsageTests(unittest.TestCase):
 def test_two_samples_exclude_idle_iowait_and_guest_double_count(self):
  c=CpuUsage();self.assertIsNone(c.sample('cpu 100 0 20 800 20 0 0 0 50 0',1,100)['percent'])
  result=c.sample('cpu 120 0 30 860 30 0 0 0 70 0',6,105)
  self.assertEqual(result['percent'],30);self.assertEqual(result['interval_seconds'],5)
 def test_idle_only_zero_is_a_valid_measurement(self):
  c=CpuUsage();c.sample('cpu 1 0 0 1',1,100)
  self.assertEqual(c.sample('cpu 1 0 0 11',6,105)['percent'],0)
 def test_regression_gap_and_clock_reset_invalidate(self):
  for raw,when in [('cpu 9 0 0 10',6),('cpu 20 0 0 20',0),('cpu 20 0 0 20',122)]:
   c=CpuUsage();c.sample('cpu 10 0 0 10',1,100)
   self.assertEqual(c.sample(raw,when,105)['reason'],'DISCONTINUITY')
 def test_invalid_or_missing_counters_do_not_become_zero(self):
  for raw in [None,'','cpu0 1 2 3 4','cpu 1 2','cpu 1 -1 2 3','cpu 1.0 2 3 4','cpu '+('9'*30)+' 1 2 3','x'*65537]:
   self.assertIsNone(CpuUsage().sample(raw,1,100)['percent'])
 def test_rapid_read_retains_original_timestamp_and_no_progress_invalidates(self):
  c=CpuUsage();c.sample('cpu 1 0 0 1',1,100)
  first=c.sample('cpu 2 0 0 2',6,105)
  self.assertEqual(c.sample('cpu 2 0 0 2',6.1,106),first)
  self.assertEqual(c.sample('cpu 2 0 0 2',7,107)['reason'],'NO_COUNTER_PROGRESS')
 def test_nonfinite_time_is_unknown(self):
  for value in [float('nan'),float('inf'),True,None]:
   self.assertEqual(CpuUsage().sample('cpu 1 2 3 4',value,100)['reason'],'INVALID_SOURCE')
