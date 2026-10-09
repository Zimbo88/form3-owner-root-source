"""C/0 legacy cartridge material assignment primitives.

Not a resin compatibility promise. No device access on import.
The caller must independently validate target catalog eligibility.
Do not use the usage-reset encoder for RO material changes. A caller must pin
the target, verify page protection, exclude the native writer, and retain a
durable rollback copy before calling commit_material.
"""
import struct

from cartridge_codec import _decrypt, checksum, decode, derive_key
import re


def material(image, record, name):
    decode(image, record, name)
    plain = _decrypt(derive_key(record.get('SecretKey'), name),
                     image[2:6] * 2, image[10:43], 10)
    return plain[21:29].decode('ascii')


def candidate(image, record, name, target_code="FLGPCL04"):
    baseline = decode(image, record, name)
    source_code=record.get('ResinID')
    if not isinstance(source_code,str) or not re.fullmatch(r'FL[A-Z0-9]{6}',source_code) or record.get('OriginalVolume_mL') != 1000:
        raise ValueError('Expected a legacy 1000 mL material record')
    if not isinstance(target_code,str) or not re.fullmatch(r'FL[A-Z0-9]{6}',target_code) or target_code==source_code:
        raise ValueError('Expected a distinct valid material code')
    if not baseline['rw_usage_equal'] or not all(
            all(copy['record_matches'].values()) for copy in baseline['rw_copies']):
        raise ValueError('Usage copies or mirror disagree')
    key, iv = derive_key(record.get('SecretKey'), name), image[2:6] * 2
    plain = _decrypt(key, iv, image[10:43], 10)
    if plain[21:29] != source_code.encode('ascii'):
        raise ValueError('RO material does not match the source mirror')
    changed_plain = plain[:21] + target_code.encode('ascii') + plain[29:]
    revised = dict(record)
    revised['ResinID'] = target_code
    result = bytearray(image)
    result[6:10] = struct.pack('<I', checksum(changed_plain))
    result[10:43] = _decrypt(key, iv, changed_plain, 10)
    result = bytes(result)
    allowed = set(range(6,10)) | set(range(31,39))
    changes = [i for i in range(128) if result[i] != image[i]]
    if not changes or any(i not in allowed for i in changes):
        raise ValueError('Material candidate changed an unexpected byte')
    decoded = decode(result, revised, name)
    if decoded != baseline or material(result, revised, name) != target_code:
        raise ValueError('Candidate verification failed')
    return result, revised, changes


def commit_material(io, before, target, original_file, target_file, event):
    """Caller supplies exclusive, pinned device adapter; two bounded writes.

    Unlike the duplicated usage records, RO has no redundant copy. While its
    payload and checksum are being changed it is temporarily inconsistent.
    The native daemon must remain stopped throughout commit/readback/rollback.
    Sysfs handles the chip's 8-byte row protocol; unchanged row bytes are kept.
    """
    if len(before) != 128 or len(target) != 128:
        raise ValueError('Expected exact image lengths')
    if any(before[i] != target[i] for i in range(128) if i not in (set(range(6,10)) | set(range(31,39)))):
        raise ValueError('Target changes bytes outside the reviewed material field')
    if before[31:39] == target[31:39]:
        raise ValueError('Expected a material change')
    attempted = []
    file_attempted = False
    try:
        io.guard()
        if io.read_image() != before or io.read_mirror() != original_file:
            raise ValueError('Baseline changed before material commit')
        file_attempted = True
        io.write_mirror(target_file)
        if io.read_mirror() != target_file:
            raise ValueError('Material mirror readback mismatch')
        event('mirror_write', 'PASS')
        expected = bytearray(before)
        for offset, length in ((24, 16), (0, 16)):
            io.guard()
            attempted.append((offset, length))
            io.write_material_rows(offset, target[offset:offset+length])
            expected[offset:offset+length] = target[offset:offset+length]
            if io.read_image() != bytes(expected):
                raise ValueError('Material row readback mismatch')
            event('row_{0}_readback'.format(offset), 'PASS')
        if io.read_image() != target or io.read_mirror() != target_file:
            raise ValueError('Material commit final comparison failed')
        event('full_target', 'PASS')
    except Exception:
        io.exclusion()
        for offset, length in reversed(attempted):
            io.write_material_rows(offset, before[offset:offset+length])
            if io.read_image()[offset:offset+length] != before[offset:offset+length]:
                event('rollback', 'FAIL')
                raise ValueError('Material rollback row mismatch')
        if file_attempted:
            io.write_mirror(original_file)
        if io.read_image() != before or io.read_mirror() != original_file:
            event('rollback', 'FAIL')
            raise ValueError('Material rollback full comparison failed')
        event('rollback', 'PASS')
        raise
