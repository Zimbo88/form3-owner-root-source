"""Synthetic isolated LAN sockets and owner transactions. No external network."""
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from test_owner_ui import server_module as ui
import test_owner_install as install_fixtures
ctl, pkg, bootstrap = install_fixtures.ctl, install_fixtures.pkg, install_fixtures.bootstrap
from lan_ipv4 import private_assignment, interface_assignment, interface_name


class IPv4Policy(unittest.TestCase):
    def test_all_rfc1918_ranges(self):
        for ip, mask, network in [('192.168.50.20','255.255.255.0','192.168.50.0/24'),
                                  ('172.20.2.3','255.255.0.0','172.20.0.0/16'),
                                  ('10.23.2.3','255.0.0.0','10.0.0.0/8')]:
            self.assertEqual(private_assignment(ip,mask),(ip,network))
    def test_invalid_nonprivate_hosts_and_masks(self):
        for ip, mask in [('0.0.0.0','255.255.255.0'),('127.0.0.1','255.0.0.0'),
                         ('169.254.1.2','255.255.0.0'),('224.0.0.1','255.0.0.0'),
                         ('100.64.1.2','255.255.0.0'),('198.18.1.2','255.255.0.0'),
                         ('8.8.8.8','255.255.255.0'),('192.168.50.20','0.0.0.255'),
                         ('192.168.50.20','255.0.255.0'),('192.168.50.20','255.255.255.255'),
                         ('192.168.50.20','128.0.0.0'),('192.168.50.0','255.255.255.0'),
                         ('192.168.50.255','255.255.255.0'),('::1','255.255.255.0')]:
            with self.subTest(ip=ip,mask=mask),self.assertRaises(ValueError):private_assignment(ip,mask)
    def test_generic_interface_and_refusals(self):
        self.assertEqual(interface_name('wlp2s0'),'wlp2s0')
        for name in ('lo','../wlan0','wlan0;id','*','a'*16,''):
            with self.assertRaises(ValueError):interface_name(name)
    def test_missing_interface_returns_unavailable(self):
        with mock.patch('lan_ipv4.fcntl.ioctl',side_effect=OSError):self.assertIsNone(interface_assignment('wlp2s0'))
    def test_netmask_read_and_address_race(self):
        import struct
        flags=b'\0'*16+struct.pack('H',1)+b'\0'*22
        def row(ip):return b'\0'*20+socket.inet_aton(ip)+b'\0'*16
        with mock.patch('lan_ipv4.fcntl.ioctl',side_effect=[flags,row('192.168.50.20'),row('255.255.255.0'),row('192.168.50.20')]):
            self.assertEqual(interface_assignment('wlp2s0'),('192.168.50.20','192.168.50.0/24'))
        with mock.patch('lan_ipv4.fcntl.ioctl',side_effect=[flags,row('192.168.50.20'),row('255.255.255.0'),row('192.168.50.21')]):
            self.assertIsNone(interface_assignment('wlp2s0'))


class WLANRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('OWNER_TEST_NETNS')!='1':
            raise RuntimeError('Run through tools/developer_check.py isolated network runner')
        cls.tmp=tempfile.TemporaryDirectory()
        cls.cert=Path(cls.tmp.name)/'cert';cls.key=Path(cls.tmp.name)/'key'
        subprocess.run(['openssl','req','-config','/dev/null','-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-subj','/CN=synthetic','-addext','subjectAltName=IP:127.0.0.1',
                        '-keyout',str(cls.key),'-out',str(cls.cert)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
    def setUp(self):
        self.assignment=('192.168.50.20','192.168.50.0/24')
        self.patch=mock.patch.object(ui,'interface_assignment',side_effect=lambda _:self.assignment);self.patch.start()
        self.secret='synthetic-WLAN-test-not-production-key'
        self.state_dir=tempfile.TemporaryDirectory()
        self.store=ui.OwnerStore(self.state_dir.name)
        self.store.save('settings.json',dict(ui.DEFAULT_SETTINGS,wlan_login_required=True))
        self.manager=ui.SecondaryHTTP('wlp2s0',ui.SampleProvider(),self.secret,self.store)
        self.assertTrue(self.manager.poll())
    def tearDown(self):self.manager.close();self.patch.stop();self.store.tree.close();self.state_dir.cleanup()
    def request(self,path='/',body=None,headers=None,source='192.168.50.21'):
        ip=self.manager.current[0]
        h={'Origin':'http://'+ip+':1328'}
        if body is not None:h['Content-Type']='application/json'
        h.update(headers or {})
        c=http.client.HTTPConnection(ip,1328,timeout=4,source_address=(source,0))
        try:
            c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,h)
            r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def login(self):
        status,headers,raw=self.request('/api/login',{'secret':self.secret})
        self.assertEqual(status,200)
        return headers,{'Cookie':headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.loads(raw)['csrf']}
    def test_exact_private_ipv4_plain_http(self):
        self.assertEqual(self.manager.server.socket.getsockname(),('192.168.50.20',1328))
        self.assertEqual(self.manager.server.socket.family,socket.AF_INET)
        self.assertIsNone(self.manager.server.tls_context)
        self.assertEqual(self.request()[0],200)
        _,auth=self.login();status,_,raw=self.request('/api/status',headers=auth)
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['network']['transport'],'OWNER LAN HTTP')
    def test_http_cookie_host_origin_csrf_and_logout(self):
        headers,auth=self.login()
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertNotIn('Secure',headers['Set-Cookie'])
        self.assertEqual(self.request('/api/status',headers={'Host':'untrusted.invalid'})[0],403)
        self.assertEqual(self.request('/api/status',headers={'Origin':'https://untrusted.invalid'})[0],403)
        self.assertEqual(self.request('/api/logout',{}, {'Cookie':auth['Cookie']})[0],403)
        self.assertEqual(self.request('/api/logout',{},dict(auth,Origin=''))[0],403)
        self.assertEqual(self.request('/api/logout',{},auth)[0],200)
        self.assertEqual(self.request('/api/status',headers=auth)[0],401)
    def test_outside_subnet_and_anonymous_refused(self):
        self.assertEqual(self.request(source='127.0.0.1')[0],403)
        self.assertEqual(self.request('/api/status')[0],401)
    def test_mask_change_rejects_old_requests_before_poll(self):
        self.assignment=('192.168.50.20','192.168.50.0/25')
        self.assertEqual(self.request()[0],503)
        self.assertTrue(self.manager.poll());self.assertEqual(self.request()[0],200)
    def test_dhcp_rebind_disappearance_primary_https_survives(self):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(self.cert,self.key)
        primary=ui.make_server(ui.SampleProvider(),self.secret,0,tls_context=context)
        worker=threading.Thread(target=primary.serve_forever,daemon=True);worker.start()
        def primary_login():
            client=ssl.create_default_context(cafile=str(self.cert))
            c=http.client.HTTPSConnection('127.0.0.1',primary.server_port,context=client,timeout=4)
            c.request('POST','/api/login',json.dumps({'secret':self.secret}),
                      {'Origin':'https://127.0.0.1:'+str(primary.server_port),'Content-Type':'application/json'})
            r=c.getresponse();self.assertEqual(r.status,200);self.assertIn('Secure',r.getheader('Set-Cookie'));r.read();c.close()
        try:
            _,auth=self.login();primary_login()
            self.assignment=('192.168.50.22','192.168.50.0/24');self.assertTrue(self.manager.poll())
            self.assertEqual(self.manager.server.socket.getsockname(),('192.168.50.22',1328))
            self.assertEqual(self.request('/api/status',headers=auth)[0],401)
            with self.assertRaises(OSError):socket.create_connection(('192.168.50.20',1328),timeout=1)
            self.assignment=None;self.assertFalse(self.manager.poll());primary_login()
            self.assignment=('192.168.50.20','192.168.50.0/24');self.assertTrue(self.manager.poll());primary_login()
        finally:primary.shutdown();primary.server_close();worker.join(5)
    def test_bind_conflict_retries_without_error(self):
        self.manager.close()
        with mock.patch.object(ui,'make_server',side_effect=OSError):self.assertFalse(self.manager.poll())
        self.manager.retry_after=0;self.assertTrue(self.manager.poll())
    def test_primary_validation_not_weakened(self):
        with self.assertRaises(ValueError):ui.make_server(ui.SampleProvider(),self.secret,1328,bind='192.168.50.20',interface='wlp2s0')
        for ip in ('0.0.0.0','::','127.0.0.1'):
            with self.assertRaises(ValueError):ui.make_server(ui.SampleProvider(),self.secret,1328,bind=ip,interface='wlp2s0',owner_lan_http=True,assignment=self.assignment)
    def test_rate_limit_expiry_maintained(self):
        _,auth=self.login()
        for session in self.manager.server.owner_sessions.values():session['created']-=3601
        self.assertEqual(self.request('/api/status',headers=auth)[0],401)
        for _ in range(6):self.assertEqual(self.request('/api/login',{'secret':'incorrect'})[0],401)
        self.assertEqual(self.request('/api/login',{'secret':self.secret})[0],429)

    def test_optional_login_off_opens_anonymous_session_with_csrf(self):
        self.store.save('settings.json',dict(ui.DEFAULT_SETTINGS,wlan_login_required=False))
        status,_,body=self.request('/api/access-policy')
        self.assertEqual(status,200);self.assertFalse(json.loads(body)['authentication_required'])
        status,headers,body=self.request('/api/login',{})
        self.assertEqual(status,200)
        auth={'Cookie':headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.loads(body)['csrf']}
        self.assertEqual(self.request('/api/status',headers=auth)[0],200)
        self.assertEqual(self.request('/api/settings',dict(ui.DEFAULT_SETTINGS),{'Cookie':auth['Cookie']})[0],403)
        self.assertEqual(self.request('/api/settings',dict(ui.DEFAULT_SETTINGS),auth)[0],200)
    def test_enabling_login_rejects_existing_anonymous_session(self):
        self.store.save('settings.json',dict(ui.DEFAULT_SETTINGS))
        _,headers,body=self.request('/api/login',{})
        auth={'Cookie':headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.loads(body)['csrf']}
        self.assertEqual(self.request('/api/settings',dict(ui.DEFAULT_SETTINGS,wlan_login_required=True),auth)[0],200)
        self.assertEqual(self.request('/api/status',headers=auth)[0],401)
        self.assertEqual(self.request('/api/login',{})[0],401)
        _,owner=self.login()
        old_client={k:v for k,v in ui.DEFAULT_SETTINGS.items() if k!='wlan_login_required'}
        self.assertEqual(self.request('/api/settings',old_client,owner)[0],200)
        self.assertTrue(self.store.settings()['wlan_login_required'])
        self.assertEqual(self.request('/api/settings',dict(ui.DEFAULT_SETTINGS),owner)[0],200)
        self.assertEqual(self.request('/api/login',{})[0],200)
    def test_power_requests_fail_closed_even_without_login_requirement(self):
        self.store.save('settings.json',dict(ui.DEFAULT_SETTINGS))
        _,headers,body=self.request('/api/login',{})
        auth={'Cookie':headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.loads(body)['csrf']}
        for action in ['reboot','shutdown']:
            status,_,raw=self.request('/api/power',{'action':action},auth)
            self.assertEqual(status,409);self.assertFalse(json.loads(raw)['enabled'])
        self.assertEqual(self.request('/api/power',{'action':'shell'},auth)[0],400)
    def test_login_policy_preserves_legacy_settings_for_rollback(self):
        self.store.save('settings.json',dict(ui.DEFAULT_SETTINGS,wlan_login_required=True))
        with open(os.path.join(self.state_dir.name,'settings.json')) as stream:
            self.assertEqual(set(json.load(stream)),set(ui.DEFAULT_SETTINGS)-{'wlan_login_required'})
        self.assertTrue(self.store.settings()['wlan_login_required'])
    def test_invalid_login_policy_fails_closed(self):
        self.store.save('settings.json',dict(ui.DEFAULT_SETTINGS,wlan_login_required='false'))
        status,_,raw=self.request('/api/access-policy')
        self.assertEqual(status,200);self.assertTrue(json.loads(raw)['authentication_required'])
        self.assertEqual(self.request('/api/login',{})[0],401)



