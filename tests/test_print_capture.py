"""Synthetic observer fixtures; never contacts hardware, D-Bus or a remote host."""
import base64,hashlib,json,os,sys,tempfile,unittest,ast
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import print_capture_agent as remote
import record_print_session as host
import print_state_snapshot as state
import record_print_state as state_host

class CaptureReadSafety(unittest.TestCase):
 def test_target_python35(self):
  ast.parse(Path(remote.__file__).read_text(),feature_version=(3,5))
 def test_log_allowlist_refuses_keys_paths_and_models(self):
  for x in ('Sauron.log','daguerreHeater_v1.csv','fluentbit_system_thermal.msgpack','syslog','CandyBus.log.1.gz'):self.assertTrue(remote.allowed_name(x))
  for x in ('../secret.log','/etc/shadow','private.pem','SecretKey','model.stl','state.sqlite','x\n.log','x.log\n'):self.assertFalse(remote.allowed_name(x))
 def test_signal_filters_do_not_invoke_vendor_methods(self):
  self.assertTrue(all("type='signal'" in m for m in remote.MATCHES))
  self.assertFalse(any("type='method_call'" in m for m in remote.MATCHES))
 def test_existing_append_and_truncate_read_only(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'log';p.write_bytes(b'abc');r=remote.Reader(str(p))
   try:
    first=r.next();self.assertEqual(base64.b64decode(first['data_b64']),b'abc');self.assertTrue(first['baseline'])
    with p.open('ab') as f:f.write(b'next')
    second=r.next();self.assertEqual(second['offset'],3);self.assertFalse(second['baseline'])
    p.write_bytes(b'x');third=r.next();self.assertTrue(third['truncated']);self.assertEqual(third['generation'],1);self.assertEqual(third['offset'],0)
   finally:r.close()
   self.assertEqual(p.read_bytes(),b'x')
 def test_rename_rotation_retains_old_reader(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'log';p.write_bytes(b'old');r=remote.Reader(str(p));r.next()
   try:
    p.rename(Path(t)/'log.1');p.write_bytes(b'new')
    with (Path(t)/'log.1').open('ab') as f:f.write(b'tail')
    self.assertEqual(base64.b64decode(r.next()['data_b64']),b'tail')
    n=remote.Reader(str(p))
    try:self.assertNotEqual(n.inode,r.inode);self.assertEqual(base64.b64decode(n.next()['data_b64']),b'new')
    finally:n.close()
   finally:r.close()
 def test_symlink_and_non_regular_refused(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'original').write_bytes(b'unchanged');(p/'link').symlink_to('original');os.mkfifo(str(p/'fifo'))
   with self.assertRaises(OSError):remote.Reader(str(p/'link'))
   with self.assertRaises(ValueError):remote.Reader(str(p/'fifo'))
 def test_oversized_history_is_explicitly_bounded(self):
  with tempfile.TemporaryDirectory() as t,mock.patch.object(remote,'BASELINE_TAIL',4):
   p=Path(t)/'log';p.write_bytes(b'123456789');r=remote.Reader(str(p))
   try:q=r.next();self.assertEqual(q['offset'],5);self.assertEqual(q['initial_size'],9);self.assertEqual(base64.b64decode(q['data_b64']),b'6789')
   finally:r.close()
 def test_unlinked_rotation_retirement_waits_for_tail(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'log';p.write_bytes(b'old');r=remote.Reader(str(p))
   try:
    p.unlink();self.assertFalse(r.retired());r.next();self.assertFalse(r.retired())
    with mock.patch.object(remote.time,'monotonic',return_value=r.last_data+31):self.assertTrue(r.retired())
   finally:r.close()

class CaptureProtocol(unittest.TestCase):
 def event(self):
  b=b'synthetic private log'
  return {'kind':'file','device_epoch':1.0,'device_monotonic':2.0,'boot_id':'0'*8+'-'+ '0'*4+'-'+'0'*4+'-'+'0'*4+'-'+'0'*12,
  'payload':{'bytes':len(b),'data_b64':base64.b64encode(b).decode(),'sha256':hashlib.sha256(b).hexdigest()}}
 def test_hash_checked_and_raw_not_summary(self):
  e=self.event();self.assertEqual(host.validate_event(json.dumps(e)),e)
  e['payload']['sha256']='0'*64
  with self.assertRaises(ValueError):host.validate_event(json.dumps(e))
 def test_corrupt_truncated_bounds(self):
  for raw in ('{','[]',json.dumps({'kind':'arbitrary'}),'x'*(host.MAX_RECORD+1)):
   with self.assertRaises(ValueError):host.validate_event(raw)
  e=self.event();e['payload']['data_b64']='!!!'
  with self.assertRaises(ValueError):host.validate_event(json.dumps(e))
 def test_invalid_clock_and_length(self):
  e=self.event();e['device_epoch']=float('nan')
  with self.assertRaises(ValueError):host.validate_event(json.dumps(e))
  e=self.event();e['payload']['bytes']=999
  with self.assertRaises(ValueError):host.validate_event(json.dumps(e))
 def test_private_session_and_symlink_guard(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'research-private'/'session';p.mkdir(parents=True,mode=0o700)
   self.assertEqual(host.session_path(p),p)
   p.chmod(0o755)
   with self.assertRaises(ValueError):host.session_path(p)
   p.chmod(0o700);link=p.parent/'link';link.symlink_to(p,target_is_directory=True)
   with self.assertRaises(ValueError):host.session_path(link)

class ConsumableMirrorSnapshots(unittest.TestCase):
 def test_target_grammar(self):
  ast.parse(Path(state.__file__).read_text(),feature_version=(3,5))
 def test_snapshot_exact_hash_without_modifying_bytes(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'record.json';data=b'{"synthetic_private_field":"never print"}';p.write_bytes(data)
   row=state.file_snapshot(str(p),65536)
   self.assertEqual(base64.b64decode(row['data_b64']),data);self.assertTrue(row['stable_metadata'])
   self.assertEqual(state_host.validate({'files':[row]})['files'][0]['sha256'],hashlib.sha256(data).hexdigest())
   self.assertEqual(p.read_bytes(),data)
 def test_symlink_fifo_and_bound(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'record').write_bytes(b'abc');(p/'link').symlink_to('record');os.mkfifo(str(p/'fifo'))
   with self.assertRaises(OSError):state.file_snapshot(str(p/'link'),99)
   with self.assertRaises(ValueError):state.file_snapshot(str(p/'fifo'),99)
   with self.assertRaises(ValueError):state.file_snapshot(str(p/'record'),2)
 def test_host_rejects_corruption(self):
  for d in ([],{}, {'files':{}}, {'files':[]*0+[{}]*521}, {'files':[{'data_b64':'!!!','bytes':0,'sha256':'0'*64}]},
            {'files':[{'data_b64':'YWJj','bytes':3,'sha256':'0'*64}]}):
   with self.assertRaises((ValueError,KeyError)):state_host.validate(d)
 def test_only_named_mirrors_and_diagnostic_databases(self):
  self.assertEqual(state.ROOTS,('/data/Cartridges','/data/Tanks'))
  self.assertEqual(state.DATABASES,('Durations_v1.sqlite','TankCartridgeDaemon_v1.sqlite'))
  self.assertNotIn('sqlite3',Path(state.__file__).read_text())
