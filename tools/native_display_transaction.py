#!/usr/bin/env python3
"""Pinned native display transactions; Python 3.5, no implicit mount/reboot.

Normal target is only acquired p6 / 2.5.6-2773. Plan first; apply/rollback require
the exact plan digest. Backups are retained under the separate owner data tree.
Does not modify QSPI, boot variables, another slot, identity or vendor services.
"""
import argparse,hashlib,json,os,re,stat,sys

PINS={
 'usr/share/Formlabs/Palantir-Form3/Palantir.rcc':
  ('969cae93da58f0e2be6040b48eea071f678b12e55b592d4fd7298060d2e05150',
   'adbfc45835a00911507d2ac2e1cd44a3785bf124d5c0c33411aa2e47503867c7','clock.rcc',0o644),
 'usr/bin/psplash-default':
  ('2d51b6ea8ea27612fb5ae6a830a702891c37944f42492ba6ebaaeed319aaac2f',
   '98d928c67a5ac92f338493c7063f1355eb846f11ec0e5a7aa2ee872c650d3b8c','splash.bin',0o755)}
LIMIT=6*1024*1024
LOCAL_SHA='27ed8d7e10d26f4ce9d03888bd69fc2a022a4b88b4a3eb452a7c25e7249f10b4'
READY_CLOCK_SHA='b184f0b135dc7752098eba1acef9aa543aeaeabef006e70a38b302917753207d'
PRINTING_CLOCK_SHA='60eba559ded4d4be0cde58f775872376e7e7168134acaef9a00bebf498ec7f45'
RCC='usr/share/Formlabs/Palantir-Form3/Palantir.rcc'
SPLASH='usr/bin/psplash-default'
SIGNATURE_SHA='6e22950da068b060aa19872713757058b8656a422e18e919fc2e0e15840fecd5'
OWNER_ROOT_SHA='9cbb2ed4bf85bacf40a2eadcb1997532f2b6bf0251164272a61d5b0ad11894ce'
PROFILES={'printing-clock':{RCC:(LOCAL_SHA,PRINTING_CLOCK_SHA,'clock.rcc',0o644)},
 'printing-clock-ready':{RCC:(READY_CLOCK_SHA,PRINTING_CLOCK_SHA,'clock.rcc',0o644)},
 'printing-clock-factory':{RCC:(PINS[RCC][0],PRINTING_CLOCK_SHA,'clock.rcc',0o644)},
 'owner-root-splash':{SPLASH:(SIGNATURE_SHA,OWNER_ROOT_SHA,'splash.bin',0o755)},
 'ready-clock':{RCC:(LOCAL_SHA,READY_CLOCK_SHA,'clock.rcc',0o644)},
 'ready-clock-factory':{RCC:(PINS[RCC][0],READY_CLOCK_SHA,'clock.rcc',0o644)},
 'owner-root-splash-factory':{SPLASH:(PINS[SPLASH][0],OWNER_ROOT_SHA,'splash.bin',0o755)},
 'local-clock-factory':{RCC:(PINS[RCC][0],LOCAL_SHA,'clock.rcc',0o644)},
 'initial-utc':PINS,
 'local-clock':{RCC:(PINS[RCC][1],LOCAL_SHA,'clock.rcc',0o644)},
 'signature-splash':{SPLASH:(PINS[SPLASH][1],SIGNATURE_SHA,'splash.bin',0o755)},
 'initial-local':dict(PINS,**{RCC:(PINS[RCC][0],LOCAL_SHA,'clock.rcc',0o644)})}
