"""Only fake responses; never contacts a printer or external server."""
import email.message,io,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import check_panel_assets as assets

class AssetChecks(unittest.TestCase):
    def test_explicit_private_ipv4_only(self):
        for url in ('http://192.168.50.20:1328/','https://172.20.0.5:1328/'):
            self.assertIn(assets.target(url)[0],('http','https'))
        for url in ('http://example.com:1328/','http://127.0.0.1:1328/','http://0.0.0.0:1328/',
                    'http://8.8.8.8:1328/','http://169.254.0.1:1328/','http://[::1]:1328/',
                    'http://192.168.50.20:80/','http://u:p@192.168.50.20:1328/',
                    'http://192.168.50.20:1328/?secret=x','http://192.168.50.20:1328/app.js'):
            with self.assertRaises(ValueError):assets.target(url)
    def response(self,raw,length,status=200):
        class Response:
            def read(self,n):return raw[:n]
        r=Response();r.status=status;r.headers=email.message.Message();r.headers['Content-Length']=str(length);return r
    def test_exact_asset_and_short_socket_body(self):
        expected=b'authored asset '*2000
        self.assertTrue(assets.response_bytes(self.response(expected,len(expected)),expected)['complete'])
        for raw in (expected[:-446],expected+b'x',b'x'*len(expected)):
            with self.assertRaises(ValueError):assets.response_bytes(self.response(raw,len(expected)),expected)
    def test_redirect_or_ambiguous_framing_refused(self):
        for status in (301,302,401,503):
            with self.assertRaises(ValueError):assets.response_bytes(self.response(b'abc',3,status),b'abc')
        r=self.response(b'abc',3);r.headers['Content-Length']='3'
        with self.assertRaises(ValueError):assets.response_bytes(r,b'abc')
        r=self.response(b'abc',3);r.headers['Transfer-Encoding']='chunked'
        with self.assertRaises(ValueError):assets.response_bytes(r,b'abc')
