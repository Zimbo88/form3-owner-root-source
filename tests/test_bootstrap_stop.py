"""Authored stop/restart protocol fixtures; never signal or run a vendor process."""
import io,json,os,stat,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-maintenance'))
import bootstrap as b

class StopTests(unittest.TestCase):
    def setUp(self):
        self.receipt={'pid':12345,'start':'2000'}
        self.identity={'start':'2000','args':[b.PYTHON.encode(),b'-E',b'-B',b'-S',(b.BASE+'/bootstrap/bootstrap.py').encode(),b'run']}
    def test_stop_requests_identity_and_waits_for_lock_release(self):
        with mock.patch.multiple(b,normal_context=mock.Mock(),trusted=mock.Mock(return_value=json.dumps(self.receipt).encode()),
             process_identity=mock.Mock(return_value=self.identity),supervisor_lock_released=mock.Mock(side_effect=[False,False,True]),atomic=mock.Mock()) as patches, \
             mock.patch.object(b.time,'sleep') as sleep,mock.patch.object(b.os,'kill',side_effect=AssertionError('No signal permitted')):
            b.stop_supervisor()
            self.assertEqual(sleep.call_count,2)
            self.assertEqual(json.loads(b.atomic.call_args[0][1]),self.receipt)
    def test_initial_pid_reuse_or_wrong_arguments_never_signalled(self):
        for changed in ({'start':'2001','args':self.identity['args']},{'start':'2000','args':[b'/unrelated']}):
            with mock.patch.multiple(b,normal_context=mock.Mock(),trusted=mock.Mock(return_value=json.dumps(self.receipt).encode()),
                 process_identity=mock.Mock(return_value=changed),atomic=mock.Mock()) as patches, \
                 mock.patch.object(b.os,'kill',side_effect=AssertionError('No signal permitted')):
                with self.assertRaises(ValueError):b.stop_supervisor()
                b.atomic.assert_not_called()
    def test_pid_reuse_after_stop_request_does_not_kill_new_process(self):
        changed={'start':'2001','args':self.identity['args']}
        with mock.patch.multiple(b,normal_context=mock.Mock(),trusted=mock.Mock(return_value=json.dumps(self.receipt).encode()),
             process_identity=mock.Mock(side_effect=[self.identity,changed]),atomic=mock.Mock()), \
             mock.patch.object(b.os,'kill',side_effect=AssertionError('No signal permitted')):
            with self.assertRaises(ValueError):b.stop_supervisor()
    def test_stop_timeout_is_bounded_and_refuses_restart(self):
        with mock.patch.multiple(b,normal_context=mock.Mock(),trusted=mock.Mock(return_value=json.dumps(self.receipt).encode()),
             process_identity=mock.Mock(return_value=self.identity),supervisor_lock_released=mock.Mock(return_value=False),atomic=mock.Mock()), \
             mock.patch.object(b.time,'monotonic',side_effect=[10,10.1,11.1]),mock.patch.object(b.time,'sleep') as sleep:
            with self.assertRaisesRegex(ValueError,'restart refused'):b.stop_supervisor(timeout=1)
            self.assertEqual(sleep.call_count,1)
    def test_missing_prior_process_needs_no_request(self):
        with mock.patch.multiple(b,normal_context=mock.Mock(),trusted=mock.Mock(return_value=json.dumps(self.receipt).encode()),
             process_identity=mock.Mock(return_value=None),atomic=mock.Mock()) as patches:
            b.stop_supervisor();b.atomic.assert_not_called()
    def test_stop_request_must_match_pid_and_starttime(self):
        with mock.patch.object(b,'trusted',return_value=json.dumps(self.receipt).encode()):
            self.assertTrue(b.stop_requested(12345,'2000'))
            self.assertFalse(b.stop_requested(12345,'2001'));self.assertFalse(b.stop_requested(12346,'2000'))
        with mock.patch.object(b,'trusted',return_value=b'{"pid":12345,"start":"2000","extra":true}'):
            with self.assertRaises(ValueError):b.stop_requested(12345,'2000')
    def test_proc_comm_with_spaces_and_parentheses(self):
        tail=[b'S']+[b'0']*18+[b'2000'];stat_data=b'12345 (python ) odd name) '+b' '.join(tail)+b'\n'
        class Handle(io.BytesIO):
            def fileno(self):return 99
        handles=[Handle(stat_data),Handle(b'\0'.join(self.identity['args'])+b'\0')]
        with mock.patch.object(b.os,'open',return_value=99),mock.patch.object(b.os,'fdopen',side_effect=handles), \
             mock.patch.object(b.os,'fstat',return_value=type('Stat',(),{'st_uid':0})()):
            self.assertEqual(b.process_identity(12345),self.identity)
    def test_nonroot_process_metadata_refused(self):
        class Handle(io.BytesIO):
            def fileno(self):return 99
        with mock.patch.object(b.os,'open',return_value=99),mock.patch.object(b.os,'fdopen',return_value=Handle(b'')), \
             mock.patch.object(b.os,'fstat',return_value=type('Stat',(),{'st_uid':1000})()):
            with self.assertRaises(ValueError):b.process_identity(12345)
    def test_existing_lock_blocks_acknowledgement_until_release(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'lock';path.touch(mode=0o600);held=os.open(str(path),os.O_RDONLY)
            actual_fstat=os.fstat
            def root_stat(fd):
                values=list(actual_fstat(fd));values[4]=0;return os.stat_result(values)
            b.fcntl.flock(held,b.fcntl.LOCK_EX|b.fcntl.LOCK_NB)
            try:
                with mock.patch.object(b,'RUN',d),mock.patch.object(b.os,'fstat',side_effect=root_stat):
                    self.assertFalse(b.supervisor_lock_released())
                    b.fcntl.flock(held,b.fcntl.LOCK_UN)
                    self.assertTrue(b.supervisor_lock_released())
            finally:os.close(held)
    def test_sysv_start_stays_nonblocking_and_restart_checks_stop(self):
        text=(Path(__file__).resolve().parents[1]/'owner-maintenance/owner-maintenance.init').read_text()
        start=next(line for line in text.splitlines() if line.strip().startswith('start)'))
        restart=next(line for line in text.splitlines() if line.strip().startswith('restart)'))
        self.assertIn(' & ;;',start);self.assertIn('|| exit $?',restart)
if __name__=='__main__':unittest.main()
