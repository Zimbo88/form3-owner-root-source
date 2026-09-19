#!/usr/bin/env python3
"""Bounded owner file transactions. Python 3.5; no flash or disk-image writes.

Default operations are preflight/plan/verify. Applying requires the exact reviewed
plan hash and device fingerprint. Filesystem fixtures are explicit; live use is
restricted to reviewed ARM rescue mounts. No mounting or read-only flag change is
performed implicitly. No vendor script, updater or printing process is executed.
"""
import argparse,base64,errno,fcntl,hashlib,json,os,re,shutil,stat,struct,sys,time,zlib
from package_format import canonical,digest,read_regular,unique_json,verify as verify_package

PREFIX='owner-maintenance'
HOOK='etc/init.d/owner-maintenance'
LINK='etc/rc5.d/S98owner-maintenance'
CLI='usr/local/sbin/ownerctl'
ACCOUNT='owner-maint'

class Tree(object):
    def __init__(self,path):
        self.path=os.path.abspath(path);self.private_directories={};fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
        try:
            for part in self.path.strip('/').split('/'):
                if not part:continue
                nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
            self.check_directory(fd,'')
            self.fd=fd
        except BaseException:os.close(fd);raise
    def check_directory(self,fd,name):
        st=os.fstat(fd)
        expected=self.private_directories.get(name)
        if expected is not None:
            if (st.st_uid,st.st_gid)!=expected or stat.S_IMODE(st.st_mode)!=0o700:
                raise ValueError('Untrusted private owner directory')
        elif st.st_uid!=os.getuid() or st.st_mode&0o022:
            raise ValueError('Untrusted root-controlled directory')
    def close(self):os.close(self.fd)
    def parent(self,name,create=False):
        parts=name.split('/')
        if any(p in ('','.','..') for p in parts) or '\\' in name:raise ValueError('Unsafe relative path')
        self.check_directory(self.fd,'')
        fd=os.dup(self.fd);walked=[]
        try:
            for p in parts[:-1]:
                created=False
                if create:
                    try:os.mkdir(p,0o755,dir_fd=fd);os.fsync(fd);created=True
                    except FileExistsError:pass
                nxt=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
                if created:os.fchmod(fd,0o755);os.fsync(fd)
                walked.append(p);self.check_directory(fd,'/'.join(walked))
            return fd,parts[-1]
        except BaseException:os.close(fd);raise
    def get(self,name):
        try:fd,leaf=self.parent(name)
        except FileNotFoundError:return None
        try:
            try:st=os.stat(leaf,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError:return None
            private=self.private_directories.get(name) or self.private_directories.get(name.rsplit('/',1)[0])
            if private is not None:
                if (st.st_uid,st.st_gid)!=private or st.st_mode&0o077:raise ValueError('Untrusted private owner object')
            elif st.st_uid!=os.getuid() or (not stat.S_ISLNK(st.st_mode) and st.st_mode&0o022):raise ValueError('Untrusted root-controlled object')
            if stat.S_ISLNK(st.st_mode):return {'type':'symlink','data':os.readlink(leaf,dir_fd=fd),'mode':0o777,'uid':st.st_uid,'gid':st.st_gid}
            if stat.S_ISDIR(st.st_mode) and name in (PREFIX+'/state',PREFIX+'/panel-identity',PREFIX+'/staging'):
                return {'type':'directory','data':'','mode':stat.S_IMODE(st.st_mode),'uid':st.st_uid,'gid':st.st_gid}
            if not stat.S_ISREG(st.st_mode) or st.st_size>4*1024*1024:raise ValueError('Unexpected target object')
            f=os.open(leaf,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            with os.fdopen(f,'rb') as h:data=h.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise ValueError('Target input limit')
            return {'type':'file','data':base64.b64encode(data).decode('ascii'),'mode':stat.S_IMODE(st.st_mode),'uid':st.st_uid,'gid':st.st_gid}
        finally:os.close(fd)
    def raw(self,name):
        obj=self.get(name)
        if obj is None:return None
        if obj['type']!='file':raise ValueError('Regular target file required')
        return base64.b64decode(obj['data'])
    def put(self,name,obj):
        try:fd,leaf=self.parent(name,create=obj is not None)
        except FileNotFoundError:
            if obj is None:return
            raise
        tmp='.owner-new-'+os.urandom(12).hex()
        try:
            if obj is None:
                try:os.unlink(leaf,dir_fd=fd)
                except IsADirectoryError:
                    if name not in (PREFIX+'/state',PREFIX+'/panel-identity',PREFIX+'/staging'):raise
                    try:os.rmdir(leaf,dir_fd=fd)
                    except OSError as e:
                        if name!=PREFIX+'/state' or e.errno!=errno.ENOTEMPTY:raise
                except FileNotFoundError:pass
            else:
                if obj['type']=='directory':
                    if name not in (PREFIX+'/state',PREFIX+'/panel-identity',PREFIX+'/staging'):raise ValueError('Unapproved directory')
                    try:os.mkdir(leaf,obj['mode'],dir_fd=fd)
                    except FileExistsError:raise ValueError('Directory collision')
                    d=os.open(leaf,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    try:
                        os.fchmod(d,obj['mode'])
                        if os.getuid()==0:os.fchown(d,obj['uid'],obj['gid'])
                        os.fsync(d)
                    finally:os.close(d)
                elif obj['type']=='symlink':
                    if name!=LINK or obj['data']!='../init.d/owner-maintenance':raise ValueError('Unapproved link')
                    os.symlink(obj['data'],tmp,dir_fd=fd)
                elif obj['type']=='file':
                    f=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,obj['mode'],dir_fd=fd)
                    with os.fdopen(f,'wb') as out:
                        out.write(base64.b64decode(obj['data']));out.flush();os.fsync(out.fileno())
                        os.fchmod(out.fileno(),obj['mode'])
                        if os.getuid()==0:os.fchown(out.fileno(),obj['uid'],obj['gid'])
                        os.fsync(out.fileno())
                else:raise ValueError('Unknown target type')
                if obj['type']!='directory':os.replace(tmp,leaf,src_dir_fd=fd,dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:os.unlink(tmp,dir_fd=fd)
            except FileNotFoundError:pass
            os.close(fd)

def obj(raw,mode=0o600,uid=None,gid=None):
    return {'type':'file','data':base64.b64encode(raw).decode('ascii'),'mode':mode,
            'uid':os.getuid() if uid is None else uid,'gid':os.getgid() if gid is None else gid}
def fingerprint(value):return digest(canonical(value))
def decode_mount_path(s):return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m.group(1),8)),s)

