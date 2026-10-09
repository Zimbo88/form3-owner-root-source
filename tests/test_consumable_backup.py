"""Private backup/restore boundaries with authored synthetic inputs only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-maintenance'))
from consumable_backup import Store
from cartridge_codec import candidate, validate_legacy_material
from test_cartridge_material import fixture, NAME


def captured(kind='cartridge'):
    image,rec=fixture()
    rec.update(DataVersionRO=0,DataVersionRW=1)
    return {'kind':kind,'device_name':NAME,'material':'FLGPCL02','eeprom':image if kind=='cartridge' else image*4,
            'record':json.dumps(rec).encode(),'validation':('CHECKSUMS_AND_MIRROR_VERIFIED' if kind=='cartridge' else 'STABLE_RAW_COPY; TANK_CODEC_NOT_VALIDATED')}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name,captured)

    def test_roundtrip_private_and_summary_redaction(self):
        row=self.store.backup('cartridge')
        meta,image,raw=self.store.load(row['id'])
        self.assertEqual(image,captured()['eeprom'])
        self.assertEqual(raw,captured()['record'])
        self.assertNotIn(NAME,json.dumps(row))
        self.assertNotIn('SYNTHETIC-NOT-A-VENDOR-KEY',json.dumps(row))
        self.assertEqual(self.store.list(),[row])
        self.assertEqual(os.stat(Path(self.tmp.name,row['id'])).st_mode & 0o777,0o700)

    def test_tank_backup_not_a_restore_claim(self):
        row=self.store.backup('tank')
        with self.assertRaisesRegex(ValueError,'Tank restore'):
            self.store.restore_usage(row['id'],captured('tank'))

    def test_cartridge_usage_restore_same_identity(self):
        row=self.store.backup('cartridge');current=captured()
        rec=json.loads(current['record'])
        target,rw,revised,decoded,diff=candidate(current['eeprom'],rec,NAME)
        current.update(eeprom=target,record=json.dumps(revised).encode())
        usage=self.store.restore_usage(row['id'],current)
        restored,rw,new,decoded,diff=candidate(target,revised,NAME,usage)
        self.assertEqual(new['EstimatedVolumeDispensed_ml'],1033.6)
        self.assertEqual(new['WriteCount'],540)
        self.assertEqual(restored[:64],target[:64])

    def test_wrong_chip_refused(self):
        row=self.store.backup('cartridge');current=captured();current['device_name']='2d-000000000001'
        with self.assertRaises(ValueError):self.store.restore_usage(row['id'],current)

    def test_material_or_unknown_ro_edit_refused(self):
        row=self.store.backup('cartridge');current=captured()
        image=bytearray(current['eeprom']);image[38]^=1;current['eeprom']=bytes(image)
        with self.assertRaises(ValueError):self.store.restore_usage(row['id'],current)

    def test_backup_corruption_refused(self):
        row=self.store.backup('cartridge');Path(self.tmp.name,row['id'],'eeprom.bin').write_bytes(b'broken')
        with self.assertRaises(ValueError):self.store.load(row['id'])

    def test_path_escape_and_symlink_refused(self):
        for identifier in ('../etc/shadow','/tmp/x','a'*33,''):
            with self.assertRaises(ValueError):self.store.load(identifier)
        Path(self.tmp.name,'f'*32).symlink_to('/tmp',target_is_directory=True)
        with self.assertRaises(ValueError):self.store.load('f'*32)

    def test_partial_backup_blocks_list(self):
        Path(self.tmp.name,'.pending-fixture').mkdir()
        with self.assertRaises(ValueError):self.store.list()

    def test_format_validation_clear_four_and_white(self):
        import cartridge_codec as c
        import struct
        for code in ('FLGPCL02','FLGPCL04','FLGPWH41','FLGPGR04'):
            value=captured();rec=json.loads(value['record']);rec['ResinID']=code
            image=bytearray(value['eeprom']);key=c.derive_key(rec['SecretKey'],NAME)
            plain=c._decrypt(key,image[2:6]*2,image[10:43],10)
            plain=plain[:21]+code.encode()+plain[29:]
            image[6:10]=struct.pack('<I',c.checksum(plain));image[10:43]=c._decrypt(key,image[2:6]*2,plain,10)
            self.assertEqual(validate_legacy_material(bytes(image),rec,NAME),code)

    def test_unknown_format_and_mismatched_material_refused(self):
        for field,value in [('DataVersionRO',1),('DataVersionRW',2),('OriginalVolume_mL',2000),('ResinID','FLGPWH41')]:
            record=captured();rec=json.loads(record['record']);rec[field]=value
            with self.assertRaises(ValueError):validate_legacy_material(record['eeprom'],rec,NAME)


if __name__=='__main__':unittest.main()
