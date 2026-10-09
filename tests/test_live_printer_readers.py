"""Synthetic read-only status fixtures: no printer, credentials or vendor execution."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-ui'))
from panel_data import SafeTree,PrinterFiles,PassivePrinterSignals
import server


def frame(interface,member,body,path='/com/formlabs/Sauron'):
    return ('signal time=123.0 sender=:1.4 -> destination=(null destination) serial=123 path='+path+'; interface='+interface+'; member='+member+'\n'+body).encode()


class StatusFiles(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ping=self.root/'data/printernet_client/ping.json';self.ping.parent.mkdir(parents=True)
        self.cart=self.root/'data/Cartridges/fixture-private-id.json';self.cart.parent.mkdir()
        self.tank=self.root/'data/Tanks/fixture-tank.json';self.tank.parent.mkdir()
        self.cart.write_text(json.dumps({'OriginalVolume_mL':1000,'EstimatedVolumeDispensed_ml':50,
            'SecretKey':'not-for-api','secret-map-key':'private-value'}))
        self.tank.write_text(json.dumps({'LastResinLevel_mm':10.25,'NumLayersPrinted':1171,'SecretKey':'tank-secret'}))
        self.status={'status':'IDLE','cartridges':[{'type':'CARTRIDGE_PRESENT','serial':'fixture-private-id','material':'FLGPWH41'}],
            'tank':{'type':'TANK_PRESENT','serial':'fixture-tank','material':'FLGPWH41'},
            'print_jobs':[{'name':'private-job','guid':'private-guid','layer_count':1171,'material':'FLGPWH41'}]}
        self.write();self.tree=SafeTree(self.root);self.reader=PrinterFiles(self.tree)
    def write(self):self.ping.write_text(json.dumps({'payload':{'device_status':self.status}}))
    def tearDown(self):self.tree.close();self.tmp.cleanup()
    def test_cached_source_separates_volume_level_and_presence(self):
        r=self.reader.snapshot();self.assertEqual(r['tank_level']['value'],10.25)
        self.assertEqual(r['tank_level']['state'],'CACHED');self.assertIsNone(r['tank_level']['fresh'])
        self.assertIn('age UNKNOWN',r['tank_level']['source'])
        self.assertEqual(r['consumables'][0]['estimated_remaining_ml']['value'],950)
        self.assertEqual(r['consumables'][0]['material']['value'],'White V4.1')
        self.assertFalse(r['automatic_refill_pause']['enabled']);self.assertFalse(r['safe_idle_proven'])
    def test_secret_and_identity_exclusion(self):
        text=json.dumps(self.reader.snapshot())
        for bad in ['not-for-api','secret-map-key','private-value','tank-secret','fixture-private-id','fixture-tank','private-job','private-guid']:
            self.assertNotIn(bad,text)
    def test_unknown_status_and_profile_do_not_pass_through(self):
        self.status['status']='SECRET_status';self.status['tank']['material']='private-token';self.write()
        r=self.reader.snapshot();self.assertIsNone(r['printer_state']['value']);self.assertIsNone(r['consumables'][1]['material']['value'])
    def test_absent_consumable_does_not_join_old_record(self):
        self.status['tank']['type']='TANK_ABSENT';self.write()
        r=self.reader.snapshot();self.assertIsNone(r['tank_level']['value']);self.assertEqual(len(r['consumables']),1)
    def test_serial_traversal_and_symlink_rejected(self):
        self.status['tank']['serial']='../Tanks/fixture-tank';self.write();self.assertIsNone(self.reader.snapshot()['tank_level']['value'])
        self.status['tank']['serial']='fixture-tank';self.write();self.tank.unlink();self.tank.symlink_to(self.cart)
        self.assertIsNone(self.reader.snapshot()['tank_level']['value'])
    def test_parent_symlink_and_malformed_oversize_fail_closed(self):
        for text in ['{','{"payload":null}', 'x'*(512*1024+1)]:
            self.ping.write_text(text);self.assertIsNone(self.reader.snapshot()['printer_state']['value'])
        self.write();copy=self.root/'copy';self.ping.parent.rename(copy);self.ping.parent.symlink_to(copy)
        self.assertIsNone(self.reader.snapshot()['printer_state']['value'])
    def test_stale_publication_and_negative_level(self):
        os.utime(str(self.ping),(1,1));self.tank.write_text('{"LastResinLevel_mm":-1}')
        r=self.reader.snapshot();self.assertFalse(r['printer_state']['fresh']);self.assertIsNone(r['tank_level']['value'])
    def test_bounded_jobs_no_active_job_inference(self):
        self.status['print_jobs']*=100;self.write();jobs=self.reader.snapshot()['jobs']
        self.assertEqual(len(jobs),64);self.assertTrue(all(not j['current_job_proven'] for j in jobs))
    def test_file_reader_has_no_external_calls(self):
        with patch('subprocess.Popen',side_effect=AssertionError('external execution')):
            self.assertEqual(self.reader.snapshot()['printer_state']['value'],'IDLE')
    def test_provider_gates_unsupported_version(self):
        p=server.LinuxProvider(self.root)
        try:self.assertNotIn('printer',p.snapshot())
        finally:p.close()


class PassiveSignals(unittest.TestCase):
    def setUp(self):self.reader=PassivePrinterSignals()
    def test_layer_and_state_only_allowlisted_values(self):
        self.reader.accept(frame('com.formlabs.Sauron','currentlyPrintingLayerChanged','   string "private-job"\n   int32 17'),10,20)
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged','   string "private-job"\n   array [\n      string "HIGH_LEVEL_JOB"\n      string "PRINT_WAIT_FOR_FLX"\n   ]'),10,20)
        r=self.reader.snapshot(11);self.assertEqual(r['job_layer']['value'],17);self.assertEqual(r['job_state']['state'],'LIVE')
        self.assertNotIn('private-job',json.dumps(r));self.assertIsNone(self.reader.snapshot(100)['job_state']['value'])
    def test_preheat_card_is_derived_from_fresh_native_state_only(self):
        self.assertEqual(set(PassivePrinterSignals.PREHEAT_LABELS), {
            'PREHEAT_IDLE', 'PREHEAT_PREHEATING', 'PREHEAT_STOP_PREHEATING',
            'PREHEAT_STOP_PREHEATING_TO_START_PREHEATING',
            'PREHEAT_STOP_PREHEATING_UNTIL_COVER_CLOSED',
            'PREHEAT_WAITING_FOR_COVER_TO_CLOSE_TO_PREHEAT'})
        self.assertEqual(len(PassivePrinterSignals.LEVELSENSE_LABELS), 14)
        body='   string "private-job"\n   array [\n      string "HIGH_LEVEL_IDLE_PREHEAT"\n      string "PREHEAT_PREHEATING"\n   ]'
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged',body),10,20)
        live=self.reader.snapshot(11)['preheat_state']
        self.assertEqual(live['value'],'Preheating')
        self.assertEqual(live['state'],'LIVE')
        self.assertTrue(live['fresh'])
        self.assertTrue(self.reader.snapshot(11)['tank_process_state']['fresh'])
        self.assertIn('not a heater-output or temperature reading',live['source'])
        self.assertEqual(self.reader.snapshot(11)['tank_process_state']['value'],'No LevelSense state listed')
        self.assertIsNone(self.reader.snapshot(71)['preheat_state']['value'])
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged',
            ' string ""\n array [\n string "PREHEAT_WAITING_FOR_COVER_TO_CLOSE_TO_PREHEAT"\n string "LEVELSENSE_FILL_TANK"\n ]'),30,40)
        latest=self.reader.snapshot(31)
        self.assertEqual(latest['preheat_state']['value'],'Waiting for cover to close')
        self.assertEqual(latest['tank_process_state']['value'],'Tank fill phase reported')
        self.assertIn('not pump activity',latest['tank_process_state']['source'])
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged',
            ' string ""\n array [\n string "PREHEAT_FUTURE_STATE"\n string "LEVELSENSE_FUTURE_STATE"\n ]'),50,60)
        unknown=self.reader.snapshot(51)
        self.assertEqual(unknown['preheat_state']['value'],'Unknown preheat state reported')
        self.assertEqual(unknown['tank_process_state']['value'],'Unknown LevelSense state reported')
    def test_temperature_not_level_and_fault_invalidates(self):
        path='/com/formlabs/momo/temperatures/Levelsense'
        for fault,want in [('false',35.5),('true',None)]:
            self.reader.accept(frame('com.formlabs.Temperature','temperature','   struct {\n      boolean '+fault+'\n      double 35.5\n   }',path),10,20)
            s=self.reader.snapshot(11)['sensors'][0];self.assertEqual(s['celsius'],want);self.assertEqual(s['observation']['unit'],'C')
        self.assertIsNone(self.reader.snapshot(21)['sensors'][0]['celsius'])
    def test_nonfinite_and_unknown_paths(self):
        for val in ['nan','inf','1e999','-100','999']:
            self.reader.accept(frame('com.formlabs.Temperature','temperature',' struct { boolean false\n double '+val+'\n }','/com/formlabs/momo/temperatures/Tower'),1,1)
            self.assertFalse(any(x['celsius'] is not None for x in self.reader.snapshot(2)['sensors']))
        self.reader.accept(frame('com.formlabs.Temperature','temperature',' struct { boolean false\n double 33\n }','/private-secret'),1,1)
        self.assertNotIn('private-secret',json.dumps(self.reader.snapshot(2)))
    def test_invalid_temperature_update_replaces_preceding_good_sample(self):
        path='/com/formlabs/momo/temperatures/Tower'
        good=frame('com.formlabs.Temperature','temperature',' struct { boolean false\n double 31\n }',path)
        for bad in ['nan','inf','-inf','1e999','-100','999','31 extra']:
            self.reader.accept(good,10,20)
            self.assertEqual(self.reader.snapshot(11)['sensors'][0]['celsius'],31)
            self.reader.accept(frame('com.formlabs.Temperature','temperature',
                ' struct { boolean false\n double '+bad+'\n }',path),11,21)
            sensor=self.reader.snapshot(12)['sensors'][0]
            self.assertIsNone(sensor['celsius'],bad)
            self.assertFalse(sensor['observation']['fresh'])
            self.assertEqual(sensor['observation']['state'],'UNAVAILABLE')
    def test_mixed_or_truncated_state_list_cannot_retain_apparent_idle(self):
        good=' string ""\n array [\n string "HIGH_LEVEL_IDLE"\n string "PREHEAT_IDLE"\n ]'
        for bad in [
            ' string "HIGH_LEVEL_IDLE"\n int32 1',
            ' string "HIGH_LEVEL_IDLE"\n string "private-token" trailing',
            ' string "HIGH_LEVEL_IDLE"\n string "PR_ERROR_TRUNCATED',
            ' string "HIGH_LEVEL_IDLE"\n string "PRINT_WAIT" extra',
            '\n'.join(['string "HIGH_LEVEL_IDLE"']*65),
            '',
        ]:
            self.reader.accept(frame('com.formlabs.Sauron','statesChanged',good),10,20)
            self.assertTrue(self.reader.snapshot(11)['job_state']['fresh'])
            self.reader.accept(frame('com.formlabs.Sauron','statesChanged',
                ' string ""\n array [\n'+bad+'\n ]'),11,21)
            result=self.reader.snapshot(12)
            for key in ('job_state','preheat_state','tank_process_state'):
                self.assertIsNone(result[key]['value'],key)
                self.assertEqual(result[key]['state'],'UNAVAILABLE')
            self.assertNotIn('private-token',json.dumps(result))
    def test_internal_native_state_labels_are_omitted_and_projection_marked(self):
        body=' string ""\n array [\n string "PAUSE_NONE"\n string "PRINT_WAIT_FOR_FLX"\n string "FLX_IDLE"\n string "synthetic-private-job.flx"\n ]'
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged',body),10,20)
        result=self.reader.snapshot(11)
        self.assertEqual(result['job_state']['value'],['FLX_IDLE','PAUSE_NONE','PRINT_WAIT_FOR_FLX'])
        self.assertEqual(result['job_state']['omitted_entries'],1)
        self.assertFalse(result['job_state']['complete_projection'])
        self.assertIn('incomplete projection',result['job_state']['source'])
        self.assertNotIn('synthetic-private-job',json.dumps(result))
        self.assertIsNone(self.reader.snapshot(71)['job_state']['omitted_entries'])
        self.assertFalse(self.reader.snapshot(71)['job_state']['complete_projection'])
    def test_complete_projection_and_all_unknown_replacement(self):
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged',
            ' string ""\n array [\n string "PRINT_IDLE"\n ]'),10,20)
        self.assertTrue(self.reader.snapshot(11)['job_state']['complete_projection'])
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged',
            ' string ""\n array [\n string "synthetic-private-job.flx"\n ]'),11,21)
        result=self.reader.snapshot(12)
        self.assertIsNone(result['job_state']['value'])
        self.assertFalse(result['job_state']['complete_projection'])
    def test_truncated_known_member_invalidates_only_its_observation(self):
        self.reader.accept(frame('com.formlabs.Sauron','currentlyPrintingLayerChanged',' string ""\n int32 8'),10,20)
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged',
            ' string ""\n array [\n string "PRINT_WAIT"\n ]'),10,20)
        self.reader.accept(frame('com.formlabs.Sauron','currentlyPrintingLayerChanged',' string ""\n int32'),11,21)
        result=self.reader.snapshot(12)
        self.assertIsNone(result['job_layer']['value'])
        self.assertEqual(result['job_state']['value'],['PRINT_WAIT'])
    def test_complete_unknown_future_state_remains_explicitly_unknown(self):
        self.reader.accept(frame('com.formlabs.Sauron','statesChanged',
            ' string ""\n array [\n string "PREHEAT_FUTURE_STATE"\n ]'),10,20)
        result=self.reader.snapshot(11)
        self.assertEqual(result['job_state']['value'],['PREHEAT_FUTURE_STATE'])
        self.assertEqual(result['preheat_state']['value'],'Unknown preheat state reported')
    def test_disconnect_owner_change_and_backward_clock_invalidate(self):
        b=frame('com.formlabs.Sauron','currentlyPrintingLayerChanged',' string ""\n int32 8')
        self.reader.accept(b,10,20);self.assertIsNone(self.reader.snapshot(9)['job_layer']['value'])
        self.reader.accept(frame('org.freedesktop.DBus','NameOwnerChanged',' string "com.formlabs.Sauron"','/org/freedesktop/DBus'))
        self.assertNotIn('job_layer',self.reader.snapshot(11));self.reader.accept(b,10,20);self.reader.clear();self.assertNotIn('job_layer',self.reader.snapshot(11))
    def test_malformed_truncated_and_large_frames(self):
        for b in [b'garbage',b'\xff',b'x'*65537,frame('com.formlabs.Sauron','currentlyPrintingLayerChanged',' string ""\n int32 3\n string "extra"')]:self.reader.accept(b,1,1)
        self.assertEqual(self.reader.snapshot(2),{'sensors':[]})
    def test_single_newline_fragmentation_and_bound(self):
        b=frame('com.formlabs.Sauron','currentlyPrintingLayerChanged',' string ""\n int32 8')
        data=b+'\n'.encode()+b+'\n'.encode()
        for offset in range(0,len(data),7):self.reader.feed(data[offset:offset+7])
        self.assertEqual(self.reader.snapshot()['job_layer']['value'],8)
        with self.assertRaises(ValueError):self.reader.feed(b'x'*65537)
        self.assertNotIn('job_layer',self.reader.snapshot())

    def test_only_fixed_passive_filters(self):
        self.assertEqual(len(self.reader.FILTERS),5)
        self.assertTrue(all("type='signal'" in v for v in self.reader.FILTERS))
        self.assertFalse(self.reader.worker)
    def test_target_projection_keeps_safety_unavailable(self):
        p=server.SampleProvider().snapshot();p['printer']={'printer_state':{'value':'IDLE','state':'CACHED'},'sensors':[]}
        r=server.decorate_snapshot(p);self.assertEqual(r['fields']['printer_state']['value'],'IDLE')
        self.assertIsNone(r['fields']['safe_idle']['value']);self.assertFalse(r['vendor_writes_enabled'])

class ShortHTTPWrites(unittest.TestCase):
    def test_real_handler_finishes_partial_headers_and_body(self):
        class Partial:
            def __init__(self):self.data=bytearray()
            def write(self,raw):
                n=min(len(raw),257);self.data.extend(raw[:n]);return n
        srv=server.make_server(server.SampleProvider(),'synthetic-fixture-access-only',0)
        try:
            handler=srv.RequestHandlerClass.__new__(srv.RequestHandlerClass)
            handler.request_version='HTTP/1.1';handler.requestline='GET /app.js HTTP/1.1';handler.command='GET';handler.wfile=Partial()
            payload=b'authored asset;'+b'x'*65536
            handler.reply(200,payload,'text/javascript')
            headers,body=bytes(handler.wfile.data).split(b'\r\n\r\n',1)
            self.assertIn(('Content-Length: '+str(len(payload))).encode(),headers)
            self.assertEqual(body,payload)
        finally:srv.server_close()
    def test_no_progress_or_invalid_write_fails_bounded(self):
        for value in [None,0,-1,10000]:
            class Broken:
                def write(self,raw):return value
            with self.assertRaises(OSError):server.write_all(Broken(),b'fixture')

if __name__=='__main__':unittest.main()