class Target(object):
    def __init__(self,slot_root,data_root,context,boot_env=None):
        slot=os.path.abspath(slot_root);data=os.path.abspath(data_root)
        for path in (slot,data):
            if (path in ('/','/etc','/data') and context!='normal') or any(x in path.split('/') for x in ('original','calibration','Cartridges','Tanks')):
                raise ValueError('Target path forbidden')
        if context=='normal' and (slot,data)!=('/','/data'):raise ValueError('Normal context requires exact system/data roots')
        if context!='normal' and (slot==data or os.path.commonpath([slot,data]) in (slot,data)):
            raise ValueError('Slot/data targets must be separate sibling mount roots')
        self.slot=Tree(slot)
        try:self.data=Tree(data)
        except BaseException:self.slot.close();raise
        self.context=context;self.boot_env=boot_env
    def close(self):self.slot.close();self.data.close()
    def preflight(self,writable=False):
        if self.context=='fixture':
            sr=self.slot.raw('.owner-fixture.json');dr=self.data.raw('.owner-fixture.json')
            if not sr or sr!=dr:raise ValueError('Matching explicit disposable fixture markers required')
            marker=unique_json(sr)
            if marker.get('fixture') is not True or marker.get('selected_slot')!=6:raise ValueError('Unsupported fixture')
            device=fingerprint(marker);slot=6;ownership='Fixture UID; not a target ownership demonstration'
        elif self.context in ('rescue','normal'):
            if os.getuid()!=0 or not os.uname().machine.startswith('armv7'):raise ValueError('Live apply requires root on ARMv7 rescue')
            cmdline=read_regular('/proc/cmdline',65536).decode().split()
            if self.context=='rescue' and 'rdinit=/init' not in cmdline:raise ValueError('Expected reviewed Rescue V2 context')
            if self.context=='normal' and ('root=/dev/mmcblk0p6' not in cmdline or 'rdinit=/init' in cmdline):raise ValueError('Expected supported normal p6 context')
            model=read_regular('/proc/device-tree/model',4096).replace(b'\0',b'')
            if b'Formlabs' not in model:raise ValueError('Unexpected platform')
            cid=read_regular('/sys/block/mmcblk0/device/cid',65536).strip()
            capacity=int(read_regular('/sys/block/mmcblk0/size',65536).strip())*512
            if capacity!=15678308352 or not re.match(b'^[0-9a-fA-F]{32}$',cid):raise ValueError('Unexpected eMMC layout/identity class')
            for number,start,length in [(1,1048576,52428800),(2,53477376,104857600),(5,159383552,1048576000),(6,1209008128,1048576000),(7,2258632704,13419675648)]:
                sysbase='/sys/class/block/mmcblk0p%d/'%number
                actual=(int(read_regular(sysbase+'start',65536).strip())*512,int(read_regular(sysbase+'size',65536).strip())*512)
                if actual!=(start,length):raise ValueError('Partition layout differs; no automatic adaptation')
            if self.context=='rescue':
                if not self.boot_env:raise ValueError('Fresh reviewed active environment capture required; do not infer slot from rescue cmdline')
                env=read_regular(self.boot_env,16384)
                if len(env)!=16384 or struct.unpack('<I',env[:4])[0]!=(zlib.crc32(env[4:])&0xffffffff):raise ValueError('Active environment CRC invalid')
                values=dict(x.split(b'=',1) for x in env[4:].split(b'\0\0',1)[0].split(b'\0'))
                if values.get(b'fl_bootpart')!=b'6' or values.get(b'fl_bootflip')!=b'0':raise ValueError('Only reviewed selected p6 with no pending flip is supported')
            slot=6;device=digest(model+b'\0'+cid+b'\0'+str(capacity).encode());ownership='Root-owned target files'
            mounts={decode_mount_path(p[1]):p for p in (line.split() for line in open('/proc/mounts')) if len(p)>3}
            for path,source in [(self.slot.path,'/dev/mmcblk0p6'),(self.data.path,'/dev/mmcblk0p7')]:
                row=mounts.get(path)
                if not row or row[2]!='ext4':raise ValueError('Exact reviewed ext4 mount required')
                allowed={source}
                if self.context=='normal' and path=='/':allowed.add('/dev/root')
                if row[0] not in allowed:raise ValueError('Unexpected mount source')
                device_stat=os.stat(source)
                if not stat.S_ISBLK(device_stat.st_mode) or os.stat(path).st_dev!=device_stat.st_rdev:raise ValueError('Mounted filesystem device number mismatch')
                if writable and (self.context=='rescue' or path==self.data.path) and 'rw' not in row[3].split(','):raise ValueError('Reviewed maintenance mounts must explicitly be writable for apply')
            forbidden={'Sauron','Formule','Palantir','CandyBus','htfu','update-utils','TankCartridgeDa'}
            for name in os.listdir('/proc') if self.context=='rescue' else []:
                if name.isdigit():
                    try:
                        if read_regular('/proc/'+name+'/comm',256).decode().strip() in forbidden:raise ValueError('Vendor printing/update stack present')
                    except (FileNotFoundError,ProcessLookupError):pass
        else:raise ValueError('Unsupported execution context')
        version=unique_json(self.slot.raw('etc/formlabs/version.json') or b'{}').get('build',{}).get('name')
        if version!='2.5.6-2773':raise ValueError('Unsupported firmware; no automatic adaptation')
        c=self.read_json('config/service.json')
        if c is not None:
            if any(type(c.get(k)) is not int or not 64900<=c[k]<=65000 for k in ('uid','gid')):raise ValueError('Invalid enrolled owner identity')
            identity=(os.getuid(),os.getgid()) if self.context=='fixture' else (c['uid'],c['gid'])
            self.data.private_directories={PREFIX+'/'+name:identity for name in ('state','panel-identity')}
        return {'device_id':device,'selected_slot':slot,'firmware':version,'context':self.context,
                'ownership_scope':ownership,'slot_root':self.slot.path,'data_root':self.data.path}
    def read_json(self,path):
        item=self.data.get(PREFIX+'/'+path)
        if item is None:return None
        if item['type']!='file' or (path!='current.json' and path!='panel-reload.json' and item['mode']&0o077):raise ValueError('Private owner record required')
        return unique_json(base64.b64decode(item['data']))
    def write_json(self,path,value):self.data.put(PREFIX+'/'+path,obj(canonical(value)))
    def package(self,path,public_key,signer):
        openssl=None
        if self.context=='rescue':
            openssl=[self.slot.path+'/lib/ld-linux-armhf.so.3','--library-path',self.slot.path+'/lib:'+self.slot.path+'/usr/lib',self.slot.path+'/usr/bin/openssl']
        return verify_package(path,public_key,signer,openssl)

