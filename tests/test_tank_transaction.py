"""Synthetic tank transaction failures, no firmware/keys/hardware required."""
import base64,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-maintenance'))
from test_tank_codec import fixture,NAME
import tank_codec as codec
import cartridge_transaction as tx
from consumable_backup import Store
from cartridge_broker import Broker,strict_request


class Memory(object):
    def __init__(self,fail=None,partial=False,corrupt=False):
        self.before,self.record=fixture()
        self.target,self.revised,_=codec.material_candidate(self.before,self.record,NAME,'FLGPCL41')
        self.image=self.before;self.file=b'old';self.calls=[];self.events={}
        self.fail=fail;self.partial=partial;self.corrupt=corrupt;self.failed=False
    def guard(self):pass
    def exclusion(self):pass
    def read_image(self):return self.image
    def read_mirror(self):return self.file
    def write_mirror(self,raw):
        self.calls.append(('file',raw));self.file=raw
        if self.fail=='file' and not self.failed:self.failed=True;raise OSError('Synthetic file failure')
    def write_copy(self,offset,raw):
        self.calls.append(('copy',offset))
        fail=offset==self.fail and not self.failed
        n=32 if fail and self.partial else 41
        self.image=self.image[:offset]+raw[:n]+self.image[offset+n:]
        if fail:
            self.failed=True
            if self.corrupt:
                v=bytearray(self.image);v[offset+7]^=1;self.image=bytes(v)
            else:raise OSError('Synthetic EEPROM failure')
    def run(self):
        tx.commit_tank_records(self,self.before,self.target,b'old',b'new',lambda k,v:self.events.update({k:v}))


class TankTransactionTests(unittest.TestCase):
    def test_order_and_complete_readback(self):
        io=Memory();io.run()
        self.assertEqual(io.calls,[('file',b'new'),('copy',128),('copy',32)])
        self.assertEqual(io.image,io.target);self.assertEqual(io.events['full_target_comparison'],'PASS')
    def test_failure_each_stage_restores_exact_original(self):
        for failure in ('file',128,32):
            with self.subTest(failure=failure):
                io=Memory(failure)
                with self.assertRaises(OSError):io.run()
                self.assertEqual(io.image,io.before);self.assertEqual(io.file,b'old')
                self.assertEqual(io.events['rollback'],'PASS')
    def test_second_page_failure_rolls_back_partial_record(self):
        for offset in (128,32):
            with self.subTest(offset=offset):
                io=Memory(offset,partial=True)
                with self.assertRaises(OSError):io.run()
                self.assertEqual(io.image,io.before);self.assertEqual(io.events['rollback'],'PASS')
    def test_corrupt_readback_rejected_and_restored(self):
        for offset in (128,32):
            io=Memory(offset,corrupt=True)
            with self.assertRaises(ValueError):io.run()
            self.assertEqual(io.image,io.before);self.assertEqual(io.events['rollback'],'PASS')
    def test_rollback_failure_never_reports_success(self):
        io=Memory(32)
        def failed_rollback(offset,raw):raise OSError('Synthetic bus unavailable')
        original=io.write_copy
        def f(offset,raw):
            if io.failed:return failed_rollback(offset,raw)
            return original(offset,raw)
        io.write_copy=f
        with self.assertRaises(OSError):io.run()
        self.assertNotEqual(io.events.get('rollback'),'PASS')
    def test_identity_extent_rejected_before_any_write(self):
        for position in (0,31,32,37,60,69,73,127,128,133,156,165,169,511):
            io=Memory();target=bytearray(io.target);target[position]^=1;io.target=bytes(target)
            with self.assertRaises(ValueError):io.run()
            self.assertEqual(io.calls,[])
    def test_changed_baseline_never_writes_target(self):
        io=Memory();io.file=b'changed'
        with self.assertRaises(ValueError):io.run()
        self.assertFalse(any(x[0]=='copy' for x in io.calls))
    def test_device_rejects_identity_and_arbitrary_operation(self):
        for name,op in [('../../x','tank_material'),('2d-000000000000','tank_material'),(NAME,'reset_lifetime')]:
            with self.assertRaises(ValueError):tx.TankDevice({'kind':'tank','device_name':name,'operation':op})
    def test_copy_extent_and_unplanned_bytes_refused(self):
        io=Memory();plan={'kind':'tank','operation':'tank_material','device_name':NAME,'record_path':'/data/Tanks/'+NAME+'.json',
                         'target_b64':base64.b64encode(io.target).decode(),'baseline_image_b64':base64.b64encode(io.before).decode(),'eeprom_sha256':tx.digest(io.before)}
        d=tx.TankDevice(plan);d.exclusion=lambda:None
        for offset,data in ((0,b'x'*41),(32,b'x'*40),(128,b'x'*41),(169,b'x'*41)):
            with self.assertRaises(ValueError):d.write_copy(offset,data)
    @patch('consumable_backup.selected',return_value=NAME)
    @patch('consumable_backup.native_tank_material',return_value='FLGPCL41')
    def test_post_reload_lifetime_and_identity_must_match(self,*mocks):
        io=Memory();d=object.__new__(tx.TankDevice);d.plan={'device_name':NAME,'material_target':'FLGPCL41'}
        d.read_image=lambda:io.target;d.read_mirror=lambda:json.dumps(io.revised).encode()
        d.verify_reloaded(io.target,json.dumps(io.record).encode())
        for field,value in [('VolumePrinted_mm3',0),('SecretKey','changed'),('DateFirstFill','2026-01-01T00:00:00'),('LastResinUsed','FLGPCL04')]:
            bad=dict(io.revised);bad[field]=value;d.read_mirror=lambda:json.dumps(bad).encode()
            with self.assertRaises(ValueError):d.verify_reloaded(io.target,json.dumps(io.record).encode())
    def test_broker_cannot_apply_tank_plan_through_cartridge_endpoint(self):
        with tempfile.TemporaryDirectory() as path:
            called=[];b=Broker(path,lambda:({'kind':'tank','material_target':'FLGPCL41'},{'already_fresh':False}),lambda p:called.append(p) or {'state':'COMPLETE'})
            b.request({'operation':'prepare'});b.worker.join(3);token=b.status()['plan_id']
            for op in ('apply','apply_material'):
                with self.assertRaises(ValueError):b.request({'operation':op,'plan_id':token})
            self.assertEqual(called,[])
            b.request({'operation':'apply_tank_material','plan_id':token});b.worker.join(3);self.assertEqual(len(called),1)
    def test_strict_tank_request(self):
        strict_request({'operation':'prepare_tank_material','material':'FLGPCL04'})
        for request in ({'operation':'prepare_tank_material','material':'FLGPCL04','lifetime':0},
                        {'operation':'apply_tank_material','plan_id':'x'},
                        {'operation':'prepare_tank_material','material':'FLGPCL04\n'}):
            with self.assertRaises(ValueError):strict_request(request)