class MaintenanceUpgrade(unittest.TestCase):
    # Reuse fixture setup without inheriting/rerunning unrelated test methods.
    setUpClass=classmethod(install_fixtures.InstallTests.setUpClass.__func__)
    tearDownClass=classmethod(install_fixtures.InstallTests.tearDownClass.__func__)
    setUp=install_fixtures.InstallTests.setUp
    tearDown=install_fixtures.InstallTests.tearDown
    install=install_fixtures.InstallTests.install
    plan=install_fixtures.InstallTests.plan
    def prepare(self):
        self.install()
        package=self.path/'maintenance.gz'
        pkg.build(str(self.source),'0.5.2-review','maintenance',str(self.key),str(self.pub),str(package))
        policy={'interface':'wlp2s0','http_enabled':True,'ssh_enabled':True}
        plan=ctl.maintenance_plan(self.target,str(package),policy)
        return package,plan
    def test_transaction_preserves_identity_primary_and_rolls_back(self):
        package,plan=self.prepare()
        paths=['config/service.json','ssh/authorized_keys']
        before={n:self.target.data.get(ctl.PREFIX+'/'+n) for n in paths}
        hook=self.target.slot.get(ctl.HOOK)
        ctl.apply_maintenance(self.target,plan,ctl.fingerprint(plan),plan['target']['device_id'],str(package))
        self.assertTrue(ctl.verify_install(self.target)['verified'])
        self.assertEqual(self.target.read_json('current.json')['version'],'0.5.2-review')
        for n in paths:self.assertEqual(self.target.data.get(ctl.PREFIX+'/'+n),before[n])
        self.assertEqual((self.slot/'etc/shadow').read_bytes(),self.original_shadow)
        ctl.rollback(self.target,plan['target']['device_id'],ctl.fingerprint(plan))
        self.assertTrue(ctl.verify_install(self.target)['verified'])
        self.assertEqual(self.target.slot.get(ctl.HOOK),hook)
        self.assertIsNone(self.target.read_json('config/owner-lan.json'))
    def test_interruption_every_write_rolls_back(self):
        package,plan=self.prepare()
        count=len(pkg.verify(str(package),str(self.pub),self.pin)['blobs'])+3
        for index in range(1,count+1):
            with self.subTest(write=index):
                with self.assertRaises(RuntimeError):ctl.apply_maintenance(self.target,plan,ctl.fingerprint(plan),plan['target']['device_id'],str(package),index)
                ctl.rollback(self.target,plan['target']['device_id'],ctl.fingerprint(plan))
                self.assertTrue(ctl.verify_install(self.target)['verified'])
    def test_stale_plan_and_wrong_device_refused(self):
        package,plan=self.prepare()
        with self.assertRaises(ValueError):ctl.apply_maintenance(self.target,plan,ctl.fingerprint(plan),'wrong',str(package))
        (self.slot/ctl.HOOK).write_text('changed')
        with self.assertRaises(ValueError):ctl.apply_maintenance(self.target,plan,ctl.fingerprint(plan),plan['target']['device_id'],str(package))
    def test_panel_kind_cannot_modify_bootstrap(self):
        self.install()
        with self.assertRaises(ValueError):ctl.maintenance_plan(self.target,str(self.update),{'interface':'wlp2s0','http_enabled':True,'ssh_enabled':True})
    def test_policy_rejects_shared_primary_and_extra_fields(self):
        package,plan=self.prepare()
        for policy in [dict(plan['lan_config'],interface='eth0'),dict(plan['lan_config'],port=9999),dict(plan['lan_config'],ssh_enabled=1)]:
            with self.assertRaises(ValueError):ctl.maintenance_plan(self.target,str(package),policy)
    def test_secondary_firewall_has_exact_ingress_destination_ports(self):
        c={'interface':'wlp2s0','http_enabled':True,'ssh_enabled':True}
        with mock.patch.object(bootstrap.subprocess,'run') as run:bootstrap.lan_firewall(c,('192.168.50.20','192.168.50.0/24'))
        commands=[x.args[0] for x in run.call_args_list]
        accept=[c for c in commands if c[-1]=='ACCEPT']
        self.assertEqual({c[c.index('--dport')+1] for c in accept},{'1328','2222'})
        for c in accept:
            self.assertIn('192.168.50.20/32',c);self.assertIn('192.168.50.0/24',c);self.assertIn('wlp2s0',c)
        self.assertTrue(all(c[3:5] in (['-F','OWNER_LAN'],['-A','OWNER_LAN']) for c in commands))
        self.assertFalse(any(c[-1]=='ACCEPT' for c in bootstrap.firewall_commands({'interface':'eth0','client_network':'192.168.60.1/32'},True)))
    def test_secondary_missing_never_starts_or_stops_primary_ssh(self):
        secondary=bootstrap.SecondaryLAN()
        with mock.patch.object(bootstrap,'interface_assignment',return_value=None),mock.patch.object(bootstrap,'lan_firewall'),mock.patch.object(bootstrap.subprocess,'Popen') as spawn:
            self.assertIsNone(secondary.poll({'interface':'wlp2s0','http_enabled':True,'ssh_enabled':True})['address'])
            spawn.assert_not_called()


