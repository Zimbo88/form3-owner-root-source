#!/usr/bin/env python3
"""Python 3.5 live observer: selected regular logs/proc/sys + passive D-Bus signals.

Read-only file descriptors with NOATIME. No vendor methods, imports, settings,
filesystem/database writes, log rotation, actuator calls or network probes.
Executed from SSH stdin; output streams to the laptop. No target installation.
"""
import base64
import hashlib
import json
import os
import re
import resource
import select
import signal
import stat
import subprocess
import sys
import threading
import time

ROOTS = ('/data/logs', '/var/volatile/log')
LOG_NAME = re.compile(r'^[A-Za-z0-9_.+-]{1,100}\.(?:log|csv|tsv|msgpack)(?:\.[0-9]{1,3})?(?:\.gz)?\Z')
PLAIN = {'syslog', 'messages', 'dmesg', 'kern.log', 'daemon.log', 'debug'}
VENDOR = {'Sauron','CandyBus','Formule','Palantir','TankCartridgeDa','RichardNixon','connmand','fluent-bit'}
STREAM_LIMIT = 512 << 20
READ_CHUNK = 65536
BASELINE_TAIL = 16 << 20
MAX_FILES = 192
MATCHES = [
 "type='signal',sender='com.formlabs.Sauron'",
 "type='signal',sender='com.formlabs.TankCartridgeController'",
 "type='signal',sender='com.formlabs.PrintQueue'",
 "type='signal',sender='com.formlabs.Orchestrator'",
 "type='signal',sender='com.formlabs.Heater'",
 "type='signal',sender='com.formlabs.Fan'",
 "type='signal',sender='com.formlabs.SensorFailure'",
 "type='signal',sender='com.formlabs.CandyBus',member='temperature'",
 "type='signal',sender='com.formlabs.CandyBus',member='fanState'",
 "type='signal',sender='org.freedesktop.DBus',member='NameOwnerChanged',arg0namespace='com.formlabs'"
]


def read(path, limit=65536):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_NOATIME', 0))
    try:
        return os.read(fd, limit)
    finally:
        os.close(fd)


def jread(path):
    return json.loads(read(path).decode('utf-8'))


def allowed_name(name):
    return bool(isinstance(name, str) and '/' not in name and (name in PLAIN or LOG_NAME.match(name)))


class Reader:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os,'O_NOATIME',0))
        st = os.fstat(self.fd)
        if not stat.S_ISREG(st.st_mode):
            os.close(self.fd)
            raise ValueError('Regular logs only')
        self.path, self.inode, self.dev = path, st.st_ino, st.st_dev
        self.offset = max(0, st.st_size-BASELINE_TAIL)
        self.initial_size = st.st_size
        self.generation = 0
        self.initialized = False
        self.last_data = time.monotonic()
        os.lseek(self.fd, self.offset, os.SEEK_SET)

    def next(self):
        st = os.fstat(self.fd)
        truncated = st.st_size < self.offset
        if truncated:
            self.offset = 0
            self.generation += 1
            os.lseek(self.fd,0,os.SEEK_SET)
        off = self.offset
        data = os.read(self.fd, READ_CHUNK)
        if data:
            self.last_data = time.monotonic()
        self.offset += len(data)
        initial = not self.initialized
        self.initialized = True
        return {'path':self.path,'inode':self.inode,'device':self.dev,'generation':self.generation,
                'offset':off,'bytes':len(data),'mtime':st.st_mtime,'size_at_read':st.st_size,
                'initial_size':self.initial_size,'initial_record':initial,'truncated':truncated,
                'baseline':self.generation==0 and off < self.initial_size,
                'sha256':hashlib.sha256(data).hexdigest(),'data_b64':base64.b64encode(data).decode('ascii')}

    def close(self):
        os.close(self.fd)

    def retired(self):
        """Release unlinked rotations only after their tail stayed quiet for 30 s.

        An application could write an unlinked file later; emit the retirement
        as a coverage boundary rather than promising an unlimited tail.
        """
        st = os.fstat(self.fd)
        return st.st_nlink == 0 and self.offset >= st.st_size and time.monotonic()-self.last_data >= 30