def validate_owner_key(raw):
    parts=raw.decode('ascii').strip().split()
    if len(parts)<2 or parts[0]!='ssh-ed25519':raise ValueError('One plain owner Ed25519 public key required; options/certificates refused')
    blob=base64.b64decode(parts[1],validate=True)
    if len(blob)!=51 or blob[:19]!=b'\0\0\0\x0bssh-ed25519\0\0\0\x20':raise ValueError('Invalid Ed25519 public key encoding')
    return ('ssh-ed25519 '+parts[1]+' owner-enrolled\n').encode('ascii')

def install_inputs(target,package,public_key,signer,owner_key):
    return (target.package(package,public_key,signer),validate_owner_key(read_regular(owner_key,16384)))

def plan(target,package,public_key,signer,owner_key,config,_snapshot=None):
    if target.context=='normal':raise ValueError('Initial selected-slot installation requires reviewed rescue context')
    info=target.preflight();p,key=_snapshot if _snapshot is not None else install_inputs(target,package,public_key,signer,owner_key)
    if p['manifest']['kind']!='install':raise ValueError('Initial install requires bootstrap package')
    config=unique_json(canonical(config))
    # Config is owner-reviewed root state, never UI preferences or executable text.
    if set(config)!={'interface','client_network','panel_enabled'} or config['interface'] not in ('eth0','wlan0') or type(config['panel_enabled']) is not bool:
        raise ValueError('Invalid typed owner network configuration')
    import ipaddress
    network=ipaddress.ip_network(config['client_network'],strict=True)
    if network.version!=4 or not network.is_private or network.prefixlen<16:raise ValueError('Narrow private IPv4 network required')
    if config['panel_enabled']:raise ValueError('Initial panel enable requires separate TLS enrollment; start with false')
    passwd=target.slot.raw('etc/passwd');group=target.slot.raw('etc/group')
    if passwd is None or group is None:raise ValueError('Account files missing')
    used=set();names=[]
    for data in (passwd,group):
        for line in data.decode().splitlines():
            fields=line.split(':');names.append(fields[0])
            if len(fields)>2:used.add(int(fields[2]))
    if ACCOUNT in names:raise ValueError('Owner account collision; use verify/update for existing installation')
    uid=next((n for n in range(65000,64900,-1) if n not in used),None)
    if uid is None:raise ValueError('No free reviewed owner UID/GID')
    for path in (HOOK,LINK,CLI):
        if target.slot.get(path) is not None:raise ValueError('Existing bootstrap path collision')
    if target.read_json('installed.json') is not None:raise ValueError('Installation already exists; no uncontrolled repeat')
    if target.read_json('pending.json') is not None:raise ValueError('Pending transaction requires rollback first')
    baseline={path:fingerprint(target.slot.get(path)) for path in ('etc/passwd','etc/group',HOOK,LINK,CLI)}
    result={'schema':1,'operation':'install','target':info,'baseline':baseline,'package_sha256':p['package_sha256'],
      'manifest_sha256':p['manifest_sha256'],'signer_sha256':signer,'owner_public_key_sha256':digest(key),
      'config':config,'owner_uid':uid,'owner_gid':uid,'version':p['manifest']['version'],
      'writes':['selected p6 account entries and owner bootstrap only','separate p7 /data/owner-maintenance tree'],
      'never_written':['p1','p2','p5','boot0','boot1','QSPI','partition table','vendor shadow','consumable memory']}
    return result

