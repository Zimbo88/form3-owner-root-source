"""Synthetic fixtures only; never touches a printer or real consumable."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"owner-maintenance"))
import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from cartridge_transaction import commit_records, read_file, replace_file, Device, mirror_semantic_pin


class Fixture(object):
    def __init__(self, fail=None):
        self.before = bytes(range(128))
        self.target = bytearray(self.before)
        self.target[64:80] = b'a'*16
        self.target[96:112] = b'b'*16
        self.target = bytes(self.target)
        self.image = self.before
        self.mirror = b'old'
        self.operations = []
        self.fail = fail
        self.failed = False
        self.events = {}
    def trigger(self, name):
        if self.fail == name and not self.failed:
            self.failed = True
            raise IOError('synthetic failure')
    def guard(self):
        self.trigger('guard')
    def exclusion(self):
        pass
    def read_image(self):
        return self.image
    def read_mirror(self):
        return self.mirror
    def write_mirror(self, data):
        self.operations.append(('file', data))
        self.mirror = data
        self.trigger('file')
        if self.fail == 'file_readback' and not self.failed:
            self.failed = True
            self.mirror = b'corrupt'
    def write_copy(self, offset, data):
        self.operations.append(('eeprom', offset, data))
        self.trigger('before_'+str(offset))
        image = bytearray(self.image)
        image[offset:offset+16] = data
        self.image = bytes(image)
        self.trigger('after_'+str(offset))
        if self.fail == 'readback_'+str(offset) and not self.failed:
            self.failed = True
            image[offset] ^= 1
            self.image = bytes(image)
    def event(self, stage, value):
        self.events[stage] = value
    def run(self):
        commit_records(self, self.before, self.target, b'old', b'new', self.event)


class TransactionTests(unittest.TestCase):
    def test_backup_parent_must_be_writable_and_have_space(self):
        device=Device({'device_name':'2d-000000000000','record_path':'/data/Cartridges/2d-000000000000.json'})
        for flags,available in [(os.ST_RDONLY,4096),(0,0)]:
            space=SimpleNamespace(f_flag=flags,f_bavail=available,f_frsize=4096)
            with patch.object(device,'guard'), patch('os.path.realpath',return_value='/data'), patch('os.path.isdir',return_value=True), patch('os.statvfs',return_value=space):
                with self.assertRaises(ValueError):device.preflight()
    def test_only_writeback_time_excluded_from_pin(self):
        a={'WriteCount':538,'LastSuccessfulWritebackTime':'old','SyntheticPrivateField':'retained'}
        b=dict(a);b['LastSuccessfulWritebackTime']='new'
        self.assertEqual(mirror_semantic_pin(a),mirror_semantic_pin(b))
        b['WriteCount']=539
        self.assertNotEqual(mirror_semantic_pin(a),mirror_semantic_pin(b))
        b=dict(a);b['SyntheticPrivateField']='changed'
        self.assertNotEqual(mirror_semantic_pin(a),mirror_semantic_pin(b))
    def states_fixture(self,states,guid):
        device=Device({'device_name':'2d-000000000000','record_path':'/data/Cartridges/2d-000000000000.json'})
        replies=[SimpleNamespace(returncode=0,stdout=('array [\n'+''.join(' string "'+s+'"\n' for s in states)+']\n').encode()),
                 SimpleNamespace(returncode=0,stdout=('string "'+guid+'"\n').encode())]
        with patch('cartridge_transaction.subprocess.run',side_effect=replies):
            return device.states()
    def test_idle_with_pause_none(self):
        states=['PREHEAT_IDLE','PRINT_IDLE','PAUSE_NONE','SAURON_IDLE','HIGH_LEVEL_IDLE']
        self.assertEqual(self.states_fixture(states,''),states)
    def test_nonidle_state_rejected(self):
        with self.assertRaises(ValueError):self.states_fixture(['HIGH_LEVEL_FILLING_TANK'],'')
    def test_current_print_rejected(self):
        with self.assertRaises(ValueError):self.states_fixture(['HIGH_LEVEL_IDLE'],'synthetic-job')
    def test_order_and_full_readback(self):
        f=Fixture();f.run()
        self.assertEqual(f.operations,[('file',b'new'),('eeprom',96,b'b'*16),('eeprom',64,b'a'*16)])
        self.assertEqual(f.image,f.target);self.assertEqual(f.mirror,b'new')
        self.assertEqual(f.events['full_target_comparison'],'PASS')
    def failure_case(self,name):
        f=Fixture(name)
        with self.assertRaises((IOError,ValueError)):f.run()
        self.assertEqual(f.image,f.before);self.assertEqual(f.mirror,b'old')
        self.assertEqual(f.events['rollback'],'PASS')
        return f
    def test_file_failure(self):self.failure_case('file')
    def test_file_readback(self):self.failure_case('file_readback')
    def test_before_b(self):self.failure_case('before_96')
    def test_after_b(self):self.failure_case('after_96')
    def test_b_mismatch(self):self.failure_case('readback_96')
    def test_before_a(self):self.failure_case('before_64')
    def test_after_a(self):self.failure_case('after_64')
    def test_a_mismatch(self):self.failure_case('readback_64')
    def test_rollback_order(self):
        f=self.failure_case('after_64')
        self.assertEqual([x[1] for x in f.operations if x[0]=='eeprom'],[96,64,64,96])
        self.assertEqual(f.operations[-1],('file',b'old'))
    def test_identity_modification_rejected(self):
        f=Fixture();a=bytearray(f.target);a[0]^=1;f.target=bytes(a)
        with self.assertRaises(ValueError):f.run()
        self.assertEqual(f.operations,[])
    def test_size_rejected(self):
        f=Fixture();f.target=f.target[:-1]
        with self.assertRaises(ValueError):f.run()
        self.assertEqual(f.operations,[])
    def test_stale_image_blocks_write(self):
        f=Fixture();f.image=b'x'*128
        with self.assertRaises(ValueError):f.run()
        self.assertEqual(f.operations,[])
    def test_stale_mirror_blocks_write(self):
        f=Fixture();f.mirror=b'changed'
        with self.assertRaises(ValueError):f.run()
        self.assertEqual(f.operations,[])
    def test_rollback_failure_not_pass(self):
        class Broken(Fixture):
            def write_copy(self,offset,data):
                self.image=b'x'*128
                raise IOError('permanent write failure')
        f=Broken()
        with self.assertRaises(IOError):f.run()
        self.assertNotEqual(f.events.get('rollback'),'PASS')
    def test_real_file_metadata_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            p=os.path.join(directory,'record');link=os.path.join(directory,'link')
            with open(p,'wb') as out:out.write(b'old')
            os.chmod(p,0o640)
            metadata={'uid':os.getuid(),'gid':os.getgid(),'mode':0o640,'xattrs':{}}
            replace_file(p,b'new',metadata)
            self.assertEqual(read_file(p),b'new')
            self.assertEqual(os.stat(p).st_mode & 0o777,0o640)
            os.symlink(p,link)
            with self.assertRaises(OSError):read_file(link)
            with self.assertRaises(ValueError):replace_file(link,b'bad',metadata)
            with self.assertRaises(ValueError):read_file(p,2)


if __name__=='__main__':unittest.main()
