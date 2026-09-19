#!/usr/bin/env python3
"""Inspect Formule frames OFFLINE. No live-device/network mode is implemented."""
import argparse
import hashlib
import json
import os
import stat
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'owner-ui'))
from formule_codec import FrameDecoder, ProtocolError, MAX_CHUNK, METHODS

MAX_INPUT = 128 * 1024 * 1024

def decode_file(path, demo=False):
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= MAX_INPUT:
            raise ProtocolError('regular bounded input required')
        decoder = FrameDecoder(provenance='DEMO' if demo else 'HISTORICAL')
        digest = hashlib.sha256()
        frames = []
        read_bytes = 0
        while True:
            data = os.read(fd, MAX_CHUNK)
            if not data:
                break
            read_bytes += len(data)
            if read_bytes > MAX_INPUT:
                raise ProtocolError('input grew outside policy')
            digest.update(data)
            frames.extend(decoder.feed(data))
        decoder.finish()
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ProtocolError('input changed during inspection')
        return {'schema': 1, 'source_sha256': digest.hexdigest(), 'source_bytes': read_bytes,
                'transport': 'Formule framing; carrier unknown from file alone',
                'live_device_contact': False, 'frames': frames}
    finally:
        os.close(fd)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command')
    d = sub.add_parser('decode', help='decode an existing copied binary stream')
    d.add_argument('--input', required=True)
    d.add_argument('--output', required=True, help='new redacted JSON report; never overwrite')
    d.add_argument('--demo', action='store_true', help='label authored fixture values DEMO')
    sub.add_parser('methods', help='show code-backed vocabulary, not live capabilities')
    args = p.parse_args(argv)
    if args.command == 'methods':
        print(json.dumps({'source':'Formule 2.5.6-2773 StringToProtocolMethod 0x7a5b80',
                          'methods':['PROTOCOL_METHOD_' + x for x in METHODS],
                          'live_requests_enabled':False}, indent=2))
        return 0
    if args.command != 'decode':
        p.print_help()
        return 2
    try:
        report = decode_file(args.input, args.demo)
        absolute=os.path.abspath(args.output)
        parts=absolute.strip('/').split('/')
        if any(part in ('original','.','..') for part in parts):
            raise ProtocolError('evidence output forbidden')
        parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
        try:
            for component in parts[:-1]:
                next_fd=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                os.close(parent);parent=next_fd
            fd=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        finally:os.close(parent)
        with os.fdopen(fd, 'w') as f:
            json.dump(report, f, sort_keys=True, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        print('Wrote redacted offline report: {0} frame(s).'.format(len(report['frames'])))
        return 0
    except (ProtocolError, OSError, ValueError):
        print('Inspection refused: malformed, changed, unsafe or existing input/output.', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
