import importlib.util,json,os,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('native_transaction',Path(__file__).resolve().parents[1]/'tools/native_display_transaction.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class NativeTransaction(unittest.TestCase):
    def setUp(self):
        self.mask=os.umask(0o077)
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'root';self.root.mkdir();(self.root/'.native-fixture').write_bytes(b'authored disposable fixture\n')
        self.stage=self.base/'stage';self.stage.mkdir();self.backup=self.base/'backup';self.pins={}
        for i,(path,(_,_,name,mode)) in enumerate(m.PINS.items()):
            before=('before%d'%i).encode();after=('after%d'%i).encode()
            f=self.root/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(before);f.chmod(mode)
            (self.stage/name).write_bytes(after);self.pins[path]=(m.digest(before),m.digest(after),name,mode)
        self.t=m.Transaction(str(self.root),fixture=True,pins=self.pins)
        self.plan=self.t.plan(str(self.stage));self.pin=m.digest(m.canonical(self.plan))
    def tearDown(self):self.temp.cleanup();os.umask(self.mask)
    def apply(self,**kw):return self.t.apply(self.plan,self.pin,str(self.stage),str(self.backup),**kw)
    def restore(self):return self.t.rollback(self.plan,self.pin,str(self.backup))
    def test_apply_restore_bytes_permissions(self):
        self.assertEqual(self.apply()['phase'],'APPLIED');self.assertEqual(self.restore()['phase'],'ROLLED_BACK')
        for e in self.plan['entries']:self.assertEqual(m.read(self.t.path(e['path']))[1],e['before'])
    def test_interruption_each_target_is_recoverable(self):
        for n in (1,2):
            with self.subTest(n=n):
                self.backup=self.base/('interrupted%d'%n)
                with self.assertRaises(RuntimeError):self.apply(fault_after=n)
                self.restore()
                for e in self.plan['entries']:self.assertEqual(m.read(self.t.path(e['path']))[1],e['before'])
    def test_backup_not_overwritten(self):
        self.apply();self.restore()
        with self.assertRaises(ValueError):self.apply()
    def test_stale_original(self):
        next(self.root.rglob('Palantir.rcc')).write_bytes(b'unrelated')
        with self.assertRaises(ValueError):self.apply()
        self.assertFalse(self.backup.exists())
    def test_candidate_changed(self):
        (self.stage/'clock.rcc').write_bytes(b'unreviewed')
        with self.assertRaises(ValueError):self.apply()
    def test_symlink_candidate(self):
        f=self.stage/'clock.rcc';f.unlink();f.symlink_to(self.root/'.native-fixture')
        with self.assertRaises(OSError):self.apply()
    def test_symlink_parent(self):
        directory=self.root/'usr/share/Formlabs';real=self.root/'safe';directory.rename(real);directory.symlink_to(real)
        with self.assertRaises(ValueError):self.apply()
    def test_hash_and_device_pins(self):
        with self.assertRaises(ValueError):self.t.validate_plan(self.plan,'0'*64)
        self.plan['device_id']='wrong'
        with self.assertRaises(ValueError):self.t.validate_plan(self.plan,m.digest(m.canonical(self.plan)))
    def test_added_target_refused(self):
        self.plan['entries'].append(dict(self.plan['entries'][0],path='etc/shadow'))
        with self.assertRaises(ValueError):self.t.validate_plan(self.plan,m.digest(m.canonical(self.plan)))
    def test_changed_backup_refused(self):
        self.apply();(self.backup/'before-0').write_bytes(b'broken')
        with self.assertRaises(ValueError):self.restore()
    def test_concurrent_target_refused_before_any_restore(self):
        self.apply();e=self.plan['entries'][-1];Path(self.t.path(e['path'])).write_bytes(b'unrelated')
        with self.assertRaises(ValueError):self.restore()
        first=self.plan['entries'][0];self.assertEqual(m.read(self.t.path(first['path']))[1]['sha256'],first['after_sha256'])
    def test_truncated_plan_refused(self):
        (self.backup).mkdir();(self.backup/'plan.json').write_bytes(b'{')
        with self.assertRaises(ValueError):self.restore()
    def test_production_cannot_override_pins(self):
        with self.assertRaises(ValueError):m.Transaction('/',pins=self.pins)
    def test_fixture_marker_required(self):
        (self.root/'.native-fixture').write_bytes(b'wrong')
        with self.assertRaises(ValueError):m.Transaction(str(self.root),fixture=True,pins=self.pins)
    def test_input_budget(self):
        with self.assertRaises(ValueError):m.read(str(self.stage/'clock.rcc'),2)
    def test_single_splash_apply_interruption_rollback_preserves_clock(self):
        clock=(self.root/m.RCC).read_bytes()
        self.t=m.Transaction(str(self.root),fixture=True,pins={m.SPLASH:self.pins[m.SPLASH]})
        self.plan=self.t.plan(str(self.stage));self.pin=m.digest(m.canonical(self.plan))
        self.assertEqual(self.plan['operation'],'native-display-splash')
        for interrupted in (False,True):
            self.backup=self.base/('single-'+str(interrupted))
            if interrupted:
                with self.assertRaises(RuntimeError):self.apply(fault_after=1)
            else:self.assertEqual(self.apply()['phase'],'APPLIED')
            self.assertEqual((self.root/m.RCC).read_bytes(),clock)
            self.restore()
            self.assertEqual(m.read(self.t.path(m.SPLASH))[1],self.plan['entries'][0]['before'])
            self.assertEqual((self.root/m.RCC).read_bytes(),clock)

    def test_factory_clock_profile_changes_only_pinned_resource(self):
        p=m.PROFILES['local-clock-factory']
        self.assertEqual(p,{m.RCC:(m.PINS[m.RCC][0],m.LOCAL_SHA,'clock.rcc',0o644)})
    def test_printing_clock_profile_is_clock_only_and_pinned(self):
        self.assertEqual(m.PROFILES['printing-clock'],{m.RCC:(m.LOCAL_SHA,m.PRINTING_CLOCK_SHA,'clock.rcc',0o644)})
        self.assertEqual(len(m.PRINTING_CLOCK_SHA),64)

    def test_ready_clock_profiles_are_separate_and_clock_only(self):
        self.assertEqual(m.PROFILES['ready-clock'],{m.RCC:(m.LOCAL_SHA,m.READY_CLOCK_SHA,'clock.rcc',0o644)})
        self.assertEqual(m.PROFILES['ready-clock-factory'],{m.RCC:(m.PINS[m.RCC][0],m.READY_CLOCK_SHA,'clock.rcc',0o644)})
        self.assertNotEqual(m.READY_CLOCK_SHA,m.LOCAL_SHA)

    def test_single_clock_interruption_and_rollback_preserve_splash(self):
        splash=(self.root/m.SPLASH).read_bytes()
        self.t=m.Transaction(str(self.root),fixture=True,pins={m.RCC:self.pins[m.RCC]})
        self.plan=self.t.plan(str(self.stage));self.pin=m.digest(m.canonical(self.plan))
        self.assertEqual(self.plan['operation'],'native-display-clock')
        with self.assertRaises(RuntimeError):self.apply(fault_after=1)
        self.assertEqual((self.root/m.SPLASH).read_bytes(),splash)
        self.restore()
        self.assertEqual(m.read(self.t.path(m.RCC))[1],self.plan['entries'][0]['before'])
        self.assertEqual((self.root/m.SPLASH).read_bytes(),splash)

if __name__=='__main__':unittest.main()