class TankBackupRestoreTests(unittest.TestCase):
    def test_material_restore_preserves_current_accounting(self):
        old,record=fixture()
        current,revised,_=codec.material_candidate(old,record,NAME,'FLGPCL41')
        value={'kind':'tank','device_name':NAME,'record':json.dumps(record).encode(),'eeprom':old,'material':'FLGPCL04','validation':'CHECKSUMS_AND_MIRROR_VERIFIED'}
        with tempfile.TemporaryDirectory() as root:
            store=Store(root,lambda _:value);identity=store.backup('tank')['id']
            live=dict(value,eeprom=current,record=json.dumps(revised).encode())
            material=store.restore_tank_material(identity,live);self.assertEqual(material,'FLGPCL04')
            target,restored,_=codec.material_candidate(current,revised,NAME,material)
            self.assertEqual(restored,record);self.assertEqual(target,old)
            with self.assertRaises(ValueError):store.restore_tank_material(identity,dict(live,device_name='4c-111111111111'))
            changed=bytearray(current);changed[500]^=1
            with self.assertRaises(ValueError):store.restore_tank_material(identity,dict(live,eeprom=bytes(changed)))
    def test_backup_tamper_refused(self):
        image,record=fixture();value={'kind':'tank','device_name':NAME,'record':json.dumps(record).encode(),'eeprom':image,'material':'FLGPCL04','validation':'CHECKSUMS_AND_MIRROR_VERIFIED'}
        with tempfile.TemporaryDirectory() as root:
            store=Store(root,lambda _:value);identity=store.backup('tank')['id']
            Path(root,identity,'eeprom.bin').write_bytes(bytes(512))
            with self.assertRaises(ValueError):store.restore_tank_material(identity,value)


class TankNativeStatusTests(unittest.TestCase):
    def test_material_only_projection_ignores_private_fields(self):
        from consumable_backup import parse_tank_material_reply
        raw=b'method return\n array [ dict entry( string "SecretKey" variant string "SYNTHETIC-PRIVATE" ) dict entry( string "LastResinUsed" variant string "FLGPCL04" ) ]'
        self.assertEqual(parse_tank_material_reply(raw),'FLGPCL04')
        for bad in (raw+raw,raw.replace(b'FLGPCL04',b'unknown'),raw.replace(b'LastResinUsed',b'OtherField'),bytes(65537)):
            with self.assertRaises(ValueError):parse_tank_material_reply(bad)
    @patch('consumable_backup.selected',return_value='4c-111111111111')
    def test_different_selected_tank_rejected(self,*mocks):
        d=object.__new__(tx.TankDevice);d.plan={'device_name':NAME,'material_target':'FLGPCL04'}
        with self.assertRaises(ValueError):d.verify_reloaded(bytes(512),b'{}')


class PreviewIdleBoundaryTests(unittest.TestCase):
    def test_blocked_preview_cannot_launch_transaction(self):
        with tempfile.TemporaryDirectory() as path:
            calls=[];b=Broker(path,lambda:({'kind':'tank'},{'already_fresh':False,'apply_ready':False}),lambda p:calls.append(p))
            b.request({'operation':'prepare'});b.worker.join(3)
            with self.assertRaises(ValueError):b.request({'operation':'apply_tank_material','plan_id':b.status()['plan_id']})
            self.assertEqual(calls,[]);self.assertEqual(b.status()['state'],'READY')
    def test_guard_defaults_to_strict_idle(self):
        from types import SimpleNamespace
        d=object.__new__(tx.Device);d.plan={'boot_id':'test','firmware':'2.5.6-2773'};d.stopped=False
        def read(path,limit=65536):
            return b'test' if path.endswith('boot_id') else b'root=/dev/mmcblk0p6' if path.endswith('cmdline') else b'{"build":{"name":"2.5.6-2773"}}'
        with patch.object(tx.os,'getuid',return_value=0),patch.object(tx.os,'uname',return_value=SimpleNamespace(machine='armv7l',release='4.9.65+')),patch.object(tx.os.path,'exists',return_value=False),patch.object(tx,'read_file',side_effect=read),patch.object(d,'states',side_effect=ValueError('Preheating')) as states:
            with self.assertRaises(ValueError):d.guard()
            self.assertEqual(states.call_count,1)
            d.guard(require_idle=False)
            self.assertEqual(states.call_count,1)
