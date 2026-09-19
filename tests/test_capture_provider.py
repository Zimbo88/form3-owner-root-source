"""Panel integration uses authored offline captures; never network or idle clearance."""
import json,struct,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-ui'))
from panel_data import read_formule_capture
from server import CaptureProvider,SampleProvider,decorate_snapshot

def frame(success=True):
    raw=json.dumps({'ReplyToMethod':'PROTOCOL_METHOD_GET_STATUS','Version':1,'Success':success,
                    'Parameters':{'isPrinting':False,'SecretKey':'SYNTHETIC-NOT-OUTPUT','SECRET-KEY-AS-NAME':7}}).encode()
    return struct.pack('<I',len(raw))+raw+struct.pack('<q',0)

class CaptureProviderTests(unittest.TestCase):
    def test_historical_not_safe_idle(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'copied';p.write_bytes(frame());capture=read_formule_capture(str(p))
            view=decorate_snapshot(CaptureProvider(SampleProvider(),capture).snapshot())
            self.assertEqual(view['protocol_observation']['state'],'HISTORICAL')
            self.assertFalse(view['protocol_observation']['safe_idle_proven'])
            self.assertEqual(view['fields']['safe_idle']['state'],'UNAVAILABLE')
            self.assertNotIn('SYNTHETIC-NOT-OUTPUT',json.dumps(view))
            self.assertNotIn('SECRET-KEY-AS-NAME',json.dumps(view))
    def test_failed_reply_has_no_status(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'copied';p.write_bytes(frame(False));self.assertEqual(read_formule_capture(str(p))['status'],{})
    def test_invalid_or_symlink_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'copied';p.write_bytes(frame()[:-1])
            with self.assertRaises(ValueError):read_formule_capture(str(p))
            p.write_bytes(frame());link=Path(d)/'link';link.symlink_to(p)
            with self.assertRaises(OSError):read_formule_capture(str(link))
    def test_explicit_demo(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'demo';p.write_bytes(frame());self.assertEqual(read_formule_capture(str(p),True)['state'],'DEMO')