def sample():
    out={'uptime':read('/proc/uptime',256).decode().strip(),
         'loadavg':read('/proc/loadavg',256).decode().strip(),
         'stat':read('/proc/stat',16384).decode(),
         'diskstats':read('/proc/diskstats',16384).decode(),
         'netdev':read('/proc/net/dev',16384).decode(),
         'meminfo':read('/proc/meminfo',8192).decode(),
         'thermal':{}}
    for i in range(16):
        root='/sys/class/thermal/thermal_zone'+str(i)
        try:
            kind=read(root+'/type',128).decode().strip()
            if kind not in ('cpu_thermal','gpu_thermal','core_thermal','dspeve_thermal','iva_thermal'):continue
            value=int(read(root+'/temp',128).decode().strip())
            out['thermal'][kind]={'raw_millicelsius':value,'celsius':value/1000.0}
        except (OSError, ValueError):pass
    return out


def processes():
    result=[]
    for n in os.listdir('/proc'):
        if not n.isdigit():continue
        try:
            comm=read('/proc/'+n+'/comm',256).decode().strip()
            if comm not in VENDOR:continue
            status=read('/proc/'+n+'/status',8192).decode().splitlines()
            result.append({'pid':int(n),'comm':comm,'stat':read('/proc/'+n+'/stat',8192).decode(),
                'status':{line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status if line.startswith(('State:','VmRSS:','Threads:','voluntary_ctxt_switches:','nonvoluntary_ctxt_switches:'))}})
        except OSError:pass
    return result


EXPECTED_OWNER_VERSION = '0.5.8-review'


