#!/usr/bin/env python3
"""Run isolated authored fixtures; optionally include explicitly supplied rescue evidence.

Default fixtures need no proprietary images. Evidence suites are counted separately,
never silently passed. No host home, credentials, vendor startup or external network.
"""
import argparse, hashlib, json, os, shutil, subprocess, tempfile
from pathlib import Path
from evidence_lib import ROOT, safe_output

SELECT = 'test_persistent_ARM_shell_twice_without_any_PTY'
CODE = '''import json,sys,unittest
sys.path.insert(0,'/work/tests')
def flatten(s):
 for t in s:
  if isinstance(t,unittest.TestSuite):yield from flatten(t)
  else:yield t
all_tests=list(flatten(unittest.defaultTestLoader.discover('/work/tests')))
mode=sys.argv[1]
chosen=[t for t in all_tests if (('test_rescue.' not in t.id()) if mode=='fixtures' else (("'''+SELECT+'''" in t.id()) == (mode=='nc')))]
print(json.dumps({'selected':len(chosen),'excluded':len(all_tests)-len(chosen),'scope':mode,'evidence_tests_excluded':mode=='fixtures'}),flush=True)
result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(chosen))
print(json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'scope':mode,'passed':result.wasSuccessful()}),flush=True)
raise SystemExit(not result.wasSuccessful())
'''

# Only the outer namespace setup needs host privilege on kernels where bubblewrap's
# nested user namespace cannot administer its network namespace. It never changes
# the host namespace. Drop to the invoking owner before starting the filesystem sandbox.
LAN_SETUP = """import os,subprocess,sys
uid,gid=int(sys.argv[1]),int(sys.argv[2])
subprocess.run(['/usr/sbin/ip','link','set','lo','up'],check=True)
for ip in ('192.168.50.20','192.168.50.21','192.168.50.22'):
 subprocess.run(['/usr/sbin/ip','addr','add',ip+'/24','dev','lo'],check=True)
os.setgroups([]);os.setgid(gid);os.setuid(uid)
os.execvp(sys.argv[3],sys.argv[3:])
"""

def run(output, scope='fixtures', evidence_root=None):
    output=safe_output(output)
    if scope not in ('fixtures','evidence'): raise ValueError('Unknown scope')
    if not shutil.which('bwrap'): raise ValueError('Missing bwrap; isolation is mandatory')
    evidence=Path(evidence_root).resolve() if evidence_root else ROOT
    if scope=='evidence':
        for command in ('qemu-arm','strace'):
            if not shutil.which(command):raise ValueError('Missing '+command)
        required=['build/rescue-v2/busybox','hardware/qspi/original/form3_qspi_FACTORY.bin']
        for name in required:
            if not (evidence/name).is_file():raise ValueError('Explicit evidence input unavailable: '+name)
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
             for area in ('tools','tests','owner-maintenance','owner-ui','rescue','scripts','docs/public')
             for p in sorted((ROOT/area).rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    sources['VERSION']=hashlib.sha256((ROOT/'VERSION').read_bytes()).hexdigest()
    groups=[]
    with tempfile.TemporaryDirectory(prefix='form3-tests-') as tmp, output.open('x') as log:
        tmp=Path(tmp); stage=tmp/'bin';stage.mkdir()
        if scope=='evidence':
            shutil.copyfile(evidence/'build/rescue-v2/busybox',stage/'busybox');(stage/'busybox').chmod(0o755)
            for name in ('nc','sh','id','uname'):(stage/name).symlink_to('busybox')
        passwd=tmp/'passwd';passwd.write_text('root:x:0:0:root:/root:/bin/sh\n')
        group=tmp/'group';group.write_text('root:x:0:\n')
        for mode in (('fixtures',) if scope=='fixtures' else ('ordinary','nc')):
            cmd=['bwrap','--unshare-user','--uid','0','--gid','0','--unshare-pid','--die-with-parent',
                 '--clearenv','--setenv','OWNER_TEST_NETNS','1','--setenv','PATH','/usr/bin:/runtime','--setenv','LC_ALL','C',
                 '--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--symlink','usr/bin','/bin',
                 '--symlink','usr/sbin','/sbin','--proc','/proc','--tmpfs','/tmp',
                 '--ro-bind',str(passwd),'/etc/passwd','--ro-bind',str(group),'/etc/group']
            if mode!='nc':cmd+=['--ro-bind','/usr','/usr','--dev','/dev'];python='/usr/bin/python3'
            else:
                cmd+=['--ro-bind','/usr/lib','/usr/lib','--ro-bind','/usr/lib64','/usr/lib64',
                      '--ro-bind',str(stage),'/usr/bin','--tmpfs','/dev','--dev-bind','/dev/null','/dev/null',
                      '--tmpfs','/run','--ro-bind','/usr/bin/python3','/runtime/python3',
                      '--ro-bind',shutil.which('qemu-arm'),'/runtime/qemu-arm',
                      '--ro-bind',shutil.which('strace'),'/runtime/strace','--setenv','FORM3_NC_PREPARED','1']
                python='/runtime/python3'
            for name in ('tools','tests','rescue','scripts','owner-ui','owner-maintenance','schemas','docs/public'):
                if (ROOT/name).is_dir():cmd+=['--ro-bind',str(ROOT/name),'/work/'+name]
            cmd+=['--ro-bind',str(ROOT/'VERSION'),'/work/VERSION']
            if scope=='evidence':
                for name in ('build/rescue','build/rescue-v2','hardware/qspi/build','hardware/qspi/build-v2'):
                    cmd+=['--ro-bind',str(evidence/name),'/work/'+name]
                cmd+=['--ro-bind',str(evidence/'hardware/qspi/original/form3_qspi_FACTORY.bin'),'/work/hardware/qspi/original/form3_qspi_FACTORY.bin']
            else:cmd+=['--dir','/work/hardware/qspi/original']
            cmd+=['--dir','/work/hardware/emmc/original','--chdir','/work',python,'-B','-c',CODE,mode]
            log.write('GROUP '+mode+': isolated user/PID/network; no host home/credentials; source/evidence read-only.\n');log.flush()
            # unshare always precedes ip setup; no fallback to host networking.
            cmd=['sudo','-n','unshare','--net','--fork','--','/usr/bin/python3','-c',LAN_SETUP,str(os.getuid()),str(os.getgid())]+cmd
            result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=300)
            groups.append({'group':mode,'exit':result.returncode})
        stable=all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h for n,h in sources.items())
        report={'scope':scope,'groups':groups,'source_sha256':sources,'sources_stable':stable,
                'evidence_suite_requested':scope=='evidence','passed':stable and all(x['exit']==0 for x in groups)}
        log.write('\nRECEIPT '+json.dumps(report,sort_keys=True)+'\n')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--scope',choices=('fixtures','evidence'),default='fixtures')
    p.add_argument('--evidence-root',help='Explicit acquisition workspace; mounted read-only for evidence scope')
    a=p.parse_args();r=run(a.output,a.scope,a.evidence_root)
    print(json.dumps({k:v for k,v in r.items() if k!='source_sha256'},indent=2));raise SystemExit(not r['passed'])
if __name__=='__main__':main()
