"""Authored legacy C/0 RW/1 cartridge codec; no device access.

Reference: docs/public/CARTRIDGE_DECODING.md. Checksums are not signatures.
Only the reviewed legacy Clear transaction currently enables this encoder.
"""
import hashlib
import json
import math
import re
import struct

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


def _invalid_constant(value):
    raise ValueError("Non-finite JSON constant")


def parse_record(data):
    if not isinstance(data, bytes) or len(data) > 65536:
        raise ValueError('Record exceeds bound')
    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=_unique,
                            parse_constant=_invalid_constant)
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



def candidate(image, record, device_name):
    before = decode(image, record, device_name)
    if not before['rw_usage_equal'] or not all(all(c['record_matches'].values()) for c in before['rw_copies']):
        raise ValueError('Baseline copies/mirror disagree')
    old = before['rw_copies'][0]['usage']
    if old['WriteCount'] >= 0xffffffff:
        raise ValueError('Counter overflow refused')
    revised = dict(record)
    revised.update(EstimatedVolumeDispensed_ml=0.0, DispenseCount=0,
                   CumulativeDispenseTime_s=0, WriteCount=old['WriteCount']+1)
    plain = bytes(3) + struct.pack('<IHH', revised['WriteCount'], 0, 0)
    encrypted = _decrypt(derive_key(record.get('SecretKey'), device_name), image[2:6]*2, plain, 0)
    rw = bytes([1]) + encrypted + struct.pack('<I', checksum(plain))
    output = bytearray(image)
    for offset in (64, 96):
        output[offset:offset+16] = rw
    output = bytes(output)
    allowed = set(range(64,80)) | set(range(96,112))
    differences = [i for i in range(128) if image[i] != output[i]]
    if any(i not in allowed for i in differences):
        raise ValueError('Unexpected region changed')
    after = decode(output, revised, device_name)
    if not all(all(c['record_matches'].values()) for c in after['rw_copies']):
        raise ValueError('Candidate decode mismatch')
    return output, rw, revised, after, differences
