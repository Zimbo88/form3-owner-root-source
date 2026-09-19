#!/usr/bin/env python3
"""Create NEW local SSH profile/pin files from an independently reviewed host key.

No network, key generation, printer access or default SSH configuration changes.
The explicit expected fingerprint must come from the separately reviewed isolated
enrollment, not an untrusted response on an ordinary LAN.
"""
import argparse
import base64
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import stat


def regular(path, limit=None):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path,) + tuple(path.parents)):
        raise ValueError('Symlink path refused')
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise ValueError('Expected an owned regular file')
    if limit is not None and st.st_size > limit:
        raise ValueError('Input size bound')
    return path


def create(directory, host, key, candidate, expected, jump=None):
    base = Path(os.path.abspath(directory))
    if any(p.is_symlink() for p in (base,) + tuple(base.parents)):
        raise ValueError('Private directory symlink refused')
    st = base.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError('Existing owner-only directory required')
    address = ipaddress.IPv4Address(host)
    if not any(address in ipaddress.IPv4Network(n) for n in
               ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('Reviewed private IPv4 target required')
    key = regular(key)
    if key.stat().st_mode & 0o077:
        raise ValueError('Client private key permissions must be owner-only')
    rows = [r.split() for r in regular(candidate, 8192).read_text().splitlines()
            if r.strip() and not r.startswith('#')]
    if (len(rows) != 1 or len(rows[0]) != 3 or rows[0][0] != '[%s]:2222' % address
            or rows[0][1] != 'ssh-ed25519'):
        raise ValueError('Expected exactly one matching Ed25519 keyscan record')
    blob = base64.b64decode(rows[0][2], validate=True)
    if len(blob) != 51 or blob[:19] != b'\0\0\0\x0bssh-ed25519\0\0\0\x20':
        raise ValueError('Malformed Ed25519 public key')
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
    if expected != fingerprint:
        raise ValueError('Independent host fingerprint mismatch')
    if jump is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', jump):
        raise ValueError('Use an existing simple pinned SSH alias for the Pi')
    known, profile = base/'owner-known-hosts', base/'owner-ssh.conf'
    if any(os.path.lexists(str(p)) for p in (known, profile)):
        raise FileExistsError('Preserve existing profile and host pin')
    def quote(path):
        text = str(path)
        if any(c in text for c in '\r\n"\\%'):
            raise ValueError('Unsupported path character for SSH configuration')
        return '"' + text + '"'
    lines = ['Host form3-owner', '    HostName ' + str(address), '    User root',
             '    Port 2222', '    HostKeyAlias form3-owner',
             '    IdentityFile ' + quote(key), '    IdentitiesOnly yes',
             '    UserKnownHostsFile ' + quote(known), '    GlobalKnownHostsFile /dev/null',
             '    StrictHostKeyChecking yes', '    HostKeyAlgorithms ssh-ed25519',
             '    PreferredAuthentications publickey', '    PasswordAuthentication no',
             '    KbdInteractiveAuthentication no', '    ForwardAgent no', '    ForwardX11 no',
             '    ServerAliveInterval 15', '    ServerAliveCountMax 2', '    ConnectTimeout 8']
    if jump:
        lines.append('    ProxyCommand /usr/bin/ssh -o BatchMode=yes -o StrictHostKeyChecking=yes '
                     '-o ForwardAgent=no -W %h:%p ' + jump)
    for path, data in [(known, 'form3-owner ssh-ed25519 ' + rows[0][2] + '\n'),
                       (profile, '\n'.join(lines) + '\n')]:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(data)
    return fingerprint


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('directory', 'host', 'key', 'candidate', 'expected-host-fingerprint'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--jump-alias', help='Existing pinned Pi alias in the laptop default SSH config')
    a = p.parse_args()
    try:
        fingerprint = create(a.directory, a.host, a.key, a.candidate, a.expected_host_fingerprint, a.jump_alias)
    except (ValueError, OSError):
        p.exit(1, 'Profile creation refused: check private paths, matching host pin and new destinations.\n')
    print('Created strict local profile and pin. No connection made. Host ' + fingerprint)


if __name__ == '__main__':
    main()
