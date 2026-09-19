#!/usr/bin/env python3
"""Bounded private host capture of consumable mirrors via an explicit pinned SSH alias.

Companion to record_print_session. No target writes or vendor method invocation.
Changed file bytes are content-addressed locally; original names stay private.
"""
import argparse
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from record_print_session import atomic, session_path, utc


def validate(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get('files'), list) or len(doc['files']) > 520:
        raise ValueError('Invalid snapshot')
    total = 0
    for f in doc['files']:
        data = base64.b64decode(f['data_b64'], validate=True)
        total += len(data)
        if total > 16 << 20 or len(data) != f['bytes'] or hashlib.sha256(data).hexdigest() != f['sha256']:
            raise ValueError('Snapshot integrity/bound')
    return doc


def run(base, config, alias, seconds):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', alias) or not 60 <= seconds <= 86400:
        raise ValueError('Explicit alias and bounded duration required')
    config = Path(config).resolve(strict=True)
    source = Path(__file__).with_name('print_state_snapshot.py').read_bytes()
    ast.parse(source.decode(), feature_version=(3, 5))
    root = base / 'consumable-state'
    root.mkdir(mode=0o700)
    (root / 'objects').mkdir(mode=0o700)
    (root / 'print_state_snapshot.accepted.py').write_bytes(source)
    (root / 'record_print_state.accepted.py').write_bytes(Path(__file__).read_bytes())
    start = time.monotonic()
    stop = False
    def halt(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    status = {'state': 'starting', 'pid': os.getpid(), 'snapshots': 0, 'unique_objects': 0,
              'stored_bytes': 0, 'failures': 0, 'started_utc': utc(), 'seconds': seconds,
              'source_sha256': hashlib.sha256(source).hexdigest()}
    cmd = ['ssh', '-F', str(config), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
           '-o', 'ConnectTimeout=8', alias,
           'env -i PATH=/usr/bin:/bin LC_ALL=C /usr/bin/python3 -E -B -S -']
    atomic(root / 'status.json', status)
    try:
        while not stop and not (base / 'STOP').exists() and time.monotonic()-start < seconds:
            with (root / 'ssh.stderr').open('ab') as err, (root / 'incoming.private').open('wb') as output:
                try:
                    p = subprocess.run(cmd, input=source, stdout=output, stderr=err, timeout=20)
                except subprocess.TimeoutExpired:
                    status['failures'] += 1
                    status['state'] = 'retrying_timeout'
                    atomic(root / 'status.json', status)
                    time.sleep(5)
                    continue
            if p.returncode:
                status['failures'] += 1
                status['state'] = 'blocked'
                status['reason'] = 'SSH or target invariant failed; inspect private stderr'
                break
            incoming = root / 'incoming.private'
            if incoming.stat().st_size > 24 << 20:
                raise ValueError('Snapshot envelope bound')
            doc = validate(json.loads(incoming.read_text()))
            for f in doc['files']:
                data = base64.b64decode(f.pop('data_b64'), validate=True)
                target = root / 'objects' / f['sha256']
                if not target.exists():
                    if status['stored_bytes'] + len(data) > 256 << 20:
                        raise ValueError('256-MiB state backup bound')
                    with target.open('xb') as obj:
                        obj.write(data); obj.flush(); os.fsync(obj.fileno())
                    status['stored_bytes'] += len(data)
                    status['unique_objects'] += 1
            doc['laptop_received_utc'] = utc()
            with (root / 'snapshots.private.jsonl').open('a') as f:
                f.write(json.dumps(doc, sort_keys=True) + '\n'); f.flush(); os.fsync(f.fileno())
            incoming.unlink()
            status.update(state='recording', snapshots=status['snapshots']+1,
                          last_received_utc=doc['laptop_received_utc'], last_monotonic=time.monotonic(),
                          last_files=len(doc['files']), gaps=len(doc['gaps']),
                          unstable_files=sum(not x['stable_metadata'] for x in doc['files']))
            atomic(root / 'status.json', status)
            for _ in range(10):
                if stop or (base / 'STOP').exists(): break
                time.sleep(1)
        if status['state'] != 'blocked': status['state'] = 'stopped'
    except Exception as exc:
        status.update(state='blocked', reason=type(exc).__name__)
        raise
    finally:
        status['ended_utc'] = utc()
        atomic(root / 'status.json', status)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', required=True); p.add_argument('--ssh-config', required=True)
    p.add_argument('--ssh-alias', required=True); p.add_argument('--seconds', type=int, default=43200)
    a = p.parse_args(); os.umask(0o077)
    run(session_path(a.session), a.ssh_config, a.ssh_alias, a.seconds)


if __name__ == '__main__':
    main()
