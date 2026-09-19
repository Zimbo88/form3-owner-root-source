#!/usr/bin/env python3
"""Python 3.5 read-only snapshot of named consumable mirrors and diagnostic DB files.

Raw output is PRIVATE: JSON keys and filenames can themselves contain secrets.
No device-memory access, SQLite connection, journal replay or forced vendor flush.
Concurrent main/WAL copies are NOT a transactionally consistent database backup.
"""
import base64
import hashlib
import json
import os
import stat
import time

ROOTS = ('/data/Cartridges', '/data/Tanks')
DATABASES = ('Durations_v1.sqlite', 'TankCartridgeDaemon_v1.sqlite')
MAX_TOTAL = 16 << 20


def file_snapshot(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                 getattr(os, 'O_NOATIME', 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('Not a bounded regular record')
        parts = []
        count = 0
        while count <= limit:
            part = os.read(fd, min(65536, limit + 1 - count))
            if not part:
                break
            parts.append(part)
            count += len(part)
        if count > limit:
            raise ValueError('Growing record exceeds bound')
        data = b''.join(parts)
        after = os.fstat(fd)
        stable = (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        return {'path': path, 'bytes': len(data), 'mtime': before.st_mtime,
                'inode': before.st_ino, 'stable_metadata': stable,
                'sha256': hashlib.sha256(data).hexdigest(),
                'data_b64': base64.b64encode(data).decode('ascii')}
    finally:
        os.close(fd)


def capture():
    result = {'device_epoch': time.time(), 'device_monotonic': time.monotonic(),
              'files': [], 'directories': [], 'gaps': [],
              'scope': 'Filesystem mirrors only; no complete chip backup',
              'sqlite_consistency': 'Concurrent byte copies; no transaction guarantee'}
    candidates = []
    for root in ROOTS:
        exists = os.path.isdir(root) and os.path.realpath(root) == root
        result['directories'].append({'path': root, 'exists': exists})
        if not exists:
            continue
        names = os.listdir(root)
        if len(names) > 256:
            raise ValueError('Consumable record count bound')
        for name in sorted(names):
            if name.endswith('.json'):
                candidates.append((root + '/' + name, 65536))
    root = '/data/logs'
    if os.path.realpath(root) == root:
        for name in DATABASES:
            for suffix in ('', '-wal', '-shm', '-journal'):
                path = root + '/' + name + suffix
                if os.path.lexists(path):
                    candidates.append((path, 4 << 20))
    total = 0
    for path, limit in candidates:
        try:
            item = file_snapshot(path, min(limit, MAX_TOTAL - total))
            total += item['bytes']
            result['files'].append(item)
        except (OSError, ValueError) as exc:
            result['gaps'].append({'path': path, 'reason': type(exc).__name__})
    return result


def main():
    if os.getuid() != 0 or os.uname().machine != 'armv7l' or os.uname().release != '4.9.65+':
        raise ValueError('Unexpected reference printer context')
    fd = os.open('/proc/cmdline', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        cmdline = os.read(fd, 4096).decode().split()
    finally:
        os.close(fd)
    if 'root=/dev/mmcblk0p6' not in cmdline or 'rdinit=/init' in cmdline:
        raise ValueError('Expected normal root slot')
    print(json.dumps(capture(), sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