class IndependentLaunch(unittest.TestCase):
    def test_no_ethernet_launcher_drops_privileges_without_primary_socket(self):
        import socket_launcher as launch
        c={'panel_enabled':True,'interface':'eth0','uid':65000,'gid':65000,'client_network':'192.168.60.1/32'}
        secondary={'interface':'wlp2s0','http_enabled':True,'ssh_enabled':True}
        import stat
        def st(path):
            directory=path.endswith('/state') or path.endswith('/panel-identity')
            return type('S',(),{'st_mode':(stat.S_IFDIR if directory else stat.S_IFREG)|0o700,'st_uid':65000,'st_gid':65000})()
        with mock.patch.multiple(launch,normal_context=mock.Mock(),configuration=mock.Mock(return_value=c),
             lan_configuration=mock.Mock(return_value=secondary),address=mock.Mock(return_value=None),
             release=mock.Mock(return_value=('/signed/release','0.5.2-review')),drop_identity=mock.Mock(),bind_and_drop=mock.Mock()), \
             mock.patch.object(launch.os,'lstat',side_effect=st),mock.patch.object(launch.os,'execve') as exe:
            launch.launch()
            launch.drop_identity.assert_called_once_with(65000,65000)
            launch.bind_and_drop.assert_not_called()
            args=exe.call_args.args[1]
            self.assertIn('--owner-lan-only',args);self.assertIn('wlp2s0',args)
            self.assertNotIn('--listen-fd',args);self.assertNotIn('--tls-cert',args)
    def test_standalone_main_never_creates_loopback_or_primary_socket(self):
        import sys
        secondary=mock.Mock()
        with mock.patch.object(sys,'argv',['server.py','--owner-lan-only','--owner-lan-http-interface','wlp2s0',
                                          '--state','/owner-state','--secret-file','/owner-secret']), \
             mock.patch.object(ui.os,'getuid',return_value=65000),mock.patch.object(ui,'OwnerStore'), \
             mock.patch.object(ui,'read_secret',return_value='synthetic-token-for-standalone-panel'), \
             mock.patch.object(ui,'SecondaryHTTP',return_value=secondary),mock.patch.object(ui,'make_server') as primary, \
             mock.patch.object(ui.time,'sleep',side_effect=KeyboardInterrupt):
            ui.main()
            secondary.poll.assert_called_once();secondary.close.assert_called_once();primary.assert_not_called()
