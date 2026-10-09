"""Synthetic fixtures only; never touches a printer or real consumable."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"owner-maintenance"))
import unittest, struct
from cartridge_codec import candidate, parse_record
from cartridge_codec import derive_key, _decrypt, checksum

class CandidateTests(unittest.TestCase):
    def fixture(self, count=538):
        name='2d-000000000000'
        record=dict(SecretKey='SYNTHETIC-NOT-A-DEVICE-KEY',DispenseCount=284,
            WriteCount=count,EstimatedVolumeDispensed_ml=1033.6,CumulativeDispenseTime_s=4779,
            Material='synthetic',Other='unchanged')
        data=bytearray([0x55]*128); data[:2]=b'C\x00'; data[2:6]=b'ABCD'
        key=derive_key(record['SecretKey'],name); iv=bytes(data[2:6])*2
        ro=bytes(range(33)); data[6:10]=struct.pack('<I',checksum(ro))
        data[10:43]=_decrypt(key,iv,ro,10)
        plain=(284).to_bytes(3,'big')+struct.pack('<IHH',count,10336,4779)
        rw=b'\x01'+_decrypt(key,iv,plain,0)+struct.pack('<I',checksum(plain))
        data[64:80]=rw; data[96:112]=rw
        return bytes(data),record,name
    def test_round_trip_and_unchanged_identity(self):
        image,record,name=self.fixture()
        target,rw,revised,decoded,diff=candidate(image,record,name)
        self.assertEqual(len(target),128); self.assertEqual(len(rw),16)
        self.assertEqual(revised['WriteCount'],539)
        self.assertTrue(decoded['ro_checksum_valid'])
        for c in decoded['rw_copies']:
            self.assertEqual(c['usage']['EstimatedVolumeDispensed_ml'],0)
            self.assertEqual(c['usage']['DispenseCount'],0)
            self.assertEqual(c['usage']['CumulativeDispenseTime_s'],0)
        for k in record:
            if k not in ('EstimatedVolumeDispensed_ml','DispenseCount','CumulativeDispenseTime_s','WriteCount'):
                self.assertEqual(record[k],revised[k])
        self.assertEqual(target[:64],image[:64]); self.assertEqual(target[80:96],image[80:96]); self.assertEqual(target[112:],image[112:])
    def test_nonfinite_unknown_field_rejected(self):
        import json
        _,record,_=self.fixture();record['Unknown']=float('nan')
        with self.assertRaises(ValueError):parse_record(json.dumps(record).encode())
    def test_truncated(self):
        image,record,name=self.fixture()
        with self.assertRaises(ValueError): candidate(image[:-1],record,name)
    def test_corrupt(self):
        image,record,name=self.fixture(); damaged=bytearray(image); damaged[65]^=1
        with self.assertRaises(ValueError): candidate(bytes(damaged),record,name)
    def test_stale_mirror(self):
        image,record,name=self.fixture(); record['WriteCount']=10
        with self.assertRaises(ValueError): candidate(image,record,name)
    def test_overflow(self):
        image,record,name=self.fixture(0xffffffff)
        with self.assertRaises(ValueError): candidate(image,record,name)
if __name__=='__main__': unittest.main()

class QuantizationTests(unittest.TestCase):
    def test_native_tenth_ml_projection_does_not_require_equal_json_float(self):
        from test_cartridge_material import fixture,NAME
        from cartridge_codec import decode,candidate
        image,record=fixture();record['EstimatedVolumeDispensed_ml']=1033.654
        decoded=decode(image,record,NAME)
        self.assertTrue(decoded['rw_copies'][0]['record_matches']['EstimatedVolumeDispensed_ml'])
        self.assertFalse(decoded['rw_copies'][0]['record_exact_matches']['EstimatedVolumeDispensed_ml'])
        candidate(image,record,NAME)
        record['EstimatedVolumeDispensed_ml']=1033.7
        with self.assertRaises(ValueError):candidate(image,record,NAME)
