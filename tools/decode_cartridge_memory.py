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

BINARY_SHA256 = 'a2a5e3c47cf1c0c2cc627bcfcba10c0c20a843420fa46ca39290be27e861a8c1'
FIELDS = ('DispenseCount', 'WriteCount', 'EstimatedVolumeDispensed_ml',
          'CumulativeDispenseTime_s')


def derive_key(secret, device_name):
    if not isinstance(secret, str) or not 1 <= len(secret) <= 1024:
        raise ValueError('Invalid private key input')
    if not isinstance(device_name, str) or not re.fullmatch(r'2d-[0-9a-f]{12}', device_name):
        raise ValueError('Expected the original recorded 1-Wire device name')
    try:
        value = (secret + device_name).encode('latin-1')
    except UnicodeError:
        raise ValueError('Unsupported key character encoding') from None
    return hashlib.sha256(value).hexdigest()[::4].encode('ascii')


def _block(key, value):
    """32-round XTEA with little-endian words, independently fixture checked."""
    if len(key) != 16 or len(value) != 8:
        raise ValueError('Invalid block dimensions')
    words = struct.unpack('<4I', key)
    a, b = struct.unpack('<2I', value)
    total, mask = 0, 0xffffffff
    for _ in range(32):
        a = (a + ((((b << 4) ^ (b >> 5)) + b) ^
                  ((total + words[total & 3]) & mask))) & mask
        total = (total + 0x9e3779b9) & mask
        b = (b + ((((a << 4) ^ (a >> 5)) + a) ^
                  ((total + words[(total >> 11) & 3]) & mask))) & mask
    return struct.pack('<2I', a, b)


def _decrypt(key, iv, ciphertext, skip):
    if len(iv) != 8 or len(ciphertext) > 33 or skip not in (0, 10):
        raise ValueError('Unsupported cartridge stream dimensions')
    stream, value = b'', iv
    while len(stream) < skip + len(ciphertext):
        value = _block(key, value)
        stream += value
    return bytes(a ^ b for a, b in zip(ciphertext, stream[skip:]))


def checksum(data):
    """Byte-wise two sums modulo 65536, unlike conventional mod-65535 Fletcher."""
    if not isinstance(data, bytes) or len(data) > 33:
        raise ValueError('Only bounded cartridge payloads are supported')
    a = b = 0
    for value in data:
        a = (a + value) & 0xffff
        b = (b + a) & 0xffff
    return a | (b << 16)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate record field')
        result[key] = value
    return result


def parse_record(data):
    if not isinstance(data, bytes) or len(data) > 65536:
        raise ValueError('Record exceeds bound')
    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=_unique,
                            parse_constant=lambda _: None)
    except (ValueError, UnicodeError):
        raise ValueError('Invalid private record JSON') from None
    if not isinstance(result, dict):
        raise ValueError('Expected record object')
    # Never enumerate/export unknown field names: they can themselves be secrets.
    for field in FIELDS:
        value = result.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e12:
            raise ValueError('Missing or invalid usage projection')
    return result


def decode(image, record, device_name):
    if not isinstance(image, bytes) or len(image) != 128 or image[:2] != b'C\x00':
        raise ValueError('Expected the reviewed 128-byte C/0 envelope')
    if image[64] != 1 or image[96] != 1:
        raise ValueError('Only RW version 1 is reviewed')
    key = derive_key(record.get('SecretKey'), device_name)
    iv = image[2:6] * 2
    ro = _decrypt(key, iv, image[10:43], 10)
    if checksum(ro) != int.from_bytes(image[6:10], 'little'):
        raise ValueError('RO checksum failed; no decoded result is trusted')
    copies = []
    for name, offset in (('A', 64), ('B', 96)):
        plain = _decrypt(key, iv, image[offset+1:offset+12], 0)
        if checksum(plain) != int.from_bytes(image[offset+12:offset+16], 'little'):
            raise ValueError('RW checksum failed; no decoded result is trusted')
        writes, volume, seconds = struct.unpack_from('<IHH', plain, 3)
        values = {'DispenseCount': int.from_bytes(plain[:3], 'big'),
                  'WriteCount': writes, 'EstimatedVolumeDispensed_ml': volume / 10,
                  'CumulativeDispenseTime_s': seconds}
        copies.append({'copy': name, 'offset': offset, 'checksum_valid': True,
                       'usage': values,
                       'record_matches': {f: values[f] == record.get(f) for f in FIELDS}})
    return {'schema_version': 1, 'reference_daemon_sha256': BINARY_SHA256,
            'ro_checksum_valid': True, 'rw_copies': copies,
            'rw_usage_equal': copies[0]['usage'] == copies[1]['usage'],
            'checksum_is_signature_or_mac': False,
            'physical_remaining_volume': 'UNKNOWN',
            'native_write_supported': False, 'restore_tested': False,
            'identity_or_key_material_exported': False,
            'scope': 'Copied main EEPROM only; no ROM/control/protection-page backup'}


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
