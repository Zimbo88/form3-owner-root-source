#!/usr/bin/env python3
"""Root-owned SysV supervisor. Python 3.5. Never run vendor startup scripts.

Only normal Form 3 p6/2.5.6 is supported. No default route, DHCP configuration,
vendor-service control, automatic firmware adaptation or QSPI writes exist here.
"""
import argparse,fcntl,hashlib,ipaddress,json,os,re,signal,socket,stat,struct,subprocess,time
from lan_ipv4 import interface_assignment, interface_name
BASE='/data/owner-maintenance'
RUN='/run/owner-maintenance'
PYTHON='/usr/bin/python3.5'

def trusted(path,limit=4*1024*1024,private=False):
    """Root-owned, non-writable ancestors and regular leaf, with no symlinks."""
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        parts=path.strip('/').split('/')
        for part in parts[:-1]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
            st=os.fstat(fd)
            if st.st_uid!=0 or st.st_mode&0o022:raise ValueError('Untrusted owner ancestor')
        f=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        with os.fdopen(f,'rb') as h:
            st=os.fstat(h.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022 or (private and st.st_mode&0o077) or st.st_size>limit:
                raise ValueError('Untrusted owner file')
            b=h.read(limit+1)
            if len(b)>limit:raise ValueError('Owner file size limit')
            return b
    finally:os.close(fd)

def normal_context():
    if os.getuid()!=0 or not os.uname().machine.startswith('armv7'):raise ValueError('Normal ARM root context required')
    with open('/proc/cmdline') as f:cmdline=f.read(65536).split()
    if 'rdinit=/init' in cmdline or 'root=/dev/mmcblk0p6' not in cmdline:raise ValueError('Unsupported boot context')
    with open('/proc/device-tree/model','rb') as f:model=f.read(4096)
    if b'Formlabs' not in model:raise ValueError('Unexpected platform')
    with open('/etc/formlabs/version.json') as f:version=json.load(f)
    if version.get('build',{}).get('name')!='2.5.6-2773':raise ValueError('Firmware changed; owner service disabled')
    rows=[line.split() for line in open('/proc/mounts')]
    if not any(r[:3]==['/dev/mmcblk0p7','/data','ext4'] for r in rows):raise ValueError('Persistent data mount missing')

def configuration():
    c=json.loads(trusted(BASE+'/config/service.json',16384,True).decode('utf-8'))
    if set(c)!={'interface','client_network','panel_enabled','uid','gid','firmware','slot','signer_sha256'}:raise ValueError('Unknown service option')
    if c['interface'] not in ('eth0','wlan0') or c['slot']!=6 or c['firmware']!='2.5.6-2773':raise ValueError('Unsupported owner configuration')
    if type(c['panel_enabled']) is not bool or any(type(c[x]) is not int or not 64900<=c[x]<=65000 for x in ('uid','gid')):raise ValueError('Invalid owner identity')
    n=ipaddress.ip_network(c['client_network'],strict=True)
    if n.version!=4 or not n.is_private or n.prefixlen<16:raise ValueError('Private owner LAN required')
    if not re.match(r'^[a-f0-9]{64}$',c['signer_sha256']):raise ValueError('Invalid signer pin')
    return c

def lan_configuration(primary):
    path = BASE + '/config/owner-lan.json'
    if not os.path.lexists(path):
        return None
    c = json.loads(trusted(path, 4096, True).decode('ascii'))
    if set(c) != {'interface', 'http_enabled', 'ssh_enabled'}:
        raise ValueError('Invalid secondary owner LAN configuration')
    interface_name(c['interface'])
    if c['interface'] == primary['interface'] or any(type(c[k]) is not bool for k in ('http_enabled', 'ssh_enabled')):
        raise ValueError('Distinct explicit owner LAN interface required')
    return c


def lan_firewall(c, assignment):
    """Update only a subordinate owner chain; empty chain returns to owner DROP.

    Source, destination, ingress interface and port are all constrained. IPv6 is
    never opened. No primary SSH rule or vendor chain is modified here.
    """
    base = ['/usr/sbin/iptables', '-w', '3']
    commands = [base + ['-F', 'OWNER_LAN']]
    if c and assignment:
        ip, network = assignment
        for key, port in (('http_enabled', '1328'), ('ssh_enabled', '2222')):
            if c[key]:
                commands.append(base + ['-A', 'OWNER_LAN', '-i', c['interface'], '-s', network,
                                        '-d', ip + '/32', '-p', 'tcp', '--dport', port, '-j', 'ACCEPT'])
    commands.append(base + ['-A', 'OWNER_LAN', '-j', 'DROP'])
    for command in commands:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)


