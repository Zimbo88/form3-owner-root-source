#!/usr/bin/env python3
"""Decode the pinned acquired psplash logo into PRIVATE output, without execution.

The ARM main call at 0x10cd0 supplies width=1280, height=720, RGBA4,
rowstride=5120 and RLE pointer=0x130bc to the drawing routine at 0x11e78.
No framebuffer, boot partition or firmware image is written.
"""
import argparse,hashlib,json,struct
from evidence_lib import open_evidence
from inspect_qt_metadata import Elf32
from inspect_qt_resources import private_destination
PIN='2d51b6ea8ea27612fb5ae6a830a702891c37944f42492ba6ebaaeed319aaac2f'

def decode_rle(data,width,height,channels=4):
    if not isinstance(data,bytes) or len(data)>8<<20:raise ValueError('RLE source bound')
    if any(type(v) is not int for v in (width,height,channels)) or not 1<=width<=2048 or not 1<=height<=2048 or channels not in(3,4):raise ValueError('Image dimensions')
    expected=width*height*channels;out=bytearray();pos=0
    while len(out)<expected:
        if pos>=len(data):raise ValueError('Truncated RLE')
        control=data[pos];pos+=1;count=control&127
        if not count:raise ValueError('Early RLE terminator')
        n=channels if control&128 else count*channels
        if pos+n>len(data) or len(out)+count*channels>expected:raise ValueError('RLE range overflow')
        chunk=data[pos:pos+n];pos+=n
        out.extend(chunk*count if control&128 else chunk)
    if pos>=len(data) or data[pos]!=0:raise ValueError('Missing RLE terminator')
    return bytes(out),pos+1

def encode_rle(pixels,channels=4):
    if not isinstance(pixels,bytes) or channels not in(3,4) or not pixels or len(pixels)%channels or len(pixels)>16<<20:raise ValueError('Pixel input bound')
    # Deterministic GdkPixbuf RLE: repeat runs, with bounded literal spans.
    out=bytearray();i=0
    def repeated(pos):
        first=pixels[pos:pos+channels];count=1
        while count<127 and pixels[pos+count*channels:pos+(count+1)*channels]==first:count+=1
        return count
    while i<len(pixels):
        count=repeated(i)
        if count>=2:
            out.append(128+count);out.extend(pixels[i:i+channels]);i+=count*channels
        else:
            first=i;i+=channels
            while i<len(pixels) and (i-first)//channels<127 and repeated(i)<2:i+=channels
            out.append((i-first)//channels);out.extend(pixels[first:i])
        if len(out)>=8<<20:raise ValueError('Encoded image bound')
    return bytes(out)+b'\0'

def inspect(data):
    if hashlib.sha256(data).hexdigest()!=PIN:raise ValueError('Unsupported psplash image')
    e=Elf32(data);base=0x130bc
    raw=b''.join(e.read(base+i,min(8192,48739-i)) for i in range(0,48739,8192))
    pixels,used=decode_rle(raw,1280,720)
    return pixels,{'schema':1,'artifact':'p6:/usr/bin/psplash-default','artifact_sha256':PIN,
        'address_convention':'ELF link VA','draw_call':'0x10cd0','draw_function':'0x11e78','rle_pointer':'0x130bc',
        'width':1280,'height':720,'channels':4,'rowstride':5120,'rle_bytes_including_terminator':used,
        'rgba_sha256':hashlib.sha256(pixels).hexdigest(),'native_execution':False,'installed':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('elf');p.add_argument('--output',required=True);a=p.parse_args()
    with open_evidence(a.elf) as f:pixels,result=inspect(f.read((8<<20)+1))
    dest=private_destination(a.output);dest.mkdir(mode=0o700)
    (dest/'logo.rgba').write_bytes(pixels)
    # PAM preserves decoded RGBA exactly; no dependency on an image editor.
    header=b'P7\nWIDTH 1280\nHEIGHT 720\nDEPTH 4\nMAXVAL 255\nTUPLTYPE RGB_ALPHA\nENDHDR\n'
    (dest/'logo.pam').write_bytes(header+pixels)
    (dest/'manifest.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
