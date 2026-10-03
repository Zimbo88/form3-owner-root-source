"""Authored disposable filesystem tests; no hardware, vendor code or live mounts."""
import ast,base64,fcntl,gzip,hashlib,importlib.util,io,json,os,shutil,socket,stat,subprocess,sys,tarfile,tempfile,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'owner-maintenance'))
import ownerctl as ctl
import package_format as pkg
import bootstrap

class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved_umask=os.umask(0o022)
        cls.tmp=tempfile.TemporaryDirectory(prefix='owner-SYNTHETIC-installer-');cls.base=Path(cls.tmp.name)
        cls.key=cls.base/'signing.pem';cls.pub=cls.base/'public.pem'
        subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(cls.key)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(cls.key),'-pubout','-out',str(cls.pub)],check=True,capture_output=True)
        cls.pin=pkg.digest(cls.pub.read_bytes());cls.owner=cls.base/'owner.pub'
        cls.owner.write_bytes(b'ssh-ed25519 '+base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+b'F'*32)+b' SYNTHETIC-NOT-DEPLOYMENT\n')
        cls.source=cls.base/'source'
        for n in pkg.PATHS:
            a,b=n.split('/',1);src=ROOT/('owner-ui' if a=='panel' and b!='lan_ipv4.py' else 'owner-maintenance')/b
            dst=cls.source/n;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        cls.package=cls.base/'install.tar.gz';pkg.build(str(cls.source),'0.4.0-review','install',str(cls.key),str(cls.pub),str(cls.package))
        cls.update=cls.base/'update.tar.gz';pkg.build(str(cls.source),'0.4.1-test','panel',str(cls.key),str(cls.pub),str(cls.update))
        cls.cert=cls.base/'tls-cert.pem';cls.tls=cls.base/'tls-key.pem';cls.secret=cls.base/'secret'
        subprocess.run(['openssl','req','-config','/dev/null','-x509','-newkey','rsa:2048','-sha256','-nodes','-days','1','-subj','/CN=SYNTHETIC',
                        '-addext','subjectAltName=IP:10.11.12.13','-keyout',str(cls.tls),'-out',str(cls.cert)],check=True,capture_output=True)
        cls.secret.write_text('SYNTHETIC_'+('X'*48))
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup();os.umask(cls.saved_umask)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=self.base,prefix='disposable-');self.path=Path(self.temp.name)
        self.slot=self.path/'p6';self.data=self.path/'p7';self.slot.mkdir();self.data.mkdir()
        marker=pkg.canonical({'fixture':True,'selected_slot':6,'test_id':self.path.name})
        for root in (self.slot,self.data):(root/'.owner-fixture.json').write_bytes(marker)
        (self.slot/'etc/formlabs').mkdir(parents=True)
        (self.slot/'etc/formlabs/version.json').write_text('{"build":{"name":"2.5.6-2773"}}')
        (self.slot/'etc/passwd').write_text('root:x:0:0:root:/home/root:/bin/sh\n')
        (self.slot/'etc/group').write_text('root:x:0:\n')
        (self.slot/'etc/shadow').write_text('root:*:19000:0:99999:7:::\n')
        self.original_shadow=(self.slot/'etc/shadow').read_bytes()
        self.target=ctl.Target(str(self.slot),str(self.data),'fixture')
        self.config={'interface':'eth0','client_network':'10.11.12.0/24','panel_enabled':False}
    def tearDown(self):self.target.close();self.temp.cleanup()
    def plan(self):return ctl.plan(self.target,str(self.package),str(self.pub),self.pin,str(self.owner),self.config)
    def install(self,fault=None):
        p=self.plan();r=ctl.apply_install(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.package),str(self.pub),str(self.owner),fault)
        return p,r
    def test_legacy_package_verification_survives_extension(self):
        legacy=self.path/'legacy.gz'
        with mock.patch.object(pkg,'PATHS',pkg.LEGACY_PATHS):
            pkg.build(str(self.source),'0.5.12-review','install',str(self.key),str(self.pub),str(legacy))
        self.assertEqual(set(pkg.verify(str(legacy),str(self.pub),self.pin)['manifest']['files']),pkg.LEGACY_PATHS)
    def test_partial_extension_refused_even_when_signed(self):
        partial=self.path/'partial.gz'
        with mock.patch.object(pkg,'PATHS',pkg.LEGACY_PATHS|{'panel/reset_client.py'}):
            with self.assertRaises(ValueError):pkg.build(str(self.source),'0.5.13-review','install',str(self.key),str(self.pub),str(partial))
        with self.assertRaises(ValueError):pkg.verify(str(partial),str(self.pub),self.pin)
    def test_plan_does_not_write(self):
        before=list(self.data.rglob('*'));p=self.plan();self.assertEqual(before,list(self.data.rglob('*')));self.assertEqual(p['target']['selected_slot'],6)
    def test_install_verify_uninstall_restores_account(self):
        p,r=self.install();self.assertGreater(r['installed_files'],10);self.assertTrue(ctl.verify_install(self.target)['verified'])
        self.assertEqual((self.slot/'etc/shadow').read_bytes(),self.original_shadow)
        ctl.rollback(self.target,p['target']['device_id'],ctl.fingerprint(p))
        self.assertEqual((self.slot/'etc/passwd').read_text(),'root:x:0:0:root:/home/root:/bin/sh\n')
        self.assertFalse((self.slot/ctl.HOOK).exists());self.assertEqual((self.slot/'etc/shadow').read_bytes(),self.original_shadow)
    def test_rescue_private_umask_does_not_break_modes(self):
        previous=os.umask(0o077)
        try:
            self.install();self.assertTrue(ctl.verify_install(self.target)['verified'])
            self.assertEqual(stat.S_IMODE((self.data/ctl.PREFIX/'bootstrap').stat().st_mode),0o755)
            self.assertEqual(stat.S_IMODE((self.slot/ctl.HOOK).stat().st_mode),0o755)
        finally:os.umask(previous)
    def test_sysfs_page_metadata_with_short_attribute_content(self):
        # Linux sysfs can report PAGE_SIZE although a read returns a few bytes.
        p=self.path/'kernel-attribute';p.write_bytes(b'30621696\n')
        st=type('SysfsStat',(),{'st_size':4096,'st_mode':stat.S_IFREG|0o444})()
        with mock.patch.object(pkg.os,'fstat',return_value=st):
            self.assertEqual(pkg.read_regular(str(p),65536),b'30621696\n')
            with self.assertRaises(ValueError):pkg.read_regular(str(p),1024)
    def test_every_install_interruption_rolls_back(self):
        p=self.plan();info=p['target'];count=len(pkg.PATHS)+11
        for stop in range(1,count+1):
            with self.subTest(after=stop):
                with self.assertRaises(RuntimeError):ctl.apply_install(self.target,p,ctl.fingerprint(p),info['device_id'],str(self.package),str(self.pub),str(self.owner),stop)
                ctl.rollback(self.target,info['device_id'],ctl.fingerprint(p))
                self.assertFalse((self.slot/ctl.HOOK).exists());self.assertEqual(self.plan(),p)
    def test_stale_plan_rejected(self):
        p=self.plan();(self.slot/'etc/passwd').write_text('root:x:0:0:changed:/home/root:/bin/sh\n')
        with self.assertRaises(ValueError):ctl.apply_install(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.package),str(self.pub),str(self.owner))
        self.assertFalse((self.data/ctl.PREFIX).exists())
    def test_wrong_device_rejected(self):
        p=self.plan()
        with self.assertRaises(ValueError):ctl.apply_install(self.target,p,ctl.fingerprint(p),'0'*64,str(self.package),str(self.pub),str(self.owner))
    def test_repeat_install_refused(self):
        self.install()
        with self.assertRaises(ValueError):self.plan()
    def test_disk_full_preflight_no_writes(self):
        p=self.plan()
        with mock.patch.object(ctl.os,'statvfs',return_value=type('Full',(),{'f_bavail':0,'f_frsize':4096})()):
            with self.assertRaises(ValueError):ctl.apply_install(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.package),str(self.pub),str(self.owner))
        self.assertFalse((self.data/ctl.PREFIX).exists())
    def test_unmarked_fixture_refused(self):
        (self.data/'.owner-fixture.json').unlink()
        with self.assertRaises(ValueError):self.plan()
    def test_wrong_version_refused(self):
        (self.slot/'etc/formlabs/version.json').write_text('{"build":{"name":"unknown"}}')
        with self.assertRaises(ValueError):self.plan()
    def test_symlink_ancestor_refused(self):
        (self.slot/'etc/init.d').symlink_to(self.data,target_is_directory=True)
        with self.assertRaises(OSError):self.plan()
    def test_marker_cannot_authorize_normal_host(self):
        with self.assertRaises(ValueError):ctl.Target(str(self.slot),str(self.data),'normal')
        with self.assertRaises(ValueError):bootstrap.normal_context()
    def test_lock_prevents_transaction(self):
        p=self.plan();directory=self.data/ctl.PREFIX;directory.mkdir()
        with open(directory/'.transaction-lock','w') as f:
            os.fchmod(f.fileno(),0o600)
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):ctl.apply_install(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.package),str(self.pub),str(self.owner))
    def test_changed_installed_file_blocks_rollback(self):
        p,_=self.install();(self.slot/ctl.HOOK).write_text('unreviewed')
        self.assertFalse(ctl.verify_install(self.target)['verified'])
        with self.assertRaises(ValueError):ctl.rollback(self.target,p['target']['device_id'],ctl.fingerprint(p))
    def test_update_and_rollback_preserve_ssh(self):
        original,_=self.install();key=self.target.data.raw(ctl.PREFIX+'/ssh/authorized_keys');hook=self.target.slot.raw(ctl.HOOK)
        p=ctl.update_plan(self.target,str(self.update));ctl.apply_update(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.update))
        self.assertTrue(ctl.verify_install(self.target)['verified']);self.assertEqual(self.target.read_json('current.json')['version'],'0.4.1-test')
        self.assertEqual(key,self.target.data.raw(ctl.PREFIX+'/ssh/authorized_keys'));self.assertEqual(hook,self.target.slot.raw(ctl.HOOK))
        ctl.rollback(self.target,p['target']['device_id'],ctl.fingerprint(p));self.assertTrue(ctl.verify_install(self.target)['verified'])
        self.assertEqual(self.target.read_json('current.json')['version'],'0.4.0-review')
        ctl.rollback(self.target,original['target']['device_id'],ctl.fingerprint(original))
    def test_update_interruption_preserves_ssh(self):
        self.install();key=self.target.data.raw(ctl.PREFIX+'/ssh/authorized_keys');p=ctl.update_plan(self.target,str(self.update))
        with self.assertRaises(RuntimeError):ctl.apply_update(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.update),2)
        ctl.rollback(self.target,p['target']['device_id'],ctl.fingerprint(p));self.assertTrue(ctl.verify_install(self.target)['verified'])
        self.assertEqual(key,self.target.data.raw(ctl.PREFIX+'/ssh/authorized_keys'))
    def test_panel_package_cannot_replace_bootstrap(self):
        self.install()
        with self.assertRaises(ValueError):ctl.update_plan(self.target,str(self.package))
    def test_tls_enrollment_and_rollback(self):
        self.install();p=ctl.enrollment_plan(self.target,str(self.cert),str(self.tls),str(self.secret))
        self.assertNotIn(self.secret.read_text(),json.dumps(p))
        ctl.apply_enrollment(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.cert),str(self.tls),str(self.secret))
        self.assertTrue(ctl.verify_install(self.target)['verified']);self.assertTrue(self.target.read_json('config/service.json')['panel_enabled'])
        state=self.data/ctl.PREFIX/'state';(state/'owner-preferences').write_text('owner data retained')
        ctl.rollback(self.target,p['target']['device_id'],ctl.fingerprint(p))
        self.assertEqual((state/'owner-preferences').read_text(),'owner data retained');self.assertFalse(self.target.read_json('config/service.json')['panel_enabled'])
    def test_tls_renewal_is_transactional(self):
        self.install();p=ctl.enrollment_plan(self.target,str(self.cert),str(self.tls),str(self.secret))
        ctl.apply_enrollment(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.cert),str(self.tls),str(self.secret))
        q=ctl.enrollment_plan(self.target,str(self.cert),str(self.tls),str(self.secret),True)
        ctl.apply_enrollment(self.target,q,ctl.fingerprint(q),q['target']['device_id'],str(self.cert),str(self.tls),str(self.secret))
        self.assertTrue(ctl.verify_install(self.target)['verified'])
        self.assertEqual(self.target.read_json('panel-reload.json')['enrollment_plan'],ctl.fingerprint(q))
        ctl.rollback(self.target,q['target']['device_id'],ctl.fingerprint(q));self.assertTrue(ctl.verify_install(self.target)['verified'])
        self.assertEqual(self.target.read_json('panel-reload.json')['enrollment_plan'],ctl.fingerprint(p))
    def test_uninstall_reverses_multiple_transactions(self):
        self.install();q=ctl.update_plan(self.target,str(self.update));ctl.apply_update(self.target,q,ctl.fingerprint(q),q['target']['device_id'],str(self.update))
        result=ctl.uninstall(self.target,q['target']['device_id'],ctl.fingerprint(q))
        self.assertEqual(result['transactions_reversed'],2);self.assertFalse((self.slot/ctl.HOOK).exists())
        self.assertIsNone(self.target.read_json('installed.json'))
    def test_unsafe_network_configuration(self):
        for network in ('0.0.0.0/0','8.8.8.0/24','10.0.0.0/8','::/0'):
            self.config['client_network']=network
            with self.assertRaises(ValueError):self.plan()
    def test_vendor_authorization_not_accepted_as_owner_key(self):
        for raw in (b'cert-authority ssh-ed25519 AAAA',b'ssh-ed25519-cert-v01@openssh.com AAAA',b'command="id" ssh-ed25519 AAAA',b'ssh-ed25519 !!!!'):
            with self.assertRaises((ValueError,UnicodeError)):ctl.validate_owner_key(raw)
    def test_package_signature_and_pin(self):
        with self.assertRaises(ValueError):pkg.verify(str(self.package),str(self.pub),'0'*64)
        r=pkg.verify(str(self.package),str(self.pub),self.pin);self.assertEqual(r['manifest']['version'],'0.4.0-review')
    def rewrite(self,transform):
        with tarfile.open(self.package,'r:gz') as t:members=[(m,t.extractfile(m).read()) for m in t]
        mem=io.BytesIO()
        with tarfile.open(fileobj=mem,mode='w') as t:
            for m,b in transform(members):t.addfile(m,io.BytesIO(b) if m.isfile() else None)
        p=self.path/'malformed.tar.gz';p.write_bytes(gzip.compress(mem.getvalue(),mtime=0));return str(p)
    def test_tampered_content_rejected(self):
        def change(rows):
            for m,b in rows:
                if m.name=='panel/server.py':b=b'X'+b[1:]
                yield m,b
        with self.assertRaises(ValueError):pkg.verify(self.rewrite(change),str(self.pub),self.pin)
    def test_tampered_signature_rejected(self):
        def change(rows):
            for m,b in rows:
                if m.name=='manifest.sig':b=b'X'+b[1:]
                yield m,b
        with self.assertRaises(ValueError):pkg.verify(self.rewrite(change),str(self.pub),self.pin)
    def test_path_link_device_duplicate_rejected(self):
        for case in ('../escape','/absolute','symlink','device','duplicate'):
            def change(rows):
                if case=='duplicate':return rows+[rows[0]]
                m,b=rows[0]
                if case in ('symlink','device'):
                    m.type=tarfile.SYMTYPE if case=='symlink' else tarfile.CHRTYPE;m.linkname='/etc/shadow';m.size=0;b=b''
                else:m.name=case
                return [(m,b)]+rows[1:]
            with self.subTest(case=case),self.assertRaises(ValueError):pkg.verify(self.rewrite(change),str(self.pub),self.pin)
    def test_truncated_and_expansion_limits(self):
        for raw in (b'\x1f\x8b',self.package.read_bytes()[:100],gzip.compress(b'X'*(pkg.LIMIT+1))):
            p=self.path/'bad.gz';p.write_bytes(raw)
            with self.assertRaises((ValueError,EOFError,OSError,tarfile.TarError)):pkg.verify(str(p),str(self.pub),self.pin)
    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):pkg.unique_json(b'{"x":1,"x":2}')
    def test_package_reproducible(self):
        p=self.path/'reproduced.gz';pkg.build(str(self.source),'0.4.0-review','install',str(self.key),str(self.pub),str(p))
        self.assertEqual(p.read_bytes(),self.package.read_bytes())
    def test_package_never_overwrites(self):
        with self.assertRaises(ValueError):pkg.build(str(self.source),'0.4.0-review','install',str(self.key),str(self.pub),str(self.package))
    def test_runtime_syntax_python35(self):
        for p in (ROOT/'owner-maintenance').glob('*.py'):ast.parse(p.read_text(),feature_version=(3,5))
    def test_firewall_plan_contains_only_owner_ports(self):
        c={'interface':'eth0','client_network':'10.11.12.0/24'}
        ipv6=bootstrap.firewall_commands(c,True)
        self.assertFalse(any('ACCEPT' in x for x in ipv6));self.assertTrue(any('DROP' in x for x in ipv6))
        self.assertTrue(all(x[:3] in (['/usr/sbin/iptables','-w','3'],['/usr/sbin/ip6tables','-w','3']) for x in bootstrap.firewall_commands(c)+ipv6))
    def test_firewall_commands_with_mocked_execution(self):
        c={'interface':'eth0','client_network':'10.11.12.0/24'}
        def result(cmd,**kw):
            return type('Result',(),{'returncode':1 if '-C' in cmd or '-S' in cmd else 0})()
        with mock.patch.object(bootstrap.subprocess,'run',side_effect=result) as run:
            bootstrap.firewall(c)
        commands=[call.args[0] for call in run.call_args_list]
        insert=[x for x in commands if '-I' in x]
        self.assertEqual(len(insert),4)
        self.assertTrue(all(x[-2:]==['-j','OWNER_MAINT'] for x in insert))
        self.assertEqual({x[x.index('--dport')+1] for x in insert},{'2222','1328'})
        self.assertFalse(any(x[-1]=='INPUT' and '-F' in x for x in commands))
    def test_bootenv_parser_uses_label_not_fixed_number(self):
        sys.path.insert(0,str(ROOT/'tools'))
        import capture_owner_bootenv as env
        self.assertEqual(env.select('dev: size erasesize name\nmtd7: 00040000 00001000 "uboot environment"\n'),(7,4096))
        for value in ('','mtd2: 00001000 00001000 "uboot environment"','mtd2: 00040000 00001000 "uboot environment"\nmtd3: 00040000 00001000 "uboot environment"'):
            with self.assertRaises(ValueError):env.select(value)
    def test_bootenv_crc_truncation_and_duplicate(self):
        import struct,zlib
        sys.path.insert(0,str(ROOT/'tools'));import capture_owner_bootenv as env
        def make(body):
            data=body+b'\0'*(0x3ffc-len(body));return struct.pack('<I',zlib.crc32(data)&0xffffffff)+data
        good=make(b'fl_bootpart=6\0fl_bootflip=0\0\0');self.assertEqual(env.validate(good)['fl_bootpart'],'6')
        for raw in (good[:-1],b'BAD!'+good[4:],make(b'fl_bootpart=6\0fl_bootpart=5\0\0')):
            with self.assertRaises(ValueError):env.validate(raw)
    def supervisor_fixture(self,pending_on_second=False,panel_crashes=False,loops=3,stop_on_second=False,recover_after=None,invalid_release_until=0):
        signals={};ticks=[0];children=[];statuses=[]
        config={'interface':'eth0','client_network':'10.11.12.0/24','panel_enabled':True}
        class Child:
            def __init__(self,cmd):self.cmd=cmd;self.rc=1 if panel_crashes and 'socket_launcher.py' in cmd[-1] else None;self.stops=0
            def poll(self):return self.rc
            def terminate(self):self.stops+=1;self.rc=0
            def kill(self):self.rc=0
            def wait(self,**_):return self.rc
        def popen(cmd,**_):
            child=Child(cmd)
            if recover_after is not None and len([c for c in children if 'socket_launcher.py' in c.cmd[-1]])>=recover_after:
                child.rc=None
            children.append(child);return child
        def release():
            if ticks[0]/10.0 < invalid_release_until:raise ValueError('SYNTHETIC_UNTRUSTED_DETAIL')
            return '/fixture','0.4.0-review'
        def exists(path):
            if path.endswith('/disabled'):return False
            if path.endswith('/pending.json'):return pending_on_second and ticks[0]>=20
            return True
        def sleep(_):
            ticks[0]+=1
            if ticks[0]>=loops*20:signals[bootstrap.signal.SIGTERM]()
        def atomic(path,raw,**_):
            if path.endswith('/status.json'):statuses.append(json.loads(raw))
        runpath=str(self.path/'supervisor-run');os.mkdir(runpath,0o700)
        original=os.umask(0o077)
        try:
            with mock.patch.multiple(bootstrap,RUN=runpath,normal_context=mock.Mock(),configuration=mock.Mock(return_value=config),
                 address=mock.Mock(return_value='10.11.12.13'),trusted=mock.Mock(return_value=b'SYNTHETIC'),stop_requested=mock.Mock(side_effect=lambda *_:stop_on_second and ticks[0]>=20),
                 firewall=mock.Mock(),release=mock.Mock(side_effect=release),atomic=mock.Mock(side_effect=atomic)), \
                 mock.patch.object(bootstrap.os.path,'exists',side_effect=exists), \
                 mock.patch.object(bootstrap.os,'lstat',return_value=type('Stat',(),{'st_mode':stat.S_IFDIR|0o700,'st_uid':0})()), \
                 mock.patch.object(bootstrap.signal,'signal',side_effect=lambda n,f:signals.update({n:f})), \
                 mock.patch.object(bootstrap.time,'sleep',side_effect=sleep), \
                 mock.patch.object(bootstrap.time,'monotonic',side_effect=lambda:ticks[0]/10.0), \
                 mock.patch.object(bootstrap.subprocess,'Popen',side_effect=popen), \
                 mock.patch.object(bootstrap.subprocess,'run',return_value=type('Result',(),{'returncode':0})()):
                bootstrap.supervise()
        finally:os.umask(original)
        return children,statuses
    def test_pending_panel_update_keeps_ssh(self):
        children,statuses=self.supervisor_fixture(pending_on_second=True)
        self.assertTrue(any(r.get('pending_owner_transaction') and r['ssh_process'] for r in statuses))
        self.assertEqual(len([c for c in children if c.cmd[0]=='/usr/sbin/sshd']),1)
    def test_panel_crashes_have_bounded_retries_without_ssh_loss(self):
        children,statuses=self.supervisor_fixture(panel_crashes=True,loops=14)
        self.assertEqual(len([c for c in children if 'socket_launcher.py' in c.cmd[-1]]),3)
        self.assertTrue(statuses[-1]['ssh_process']);self.assertEqual(statuses[-1]['panel_start_attempts'],3)

    def test_panel_recovers_after_three_failed_starts_without_ssh_restart(self):
        children,statuses=self.supervisor_fixture(panel_crashes=True,recover_after=3,loops=35)
        self.assertEqual(len([c for c in children if 'socket_launcher.py' in c.cmd[-1]]),4)
        self.assertTrue(statuses[-1]['panel_process'])
        self.assertEqual(len([c for c in children if c.cmd[0]=='/usr/sbin/sshd']),1)

    def test_invalid_release_remains_closed_then_revalidates_on_retry(self):
        children,statuses=self.supervisor_fixture(invalid_release_until=30,loops=30)
        self.assertFalse(any(s['panel_process'] for s in statuses[:15]))
        self.assertTrue(statuses[-1]['panel_process'])
        self.assertNotIn('SYNTHETIC_UNTRUSTED_DETAIL',json.dumps(statuses))
        self.assertEqual(len([c for c in children if c.cmd[0]=='/usr/sbin/sshd']),1)

    def test_panel_retry_uses_monotonic_bounded_backoff_and_reset(self):
        r=bootstrap.PanelRetry();now=0
        for expected in (5,10,20,40,80,160,300,300):
            r.begin(now);r.failed(now,'CHILD_EXITED',1)
            self.assertFalse(r.due(now+expected-1));self.assertTrue(r.due(now+expected))
            now+=expected
        r.begin(now);r.running(now+60);r.failed(now+61,'CHILD_EXITED',1)
        self.assertEqual(r.status(now+61)['retry_in_seconds'],5)
        with self.assertRaises(ValueError):r.failed(now,'arbitrary error/secret')
        r.reset();self.assertTrue(r.due(0));self.assertEqual(r.attempts,0)

    def test_apply_uses_one_bound_install_input_snapshot(self):
        package=self.path/'input-package';public=self.path/'input-public';owner=self.path/'input-owner'
        package.write_bytes(self.package.read_bytes());public.write_bytes(self.pub.read_bytes());owner.write_bytes(self.owner.read_bytes())
        p=ctl.plan(self.target,str(package),str(public),self.pin,str(owner),self.config)
        original=ctl.install_inputs
        def changed(*args):
            snapshot=original(*args)
            package.write_bytes(b'changed after snapshot');public.write_bytes(b'changed after snapshot')
            owner.write_bytes(b'changed after snapshot')
            return snapshot
        with mock.patch.object(ctl,'install_inputs',side_effect=changed) as inputs:
            ctl.apply_install(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(package),str(public),str(owner))
        self.assertEqual(inputs.call_count,1)
        self.assertEqual(self.target.data.raw(ctl.PREFIX+'/config/signing-public.pem'),self.pub.read_bytes())
        self.assertEqual(self.target.data.raw(ctl.PREFIX+'/ssh/authorized_keys'),ctl.validate_owner_key(self.owner.read_bytes()))
        self.assertTrue(ctl.verify_install(self.target)['verified'])

    def test_changed_owner_key_before_apply_refused(self):
        owner=self.path/'owner-input';owner.write_bytes(self.owner.read_bytes())
        p=ctl.plan(self.target,str(self.package),str(self.pub),self.pin,str(owner),self.config)
        owner.write_bytes(b'ssh-ed25519 '+base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+b'G'*32))
        with self.assertRaises(ValueError):ctl.apply_install(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.package),str(self.pub),str(owner))
        self.assertFalse((self.data/ctl.PREFIX).exists())

    def test_apply_uses_one_bound_update_snapshot(self):
        self.install();package=self.path/'input-update';package.write_bytes(self.update.read_bytes())
        p=ctl.update_plan(self.target,str(package));original=self.target.package
        def changed(*args):
            result=original(*args);package.write_bytes(b'changed after snapshot');return result
        with mock.patch.object(self.target,'package',side_effect=changed) as verifier:
            ctl.apply_update(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(package))
        self.assertEqual(verifier.call_count,1);self.assertTrue(ctl.verify_install(self.target)['verified'])

    def test_enrollment_uses_one_bound_identity_snapshot(self):
        self.install();secret=self.path/'secret-input';secret.write_bytes(self.secret.read_bytes())
        p=ctl.enrollment_plan(self.target,str(self.cert),str(self.tls),str(secret));original=ctl.panel_identity
        def changed(*args):
            result=original(*args);secret.write_text('SYNTHETIC_CHANGED_'+('Q'*40));return result
        with mock.patch.object(ctl,'panel_identity',side_effect=changed) as loader:
            ctl.apply_enrollment(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.cert),str(self.tls),str(secret))
        self.assertEqual(loader.call_count,1)
        self.assertEqual(self.target.data.raw(ctl.PREFIX+'/panel-identity/access-secret'),self.secret.read_bytes()+b'\n')

    def test_writable_control_ancestor_rejected(self):
        directory=self.data/ctl.PREFIX;directory.mkdir();directory.chmod(0o777)
        with self.assertRaises(ValueError):self.plan()
        self.assertFalse((self.slot/ctl.HOOK).exists())

    def test_control_ancestor_permissions_rechecked_after_plan(self):
        directory=self.data/ctl.PREFIX;directory.mkdir(mode=0o755);p=self.plan();directory.chmod(0o775)
        with self.assertRaises(ValueError):ctl.apply_install(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.package),str(self.pub),str(self.owner))
        self.assertFalse((self.slot/ctl.HOOK).exists())

    def test_wrong_control_owner_rejected(self):
        original=os.fstat
        def foreign(fd):
            st=original(fd)
            if fd==self.target.data.fd:
                values=list(st);values[4]=os.getuid()+1;return os.stat_result(values)
            return st
        with mock.patch.object(ctl.os,'fstat',side_effect=foreign):
            with self.assertRaises(ValueError):self.plan()

    def test_fifo_transaction_lock_rejected_without_blocking(self):
        p=self.plan();directory=self.data/ctl.PREFIX;directory.mkdir();os.mkfifo(str(directory/'.transaction-lock'),0o600)
        with self.assertRaises(ValueError):ctl.apply_install(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.package),str(self.pub),str(self.owner))
        self.assertFalse((self.slot/ctl.HOOK).exists())

    def test_private_transaction_record_permissions_rejected(self):
        self.install();record=self.data/ctl.PREFIX/'installed.json';record.chmod(0o644)
        with self.assertRaises(ValueError):ctl.verify_install(self.target)

    def test_enroll_rollback_reenroll_preserves_recorded_owner_state(self):
        self.install();p=ctl.enrollment_plan(self.target,str(self.cert),str(self.tls),str(self.secret))
        ctl.apply_enrollment(self.target,p,ctl.fingerprint(p),p['target']['device_id'],str(self.cert),str(self.tls),str(self.secret))
        state=self.data/ctl.PREFIX/'state';(state/'owner-preferences').write_text('preserve owner content')
        ctl.rollback(self.target,p['target']['device_id'],ctl.fingerprint(p))
        q=ctl.enrollment_plan(self.target,str(self.cert),str(self.tls),str(self.secret))
        ctl.apply_enrollment(self.target,q,ctl.fingerprint(q),q['target']['device_id'],str(self.cert),str(self.tls),str(self.secret))
        self.assertTrue(ctl.verify_install(self.target)['verified'])
        self.assertEqual((state/'owner-preferences').read_text(),'preserve owner content')

    def test_unrecorded_or_hostile_retained_state_refused(self):
        self.install();state=self.data/ctl.PREFIX/'state';state.mkdir(mode=0o700)
        with self.assertRaises(ValueError):ctl.enrollment_plan(self.target,str(self.cert),str(self.tls),str(self.secret))
        state.chmod(0o777)
        with self.assertRaises(ValueError):ctl.enrollment_plan(self.target,str(self.cert),str(self.tls),str(self.secret))

    def test_rollback_refuses_state_changed_before_lock(self):
        p,_=self.install();original=ctl.transaction_lock
        def changed(target):
            lock=original(target)
            installed=target.read_json('installed.json');installed['plan_hash']='0'*64
            target.write_json('installed.json',installed)
            target.write_json('transactions/'+('0'*64)+'.json',dict(installed,operation='install',previous_install=None))
            return lock
        with mock.patch.object(ctl,'transaction_lock',side_effect=changed):
            with self.assertRaises(ValueError):ctl.rollback(self.target,p['target']['device_id'],ctl.fingerprint(p))
        self.assertTrue((self.slot/ctl.HOOK).exists())

    def test_identity_stop_request_ends_supervisor_after_child_cleanup(self):
        children,statuses=self.supervisor_fixture(stop_on_second=True)
        self.assertEqual(len(children),2)
        self.assertTrue(all(child.stops==1 for child in children))
        self.assertEqual(len(statuses),1)

if __name__=='__main__':unittest.main()
