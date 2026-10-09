"""Bounded broker state machine with synthetic transactions and no device I/O."""
import sys, tempfile, unittest, time, threading, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-maintenance'))
from cartridge_broker import Broker, strict_request

class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.writes=[]
        self.broker=Broker(self.tmp.name,lambda:({'private':'not returned'},{'already_fresh':False}),self.execute)
    def execute(self,plan):
        self.writes.append(plan);return {'state':'COMPLETE'}
    def ready(self):
        self.broker.request({'operation':'prepare'});self.broker.worker.join(2)
        return self.broker.status()['plan_id']
    def test_prepare_contains_no_private_plan(self):
        self.ready();self.assertNotIn('not returned',json.dumps(self.broker.status()));self.assertEqual(self.writes,[])
    def test_apply_once_and_no_replay(self):
        token=self.ready();self.broker.request({'operation':'apply','plan_id':token});self.broker.worker.join(2)
        self.assertEqual(self.broker.status()['state'],'COMPLETE');self.assertEqual(len(self.writes),1)
        with self.assertRaises(ValueError):self.broker.request({'operation':'apply','plan_id':token})
    def test_no_apply_without_preview(self):
        with self.assertRaises(ValueError):self.broker.request({'operation':'apply','plan_id':'a'*48})
    def test_wrong_preview(self):
        self.ready()
        with self.assertRaises(ValueError):self.broker.request({'operation':'apply','plan_id':'f'*48})
        self.assertEqual(self.writes,[])
    def test_expiry(self):
        token=self.ready();self.broker.deadline=time.monotonic()-1
        self.assertEqual(self.broker.status()['state'],'EXPIRED')
        with self.assertRaises(ValueError):self.broker.request({'operation':'apply','plan_id':token})
    def test_fresh_never_writes(self):
        self.broker.prepare_fn=lambda:({}, {'already_fresh':True});token=self.ready()
        self.assertEqual(self.broker.status()['state'],'ALREADY_FRESH')
        with self.assertRaises(ValueError):self.broker.request({'operation':'apply','plan_id':token})
        self.assertEqual(self.writes,[])
    def test_no_concurrent_operations(self):
        gate=threading.Event()
        self.broker.prepare_fn=lambda:(gate.wait(2),{'already_fresh':False})
        self.broker.request({'operation':'prepare'})
        try:
            with self.assertRaises(ValueError):self.broker.request({'operation':'prepare'})
        finally:gate.set();self.broker.worker.join(3)
    def test_interrupted_transaction_locks(self):
        Path(self.tmp.name,'in-progress.json').write_text('{}');b=Broker(self.tmp.name)
        self.assertEqual(b.status()['state'],'RECOVERY_REQUIRED')
        with self.assertRaises(ValueError):b.request({'operation':'prepare'})
    def test_failure_requires_recovery(self):
        def fail(_):raise OSError('synthetic private OS detail')
        self.broker.execute_fn=fail;token=self.ready()
        self.broker.request({'operation':'apply','plan_id':token});self.broker.worker.join(2)
        self.assertEqual(self.broker.status()['state'],'RECOVERY_REQUIRED')
        self.assertNotIn('private OS',json.dumps(self.broker.status()))
    def test_shutdown_refuses_new_operations(self):
        self.broker.closing=True
        with self.assertRaises(ValueError):self.broker.request({'operation':'prepare'})
    def test_unknown_fields_and_paths(self):
        for value in [{},[],{'operation':'shell'}, {'operation':'prepare','path':'/etc/shadow'},
                      {'operation':'apply','plan_id':'../x'}, {'operation':'status','command':'id'}]:
            with self.assertRaises(ValueError):strict_request(value)
    def test_retention_limit(self):
        for i in range(512):Path(self.tmp.name,str(i)).touch()
        self.broker.request({'operation':'prepare'});self.broker.worker.join(2)
        self.assertEqual(self.broker.status()['state'],'UNAVAILABLE');self.assertEqual(self.writes,[])

    def test_material_apply_cannot_consume_usage_preview(self):
        token=self.ready()
        with self.assertRaises(ValueError):self.broker.request({'operation':'apply_material','plan_id':token})
        self.assertEqual(self.writes,[])

    def test_usage_apply_cannot_consume_material_preview(self):
        self.broker.prepare_fn=lambda:({'material_target':'FLGPCL04'},{'already_fresh':False})
        token=self.ready()
        with self.assertRaises(ValueError):self.broker.request({'operation':'apply','plan_id':token})
        self.assertEqual(self.writes,[])
        self.broker.request({'operation':'apply_material','plan_id':token});self.broker.worker.join(2)
        self.assertEqual(len(self.writes),1)