def apply_install(target,reviewed,plan_hash,device_id,package,public_key,owner_key,fault_after=None):
    if fingerprint(reviewed)!=plan_hash or reviewed['target']['device_id']!=device_id:raise ValueError('Explicit reviewed plan/device mismatch')
    snapshot=install_inputs(target,package,public_key,reviewed['signer_sha256'],owner_key)
    now=plan(target,package,public_key,reviewed['signer_sha256'],owner_key,reviewed['config'],snapshot)
    if now!=reviewed:raise ValueError('Stale plan/baseline; review again')
    target.preflight(writable=True)
    v=os.statvfs(target.data.path)
    if v.f_bavail*v.f_frsize<32*1024*1024:raise ValueError('Insufficient free space; no writes applied')
    if fault_after is not None and target.context!='fixture':raise ValueError('Fault injection is fixture-only')
    p,key=snapshot;version=reviewed['version'];ops=[]
    def operation(tree,path,after):
        before=getattr(target,tree).get(path)
        if tree=='slot' and fingerprint(before)!=reviewed['baseline'][path]:raise ValueError('Slot changed after plan validation')
        ops.append({'tree':tree,'path':path,'before':before,'after':after})
    uid=reviewed['owner_uid'];gid=reviewed['owner_gid']
    pw=target.slot.raw('etc/passwd').rstrip(b'\n')+('\n'+ACCOUNT+':x:%d:%d:Owner maintenance:/data/owner-maintenance/state:/bin/false\n'%(uid,gid)).encode()
    gr=target.slot.raw('etc/group').rstrip(b'\n')+('\n'+ACCOUNT+':x:%d:\n'%gid).encode()
    operation('slot','etc/passwd',obj(pw,0o644));operation('slot','etc/group',obj(gr,0o644))
    for name,raw in sorted(p['blobs'].items()):
        if name.startswith('bootstrap/'):
            operation('data',PREFIX+'/'+name,obj(raw,0o644))
        elif name.startswith('panel/') or name in ('manifest.json','manifest.sig'):
            operation('data',PREFIX+'/releases/'+version+'/'+name,obj(raw,0o644))
    operation('data',PREFIX+'/config/signing-public.pem',obj(p['_verified_public_key'],0o644))
    operation('data',PREFIX+'/ssh/authorized_keys',obj(key,0o600))
    config=dict(reviewed['config'],uid=uid,gid=gid,firmware=reviewed['target']['firmware'],slot=6,signer_sha256=reviewed['signer_sha256'])
    operation('data',PREFIX+'/config/service.json',obj(canonical(config),0o600))
    pointer={'version':version,'manifest_sha256':p['manifest_sha256']}
    operation('data',PREFIX+'/current.json',obj(canonical(pointer),0o644))
    hook=p['blobs']['bootstrap/owner-maintenance.init'].replace(b'@BOOTSTRAP_SHA256@',digest(p['blobs']['bootstrap/bootstrap.py']).encode())
    operation('slot',HOOK,obj(hook,0o755))
    operation('slot',LINK,{'type':'symlink','data':'../init.d/owner-maintenance','mode':0o777,'uid':os.getuid(),'gid':os.getgid()})
    cli=b'#!/bin/sh\nexec /usr/bin/python3.5 -E -B -S /data/owner-maintenance/bootstrap/ownerctl.py "$@"\n'
    operation('slot',CLI,obj(cli,0o755))
    # Write-ahead log precedes every affected file. Root-only backups remain local.
    journal={'schema':1,'operation':'install','plan_hash':plan_hash,'device_id':device_id,'version':version,'operations':ops,'phase':'PREPARED'}
    execute_transaction(target,journal,fault_after)
    return {'installed_files':len(ops),'version':version,'started_services':False,'normal_boot_proven':False}

