"""Real local UNIX socket fixtures in the isolated test namespace."""
import sys,os,socket,tempfile,threading,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-ui'))
import reset_client

class ClientTests(unittest.TestCase):
    def exchange(self,reply):
        with tempfile.TemporaryDirectory() as root:
            path=root+'/broker.sock';listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            listener.bind(path);os.chmod(path,0o600);listener.listen(1);listener.settimeout(3)
            received=[]
            def serve():
                c,_=listener.accept()
                with c:received.append(c.recv(4096));c.sendall(reply)
            thread=threading.Thread(target=serve);thread.start()
            try:
                with patch.object(reset_client,'SOCKET',path):return reset_client.ResetClient().request('status'),received
            finally:thread.join(4);listener.close()
    def test_fixed_typed_request_and_root_peer(self):
        result,received=self.exchange(b'{"state":"AVAILABLE"}\n')
        self.assertEqual(result['state'],'AVAILABLE');self.assertEqual(json.loads(received[0]),{'operation':'status'})
    def test_bounded_malformed_response(self):
        for raw in [b'[]\n',b'{}',b'x'*8193+b'\n']:
            with self.assertRaises(ValueError):self.exchange(raw)
    def test_regular_file_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root,'not-socket');p.write_text('no');link=Path(root,'link');link.symlink_to(p)
            for f in [p,link]:
                with patch.object(reset_client,'SOCKET',str(f)),self.assertRaises(ValueError):reset_client.ResetClient().request('status')
    def test_unknown_operation_before_connect(self):
        with self.assertRaises(ValueError):reset_client.ResetClient().request('execute')