def main():
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_NOFILE,(256,256))
    # Child monitor queue/output is bounded; these limits affect only the observer.
    resource.setrlimit(resource.RLIMIT_AS,(192<<20,192<<20))
    boot=read('/proc/sys/kernel/random/boot_id',128).decode().strip()
    cmdline=read('/proc/cmdline',4096).decode().split()
    if os.getuid()!=0 or os.uname().machine!='armv7l' or os.uname().release!='4.9.65+' or 'root=/dev/mmcblk0p6' not in cmdline or 'rdinit=/init' in cmdline:
        raise ValueError('Expected reference normal-OS identity')
    if jread('/etc/formlabs/version.json').get('build',{}).get('name')!='2.5.6-2773':raise ValueError('Unsupported firmware')
    current=jread('/data/owner-maintenance/current.json')
    if current.get('version')!=EXPECTED_OWNER_VERSION or os.path.exists('/data/owner-maintenance/pending.json'):raise ValueError('Unexpected owner state')
    lock=threading.Lock();done=threading.Event();counts={'bytes':0,'events':0};children=[];start=time.monotonic()
    def emit(kind, payload):
        with lock:
            if done.is_set():return
            doc={'kind':kind,'device_epoch':time.time(),'device_monotonic':time.monotonic(),'boot_id':boot,'payload':payload}
            data=json.dumps(doc,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n'
            if counts['bytes']+len(data)>STREAM_LIMIT:done.set();return
            try:sys.stdout.write(data);sys.stdout.flush()
            except (OSError, IOError):done.set();return
            counts['bytes']+=len(data);counts['events']+=1
    def pipe_observer(kind, command):
        try:
            child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
            children.append(child)
            emit('observer_started',{'observer':kind,'pid':child.pid,'command':command})
            pipes={child.stdout.fileno():'stdout',child.stderr.fileno():'stderr'}
            sent=0
            while pipes and not done.is_set():
                ready,_,_=select.select(list(pipes),[],[],1)
                for fd in ready:
                    data=os.read(fd,READ_CHUNK)
                    if not data:del pipes[fd];continue
                    sent+=len(data)
                    if sent>128<<20:
                        emit('coverage_gap',{'observer':kind,'reason':'128-MiB observer stream bound'});return
                    emit(kind,{'channel':pipes[fd],'bytes':len(data),'data_b64':base64.b64encode(data).decode('ascii'),'sha256':hashlib.sha256(data).hexdigest()})
            emit('observer_exit',{'observer':kind,'exit':child.poll()})
        except (OSError,ValueError) as e:emit('coverage_gap',{'observer':kind,'reason':type(e).__name__})
        finally:
            if 'child' in locals() and child.poll() is None:child.terminate()
    signal.signal(signal.SIGTERM,lambda *_:done.set())
    signal.signal(signal.SIGINT,lambda *_:done.set())
    emit('identity',{'uid':os.getuid(),'kernel':os.uname().release,'architecture':os.uname().machine,
        'firmware':'2.5.6-2773','selected_slot':6,'owner_version':current['version'],'observer_pid':os.getpid(),
        'mounts':read('/proc/self/mounts',32768).decode(),'boot_id':boot,'python':sys.version.split()[0],
        'limits':{'connection_seconds':1800,'stream_bytes':STREAM_LIMIT,'baseline_tail_per_file':BASELINE_TAIL}})
    for kind,command in [('dbus',['/usr/bin/dbus-monitor','--system']+MATCHES)]:
        thread=threading.Thread(target=pipe_observer,args=(kind,command));thread.daemon=True;thread.start()
    readers={};last_scan=last_proc=last_kernel=-100.0;kernel_sha=None
    try:
        while not done.is_set() and time.monotonic()-start<1800:
            now=time.monotonic()
            if now-last_scan>=5:
                for root in ROOTS:
                    try:
                        if os.path.realpath(root)!=root:raise ValueError('Log root changed')
                        names=sorted(os.listdir(root))
                        if len(names)>1024:raise ValueError('Directory count bound')
                        for name in names:
                            if not allowed_name(name):continue
                            path=root+'/'+name
                            try:
                                st=os.lstat(path);key=(st.st_dev,st.st_ino)
                                if not stat.S_ISREG(st.st_mode) or key in readers:continue
                                if len(readers)>=MAX_FILES:
                                    emit('coverage_gap',{'reason':'open log count bound'});continue
                                readers[key]=Reader(path)
                            except OSError:pass
                    except (OSError,ValueError):emit('coverage_gap',{'root':root,'reason':'log root unavailable/changed'})
                last_scan=now
            for key,reader in list(readers.items()):
                try:
                    chunk=reader.next()
                    if chunk['bytes'] or chunk['initial_record'] or chunk['truncated']:emit('file',chunk)
                    if reader.retired():
                        emit('coverage_boundary',{'path':reader.path,'inode':reader.inode,
                             'reason':'unlinked log fully read; no further bytes for 30 seconds',
                             'offset':reader.offset})
                        reader.close();del readers[key]
                except OSError:
                    emit('coverage_gap',{'path':reader.path,'reason':'read failed'});reader.close();del readers[key]
            emit('sample',sample())
            if now-last_proc>=10:
                emit('processes',{'processes':processes(),'observer_usage':list(resource.getrusage(resource.RUSAGE_SELF))})
                last_proc=now
            if now-last_kernel>=10:
                try:
                    r=subprocess.run(['/bin/dmesg'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3)
                    data=r.stdout[:1<<20];sha=hashlib.sha256(data).hexdigest()
                    if sha!=kernel_sha:
                        emit('kernel',{'data_b64':base64.b64encode(data).decode('ascii'),'sha256':sha,'exit':r.returncode,'bounded':len(r.stdout)>len(data)})
                        kernel_sha=sha
                except (OSError,subprocess.TimeoutExpired):emit('coverage_gap',{'reason':'kernel snapshot unavailable'})
                last_kernel=now
            emit('heartbeat',{'events':counts['events'],'stream_bytes':counts['bytes'],'open_logs':len(readers),'baseline_pending':sum(r.offset<r.initial_size for r in readers.values())})
            done.wait(1)
        emit('complete',{'reason':'observer session boundary','events':counts['events'],'stream_bytes':counts['bytes']})
    finally:
        done.set()
        for child in children:
            if child.poll() is None:child.terminate()
        for reader in readers.values():reader.close()


if __name__=='__main__':
    main()