def transaction_lock(target):
    fd,leaf=target.data.parent(PREFIX+'/.transaction-lock',create=True)
    try:lock=os.open(leaf,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=fd)
    finally:os.close(fd)
    try:
        st=os.fstat(lock)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_size>0:
            raise ValueError('Untrusted transaction lock')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return lock
    except BaseException:os.close(lock);raise

def execute_transaction(target,journal,fault_after=None):
    # All code paths use this lock; no busy-wait or stale PID lock.
    lock=transaction_lock(target)
    try:
        if target.read_json('pending.json') is not None:raise ValueError('Concurrent/pending transaction')
        for op in journal['operations']:
            if getattr(target,op['tree']).get(op['path'])!=op['before']:raise ValueError('Concurrent target change')
        journal['previous_install']=target.read_json('installed.json')
        target.write_json('pending.json',journal)
        for i,op in enumerate(journal['operations']):
            getattr(target,op['tree']).put(op['path'],op['after'])
            if fault_after==i+1:raise RuntimeError('Injected fixture interruption; rollback pending transaction')
        for op in journal['operations']:
            if getattr(target,op['tree']).get(op['path'])!=op['after']:raise ValueError('Readback mismatch')
        journal['phase']='COMMITTED'
        target.write_json('transactions/'+journal['plan_hash']+'.json',journal)
        prior=journal['previous_install']
        cumulative={(o['tree'],o['path']):o for o in prior['operations']} if prior else {}
        for op in journal['operations']:
            original=cumulative.get((op['tree'],op['path']),op)
            cumulative[(op['tree'],op['path'])]=dict(op,before=original['before'])
        installed={k:journal[k] for k in ('schema','plan_hash','device_id','version','phase')}
        installed['operations']=[cumulative[k] for k in sorted(cumulative)]
        target.write_json('installed.json',installed)
        target.data.put(PREFIX+'/pending.json',None)
    finally:os.close(lock)

def verify_install(target):
    target.preflight();j=target.read_json('installed.json')
    if not j:raise ValueError('No committed installation')
    if target.read_json('pending.json'):raise ValueError('Interrupted transaction requires review')
    conflicts=[{'tree':op['tree'],'path':op['path']} for op in j['operations'] if getattr(target,op['tree']).get(op['path'])!=op['after']]
    return {'verified':not conflicts,'conflicts':conflicts,'version':j['version'],'hardware_boot_proven':False}

def rollback(target,device_id,plan_hash):
    info=target.preflight(writable=True)
    installed=target.read_json('installed.json')
    j=target.read_json('pending.json') or (target.read_json('transactions/'+installed['plan_hash']+'.json') if installed else None)
    if not j or j['device_id']!=device_id or info['device_id']!=device_id or j['plan_hash']!=plan_hash:raise ValueError('Rollback transaction/device mismatch')
    if target.context=='normal' and any(op['tree']=='slot' for op in j['operations']):
        if j.get('operation')!='maintenance-update' or any(op['tree']=='slot' and (op['path']!=HOOK or op['before'] is None or op['after'] is None) for op in j['operations']):
            raise ValueError('Bootstrap/account removal requires isolated rescue')
    lock=transaction_lock(target)
    try:
        locked_installed=target.read_json('installed.json')
        locked_j=target.read_json('pending.json') or (target.read_json('transactions/'+locked_installed['plan_hash']+'.json') if locked_installed else None)
        if locked_installed!=installed or locked_j!=j:raise ValueError('Rollback state changed before lock')
        for op in j['operations']:
            current=getattr(target,op['tree']).get(op['path'])
            if current!=op['before'] and current!=op['after']:raise ValueError('Concurrent modification; no automatic rollback')
        for op in reversed(j['operations']):getattr(target,op['tree']).put(op['path'],op['before'])
        target.write_json('rollback-receipt.json',{'plan_hash':plan_hash,'restored':True,'owner_runtime_state_preserved':True,'retained_state':target.data.get(PREFIX+'/state')})
        if j.get('previous_install'):target.write_json('installed.json',j['previous_install'])
        else:target.data.put(PREFIX+'/installed.json',None)
        target.data.put(PREFIX+'/pending.json',None)
    finally:os.close(lock)
    return {'rolled_back':True,'vendor_shadow_changed':False,'owner_runtime_state_preserved':True}

def update_plan(target,package,_snapshot=None):
    info=target.preflight()
    if not verify_install(target)['verified']:raise ValueError('Installed baseline changed')
    config=target.read_json('config/service.json');public=target.data.path+'/'+PREFIX+'/config/signing-public.pem'
    p=_snapshot if _snapshot is not None else target.package(package,public,config['signer_sha256'])
    if p['manifest']['kind']!='panel':raise ValueError('Only a panel update may be applied during normal operation')
    version=p['manifest']['version'];prefix=PREFIX+'/releases/'+version
    if target.data.get(prefix+'/manifest.json') is not None:raise ValueError('Release already exists; never replace in place')
    releases=os.path.join(target.data.path,PREFIX,'releases')
    if len(os.listdir(releases))>=8:raise ValueError('Release retention limit; reviewed offline cleanup required')
    return {'schema':1,'operation':'panel-update','target':info,'version':version,
            'package_sha256':p['package_sha256'],'manifest_sha256':p['manifest_sha256'],
            'installed_sha256':fingerprint(target.read_json('installed.json')),
            'signer_sha256':config['signer_sha256'],'ssh_changed':False,'bootstrap_changed':False}

