#!/usr/bin/env python3
"""Offline, read-only decoding of a copied C/0, RW/1 cartridge EEPROM.

Reference: TankCartridgeDaemon on 2.5.6-2773 (see CARTRIDGE_DECODING.md).
No keys are included. Supply privately retained, independently pinned inputs.
No device access, encoder/reset command, network access or firmware execution.
The stored checksum is an error check, NOT a manufacturer signature or MAC.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct

from evidence_lib import open_evidence


import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'owner-maintenance'))
from cartridge_codec import (BINARY_SHA256, FIELDS, derive_key, _block, _decrypt, checksum,
                             _unique, parse_record, decode)

def read_pinned(path, pin, limit):
    if not isinstance(pin, str) or not re.fullmatch('[a-f0-9]{64}', pin):
        raise ValueError('Independent SHA256 pin required')
    p = Path(path).absolute()
    if p.resolve() != p:
        raise ValueError('Symlink input paths are not supported')
    with open_evidence(p) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != pin:
        raise ValueError('Input size or SHA256 mismatch')
    return data


def write_report(path, report):
    p = Path(path).absolute()
    if p.resolve() != p or not p.parent.is_dir():
        raise ValueError('Use an existing private output directory without symlinks')
    if str(p).startswith(('/dev/', '/proc/', '/sys/')) or any(
            x in str(p) for x in ('/hardware/emmc/original/', '/hardware/qspi/original/')):
        raise ValueError('Output in evidence or device trees is forbidden')
    encoded = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode('utf-8')
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--sha256', required=True)
    for name in ('record', 'device-name'):
        parser.add_argument('--' + name + '-file', required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        image = read_pinned(args.image, args.sha256, 128)
        record = parse_record(read_pinned(args.record_file, args.record_sha256, 65536))
        name = read_pinned(args.device_name_file, args.device_name_sha256, 64).decode('ascii').strip()
        result = decode(image, record, name)
        result['input_sha256'] = {'image': args.sha256, 'record': args.record_sha256,
                                  'device_name_file': args.device_name_sha256}
        write_report(args.output, result)
    except (ValueError, OSError, UnicodeError, TypeError, OverflowError):
        parser.exit(2, 'Offline decoding refused: invalid input, checksum, pin or output. No device was accessed.\n')
    print(json.dumps({'checksums_valid': 3, 'native_write_supported': False,
                      'all_usage_fields_match_record': all(all(c['record_matches'].values()) for c in result['rw_copies'])}))


if __name__ == '__main__':
    main()
