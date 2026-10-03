#!/usr/bin/env python3
"""Read-only envelope inspection for a copied, hash-pinned 128-byte cartridge image.

Reference: TankCartridgeDaemon a2a5e3c... on firmware 2.5.6-2773. This does not
identify a connected chip, decrypt, validate its Fletcher field, encode a reset,
write a device or establish restoration/safe-filling readiness. No secret input.
"""
import argparse
import hashlib
import json
import math
import re
import struct
from evidence_lib import open_evidence, write_json

BINARY_SHA256='a2a5e3c47cf1c0c2cc627bcfcba10c0c20a843420fa46ca39290be27e861a8c1'
USAGE_FIELDS=('EstimatedVolumeDispensed_ml','CumulativeDispenseTime_s','DispenseCount')


def inspect_image(data, expected_sha256):
    if not isinstance(expected_sha256,str) or not re.fullmatch('[a-f0-9]{64}',expected_sha256):
        raise ValueError('Independent SHA256 pin required')
    if len(data)!=128 or hashlib.sha256(data).hexdigest()!=expected_sha256:
        raise ValueError('Image size/hash mismatch')
    if data[:2]!=b'C\x00':
        raise ValueError('Only observed cartridge type C / RO version 0 is supported')
    copies=[]
    for name,offset in (('A',64),('B',96)):
        raw=data[offset:offset+16]
        copies.append({'copy':name,'offset':offset,'bytes':16,'sha256':hashlib.sha256(raw).hexdigest(),
                       'data_version_rw':raw[0],'reviewed_version':raw[0]==1,
                       'checksum_verified':False,'decrypted':False})
    return {'schema_version':1,'image_sha256':expected_sha256,'image_bytes':128,
            'reference_daemon_sha256':BINARY_SHA256,'ro_bytes':43,'rw_copies':copies,
            'rw_copies_equal':data[64:80]==data[96:112],
            'identity_or_key_material_exported':False,'write_supported':False,
            'restore_tested':False,'physically_full_proven':False,
            'note':'Equal ciphertext is not authenticated contents, a full cartridge, or safe rollback.'}


def decode_decrypted_rw(data):
    """Projected 11-byte plaintext STRUCTURE only; caller must establish provenance.

    No ciphertext/key acceptance or checksum claim. The three-byte count is exposed
    as bytes because the field's packed counter semantics need a separate check.
    """
    if not isinstance(data,bytes) or len(data)!=11:
        raise ValueError('Exactly 11 independently obtained plaintext bytes required')
    writes,volume,time=struct.unpack_from('<IHH',data,3)
    return {'packed_dispense_counter_bytes':list(data[:3]),'WriteCount':writes,
            'EstimatedVolumeDispensed_100uL':volume,'EstimatedVolumeDispensed_ml':volume/10,
            'CumulativeDispenseTime_s':time,'checksum_verified':False,
            'provenance_verified':False,'write_supported':False}


def monotonic_usage_model(a,b):
    """Model the three previously traced maxima; NOT the full native Merge method.

    Excludes write-count/identity/format-version/transaction behavior deliberately.
    Only selected numeric fields are read; secret values and unknown map keys are
    never projected into output. No model outcome authorizes native writes.
    """
    if not isinstance(a,dict) or not isinstance(b,dict):raise ValueError('Two projections required')
    for source in (a,b):
        for key in USAGE_FIELDS:
            v=source.get(key)
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1e12:
                raise ValueError('Missing/invalid usage field')
    return {'projected_usage':{key:max(a[key],b[key]) for key in USAGE_FIELDS},
            'full_native_merge_implemented':False,'native_write_authorized':False,
            'identity_change_supported':False,'write_count_policy':'UNKNOWN'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image');p.add_argument('--sha256',required=True);p.add_argument('--output',required=True)
    args=p.parse_args()
    with open_evidence(args.image) as stream:data=stream.read(129)
    result=inspect_image(data,args.sha256);write_json(args.output,result)
    print(json.dumps({'image_bytes':128,'rw_copies_equal':result['rw_copies_equal'],
                      'checksum_verified':False,'write_supported':False}))


if __name__=='__main__':main()
