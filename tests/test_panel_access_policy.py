"""Open/locked panel behavior over real loopback HTTP with synthetic helpers."""
import json,tempfile,threading,unittest,http.client,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-ui'))
import server

class Helper:
    def __init__(self):self.calls=[]
    def request(self,*args,**kw):self.calls.append((args,kw));return {'state':'AVAILABLE'}
class Logs:
    def raw_log(self,file_id):
        if file_id!='fixture':raise ValueError('Unknown log')
        return b'SYNTHETIC LOG\n'
class PanelAccessPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=server.OwnerStore(self.tmp.name)
        self.secret='synthetic-panel-access-secret-only';self.helper=Helper()
        self.http=server.make_server(server.SampleProvider(),self.secret,0,store=self.store,bundle=Logs(),reset_client=self.helper)
        self.worker=threading.Thread(target=self.http.serve_forever);self.worker.start()
        self.port=self.http.server_port;self.cookie='';self.csrf=''
    def tearDown(self):self.http.shutdown();self.http.server_close();self.worker.join(3);self.store.tree.close();self.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        h={'Origin':'http://127.0.0.1:'+str(self.port),'Cookie':self.cookie,'X-CSRF-Token':self.csrf}
        if body is not None:h['Content-Type']='application/json'
        h.update(headers or {});c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        try:
            c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),h)
            r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def login(self,locked=False):
        code,h,b=self.request('/api/login',{'secret':self.secret} if locked else {})
        self.assertEqual(code,200);self.cookie=h['Set-Cookie'].split(';')[0];self.csrf=json.loads(b)['csrf']
        self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie'])
    def test_default_open_all_consumable_actions_without_secret(self):
        self.assertFalse(json.loads(self.request('/api/access-policy')[2])['authentication_required'])
        self.login()
        cases=[('prepare',{}),('backup',{'kind':'tank'}),('backups',{}),('materials',{}),
               ('restore-preview',{'backup_id':'b'*32}),('tank-material-preview',{'material':'FLGPCL04'}),
               ('material-preview',{'material':'FLGPCL04'}),
               ('apply',{'plan_id':'a'*48,'confirmation':'APPLY CARTRIDGE USAGE'}),
               ('material-apply',{'plan_id':'a'*48,'confirmation':'CHANGE CARTRIDGE MATERIAL'}),
               ('tank-material-apply',{'plan_id':'a'*48,'confirmation':'CHANGE CLEAN TANK MATERIAL','tank_empty_clean':True})]
        for name,body in cases:
            with self.subTest(name=name):self.assertEqual(self.request('/api/cartridge-reset/'+name,body)[0],202)
        self.assertEqual(len(self.helper.calls),len(cases))
    def test_open_still_requires_session_csrf_host_origin(self):
        path='/api/cartridge-reset/prepare'
        self.assertEqual(self.request(path,{})[0],401);self.login()
        for h in ({'X-CSRF-Token':''},{'Origin':'http://other.invalid'},{'Host':'other.invalid'}):
            self.assertEqual(self.request(path,{},h)[0],403)
        self.assertEqual(self.helper.calls,[])
    def test_open_tank_still_requires_clean_ack_and_confirmation(self):
        self.login();body={'plan_id':'a'*48,'confirmation':'CHANGE CLEAN TANK MATERIAL'}
        for extra in ({},{'tank_empty_clean':False},{'tank_empty_clean':1},{'tank_empty_clean':True,'path':'/etc/shadow'}):
            self.assertEqual(self.request('/api/cartridge-reset/tank-material-apply',dict(body,**extra))[0],400)
        self.assertEqual(self.helper.calls,[])
    def test_switch_on_rejects_existing_open_session_and_requires_secret(self):
        self.login();v=dict(server.DEFAULT_SETTINGS,wlan_login_required=True)
        self.assertEqual(self.request('/api/settings',v)[0],200)
        self.assertEqual(self.request('/api/cartridge-reset/prepare',{})[0],401)
        self.assertEqual(self.request('/api/login',{})[0],401)
        self.login(True);body={'plan_id':'a'*48,'confirmation':'APPLY CARTRIDGE USAGE'}
        self.assertEqual(self.request('/api/cartridge-reset/apply',body)[0],403)
        self.assertEqual(self.request('/api/cartridge-reset/apply',dict(body,secret=self.secret))[0],202)
        self.assertEqual(self.request('/api/settings',dict(server.DEFAULT_SETTINGS))[0],200)
        self.assertEqual(self.request('/api/cartridge-reset/apply',body)[0],202)
    def test_private_export_uses_same_policy_but_keeps_explicit_confirmation(self):
        self.login();body={'private':True,'file_id':'fixture'}
        self.assertEqual(self.request('/api/export',body)[0],403)
        body['confirm_private']='DOWNLOAD PRIVATE LOG'
        code,_,data=self.request('/api/export',body);self.assertEqual(code,200);self.assertEqual(data,b'SYNTHETIC LOG\n')
        self.store.save('settings.json',dict(server.DEFAULT_SETTINGS,wlan_login_required=True));self.login(True)
        self.assertEqual(self.request('/api/export',body)[0],403)
        self.assertEqual(self.request('/api/export',dict(body,secret=self.secret))[0],200)
    def test_invalid_policy_fails_closed(self):
        self.login();self.store.save('access-policy.json',{'wlan_login_required':'false'})
        self.assertTrue(json.loads(self.request('/api/access-policy')[2])['authentication_required'])
        self.assertEqual(self.request('/api/cartridge-reset/prepare',{})[0],401)
