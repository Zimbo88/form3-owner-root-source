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
from capture_policy import bind_source, RetryBudget


def validate(doc, owner_version=None):
    if not isinstance(doc, dict) or not isinstance(doc.get('files'), list) or len(doc['files']) > 520:
        raise ValueError('Invalid snapshot')
    if owner_version is not None:
        ident = doc.get('identity', {})
        expected = {'uid':0, 'architecture':'armv7l', 'kernel':'4.9.65+',
                    'selected_slot':6, 'firmware':'2.5.6-2773', 'owner_version':owner_version}
        if (not isinstance(ident, dict) or any(ident.get(k) != v for k,v in expected.items())
                or not isinstance(ident.get('boot_id'), str)
                or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', ident['boot_id'])):
            raise ValueError('Snapshot target identity failed')
    total = 0
    for f in doc['files']:
        data = base64.b64decode(f['data_b64'], validate=True)
        total += len(data)
        if total > 16 << 20 or len(data) != f['bytes'] or hashlib.sha256(data).hexdigest() != f['sha256']:
            raise ValueError('Snapshot integrity/bound')
    return doc


def run(base, config, alias, seconds, owner_version='0.5.8-review'):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', alias) or not 60 <= seconds <= 86400:
        raise ValueError('Explicit alias and bounded duration required')
    config = Path(config).resolve(strict=True)
    source = bind_source(Path(__file__).with_name('print_state_snapshot.py').read_bytes(), owner_version)
    ast.parse(source.decode(), feature_version=(3, 5))
    root = base / 'consumable-state'
    root.mkdir(mode=0o700)
    (root / 'objects').mkdir(mode=0o700)
    (root / 'print_state_snapshot.accepted.py').write_bytes(source)
    (root / 'record_print_state.accepted.py').write_bytes(Path(__file__).read_bytes())
    (root / 'capture_policy.accepted.py').write_bytes(Path(__file__).with_name('capture_policy.py').read_bytes())
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
    retry_budget = RetryBudget()
    previous_boot = None
    cmd = ['ssh', '-F', str(config), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
           '-o', 'ConnectTimeout=8', alias,
           'env -i PATH=/usr/bin:/bin LC_ALL=C /usr/bin/python3 -E -B -S -']
    atomic(root / 'status.json', status)
    try:
        while not stop and not (base / 'STOP').exists() and time.monotonic()-start < seconds:
            timed_out = False
            error_path = root / 'ssh.stderr'
            error_start = error_path.stat().st_size if error_path.exists() else 0
            if error_start > 4 << 20:
                raise ValueError('SSH diagnostic budget')
            with (root / 'ssh.stderr').open('ab') as err, (root / 'incoming.private').open('wb') as output:
                try:
                    p = subprocess.run(cmd, input=source, stdout=output, stderr=err, timeout=20)
                except subprocess.TimeoutExpired:
                    timed_out = True
            if timed_out or p.returncode:
                status['failures'] += 1
                with error_path.open('rb') as f:
                    f.seek(error_start); error = f.read(65537)
                retry, reason, delay = retry_budget.failure(None if timed_out else p.returncode, error, timed_out)
                status.update(state='retrying' if retry else 'blocked', reason=reason,
                              consecutive_failures=retry_budget.consecutive,
                              coverage_gap_open=True)
                with (root/'coverage.private.jsonl').open('a') as f:
                    f.write(json.dumps({'host_utc':utc(),'event':'snapshot_failed','reason':reason,
                                        'retry':retry,'attempt':retry_budget.consecutive})+'\n')
                    f.flush();os.fsync(f.fileno())
                atomic(root / 'status.json', status)
                if not retry:
                    break
                for _ in range(delay):
                    if stop or (base/'STOP').exists() or time.monotonic()-start >= seconds: break
                    time.sleep(1)
                continue
            incoming = root / 'incoming.private'
            if incoming.stat().st_size > 24 << 20:
                raise ValueError('Snapshot envelope bound')
            doc = validate(json.loads(incoming.read_text()), owner_version)
            if status.get('coverage_gap_open'):
                with (root/'coverage.private.jsonl').open('a') as f:
                    f.write(json.dumps({'host_utc':utc(),'event':'validated_snapshot_resumed'})+'\n')
                    f.flush();os.fsync(f.fileno())
            retry_budget.success()
            boot = doc['identity']['boot_id']
            if boot != previous_boot:
                status['boot_contexts'] = status.get('boot_contexts', 0)+1
                previous_boot = boot
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
                          unstable_files=sum(not x['stable_metadata'] for x in doc['files']),
                          expected_owner_version=owner_version, consecutive_failures=0,
                          coverage_gap_open=False)
            status.pop('reason', None)
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
    p.add_argument('--owner-version', required=True, help='Exact reviewed installed owner version')
    a = p.parse_args(); os.umask(0o077)
    run(session_path(a.session), a.ssh_config, a.ssh_alias, a.seconds, a.owner_version)


if __name__ == '__main__':
    main()
