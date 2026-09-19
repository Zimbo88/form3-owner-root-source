#!/usr/bin/env python3
"""Compare three existing QSPI reads without opening a programmer or writing an image.

Different regular-file inodes are required. This cannot prove the reads were acquired
independently or certify wiring; the operator supplies that provenance separately.
"""
import argparse, hashlib, json, os, re, stat, struct, zlib
from pathlib import Path
from evidence_lib import open_evidence, write_json
from rescue_common import parse_env

SIZE=4194304

def boot_headers(raw):
    header=raw[0x40000:0x40040]
    magic,hcrc,created,length,load,entry,dcrc,os_id,arch,kind,compression,name=struct.unpack('>7I4B32s',header)
    if (magic,arch,kind,compression)!=(0x27051956,2,5,0) or not 0<length<0x7ffc0:
        raise ValueError('Invalid ARM U-Boot legacy header/length')
    if zlib.crc32(header[:4]+b'\0'*4+header[8:])!=hcrc:raise ValueError('U-Boot header CRC mismatch')
    payload=raw[0x40040:0x40040+length]
    if zlib.crc32(payload)!=dcrc or b'U-Boot' not in payload:raise ValueError('U-Boot payload CRC/content mismatch')
    spl_size,spl_load=struct.unpack_from('<II',raw,0x200)
    if raw[20:30]!=b'CHSETTINGS' or not 0<spl_size<0x3fdf8:raise ValueError('Unexpected TI SPL header')
    return {'uboot_header_crc32':'%08x'%hcrc,'uboot_payload_crc32':'%08x'%dcrc,
            'uboot_payload_bytes':length,'spl_payload_bytes':spl_size,
            'spl_contents_authenticated_by_header':False}


def inspect(paths, expected_sha256=None):
    if len(paths)!=3:raise ValueError('Exactly three independent read files are required')
    if expected_sha256 is not None and not re.fullmatch(r'[0-9a-f]{64}',expected_sha256):
        raise ValueError('Expected SHA256 must be 64 lowercase hexadecimal characters')
    seen=set();rows=[];first=None
    for path in paths:
        with open_evidence(path) as f:
            st=os.fstat(f.fileno());identity=(st.st_dev,st.st_ino)
            if identity in seen:raise ValueError('Repeated file/inode is not a separate read')
            seen.add(identity)
            if st.st_size!=SIZE:raise ValueError('QSPI read must be exactly 4194304 bytes')
            raw=f.read(SIZE+1)
            if len(raw)!=SIZE:raise ValueError('Read size changed')
        headers=boot_headers(raw)
        env,crc=parse_env(raw)
        if env.get('fl_bootpart') not in ('5','6'):raise ValueError('Unexpected boot partition')
        digest=hashlib.sha256(raw).hexdigest()
        if expected_sha256 and digest!=expected_sha256:raise ValueError('Authoritative SHA256 mismatch')
        if first is not None and raw!=first:raise ValueError('Three reads differ; preserve all and stop')
        first=raw
        # No filenames or environment identifiers are emitted: paths can contain identity.
        rows.append({'read_number':len(rows)+1,'bytes':len(raw),'sha256':digest,'environment_crc32':'%08x'%crc,
                     'boot_headers':headers,'factory_payload_area_all_ff':raw[0x100000:]==b'\xff'*0x300000})
    return {'schema':1,'three_byte_identical':True,'reads':rows,'expected_hash_checked':expected_sha256 is not None,
            'independent_acquisition_proven':False,'electrical_safety_proven':False,'hardware_access':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--read',action='append',required=True)
    p.add_argument('--expected-sha256');p.add_argument('--output',required=True);a=p.parse_args()
    report=inspect(a.read,a.expected_sha256);write_json(a.output,report);print(json.dumps(report,indent=2))
if __name__=='__main__':main()
