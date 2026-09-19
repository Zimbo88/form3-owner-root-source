#!/usr/bin/env python3
"""Build a PRIVATE psplash image-only derivative from an explicitly supplied RGBA.

No install or hardware operation exists. The pinned executable's code and every
byte outside its original fixed RLE-image allocation remain identical. Oversized
images fail instead of relocating executable sections or changing draw dimensions.
"""
import argparse,hashlib,json
from evidence_lib import open_evidence
from inspect_qt_resources import private_destination
from inspect_qt_metadata import Elf32
from inspect_psplash_image import PIN,inspect,encode_rle,decode_rle

def build(binary,pixels,output):
    original,source=inspect(binary)
    if type(pixels) is not bytes or len(pixels)!=1280*720*4:raise ValueError('Exact 1280x720 RGBA required')
    encoded=encode_rle(pixels);capacity=source['rle_bytes_including_terminator']
    if len(encoded)>capacity:raise ValueError('Image exceeds fixed RLE capacity; simplify artwork, do not enlarge executable')
    elf=Elf32(binary);va=int(source['rle_pointer'],16)
    matches=[off+va-start for start,off,size in elf.segments if start<=va and va+capacity<=start+size]
    if len(matches)!=1:raise ValueError('Ambiguous image range')
    offset=matches[0];out=bytearray(binary);out[offset:offset+capacity]=encoded+b'\0'*(capacity-len(encoded))
    if out[:offset]!=binary[:offset] or out[offset+capacity:]!=binary[offset+capacity:]:raise ValueError('Unexpected executable change')
    if decode_rle(bytes(out[offset:offset+capacity]),1280,720)[0]!=pixels:raise ValueError('RLE readback mismatch')
    dest=private_destination(output);dest.mkdir(mode=0o700)
    (dest/'psplash-default-root-review').write_bytes(out)
    report={'schema':1,'kind':'OFFLINE_REVIEW_ONLY','source_path':'p6:/usr/bin/psplash-default','source_sha256':PIN,
        'candidate_sha256':hashlib.sha256(out).hexdigest(),'candidate_bytes':len(out),'rgba_sha256':hashlib.sha256(pixels).hexdigest(),
        'image_file_offset':offset,'image_capacity':capacity,'encoded_bytes':len(encoded),'outside_image_identical':True,
        'draw_code_changed':False,'all_pixels_roundtrip_verified':True,'native_execution':False,'installed':False,
        'source_rotation_degrees':270,'rotation_changed':False,
        'rollback':'Restore exact source executable using a separately reviewed transaction',
        'open_gates':['Real display rotation/cropping','Approved native executable hash','Atomic installation/rollback','Update replacement of p6 splash']}
    (dest/'manifest.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('elf');p.add_argument('--rgba',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    with open_evidence(a.elf) as f:binary=f.read((8<<20)+1)
    with open_evidence(a.rgba) as f:pixels=f.read(1280*720*4+1)
    print(json.dumps(build(binary,pixels,a.output),indent=2))
if __name__=='__main__':main()
