"""Exercise real localhost HTTP requests and synthetic Linux files; no printer."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import socket,time
import unittest

spec=importlib.util.spec_from_file_location('owner_server',Path(__file__).resolve().parents[1]/'owner-ui/server.py')
server_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(server_module)

class LocalDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token='synthetic-test-token-not-a-credential'
        cls.server=server_module.make_server(server_module.SampleProvider(),cls.token,0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(5)
    def request(self,path='/api/status',method='GET',auth=True,headers=None):
        h={'Authorization':'Bearer '+self.token} if auth else {}
        h.update(headers or {})
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            c.request(method,path,headers=h);r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def test_loopback_only(self):self.assertEqual(self.server.server_address[0],'127.0.0.1')
    def test_no_anonymous_status(self):self.assertEqual(self.request(auth=False)[0],401)
    def test_wrong_token(self):self.assertEqual(self.request(headers={'Authorization':'Bearer incorrect'})[0],401)
    def test_non_ascii_token_refused(self):self.assertEqual(self.request(headers={'Authorization':'Bearer invalid-\u00e9'})[0],401)
    def test_sample_endpoints_and_second_connection(self):
        for path in ['status','thermal','system','storage','firmware','services','status']:
            status,headers,body=self.request('/api/'+path)
            self.assertEqual(status,200);data=json.loads(body)
            self.assertEqual(data['source'],'sample');self.assertTrue(data['read_only'])
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertNotIn(self.token,body.decode())
    def test_writes_refused(self):
        for method in ['POST','PUT','PATCH','DELETE','OPTIONS']:
            self.assertEqual(self.request(method=method)[0],405)
    def test_cross_origin_refused(self):
        self.assertEqual(self.request(headers={'Origin':'https://untrusted.invalid'})[0],403)
    def test_dns_rebinding_host_refused(self):
        self.assertEqual(self.request(headers={'Host':'untrusted.invalid'})[0],403)
    def test_no_arbitrary_file_or_command_endpoint(self):
        for path in ['/../../etc/passwd','/api/read?path=/etc/shadow','/api/run?command=id','/%2e%2e/server.py']:
            self.assertEqual(self.request(path)[0],404)
    def test_assets_have_browser_guards(self):
        for path in ['/','/app.js','/style.css']:
            status,headers,_=self.request(path,auth=False)
            self.assertEqual(status,200);self.assertEqual(headers['X-Frame-Options'],'DENY')
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
    def test_weak_token_refused(self):
        with self.assertRaises(ValueError):server_module.make_server(server_module.SampleProvider(),'short',0)
    def test_excess_connections_are_bounded_and_recover(self):
        # Hold all four worker slots with incomplete requests, then exercise
        # refusal and recovery using actual sockets, not a host nc listener.
        held=[]
        try:
            for _ in range(4):
                s=socket.create_connection(self.server.server_address,timeout=2);s.sendall(b'GET / HTTP/1.1\r\n');held.append(s)
            deadline=time.monotonic()+2
            while self.server.request_slots._value and time.monotonic()<deadline:time.sleep(.01)
            extra=socket.create_connection(self.server.server_address,timeout=2)
            try:self.assertEqual(extra.recv(1),b'')
            finally:extra.close()
        finally:
            for s in held:s.close()
        deadline=time.monotonic()+2
        while self.server.request_slots._value!=4 and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.request()[0],200)
    def test_slow_header_times_out(self):
        s=socket.create_connection(self.server.server_address,timeout=5)
        try:
            s.sendall(b'GET / HTTP/1.1\r\n');self.assertEqual(s.recv(1),b'')
        finally:s.close()

class LinuxReadAdapter(unittest.TestCase):
    def test_fixture_and_missing_sensors(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            fixture={'proc/uptime':'123.5 22','proc/loadavg':'0.1 0.2 0.3 1/3 5',
                'proc/meminfo':'MemTotal: 1024 kB\nMemAvailable: 512 kB\n',
                'proc/cmdline':'console=ttyS2 root=/dev/mmcblk0p6 rw',
                'proc/42/comm':'Formule',
                'etc/formlabs/version.json':'{"build":{"name":"TEST-VERSION"}}',
                'sys/class/thermal/thermal_zone0/type':'cpu_thermal',
                'sys/class/thermal/thermal_zone0/temp':'43200',
                'sys/class/thermal/thermal_zone1/type':'unavailable'}
            for name,value in fixture.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
            result=server_module.LinuxProvider(root).snapshot()
            self.assertEqual(result['firmware'],{'slot':6,'version':'TEST-VERSION'})
            self.assertEqual(result['thermal_zones'][0]['celsius'],43.2)
            self.assertIsNone(result['thermal_zones'][1]['celsius'])
            self.assertEqual(result['system']['memory_available_bytes'],512*1024)
            self.assertTrue(next(s['running'] for s in result['services'] if s['name']=='Formule'))
            self.assertEqual((root/'proc/cmdline').read_text(),fixture['proc/cmdline'])
    def test_missing_proc_is_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            result=server_module.LinuxProvider(Path(d)).snapshot()
            self.assertIsNone(result['firmware']['slot']);self.assertEqual(result['thermal_zones'],[])

if __name__=='__main__':unittest.main()