def digest(b):return hashlib.sha256(b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')
def checked_parents(path):
    path=os.path.abspath(path);p=os.path.dirname(path)
    while True:
        st=os.lstat(p)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid not in (0,os.getuid()) or st.st_mode&0o022:
            # Fixture ancestry may include the host's sticky /tmp directory.
            if not (p=='/tmp' and stat.S_ISDIR(st.st_mode) and st.st_mode&stat.S_ISVTX):
                raise ValueError('Untrusted parent directory')
        if p=='/':break
        p=os.path.dirname(p)
def read(path,limit=LIMIT):
    checked_parents(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o022 or st.st_size>limit:
            raise ValueError('Untrusted or oversized regular input')
        b=f.read(limit+1)
        if len(b)!=st.st_size:raise ValueError('Input changed or exceeded limit')
    return b,{'sha256':digest(b),'bytes':len(b),'mode':stat.S_IMODE(st.st_mode),'uid':st.st_uid,'gid':st.st_gid}
def atomic(path,b,mode=0o600,uid=None,gid=None):
    checked_parents(path);parent=os.path.dirname(path);temp=parent+'/.owner-native-'+os.urandom(12).hex()
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(b);f.flush();os.fchmod(f.fileno(),mode)
            if uid is not None and os.getuid()==0:os.fchown(f.fileno(),uid,gid)
            os.fsync(f.fileno())
        os.replace(temp,path)
        fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.lexists(temp):os.unlink(temp)

class Transaction(object):
    def __init__(self,root='/',fixture=False,pins=None,profile='initial-utc'):
        self.root=os.path.abspath(root);self.fixture=fixture;self.pins=PROFILES[profile] if pins is None else pins
        if fixture:
            if self.root=='/' or read(self.root+'/.native-fixture')[0]!=b'authored disposable fixture\n':raise ValueError('Explicit fixture required')
        elif self.root!='/' or self.pins!=PROFILES[profile] or os.getuid()!=0:raise ValueError('Exact normal target required')
    def path(self,rel):
        if rel not in self.pins:raise ValueError('Unapproved target path')
        return self.root.rstrip('/')+'/'+rel
    def operation(self):
        if len(self.pins)==2:return 'native-display-two-files'
        return 'native-display-splash' if set(self.pins)=={SPLASH} else 'native-display-clock'
    def identity(self):
        if self.fixture:return 'synthetic-fixture'
        sys.path.insert(0,'/data/owner-maintenance/bootstrap')
        import ownerctl
        t=ownerctl.Target('/','/data','normal')
        try:
            p=t.preflight()
            if not ownerctl.verify_install(t)['verified']:raise ValueError('Owner baseline does not verify')
            return p['device_id']
        finally:t.close()
    def plan(self,staging):
        entries=[]
        for rel,(old,new,name,mode) in sorted(self.pins.items()):
            before,meta=read(self.path(rel));after,ameta=read(staging+'/'+name)
            if digest(before)!=old or digest(after)!=new or meta['mode']!=mode:raise ValueError('Exact reviewed file mismatch')
            entries.append({'path':rel,'candidate':name,'before':meta,'after_sha256':new,'after_bytes':len(after)})
        return {'schema':1,'operation':self.operation(),'device_id':self.identity(),'entries':entries}
    def validate_plan(self,plan,pin):
        operation=self.operation()
        if digest(canonical(plan))!=pin or plan.get('schema')!=1 or plan.get('operation')!=operation or plan.get('device_id')!=self.identity():raise ValueError('Plan/device mismatch')
        if len(plan['entries'])!=len(self.pins) or {x['path'] for x in plan['entries']}!=set(self.pins):raise ValueError('Plan path mismatch')
        for e in plan['entries']:
            old,new,name,mode=self.pins[e['path']]
            if (e['before']['sha256'],e['after_sha256'],e['candidate'],e['before']['mode'])!=(old,new,name,mode):raise ValueError('Plan pins changed')
    def backup_location(self,backup):
        if not self.fixture and not re.match(r'^/data/owner-maintenance/native-display/[A-Za-z0-9_-]{8,80}$',backup):raise ValueError('Unapproved backup location')
        checked_parents(backup)
    def apply(self,plan,pin,staging,backup,fault_after=None):
        self.validate_plan(plan,pin);self.backup_location(backup)
        if not self.fixture and fault_after is not None:raise ValueError('Fixture fault only')
        if self.plan(staging)!=plan:raise ValueError('Stale plan')
        if os.path.lexists(backup):raise ValueError('Never overwrite a backup')
        os.mkdir(backup,0o700)
        # All originals saved and synced before the first target replacement.
        for i,e in enumerate(plan['entries']):atomic(backup+'/before-%d'%i,read(self.path(e['path']))[0])
        atomic(backup+'/plan.json',canonical(plan))
        journal={'plan_sha256':pin,'phase':'PREPARED','completed':0}
        atomic(backup+'/receipt.json',canonical(journal))
        for i,e in enumerate(plan['entries']):
            if read(self.path(e['path']))[1]!=e['before']:raise ValueError('Concurrent target change')
            b=read(staging+'/'+e['candidate'])[0]
            if digest(b)!=e['after_sha256']:raise ValueError('Candidate changed')
            m=e['before'];atomic(self.path(e['path']),b,m['mode'],m['uid'],m['gid'])
            if read(self.path(e['path']))[1]['sha256']!=e['after_sha256']:raise ValueError('Readback failed')
            journal['completed']=i+1;atomic(backup+'/receipt.json',canonical(journal))
            if fault_after==i+1:raise RuntimeError('Fixture interruption')
        journal['phase']='APPLIED';atomic(backup+'/receipt.json',canonical(journal));return journal
    def rollback(self,plan,pin,backup):
        self.validate_plan(plan,pin);self.backup_location(backup)
        if read(backup+'/plan.json')[0]!=canonical(plan):raise ValueError('Backup plan mismatch')
        saved=[]
        for i,e in enumerate(plan['entries']):
            b=read(backup+'/before-%d'%i)[0];now=read(self.path(e['path']))[1]
            if digest(b)!=e['before']['sha256'] or now['sha256'] not in (e['before']['sha256'],e['after_sha256']):raise ValueError('Backup or concurrent file mismatch')
            saved.append((e,b))
        for e,b in saved:
            m=e['before'];atomic(self.path(e['path']),b,m['mode'],m['uid'],m['gid'])
        result={'phase':'ROLLED_BACK','plan_sha256':pin,'originals_retained':True}
        atomic(backup+'/receipt.json',canonical(result));return result

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('plan','apply','rollback'))
    p.add_argument('--staging');p.add_argument('--plan',required=True);p.add_argument('--plan-sha256');p.add_argument('--backup')
    p.add_argument('--profile',choices=sorted(PROFILES),default='initial-local')
    a=p.parse_args()
    if not re.match(r'^/run/owner-[A-Za-z0-9_-]{4,80}/[A-Za-z0-9_-]+\.json$',a.plan):
        p.error('Plan must be a named JSON file in explicit owner RAM staging')
    t=Transaction(profile=a.profile)
    if a.command=='plan':
        if not a.staging:p.error('--staging required')
        if os.path.lexists(a.plan):raise ValueError('Never overwrite a plan')
        r=t.plan(a.staging);atomic(a.plan,canonical(r));print(json.dumps({'plan_sha256':digest(canonical(r)),'files':len(r['entries'])}));return
    if not a.plan_sha256 or not a.backup:p.error('Exact plan SHA256 and retained backup path required')
    r=json.loads(read(a.plan,32768)[0].decode())
    result=t.apply(r,a.plan_sha256,a.staging,a.backup) if a.command=='apply' else t.rollback(r,a.plan_sha256,a.backup)
    print(json.dumps(result))
if __name__=='__main__':main()