def apply_update(target,reviewed,plan_hash,device_id,package,fault_after=None):
    if fingerprint(reviewed)!=plan_hash or reviewed['target']['device_id']!=device_id:raise ValueError('Reviewed update identity mismatch')
    target.preflight()
    config=target.read_json('config/service.json');public=target.data.path+'/'+PREFIX+'/config/signing-public.pem'
    snapshot=target.package(package,public,config['signer_sha256'])
    if update_plan(target,package,snapshot)!=reviewed:raise ValueError('Stale update plan')
    target.preflight(writable=True)
    if fault_after is not None and target.context!='fixture':raise ValueError('Fixture-only fault injection')
    v=os.statvfs(target.data.path)
    if v.f_bavail*v.f_frsize<32*1024*1024:raise ValueError('Insufficient update free space')
    p=snapshot;ops=[];version=reviewed['version']
    for n,b in sorted(p['blobs'].items()):
        path=PREFIX+'/releases/'+version+'/'+n
        ops.append({'tree':'data','path':path,'before':target.data.get(path),'after':obj(b,0o644)})
    path=PREFIX+'/current.json'
    ops.append({'tree':'data','path':path,'before':target.data.get(path),'after':obj(canonical({'version':version,'manifest_sha256':p['manifest_sha256']}),0o644)})
    journal={'schema':1,'operation':'panel-update','plan_hash':plan_hash,'device_id':device_id,'version':version,'operations':ops,'phase':'PREPARED'}
    execute_transaction(target,journal,fault_after)
    return {'updated':True,'version':version,'ssh_changed':False,'started_services':False,
            'reload':'Normal supervisor observes pointer; only panel child is replaced'}

def maintenance_plan(target, package, lan_config, _snapshot=None):
    """Explicit owner-service upgrade, separate from the panel-only update path."""
    info = target.preflight()
    if target.context not in ('normal', 'fixture') or not verify_install(target)['verified']:
        raise ValueError('Verified normal owner installation required')
    config = target.read_json('config/service.json')
    public = target.data.path + '/' + PREFIX + '/config/signing-public.pem'
    p = _snapshot if _snapshot is not None else target.package(package, public, config['signer_sha256'])
    if p['manifest']['kind'] != 'maintenance':
        raise ValueError('Separately signed maintenance package required')
    lan_config = unique_json(canonical(lan_config))
    from lan_ipv4 import interface_name
    if set(lan_config) != {'interface', 'http_enabled', 'ssh_enabled'}:
        raise ValueError('Explicit typed secondary LAN policy required')
    interface_name(lan_config['interface'])
    if lan_config['interface'] == config['interface'] or any(type(lan_config[k]) is not bool for k in ('http_enabled', 'ssh_enabled')):
        raise ValueError('Invalid secondary LAN policy')
    version = p['manifest']['version']
    if target.data.get(PREFIX + '/releases/' + version + '/manifest.json') is not None:
        raise ValueError('Release already exists')
    if len(os.listdir(target.data.path + '/' + PREFIX + '/releases')) >= 8:
        raise ValueError('Release retention limit')
    return {'schema':1, 'operation':'maintenance-update', 'target':info, 'version':version,
            'package_sha256':p['package_sha256'], 'manifest_sha256':p['manifest_sha256'],
            'installed_sha256':fingerprint(target.read_json('installed.json')),
            'signer_sha256':config['signer_sha256'], 'lan_config':lan_config,
            'bootstrap_changed':True, 'ssh_changed':True, 'primary_ssh_identity_changed':False,
            'primary_service_config_changed':False, 'slot_paths':[HOOK],
            'existing_lan_config_sha256':fingerprint(target.data.get(PREFIX + '/config/owner-lan.json')),
            'restart':'Reviewed owner supervisor activation required; no printer reboot'}


