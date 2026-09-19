#!/usr/bin/env python3
"""Bind one reviewed HTTPS socket, drop privileges, execute one verified panel.

No arbitrary command, port, interface, path or D-Bus request is accepted.
Python 3.5; subprocess invocation occurs only after validating normal ARM context.
"""
import math,os,socket,ssl,stat,sys
from bootstrap import BASE,normal_context,configuration,address,release,lan_configuration

class CertificateStateError(ValueError):
    """Fixed exit codes expose no paths, certificate values or access secrets."""
    def __init__(self, code):
        self.exit_code = code
        ValueError.__init__(self, 'Primary TLS readiness check failed')


def validate_primary_certificate(cert, ip, now):
    """Exact address and validity window remain mandatory, even with WLAN HTTP."""
    if type(now) not in (float, int) or not math.isfinite(now):
        raise CertificateStateError(24)  # Invalid local clock value
    try:
        before = ssl.cert_time_to_seconds(cert['notBefore'])
        after = ssl.cert_time_to_seconds(cert['notAfter'])
        names = cert.get('subjectAltName', ())
        if not math.isfinite(before) or not math.isfinite(after) or before >= after:
            raise ValueError('Invalid interval')
        if not isinstance(names, (tuple, list)):
            raise ValueError('Invalid SAN structure')
    except (KeyError, TypeError, ValueError, OverflowError):
        raise CertificateStateError(25)  # Malformed certificate metadata
    if ('IP Address', ip) not in names:
        raise CertificateStateError(22)  # Current primary address not covered
    if now < before:
        raise CertificateStateError(20)  # Not yet valid; clock may be behind
    if now >= after:
        raise CertificateStateError(21)  # Expired; clock may be ahead


def drop_identity(uid,gid):
    if os.getuid()!=0 or not 64900<=uid<=65000 or not 64900<=gid<=65000:
        raise ValueError('Reviewed root-to-owner privilege drop required')
    os.setgroups([]);os.setgid(gid);os.setuid(uid);os.umask(0o077)
    if os.getuid()!=uid or os.geteuid()!=uid or os.getgid()!=gid or os.getgroups():raise ValueError('Privilege drop failed')

def bind_and_drop(ip,interface,uid,gid):
    if interface not in ('eth0','wlan0') or not 64900<=uid<=65000 or not 64900<=gid<=65000:
        raise ValueError('Unapproved privilege-drop parameters')
    if os.getuid()!=0:raise ValueError('Socket setup requires privileged launcher')
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    s.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,interface.encode()+b'\0')
    s.bind((ip,1328));s.listen(4);s.set_inheritable(True)
    drop_identity(uid,gid)
    return s

def launch():
    normal_context();c=configuration()
    if not c['panel_enabled']:raise ValueError('Panel enrollment not enabled')
    ip=address(c['interface'])
    secondary=lan_configuration(c)
    if not ip and not (secondary and secondary['http_enabled']):raise ValueError('No reviewed panel interface')
    path,_=release();identity=BASE+'/panel-identity';state=BASE+'/state'
    for directory in (identity,state):
        st=os.lstat(directory)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=c['uid'] or st.st_gid!=c['gid'] or st.st_mode&0o077:raise ValueError('Private unprivileged panel directory required')
    for name in ('cert.pem','key.pem','access-secret'):
        st=os.lstat(identity+'/'+name)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=c['uid'] or st.st_mode&0o077:raise ValueError('Invalid panel identity input')
    args=['/usr/bin/python3.5','-E','-B','-S',path+'/panel/server.py','--live-host','--state',state,
          '--secret-file',identity+'/access-secret']
    if ip:
        cert=ssl._ssl._test_decode_cert(identity+'/cert.pem')
        import time
        validate_primary_certificate(cert,ip,time.time())
        # Existing primary socket validation is unchanged when Ethernet is present.
        s=bind_and_drop(ip,c['interface'],c['uid'],c['gid']);fd=s.fileno()
        args+=['--tls-cert',identity+'/cert.pem','--tls-key',identity+'/key.pem',
               '--interface',c['interface'],'--allow-client-network',c['client_network'],'--listen-fd',str(fd)]
    else:
        drop_identity(c['uid'],c['gid'])
        args+=['--owner-lan-only']
    if secondary and secondary['http_enabled']:
        args+=['--owner-lan-http-interface',secondary['interface']]
    os.execve(args[0],args,{'PATH':'/usr/bin:/bin','HOME':state,'LANG':'C','PYTHONDONTWRITEBYTECODE':'1'})

if __name__=='__main__':
    try:launch()
    except CertificateStateError as exc:sys.exit(exc.exit_code)
