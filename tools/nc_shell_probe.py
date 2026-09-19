"""Exercise the delivered ARM nc command in a local namespace with an empty /dev.

The isolated /usr/bin contains only the generated ARM BusyBox and its applets.
QEMU and strace are bound separately for the test harness; no host shell/nc is
available in the namespace. Network traffic is restricted by the command to
localhost. No printer/Pi address is contacted and /init is never executed.
"""
import json
import os
from pathlib import Path
import re
import shlex
import signal
import shutil
import socket
import subprocess
import tempfile
import time

from rescue_common import ROOT, require, sha256


def probe(binary, evidence_dir, prepared_namespace=False):
    binary = Path(binary).resolve()
    evidence_dir = Path(evidence_dir).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for tool in (('qemu-arm','strace') if prepared_namespace else ('qemu-arm', 'bwrap', 'strace')):
        require(shutil.which(tool), f'{tool} is required for the no-PTY proof')
    if prepared_namespace:
        # The offline runner prepares one namespace rather than nesting user
        # namespaces, which this host's policy rejects. Refuse ordinary hosts.
        require(os.geteuid()==0 and not Path('/dev/ptmx').exists()
                and not Path('/dev/pts').exists()
                and Path('/bin/sh').is_symlink()
                and Path('/bin/sh').resolve()==Path('/bin/busybox').resolve()
                and Path('/bin/busybox').read_bytes()==binary.read_bytes(),
                'Prepared no-PTY ARM namespace missing')
        interfaces=[line.split(':')[0].strip() for line in Path('/proc/net/dev').read_text().splitlines()[2:]]
        require(interfaces==['lo'],'Prepared network namespace contains an external interface')
    original = (ROOT / 'rescue/rootfs/bin/form3-nc-listen').read_text().splitlines()[-1]
    args = shlex.split(original)
    require(args.pop(0) == 'exec', 'Unexpected nc service launcher')
    require(args == ['/bin/nc', '-ll', '-s', '10.0.0.77', '-p', '2324', '-e', '/bin/sh'], 'Listener command changed; review its proof')
    args[3] = '127.0.0.1'  # Only the bind address changes for offline testing.
    qemu = shutil.which('qemu-arm')
    applets = subprocess.check_output([qemu, str(binary), '--list'], text=True).split()
    request = ('echo FORM3-NC-SHELL-OK\nid\nuname -a\n'
               'echo FORM3-NC-STDERR-OK >&2\n'
               'if [ -t 0 ] || [ -t 1 ] || [ -t 2 ]; then echo BAD-TTY; else echo NO-TTY; fi\n'
               'if [ -S /proc/self/fd/0 ] && [ -S /proc/self/fd/1 ] && [ -S /proc/self/fd/2 ]; then echo SOCKET-FDS-012; fi\n'
               'if [ ! -e /dev/pts ] && [ ! -e /dev/ptmx ] && [ ! -e /dev/tty ]; then echo NO-PTY-DEVICES; fi\n'
               'read pid comm state ppid pgrp session tty rest < /proc/self/stat\necho CONTROLLING-TTY=$tty\n'
               'exit\n')
    with tempfile.TemporaryDirectory(prefix='form3-nc-proof-') as temp:
        stage = Path(temp) / 'bin'; stage.mkdir()
        shutil.copyfile(binary, stage / 'busybox'); (stage / 'busybox').chmod(0o755)
        for applet in applets:
            (stage / applet).symlink_to('busybox')
        command = ['bwrap', '--ro-bind', '/', '/', '--ro-bind', str(stage), '/usr/bin',
                   '--tmpfs', '/tmp', '--ro-bind', qemu, '/tmp/qemu-arm',
                   '--ro-bind', shutil.which('strace'), '/tmp/strace',
                   '--bind', str(evidence_dir), '/tmp/evidence', '--tmpfs', '/dev',
                   '--tmpfs', '/run', '--proc', '/proc', '--unshare-user', '--uid', '0',
                   '--gid', '0', '--unshare-pid', '--die-with-parent', '--',
                   '/tmp/strace', '-f', '-qq', '-s', '200', '-o', '/tmp/evidence/nc-shell.strace',
                   '/tmp/qemu-arm', *args]
        if prepared_namespace:
            command=[shutil.which('strace'),'-f','-qq','-s','200','-o',str(evidence_dir/'nc-shell.strace'),qemu,*args]
        env = dict(os.environ, PATH='/bin', HOME='/root', LC_ALL='C')
        # A prepared namespace has no enclosing per-listener bwrap to reap the
        # persistent server. Give the test wrapper its own cleanup group. This
        # happens before strace/ARM nc starts; the delivered service is unchanged.
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=prepared_namespace)
        connections = []
        try:
            for number in (1, 2):
                connection = None
                for _ in range(80):
                    if process.poll() is not None:
                        raise RuntimeError('nc test exited: ' + process.communicate()[1].decode())
                    try:
                        connection = socket.create_connection(('127.0.0.1', 2324), timeout=0.25)
                        break
                    except ConnectionRefusedError:
                        time.sleep(0.05)
                require(connection is not None, 'nc did not start listening on localhost:2324')
                with connection:
                    connection.settimeout(8)
                    connection.sendall(request.encode())
                    received = b''
                    while True:
                        chunk = connection.recv(65536)
                        if not chunk:
                            break
                        received += chunk
                output = received.decode()
                for expected in ('FORM3-NC-SHELL-OK', 'uid=0(root)', 'Linux ', 'armv7l',
                                 'FORM3-NC-STDERR-OK', 'NO-TTY', 'SOCKET-FDS-012',
                                 'NO-PTY-DEVICES', 'CONTROLLING-TTY=0'):
                    require(expected in output, f'Connection {number} missing {expected!r}: {output!r}')
                require('BAD-TTY' not in output, 'Shell acquired a terminal')
                require(process.poll() is None, 'Persistent listener exited after disconnect')
                connections.append({'connection': number, 'passed': True, 'request': request, 'output': output})
            require(process.poll() is None, 'Listener failed after the second connection')
        finally:
            if process.poll() is None:
                if prepared_namespace:os.killpg(process.pid,signal.SIGTERM)
                else:process.terminate()
            try:
                _, diagnostic = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if prepared_namespace:os.killpg(process.pid,signal.SIGKILL)
                else:process.kill()
                _, diagnostic = process.communicate(timeout=5)
            (evidence_dir / 'nc-shell-harness.log').write_bytes(diagnostic)
    trace = (evidence_dir / 'nc-shell.strace').read_text()
    require('execve("/bin/sh"' in trace and 'execve("/bin/id"' in trace and 'execve("/bin/uname"' in trace, 'Expected ARM shell/applet execs missing')
    require(not re.search(r'"/dev/(?:ptmx|pts[^" ]*|tty)[" ]', '\n'.join(line for line in trace.splitlines() if re.search(r'\bopen(?:at|at2)?\(', line))), 'Opened a PTY or controlling terminal')
    require('setsid(' not in trace and 'TIOCSCTTY' not in trace and 'TIOCSPTLCK' not in trace, 'PTY/session creation appeared in service trace')
    result = {'passed': True, 'busybox_sha256': sha256(binary.read_bytes()),
              'production_command': original.removeprefix('exec '), 'tested_command': shlex.join(args),
              'test_environment': 'Local user/PID namespace; no PTY devices; /bin and /usr/bin contain only generated ARM BusyBox applets; host nc and host sh unavailable.',
              'connections': connections, 'persistent_listener_survived_both': True,
              'pty_devices_absent': True, 'all_three_streams_are_sockets': True,
              'controlling_tty': 0, 'no_pty_open_or_session_creation_in_trace': True,
              'trace_sha256': sha256(trace.encode())}
    (evidence_dir / 'NC_SHELL_TEST.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--busybox', type=Path, default=ROOT / 'build/rescue-v2/busybox')
    parser.add_argument('--evidence-dir', type=Path, default=ROOT / 'build/nc-v2-probe')
    args = parser.parse_args()
    print(json.dumps(probe(args.busybox, args.evidence_dir), indent=2))
