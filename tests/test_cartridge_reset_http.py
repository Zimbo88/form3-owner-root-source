"""Real localhost auth/CSRF requests; fake broker, no target writes."""
import sys, unittest, threading, http.client, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-ui'))
import server

class FakeBroker(object):
    def __init__(self):self.calls=[]
    def request(self,*args,**kwargs):self.calls.append((args,kwargs) if kwargs else args);return {'state':'AVAILABLE'}

class ResetHTTPTests(unittest.TestCase):
    def setUp(self):
        self.helper=FakeBroker();self.secret='synthetic-reset-test-secret-only'
        self.http=server.make_server(server.SampleProvider(),self.secret,0,reset_client=self.helper)
        self.thread=threading.Thread(target=self.http.serve_forever);self.thread.start()
        self.cookie='';self.csrf='';self.port=self.http.server_port
    def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join(3)
    def request(self,path,body=None,headers=None):
        h={'Origin':'http://127.0.0.1:'+str(self.port),'Cookie':self.cookie,'X-CSRF-Token':self.csrf}
        if body is not None:h['Content-Type']='application/json'
        h.update(headers or {});c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        try:
            c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,h)
            r=c.getresponse();return r.status,dict(r.getheaders()),json.loads(r.read())
        finally:c.close()
    def login(self):
        code,h,b=self.request('/api/login',{'secret':self.secret});self.assertEqual(code,200)
        self.cookie=h['Set-Cookie'].split(';')[0];self.csrf=b['csrf']
    def apply_body(self):return {'secret':self.secret,'plan_id':'a'*48,'confirmation':'RESET CLEAR USAGE'}
    def test_anonymous_refused(self):
        self.assertEqual(self.request('/api/cartridge-reset')[0],401)
        self.assertEqual(self.request('/api/cartridge-reset/prepare',{})[0],401);self.assertEqual(self.helper.calls,[])
    def test_preview_and_apply_typed_only(self):
        self.login();self.assertEqual(self.request('/api/cartridge-reset/prepare',{})[0],202)
        self.assertEqual(self.request('/api/cartridge-reset/apply',self.apply_body())[0],202)
        self.assertEqual(self.helper.calls,[('prepare',),('apply','a'*48)])
    def test_csrf(self):
        self.login();self.assertEqual(self.request('/api/cartridge-reset/prepare',{}, {'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.helper.calls,[])
    def test_origin_host(self):
        self.login()
        for h in [{'Origin':'http://foreign.invalid'},{'Host':'foreign.invalid'}]:
            self.assertEqual(self.request('/api/cartridge-reset/prepare',{},h)[0],403)
        self.assertEqual(self.helper.calls,[])
    def test_reauthentication_and_confirmation(self):
        self.login();body=self.apply_body();body['secret']='wrong'
        self.assertEqual(self.request('/api/cartridge-reset/apply',body)[0],403)
        body=self.apply_body();body['confirmation']='yes'
        self.assertEqual(self.request('/api/cartridge-reset/apply',body)[0],400)
        self.assertEqual(self.helper.calls,[])
    def test_no_arbitrary_settings(self):
        self.login();self.assertEqual(self.request('/api/cartridge-reset/prepare',{'path':'/etc/passwd'})[0],400)
        self.assertEqual(self.helper.calls,[])
    def test_reauthentication_rate_limit(self):
        self.login();body=self.apply_body();body['secret']='wrong'
        for _ in range(6):self.assertEqual(self.request('/api/cartridge-reset/apply',body)[0],403)
        self.assertEqual(self.request('/api/cartridge-reset/apply',self.apply_body())[0],429)
        self.assertEqual(self.helper.calls,[])
    def test_missing_helper(self):
        self.login();self.assertEqual(self.request('/api/cartridge-reset')[0],200)
    def test_bearer_cannot_mutate(self):
        self.assertEqual(self.request('/api/cartridge-reset/prepare',{}, {'Authorization':'Bearer '+self.secret})[0],401)

    def test_backup_restore_and_material_typed_requests(self):
        self.login()
        cases=[('backup',{'kind':'tank'},(('backup',),{'kind':'tank'})),
               ('backups',{},('backups',)),
               ('restore-preview',{'backup_id':'b'*32},(('prepare_restore',),{'backup_id':'b'*32})),
               ('materials',{},('materials',)),
               ('material-preview',{'material':'FLGPCL04'},(('prepare_material',),{'material':'FLGPCL04'}))]
        for endpoint,body,expected in cases:
            self.assertEqual(self.request('/api/cartridge-reset/'+endpoint,body)[0],202)
            self.assertEqual(self.helper.calls[-1],expected)

    def test_new_operations_require_login_csrf_and_origin(self):
        cases=[('backup',{'kind':'cartridge'}),('restore-preview',{'backup_id':'b'*32}),
               ('material-preview',{'material':'FLGPCL04'}),('backups',{}),('materials',{})]
        for endpoint,body in cases:
            self.assertEqual(self.request('/api/cartridge-reset/'+endpoint,body)[0],401)
        self.login()
        for endpoint,body in cases:
            for headers in ({'X-CSRF-Token':'wrong'},{'Origin':'http://foreign.invalid'}):
                self.assertEqual(self.request('/api/cartridge-reset/'+endpoint,body,headers)[0],403)
        self.assertEqual(self.helper.calls,[])

    def test_new_operations_reject_paths_unknown_types_and_fields(self):
        self.login()
        for endpoint,body in [('backup',{'kind':'tank','path':'/etc/shadow'}),('backup',{'kind':'chip'}),
                              ('restore-preview',{'backup_id':'../x'}),('material-preview',{'material':'FLGPCL04\n'}),
                              ('materials',{'device':'other'}),('backups',{'all':True})]:
            self.assertEqual(self.request('/api/cartridge-reset/'+endpoint,body)[0],400)
        self.assertEqual(self.helper.calls,[])

    def test_material_apply_requires_distinct_confirmation_and_secret(self):
        self.login();body=self.apply_body()
        self.assertEqual(self.request('/api/cartridge-reset/material-apply',body)[0],400)
        body['confirmation']='CHANGE CARTRIDGE MATERIAL';body['secret']='wrong'
        self.assertEqual(self.request('/api/cartridge-reset/material-apply',body)[0],403)
        body['secret']=self.secret
        self.assertEqual(self.request('/api/cartridge-reset/material-apply',body)[0],202)
        self.assertEqual(self.helper.calls,[('apply_material','a'*48)])

    def test_tank_material_preview_is_typed_and_authenticated(self):
        endpoint='/api/cartridge-reset/tank-material-preview';body={'material':'FLGPCL41'}
        self.assertEqual(self.request(endpoint,body)[0],401)
        self.login()
        self.assertEqual(self.request(endpoint,body,{'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.request(endpoint,body,{'Origin':'http://other.invalid'})[0],403)
        self.assertEqual(self.request(endpoint,dict(body,path='/etc/shadow'))[0],400)
        self.assertEqual(self.request(endpoint,body)[0],202)
        self.assertEqual(self.helper.calls,[(('prepare_tank_material',),{'material':'FLGPCL41'})])

    def test_tank_apply_requires_clean_confirmation_and_reauthentication(self):
        self.login();endpoint='/api/cartridge-reset/tank-material-apply'
        body={'plan_id':'a'*48,'confirmation':'CHANGE CLEAN TANK MATERIAL','secret':self.secret}
        self.assertEqual(self.request(endpoint,body)[0],400)
        for bad in (False,1,'yes',None):
            self.assertEqual(self.request(endpoint,dict(body,tank_empty_clean=bad))[0],400)
        body['tank_empty_clean']=True
        self.assertEqual(self.request(endpoint,dict(body,secret='wrong'))[0],403)
        self.assertEqual(self.request(endpoint,body,{'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.request(endpoint,body)[0],202)
        self.assertEqual(self.helper.calls,[('apply_tank_material','a'*48)])
