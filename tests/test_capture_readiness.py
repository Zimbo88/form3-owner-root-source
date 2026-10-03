"""Offline transport-loss, identity and sealed-consumable-history fixtures."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import capture_policy as policy
import record_print_state as recorder
import review_consumable_history as history


class CapturePolicy(unittest.TestCase):
    def test_binding_is_exact_and_keeps_target_invariants(self):
        root=Path(recorder.__file__).parent
        for name in ('print_capture_agent.py','print_state_snapshot.py'):
            bound=policy.bind_source((root/name).read_bytes(),'0.5.12-review')
            self.assertIn(b"EXPECTED_OWNER_VERSION = '0.5.12-review'",bound)
            for marker in (b'2.5.6-2773',b'4.9.65+',b'root=/dev/mmcblk0p6',b'pending.json'):
                self.assertIn(marker,bound)
        for value in (None,'latest','0.5.12-review\n','x; reboot'):
            with self.assertRaises(ValueError):policy.bind_source(policy.VERSION_MARKER,value)
        with self.assertRaises(ValueError):policy.bind_source(b'changed-source','0.5.12-review')

    def test_transient_is_bounded_and_auth_never_retried(self):
        for text in (b'Connection timed out',b'Connection reset by peer',b'Connection refused'):
            self.assertTrue(policy.transport_failure(255,text)[0])
        for text in (b'Permission denied (publickey). Connection reset',
                     b'REMOTE HOST IDENTIFICATION HAS CHANGED',b'Host key verification failed',b'unknown diagnostic'):
            self.assertFalse(policy.transport_failure(255,text)[0])
        self.assertFalse(policy.transport_failure(1,b'Connection reset')[0])
        self.assertFalse(policy.transport_failure(255,b'Permission denied',True)[0])
        r=policy.RetryBudget(3)
        self.assertEqual(r.failure(255,b'Connection reset')[2],5)
        self.assertEqual(r.failure(255,b'Connection reset')[2],10)
        self.assertFalse(r.failure(255,b'Connection reset')[0])
        r.success();self.assertTrue(r.failure(255,b'Connection reset')[0])

    def test_wrong_target_and_missing_identity_refused(self):
        with self.assertRaises(ValueError):recorder.validate({'files':[]},'0.5.12-review')
        ident={'uid':0,'architecture':'armv7l','kernel':'4.9.65+','selected_slot':6,
               'firmware':'2.5.6-2773','owner_version':'0.5.12-review','boot_id':'0'*8+'-'+'0'*4+'-'+'0'*4+'-'+'0'*4+'-'+'0'*12}
        doc={'identity':ident,'files':[]}
        self.assertEqual(recorder.validate(doc,'0.5.12-review'),doc)
        for key,bad in [('uid',1000),('selected_slot',5),('owner_version','0.5.11-review'),('kernel','6.12')]:
            d={'identity':dict(ident,**{key:bad}),'files':[]}
            with self.assertRaises(ValueError):recorder.validate(d,'0.5.12-review')

    def test_real_recorder_reconnects_after_transport_loss_then_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'ssh.conf';config.write_text('fixture')
            session=root/'session';session.mkdir()
            boot='0'*8+'-'+'0'*4+'-'+'0'*4+'-'+'0'*4+'-'+'0'*12
            doc={'identity':{'uid':0,'architecture':'armv7l','kernel':'4.9.65+','selected_slot':6,
                'firmware':'2.5.6-2773','owner_version':'0.5.12-review','boot_id':boot},
                 'files':[],'gaps':[],'device_epoch':100,'device_monotonic':5}
            calls=[]
            def run(cmd,**kw):
                calls.append(cmd)
                self.assertIn('StrictHostKeyChecking=yes',cmd)
                if len(calls)==1:
                    kw['stderr'].write(b'Connection timed out\n');kw['stderr'].flush()
                    return subprocess.CompletedProcess(cmd,255)
                kw['stdout'].write(json.dumps(doc).encode());kw['stdout'].flush()
                (session/'STOP').write_text('fixture')
                return subprocess.CompletedProcess(cmd,0)
            with mock.patch.object(recorder.subprocess,'run',side_effect=run),mock.patch.object(recorder.time,'sleep'),mock.patch.object(recorder.signal,'signal'):
                recorder.run(session,config,'fixture',60,'0.5.12-review')
            status=json.loads((session/'consumable-state/status.json').read_text())
            self.assertEqual(len(calls),2);self.assertEqual(status['snapshots'],1)
            self.assertEqual(status['failures'],1);self.assertEqual(status['state'],'stopped')
            self.assertFalse(status['coverage_gap_open'])


class ConsumableHistory(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.objects=self.root/'consumable-state/objects';self.objects.mkdir(parents=True)
        self.rows=[];self.files={}
        for i in range(2):
            raw=json.dumps({'ConsumableType':'tank','LastResinLevel_mm':5+i,'NumLayersPrinted':i,
                'SecretKey':'DO_NOT_EXPORT','sensitive-dictionary-key':'private'}).encode()
            sha=hashlib.sha256(raw).hexdigest();name='consumable-state/objects/'+sha
            (self.root/name).write_bytes(raw);self.files[name]=raw
            self.rows.append({'device_epoch':100+i*10,'device_monotonic':10+i*10,
                'files':[{'path':'/data/Tanks/private-serial.json','bytes':len(raw),'sha256':sha,'stable_metadata':True,'mtime':90+i}]})
        self.seal()
    def seal(self):
        data=b''.join(json.dumps(r).encode()+b'\n' for r in self.rows)
        (self.root/history.INDEX).write_bytes(data);self.files[history.INDEX]=data
        self.manifest={'files':[{'path':k,'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in self.files.items()]}
        (self.root/'SESSION_SHA256.json').write_text(json.dumps(self.manifest))
    def test_verified_changes_with_no_identity_or_secret_export(self):
        result,summary=history.review(self.root)
        self.assertEqual(summary['snapshots'],2);self.assertEqual(summary['record_counts'],{'tank':1})
        self.assertEqual(result['records'][0]['changed_observations']['LastResinLevel_mm'],1)
        for secret in ('DO_NOT_EXPORT','sensitive-dictionary-key','private-serial'):
            self.assertNotIn(secret,json.dumps(result));self.assertNotIn(secret,json.dumps(summary))
        self.assertFalse(result['measurement_age_proven']);self.assertFalse(result['device_chip_image'])
    def test_corrupted_object_index_and_symlink_refused(self):
        name=next(k for k in self.files if k.startswith('consumable-state/objects/'))
        (self.root/name).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):history.review(self.root)
        (self.root/name).unlink();(self.root/name).symlink_to('/etc/passwd')
        with self.assertRaises((ValueError,OSError)):history.review(self.root)
        (self.root/name).unlink();(self.root/name).write_bytes(self.files[name])
        (self.root/history.INDEX).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):history.review(self.root)
    def test_sealed_truncated_index_and_duplicate_file_rejected(self):
        self.rows[0]['files']*=2;self.seal()
        with self.assertRaises(ValueError):history.review(self.root)
        self.rows[0]['files']=self.rows[0]['files'][:1];self.seal()
        data=self.files[history.INDEX][:-1];self.files[history.INDEX]=data
        (self.root/history.INDEX).write_bytes(data)
        self.manifest['files'][-1].update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        (self.root/'SESSION_SHA256.json').write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError):history.review(self.root)
    def test_unknown_path_not_followed_or_published(self):
        self.rows[0]['files'][0]['path']='/data/Tanks/../private-secret.json';self.seal()
        result,_=history.review(self.root)
        self.assertNotIn('private-secret',json.dumps(result))
        self.assertEqual(len(result['records'][0]['observations']),1)
