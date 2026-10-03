"""Synthetic, offline session and immutable diagnostic database fixtures."""
import base64,hashlib,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import review_print_progress as progress
import inspect_diagnostic_databases as db


def signal(member,body,stamp=1):
    return ('signal time='+str(stamp)+'.0 sender=:1.1 -> destination=(null destination) serial='+str(stamp)+' path=/com/formlabs/Sauron; interface=com.formlabs.Sauron; member='+member+'\n'+body).encode()


class ProgressTests(unittest.TestCase):
    def test_task_finish_layer_index_and_boot_are_separate(self):
        p=progress.Progress();p.boot('boot-one')
        p.signal(signal('currentlyPrintingLayerChanged',' string "secret-guid"\n int32 4'))
        p.signal(signal('currentlyPrintingLayerChanged',' string "secret-guid"\n int32 6',2))
        p.signal(signal('finished',' string "another-task"',3))
        self.assertEqual(p.result()[0]['tasks_with_matching_finish'],0)
        p.signal(signal('finished',' string "secret-guid"',4))
        p.boot('boot-two');p.signal(signal('finished',' string "secret-guid"',4))
        rows=p.result();self.assertEqual(rows[0]['tasks_with_matching_finish'],1)
        self.assertEqual(rows[0]['missing_indices_between_observed_extremes'],1)
        self.assertFalse(rows[0]['print_success_proven']);self.assertEqual(rows[1]['tasks_with_matching_finish'],0)
        self.assertNotIn('secret-guid',json.dumps(rows))
    def test_duplicate_frames_and_invalid_layers(self):
        p=progress.Progress();p.boot('one');b=signal('currentlyPrintingLayerChanged',' string "x"\n int32 1')
        p.signal(b);p.signal(b);self.assertEqual(p.duplicates,1);self.assertEqual(p.result()[0]['layer_events'],1)
        p.signal(signal('currentlyPrintingLayerChanged',' string "x"\n int32 -1',2))
        self.assertEqual(p.result()[0]['layer_events'],1)
    def test_unknown_state_strings_are_not_exported(self):
        p=progress.Progress();p.boot('one')
        p.signal(signal('statesChanged',' string "HIGH_LEVEL_PRIVATE_TOKEN"\n string "HIGH_LEVEL_IDLE"'))
        result=p.result()
        self.assertNotIn('PRIVATE_TOKEN',json.dumps(result))
        self.assertIn('HIGH_LEVEL_IDLE',result[0]['states'])
        self.assertEqual(result[0]['unknown_state_values_omitted'],1)
    def fixture(self,root):
        raw=root/'raw';raw.mkdir();boot='0'*8+'-'+'0'*4+'-'+'0'*4+'-'+'0'*4+'-'+'0'*12
        payload={'kernel':'4.9.65+','firmware':'2.5.6-2773','selected_slot':6}
        events=[{'kind':'identity','device_epoch':1,'device_monotonic':1,'boot_id':boot,'payload':payload}]
        frame=signal('currentlyPrintingLayerChanged',' string "private"\n int32 2')+b'\n'+signal('finished',' string "private"',2)+b'\n'+signal('finished',' string "other"',3)
        events.append({'kind':'dbus','device_epoch':2,'device_monotonic':2,'boot_id':boot,'payload':{'channel':'stdout','bytes':len(frame),'sha256':hashlib.sha256(frame).hexdigest(),'data_b64':base64.b64encode(frame).decode()}})
        data=b''.join(json.dumps({'event':e}).encode()+b'\n' for e in events)
        (raw/'stream-0001.jsonl').write_bytes(data)
        (root/'SESSION_SHA256.json').write_text(json.dumps({'files':[{'path':'raw/stream-0001.jsonl','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}]}))
        return raw/'stream-0001.jsonl'
    def test_sealed_stream_checks_content_and_does_not_follow_link(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=self.fixture(root);r=progress.review(root)
            self.assertEqual(r['events'],2);self.assertEqual(r['boots'][0]['max_layer_index'],2)
            self.assertEqual(r['undelimited_tail_frames_omitted'],1)
            raw=p.read_bytes();p.write_bytes(raw.replace(b'4.9.65+',b'6.9.65+'))
            with self.assertRaises(ValueError):progress.review(root)
            p.unlink();p.symlink_to('/etc/passwd')
            with self.assertRaises((OSError,ValueError)):progress.review(root)


class DiagnosticDatabase(unittest.TestCase):
    def test_duration_records_are_not_successful_prints(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'input.sqlite';c=sqlite3.connect(p)
            c.execute('CREATE TABLE Durations (Timestamp INTEGER, GUID TEXT, Print_GUID TEXT, Print_Layer INTEGER, Name TEXT, Duration_ms INTEGER, Context TEXT, Data TEXT)')
            c.execute('INSERT INTO Durations VALUES (1,"PRIVATE_GUID","PRIVATE_PRINT",-1,"PRIVATE_NAME",100,"PRIVATE_CONTEXT","PRIVATE_DATA")');c.commit();c.close()
            before=p.read_bytes();r=db.inspect(p,'durations')
            self.assertEqual(r['rows'],1);self.assertEqual(r['rows_without_nonnegative_layer'],1)
            self.assertIsNone(r['successful_print_count']);self.assertNotIn('PRIVATE',json.dumps(r));self.assertEqual(p.read_bytes(),before)
    def test_corrupt_changed_schema_and_symlink_fail(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'input.sqlite';p.write_bytes(b'not a database')
            with self.assertRaises(ValueError):db.inspect(p,'durations')
            p.unlink();c=sqlite3.connect(p);c.execute('CREATE TABLE Durations (secret TEXT)');c.close()
            with self.assertRaises(ValueError):db.inspect(p,'durations')
            link=Path(t)/'link';link.symlink_to(p)
            with self.assertRaises((ValueError,OSError)):db.inspect(link,'durations')
