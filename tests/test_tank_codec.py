"""Synthetic T/65 fixtures; no real tank keys, bytes, identities or writes."""
import json,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-maintenance'))
import tank_codec as c
NAME='4c-000000000000'
def fixture():
    record={'SecretKey':'SYNTHETIC-TANK-NOT-A-DEVICE-KEY','DataVersionRO':65,'DataVersionRW':65,
            'TankVersionMajor':3,'TankVersionMinor':3,'MixerVersion':1,'FloatVersion':1,
            'VolumePrinted_mm3':123.4,'NumLayersPrinted':123,'PrintTime_mS':234567,
            'LastResinLevel_mm':8.766411,'LastResinUsed':'FLGPCL04','LastPrintDate':'2023-11-14T22:13:20',
            'DateFirstFill':'2020-09-13T12:26:40','PrivateUnknown':'preserve'}
    image=bytearray([0xff]*512);image[:6]=b'TAABCD';key=c.key_for(record,NAME);iv=b'ABCDABCD'
    ro=bytes(range(18))+bytes([3,3,1,1]);image[6:10]=struct.pack('<I',c.checksum(ro));image[10:32]=c.crypt(key,iv,ro,10)
    raw=struct.pack('<fIQIf8sI',123.4,123,234567,1700000000,8.766411,b'FLGPCL04',1600000000)
    rw=b'A'+struct.pack('<I',c.checksum(raw))+c.crypt(key,iv,raw)
    image[32:73]=rw;image[128:169]=rw
    return bytes(image),record
class TankTests(unittest.TestCase):
    def test_decode_and_float32_mirror_projection(self):
        image,rec=fixture();r=c.decode(image,rec,NAME)
        self.assertTrue(r['ro_checksum_valid']);self.assertTrue(r['rw_equal'])
        self.assertTrue(all(r['copies'][0]['record_matches'].values()))
        self.assertNotIn(rec['SecretKey'],json.dumps(r));self.assertNotIn(NAME,json.dumps(r))
    def test_material_candidate_preserves_lifetime_identity_and_padding(self):
        image,rec=fixture();target,revised,r=c.material_candidate(image,rec,NAME,'FLGPWH41')
        self.assertEqual(revised['PrivateUnknown'],'preserve');self.assertEqual(r['copies'][0]['values']['NumLayersPrinted'],123)
        allowed=set(range(33,37))|set(range(61,69))|set(range(129,133))|set(range(157,165))
        self.assertTrue(all(image[i]==target[i] for i in range(512) if i not in allowed))
    def test_corruption_each_record(self):
        image,rec=fixture()
        for offset in (20,42,150):
            bad=bytearray(image);bad[offset]^=1
            with self.assertRaises(ValueError):c.decode(bytes(bad),rec,NAME)
    def test_truncated_and_unknown_header(self):
        image,rec=fixture()
        for bad in (image[:-1],image+b'x',b'TB'+image[2:]):
            with self.assertRaises(ValueError):c.decode(bad,rec,NAME)
    def test_wrong_key_identity(self):
        image,rec=fixture()
        for name in ('2d-000000000000','4c-000000000001',NAME+'\n'):
            with self.assertRaises(ValueError):c.decode(image,rec,name)
    def test_mirror_mismatch_blocks_candidate(self):
        image,rec=fixture();rec['NumLayersPrinted']+=1
        with self.assertRaises(ValueError):c.material_candidate(image,rec,NAME,'FLGPWH41')
    def test_date_mismatch_blocks_candidate(self):
        for field in ('LastPrintDate','DateFirstFill'):
            image,rec=fixture();rec[field]='2025-01-01T00:00:00'
            with self.assertRaises(ValueError):c.material_candidate(image,rec,NAME,'FLGPWH41')
    def test_material_injection_refused(self):
        image,rec=fixture()
        for material in ('../bad','FLGPCL04\n','x'*100):
            with self.assertRaises(ValueError):c.material_candidate(image,rec,NAME,material)
if __name__=='__main__':unittest.main()