class SecondaryLAN(object):
    """WLAN changes restart only secondary SSH, never primary SSH or HTTPS."""
    def __init__(self):
        self.current = None
        self.child = None
        self.retry_after = 0
        self.failed = False

    def close(self):
        stop_process(self.child)
        self.child = None

    def poll(self, c):
        observed = interface_assignment(c['interface']) if c else None
        policy = (tuple(sorted(c.items())) if c else None, observed)
        try:
            if policy != self.current:
                self.close()
                lan_firewall(c, observed)
                self.current = policy
                self.retry_after = 0
            if c and c['ssh_enabled'] and observed:
                if self.child is not None and self.child.poll() is not None:
                    self.close()
                    self.retry_after = time.monotonic() + 10
                if self.child is None and time.monotonic() >= self.retry_after:
                    trusted(BASE+'/ssh/authorized_keys',16384,True)
                    trusted(BASE+'/ssh/host_ed25519',16384,True)
                    conf = ssh_configuration(observed[0]).replace('/sshd.pid', '/lan-sshd.pid')
                    atomic(RUN + '/lan-sshd_config', conf.encode('ascii'))
                    subprocess.run(['/usr/sbin/sshd', '-t', '-f', RUN + '/lan-sshd_config'],
                                   check=True, timeout=5, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.child = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', RUN + '/lan-sshd_config'],
                                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.failed = False
        except (OSError, ValueError, subprocess.SubprocessError):
            self.close()
            self.current = None
            self.failed = True
            try:lan_firewall(None,None)
            except (OSError,subprocess.SubprocessError):pass
            # A failed insertion leaves no successful secondary listener startup.
            # Per-request panel assignment checks also reject stale HTTP state.
        return {'address': observed[0] if observed else None,
                'ssh_process': self.child is not None and self.child.poll() is None,
                'failed_closed': self.failed}


def address(interface):
    if interface not in ('eth0','wlan0'):raise ValueError('Physical owner interface required')
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            data=fcntl.ioctl(s.fileno(),0x8915,struct.pack('256s',interface.encode('ascii')))
        result=socket.inet_ntoa(data[20:24])
        return result if ipaddress.ip_address(result).is_private else None
    except OSError:return None

def firewall_commands(c,ipv6=False):
    """Typed plan only; caller must establish ARM normal context before execution.

    Owner chain intercepts ONLY the two owner ports. No vendor chain is flushed.
    IPv6 is refused for these ports until a reviewed IPv6 implementation exists.
    """
    exe='/usr/sbin/ip6tables' if ipv6 else '/usr/sbin/iptables'
    common=[exe,'-w','3']
    out=[common+['-N','OWNER_MAINT'],common+['-F','OWNER_MAINT']]
    if not ipv6:
        out+=[common+['-A','OWNER_MAINT','-i',c['interface'],'-s',c['client_network'],'-j','ACCEPT']]
        out+=[common+['-A','OWNER_MAINT','-j','OWNER_LAN']]
    out+=[common+['-A','OWNER_MAINT','-j','DROP']]
    return out

def firewall(c):
    base=['/usr/sbin/iptables','-w','3']
    probe=subprocess.run(base+['-S','OWNER_LAN'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
    if probe.returncode:
        subprocess.run(base+['-N','OWNER_LAN'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
    lan_firewall(None,None)
    # Block IPv6 first. A missing utility or unsupported match prevents startup.
    for v6 in (True,False):
        cmds=firewall_commands(c,v6)
        exists=subprocess.run(cmds[0][:-2]+['-S','OWNER_MAINT'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        if exists.returncode==0:
            # Refuse unexpected owner-chain content? The root-owned supervisor is
            # its only authorized writer; service children are stopped before use.
            pass
        else:subprocess.run(cmds[0],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        for cmd in cmds[1:]:subprocess.run(cmd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        prefix=cmds[0][:3]
        for port in ('2222','1328'):
            rule=['INPUT','-p','tcp','--dport',port,'-j','OWNER_MAINT']
            probe=subprocess.run(prefix+['-C']+rule,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
            if probe.returncode:subprocess.run(prefix+['-I']+rule[:1]+['1']+rule[1:],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)

def ssh_configuration(ip):
    ipaddress.IPv4Address(ip)
    return '''Port 2222
AddressFamily inet
ListenAddress %s
HostKey /data/owner-maintenance/ssh/host_ed25519
PidFile /run/owner-maintenance/sshd.pid
AuthorizedKeysFile /data/owner-maintenance/ssh/authorized_keys
StrictModes yes
PermitRootLogin prohibit-password
PasswordAuthentication no
ChallengeResponseAuthentication no
AuthenticationMethods publickey
TrustedUserCAKeys none
AllowUsers root
AllowTcpForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
PermitUserEnvironment no
UseDNS no
LoginGraceTime 20
MaxAuthTries 3
MaxStartups 3:30:6
Subsystem sftp internal-sftp
LogLevel VERBOSE
'''%ip

def atomic(path,data,mode=0o600):
    temp=path+'.new-'+os.urandom(8).hex()
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        d=os.open(os.path.dirname(path),os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        try:os.unlink(temp)
        except FileNotFoundError:pass

def release():
    from package_format import unique_json,digest,canonical,PATHS
    p=unique_json(trusted(BASE+'/current.json',4096))
    if set(p)!={'version','manifest_sha256'} or not re.match(r'^[0-9]+\.[0-9]+\.[0-9]+-[a-z0-9-]{1,24}$',p['version']):raise ValueError('Invalid release pointer')
    directory=BASE+'/releases/'+p['version']
    raw=trusted(directory+'/manifest.json',32768)
    if digest(raw)!=p['manifest_sha256']:raise ValueError('Release manifest changed')
    m=unique_json(raw)
    if canonical(m)!=raw or m.get('version')!=p['version']:raise ValueError('Release manifest invalid')
    for name in sorted(n for n in PATHS if n.startswith('panel/')):
        if digest(trusted(directory+'/'+name))!=m['files'][name]['sha256']:raise ValueError('Panel file changed')
    return directory,p['version']

def stop_process(p):
    if p is None or p.poll() is not None:return
    p.terminate()
    try:p.wait(timeout=5)
    except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)

def stop_requested(pid,start):
    try:value=json.loads(trusted(RUN+'/stop-request.json',1024,True).decode('ascii'))
    except FileNotFoundError:return False
    if set(value)!={'pid','start'} or type(value['pid']) is not int or not isinstance(value['start'],str):
        raise ValueError('Malformed owner stop request')
    return value=={'pid':pid,'start':start}

class PanelRetry(object):
    """Bounded retries, independent of SSH. Presence never means health.

    A clock/certificate/readiness failure may clear without a release change.
    Every attempt still passes through release validation and socket_launcher.
    Diagnostic reasons are a fixed allowlist, never child stderr or exceptions.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.attempts = 0
        self.failures = 0
        self.next_attempt = 0.0
        self.started = None
        self.reason = None
        self.exit_code = None

    def due(self, now):
        return now >= self.next_attempt

    def begin(self, now):
        self.attempts = min(self.attempts + 1, 2147483647)
        self.started = now
        self.reason = None
        self.exit_code = None

    def failed(self, now, reason, exit_code=None):
        if reason not in ('RELEASE_VALIDATION', 'LAUNCH_FAILED', 'CHILD_EXITED'):
            raise ValueError('Unknown panel failure category')
        self.failures = min(self.failures + 1, 7)
        self.next_attempt = now + min(300.0, 5.0 * 2 ** (self.failures - 1))
        self.started = None
        self.reason = reason
        self.exit_code = exit_code if type(exit_code) is int and -255 <= exit_code <= 255 else None

    def running(self, now):
        if self.started is not None and now - self.started >= 60.0:
            self.failures = 0

    def status(self, now):
        return {'attempts': self.attempts, 'failure_category': self.reason,
                'exit_code': self.exit_code,
                'retry_in_seconds': max(0, int(self.next_attempt - now + .999)),
                'process_presence_is_not_health': True}

def supervise():
    normal_context();os.umask(0o077)
    if not os.path.exists(RUN):os.mkdir(RUN,0o700)
    st=os.lstat(RUN)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077:raise ValueError('Invalid runtime directory')
    lock=os.open(RUN+'/lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stop=[False]
    def ending(*_):stop[0]=True
    signal.signal(signal.SIGTERM,ending);signal.signal(signal.SIGINT,ending)
    with open('/proc/self/stat') as f:start=f.read().split()[21]
    atomic(RUN+'/supervisor.json',json.dumps({'pid':os.getpid(),'start':start}).encode())
    secondary=SecondaryLAN()
    ssh=None;panel=None;previous=None;last_release=None;failures=0;panel_retry=PanelRetry()
    try:
        while not stop[0]:
            try:
                normal_context()
                if stop_requested(os.getpid(),start):break
                if os.path.exists(BASE+'/disabled'):break
                pending=os.path.exists(BASE+'/pending.json')
                if pending and not os.path.exists(BASE+'/installed.json'):break
                c=configuration();ip=address(c['interface']);policy=(ip,c['interface'],c['client_network'])
                if policy!=previous:
                    stop_process(panel);panel=None;stop_process(ssh);ssh=None
                    panel_retry.reset()
                    firewall(c)
                    secondary.current=None
                    if ip:
                        trusted(BASE+'/ssh/authorized_keys',16384,True)
                        host=BASE+'/ssh/host_ed25519'
                        if not os.path.lexists(host):
                            subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-C','owner-service-host','-f',host],check=True,timeout=15,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                        trusted(host,16384,True)
                        atomic(RUN+'/sshd_config',ssh_configuration(ip).encode('ascii'))
                        subprocess.run(['/usr/sbin/sshd','-t','-f',RUN+'/sshd_config'],check=True,timeout=5,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    previous=policy
                if ip and (ssh is None or ssh.poll() is not None):
                    if ssh is not None:raise ValueError('Owner sshd exited unexpectedly')
                    ssh=subprocess.Popen(['/usr/sbin/sshd','-D','-e','-f',RUN+'/sshd_config'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                lan_config_error=False
                try:lan_config=lan_configuration(c)
                except (ValueError,OSError):
                    lan_config=None;lan_config_error=True
                if (ip or (lan_config and lan_config['http_enabled'])) and c['panel_enabled'] and not pending:
                    now=time.monotonic()
                    if panel is not None and panel.poll() is not None:
                        panel_retry.failed(now,'CHILD_EXITED',panel.poll())
                        stop_process(panel);panel=None
                    elif panel is not None:
                        panel_retry.running(now)
                    try:
                        # Read the trusted reload marker to notice an explicit
                        # enrollment/update even while a retry is delayed.
                        marker=hashlib.sha256(trusted(BASE+'/panel-reload.json',4096)).hexdigest()
                        pointer=hashlib.sha256(trusted(BASE+'/current.json',4096)).hexdigest()
                        identity=(pointer,marker)
                        if identity!=last_release:
                            stop_process(panel);panel=None;panel_retry.reset();last_release=identity
                        if panel is not None or panel_retry.due(now):
                            # Running releases are still checked on every pass.
                            path,version=release()
                        if panel is None and panel_retry.due(now):
                            panel_retry.begin(now)
                            try:
                                panel=subprocess.Popen([PYTHON,'-E','-B','-S',BASE+'/bootstrap/socket_launcher.py'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                            except (OSError,subprocess.SubprocessError):
                                panel_retry.failed(now,'LAUNCH_FAILED')
                    except Exception:
                        stop_process(panel);panel=None
                        if panel_retry.due(now):panel_retry.failed(now,'RELEASE_VALIDATION')
                else:stop_process(panel);panel=None;panel_retry.reset()
                try:
                    lan_status=secondary.poll(lan_config) if not pending else {'pending':True}
                    if lan_config_error:lan_status['configuration_invalid']=True
                except (ValueError,OSError):
                    secondary.close()
                    try:lan_firewall(None,None)
                    except (OSError,subprocess.SubprocessError):pass
                    lan_status={'failed_closed':True}
                atomic(RUN+'/status.json',json.dumps({'secondary_lan':lan_status,'ssh_process':ssh is not None and ssh.poll() is None,'panel_process':panel is not None and panel.poll() is None,'panel_start_attempts':panel_retry.attempts,'panel_retry':panel_retry.status(time.monotonic()),'pending_owner_transaction':pending,'process_presence_is_not_health':True,'failures':failures,'address':ip}).encode())
                failures=0
            except Exception:
                # No exception details/private input in diagnostics. Retry is bounded.
                failures+=1
                atomic(RUN+'/status.json',json.dumps({'state':'FAILED_CLOSED','failures':failures}).encode())
                stop_process(panel);panel=None
                if failures>=3:break
            for _ in range(20):
                if stop[0]:break
                time.sleep(.1)
    finally:
        secondary.close();stop_process(panel);stop_process(ssh);os.close(lock)

def process_identity(pid):
    # No signal is sent on this path; a PID reused between observations is inert.
    results=[]
    for name in ('stat','cmdline'):
        try:fd=os.open('/proc/%d/%s'%(pid,name),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        except (FileNotFoundError,ProcessLookupError):return None
        with os.fdopen(fd,'rb') as f:
            st=os.fstat(f.fileno());raw=f.read(4097)
            if st.st_uid!=0 or len(raw)>4096:raise ValueError('Untrusted supervisor process metadata')
            results.append(raw)
    # A comm field can contain whitespace/parentheses. Fields after its final
    # closing parenthesis start with state(field3); starttime(field22) is index19.
    tail=results[0].rpartition(b') ')[2].split()
    if len(tail)<20:raise ValueError('Malformed supervisor process stat')
    if tail[0] in (b'Z',b'X'):return None
    start=tail[19].decode('ascii')
    if not start.isdigit():raise ValueError('Malformed supervisor process start time')
    return {'start':start,'args':results[1].rstrip(b'\0').split(b'\0')}

def supervisor_lock_released():
    fd=os.open(RUN+'/lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077:
            raise ValueError('Untrusted supervisor lock')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        return True
    finally:os.close(fd)

def stop_supervisor(timeout=25.0):
    normal_context()
    try:p=json.loads(trusted(RUN+'/supervisor.json',1024,True).decode())
    except FileNotFoundError:return
    pid=p.get('pid');start=p.get('start')
    if type(pid) is not int or pid<=1 or not isinstance(start,str) or not start.isdigit():
        raise ValueError('Invalid supervisor identity')
    expected=[PYTHON.encode(),b'-E',b'-B',b'-S',(BASE+'/bootstrap/bootstrap.py').encode(),b'run']
    identity=process_identity(pid)
    if identity is None:return
    if identity['start']!=start or identity['args']!=expected:raise ValueError('Supervisor PID reused or unexpected command')
    request={'pid':pid,'start':start}
    atomic(RUN+'/stop-request.json',json.dumps(request,sort_keys=True).encode('ascii'))
    deadline=time.monotonic()+timeout
    while True:
        identity=process_identity(pid)
        if identity is not None and (identity['start']!=start or identity['args']!=expected):
            raise ValueError('Supervisor identity changed while stopping; no signal sent')
        # Wait for finally's lock release, after owned children were stopped.
        # A missing PID alone is not permission to race another owner supervisor.
        if supervisor_lock_released():return
        if time.monotonic()>=deadline:raise ValueError('Owner stop timeout; restart refused')
        time.sleep(.1)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['run','stop']);a=p.parse_args()
    if a.action=='run':supervise()
    else:stop_supervisor()