def apply_maintenance(target, reviewed, plan_hash, device_id, package, fault_after=None):
    if fingerprint(reviewed) != plan_hash or reviewed['target']['device_id'] != device_id:
        raise ValueError('Reviewed maintenance plan/device mismatch')
    target.preflight()
    config = target.read_json('config/service.json')
    public = target.data.path + '/' + PREFIX + '/config/signing-public.pem'
    snapshot = target.package(package, public, config['signer_sha256'])
    if maintenance_plan(target, package, reviewed['lan_config'], snapshot) != reviewed:
        raise ValueError('Stale maintenance plan')
    target.preflight(writable=True)
    if target.context != 'fixture' and fault_after is not None:
        raise ValueError('Fixture-only fault injection')
    if target.context == 'normal':
        rows = [line.split() for line in open('/proc/mounts')]
        if not any(r[1] == '/' and 'rw' in r[3].split(',') for r in rows):
            raise ValueError('Selected owner hook filesystem must already be writable')
    v = os.statvfs(target.data.path)
    if v.f_bavail * v.f_frsize < 32*1024*1024:
        raise ValueError('Insufficient update free space')
    ops = []
    version = reviewed['version']
    def add(tree, path, after):
        ops.append({'tree':tree, 'path':path, 'before':getattr(target,tree).get(path), 'after':after})
    # Only owner bootstrap files; never replace account, shadow, vendor init or identity.
    for name, raw in sorted(snapshot['blobs'].items()):
        path = PREFIX + '/' + name if name.startswith('bootstrap/') else PREFIX + '/releases/' + version + '/' + name
        add('data', path, obj(raw, 0o644))
    add('data', PREFIX + '/config/owner-lan.json', obj(canonical(reviewed['lan_config']), 0o600))
    hook = snapshot['blobs']['bootstrap/owner-maintenance.init'].replace(
        b'@BOOTSTRAP_SHA256@', digest(snapshot['blobs']['bootstrap/bootstrap.py']).encode())
    add('slot', HOOK, obj(hook, 0o755))
    add('data', PREFIX + '/current.json', obj(canonical({'version':version,'manifest_sha256':snapshot['manifest_sha256']}), 0o644))
    journal = {'schema':1, 'operation':'maintenance-update', 'plan_hash':plan_hash,
               'device_id':device_id, 'version':version, 'operations':ops, 'phase':'PREPARED'}
    execute_transaction(target, journal, fault_after)
    return {'updated':True, 'version':version, 'bootstrap_changed':True,
            'primary_ssh_identity_changed':False, 'primary_service_config_changed':False,
            'started_services':False, 'supervisor_restart_required':True}


def panel_identity(cert,key,secret):
    import ssl,tempfile
    c=read_regular(cert,32768);k=read_regular(key,32768);s=read_regular(secret,256).strip()
    if len(s)<32 or len(s)>128 or not re.match(b'^[A-Za-z0-9_-]+$',s):raise ValueError('Random base64url access secret of 32..128 characters required')
    # Check key/certificate pairing with the runtime TLS implementation; no output
    # contains either credential. Caller explicitly supplied the files locally.
    with tempfile.TemporaryDirectory(prefix='owner-tls-validation-') as directory:
        for name,data in (('cert.pem',c),('key.pem',k)):
            fd=os.open(directory+'/'+name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(data)
        context=ssl.SSLContext(ssl.PROTOCOL_TLSv1_2);context.load_cert_chain(directory+'/cert.pem',directory+'/key.pem')
        decoded=ssl._ssl._test_decode_cert(directory+'/cert.pem')
    sans=[v for t,v in decoded.get('subjectAltName',[]) if t=='IP Address']
    if not sans or any(not __import__('ipaddress').ip_address(v).is_private for v in sans):raise ValueError('Private LAN IP SAN required')
    if not ssl.cert_time_to_seconds(decoded['notBefore'])<=time.time()<ssl.cert_time_to_seconds(decoded['notAfter']):raise ValueError('TLS validity interval does not include now')
    return {'cert.pem':c,'key.pem':k,'access-secret':s+b'\n'}

def enrollment_plan(target,cert,key,secret,renew=False,_snapshot=None):
    info=target.preflight()
    if not verify_install(target)['verified']:raise ValueError('Installed baseline changed')
    if target.read_json('config/service.json')['panel_enabled'] and not renew:raise ValueError('Panel already enrolled; use renew-panel')
    blobs=_snapshot if _snapshot is not None else panel_identity(cert,key,secret)
    for name in ('state','panel-identity'):
        present=target.data.get(PREFIX+'/'+name)
        if not renew and present is not None:
            if name!='state' or present['type']!='directory' or present['mode']!=0o700:raise ValueError('Panel directory collision')
            receipt=target.read_json('rollback-receipt.json')
            if not receipt or receipt.get('retained_state')!=present:raise ValueError('Unrecorded retained owner state')
        if renew and (not present or present['type']!='directory' or present['mode']!=0o700):raise ValueError('Existing private enrollment required')
    return {'schema':1,'operation':'panel-renewal' if renew else 'panel-enrollment','target':info,
            'installed_sha256':fingerprint(target.read_json('installed.json')),
            'inputs':{n:digest(b) for n,b in blobs.items()},
            'state_before':target.data.get(PREFIX+'/state'),'ssh_changed':False}

def apply_enrollment(target,reviewed,plan_hash,device_id,cert,key,secret):
    if fingerprint(reviewed)!=plan_hash or reviewed['target']['device_id']!=device_id:raise ValueError('Enrollment identity mismatch')
    renew=reviewed['operation']=='panel-renewal'
    blobs=panel_identity(cert,key,secret)
    if enrollment_plan(target,cert,key,secret,renew,blobs)!=reviewed:raise ValueError('Stale enrollment plan')
    target.preflight(writable=True);config=target.read_json('config/service.json');ops=[]
    uid=os.getuid() if target.context=='fixture' else config['uid'];gid=os.getgid() if target.context=='fixture' else config['gid']
    for name in (() if renew else ('state','panel-identity')):
        if name=='state' and reviewed['state_before'] is not None:continue
        ops.append({'tree':'data','path':PREFIX+'/'+name,'before':None,'after':{'type':'directory','data':'','mode':0o700,'uid':uid,'gid':gid}})
    for name,b in sorted(blobs.items()):
        path=PREFIX+'/panel-identity/'+name
        ops.append({'tree':'data','path':path,'before':target.data.get(path),'after':obj(b,0o600,uid,gid)})
    config['panel_enabled']=True;path=PREFIX+'/config/service.json'
    ops.append({'tree':'data','path':path,'before':target.data.get(path),'after':obj(canonical(config),0o600)})
    path=PREFIX+'/panel-reload.json'
    ops.append({'tree':'data','path':path,'before':target.data.get(path),'after':obj(canonical({'enrollment_plan':plan_hash}),0o644)})
    j={'schema':1,'operation':reviewed['operation'],'plan_hash':plan_hash,'device_id':device_id,
       'version':target.read_json('installed.json')['version'],'operations':ops,'phase':'PREPARED'}
    execute_transaction(target,j)
    return {'enrolled':True,'ssh_changed':False,'started_services':False,'tls_ip_must_match_current_interface':True}

def uninstall(target,device_id,plan_hash):
    if target.context=='normal':raise ValueError('Removing bootstrap/account requires isolated rescue')
    current=target.read_json('pending.json') or target.read_json('installed.json')
    if not current or current['plan_hash']!=plan_hash:raise ValueError('Uninstall reviewed transaction mismatch')
    count=0
    while current:
        if count>=32:raise ValueError('Transaction history bound reached; inspect remaining history')
        rollback(target,device_id,current['plan_hash']);count+=1
        current=target.read_json('pending.json') or target.read_json('installed.json')
    return {'uninstalled':True,'transactions_reversed':count,'owner_runtime_state_and_host_keys_preserved':True}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['preflight','plan','install','update','maintenance-update','enroll-panel','renew-panel','verify','rollback','uninstall'])
    p.add_argument('--slot-root',required=True);p.add_argument('--data-root',required=True);p.add_argument('--context',choices=['fixture','rescue','normal'],required=True)
    p.add_argument('--boot-env');p.add_argument('--package');p.add_argument('--public-key');p.add_argument('--signer-sha256');p.add_argument('--owner-key');p.add_argument('--config')
    p.add_argument('--plan');p.add_argument('--plan-hash');p.add_argument('--device-id');p.add_argument('--apply',action='store_true');p.add_argument('--output')
    p.add_argument('--tls-cert');p.add_argument('--tls-key');p.add_argument('--access-secret')
    a=p.parse_args();target=Target(a.slot_root,a.data_root,a.context,a.boot_env)
    try:
        if a.command=='preflight':r=target.preflight()
        elif a.command=='verify':r=verify_install(target)
        elif a.command in ('plan','install') and not a.apply:
            r=plan(target,a.package,a.public_key,a.signer_sha256,a.owner_key,unique_json(read_regular(a.config,16384)))
            r={'plan':r,'plan_hash':fingerprint(r),'target_writes':False}
        elif a.command=='install' and a.apply:
            doc=unique_json(read_regular(a.plan,65536));r=apply_install(target,doc.get('plan',doc),a.plan_hash,a.device_id,a.package,a.public_key,a.owner_key)
        elif a.command=='maintenance-update':
            if not a.apply:
                q=maintenance_plan(target,a.package,unique_json(read_regular(a.config,4096)))
                r={'plan':q,'plan_hash':fingerprint(q),'target_writes':False}
            else:
                doc=unique_json(read_regular(a.plan,65536));q=doc.get('plan',doc)
                r=apply_maintenance(target,q,a.plan_hash,a.device_id,a.package)
        elif a.command in ('update','enroll-panel','renew-panel'):
            if not a.apply:
                q=update_plan(target,a.package) if a.command=='update' else enrollment_plan(target,a.tls_cert,a.tls_key,a.access_secret,a.command=='renew-panel')
                r={'plan':q,'plan_hash':fingerprint(q),'target_writes':False}
            else:
                doc=unique_json(read_regular(a.plan,65536));q=doc.get('plan',doc)
                r=apply_update(target,q,a.plan_hash,a.device_id,a.package) if a.command=='update' else apply_enrollment(target,q,a.plan_hash,a.device_id,a.tls_cert,a.tls_key,a.access_secret)
        elif a.command in ('rollback','uninstall') and a.apply:r=(rollback if a.command=='rollback' else uninstall)(target,a.device_id,a.plan_hash)
        else:raise ValueError('Mutation requires explicit --apply, reviewed plan hash and device identity')
        raw=json.dumps(r,indent=2,sort_keys=True)
        if a.output:
            fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as f:f.write(raw+'\n')
        print(raw)
        if a.command=='verify' and not r['verified']:raise SystemExit(2)
    finally:target.close()
if __name__=='__main__':main()
