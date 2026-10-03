#!/usr/bin/env python3
"""Extract selected Go type/call metadata from one authenticated TKD binary.

Static ELF reads only. No firmware execution, key extraction, decryption or writes.
Addresses are ELF virtual addresses; old Ghidra exports use VA + 0x10000.
"""
import argparse
import hashlib
import json
import re
import struct
from evidence_lib import open_evidence,write_json
from go_function_index import parse
from inspect_cartridge_memory import BINARY_SHA256

FIELD_NAMES=frozenset(('ConsumableType','DataVersionRO','IVHalf','Fletcher32CRC',
                      'EncryptedSection','DataVersionRW','DispenseCount','WriteCount',
                      'EstimatedVolumeDispensed_100uL','CumulativeDispenseTime_s'))
TYPES={'ro_envelope':0x5fa5d8,'rw_envelope':0x5f0738,'rw_payload_pointer':0x5d60b8}
FUNCTIONS=(0x48e904,0x48f0c4,0x48f678,0x48fa40,0x48fbc0,
           0x499ae4,0x499bc4,0x4ebeb8,0x4edf8c,0x4ce7c4,0x1db5dc,0x1db784)


class Image:
    def __init__(self,data):
        if hashlib.sha256(data).hexdigest()!=BINARY_SHA256:raise ValueError('Unreviewed daemon binary')
        self.data=data
        if data[:6]!=b'\x7fELF\1\1':raise ValueError('Expected ELF32 little endian')
        off=struct.unpack_from('<I',data,28)[0];entry,count=struct.unpack_from('<HH',data,42)
        if entry!=32 or not 1<=count<=128 or off+entry*count>len(data):raise ValueError('Invalid segment table')
        self.segments=[struct.unpack_from('<8I',data,off+i*entry) for i in range(count)]
    def read(self,address,length):
        if not 0<=length<=65536:raise ValueError('Read budget')
        found=[(off,va,size) for typ,off,va,_,size,_,_,_ in self.segments
               if typ==1 and va<=address and address+length<=va+size]
        if len(found)!=1:raise ValueError('Ambiguous/unmapped static address')
        off,va,_=found[0];start=off+address-va;raw=self.data[start:start+length]
        if len(raw)!=length:raise ValueError('Truncated segment')
        return raw
    def field_name(self,pointer):
        raw=self.read(pointer,128);length=raw[1];value=raw[2:2+length]
        # This pinned Go metadata uses one-byte lengths for the selected short names.
        try:text=value.decode('ascii')
        except UnicodeError:raise ValueError('Unexpected metadata name')
        if text not in FIELD_NAMES:raise ValueError('Unreviewed field name')
        return text
    def datatype(self,pointer,depth=0):
        if depth>=8:raise ValueError('Type recursion budget')
        raw=self.read(pointer,48);size=struct.unpack_from('<I',raw)[0];kind=raw[15]&31
        if size>1024:raise ValueError('Type size budget')
        out={'kind':kind,'memory_bytes':size,'elf_va':hex(pointer)}
        if kind==22:
            out['points_to']=self.datatype(struct.unpack_from('<I',raw,32)[0],depth+1)
        elif kind==25:
            address,count=struct.unpack_from('<II',raw,36)
            if not 1<=count<=30:raise ValueError('Field count budget')
            fields=[];packed=0
            for index in range(count):
                np,tp,offset=struct.unpack('<III',self.read(address+index*12,12))
                sub=self.datatype(tp,depth+1)
                if 'binary_bytes' not in sub:raise ValueError('Pointer field not serializable')
                fields.append({'name':self.field_name(np),'memory_offset':offset>>1,
                               'binary_offset':packed,'type':sub});packed+=sub['binary_bytes']
            out.update(fields=fields,binary_bytes=packed)
        elif kind==17:
            elem,_,length=struct.unpack_from('<III',raw,32)
            if not 1<=length<=1024:raise ValueError('Array bound')
            sub=self.datatype(elem,depth+1)
            if 'binary_bytes' not in sub:raise ValueError('Unsupported array element')
            out.update(length=length,element=sub,binary_bytes=length*sub['binary_bytes'])
        elif kind in (8,9,10) and size in (1,2,4):out['binary_bytes']=size
        else:raise ValueError('Unreviewed scalar kind')
        return out


def inspect(data):
    image=Image(data);functions=parse(data)['functions']
    names={int(f['address'],16):f['name'] for f in functions}
    ends={int(a['address'],16):int(b['address'],16) for a,b in zip(functions,functions[1:])}
    rows=[]
    for address in FUNCTIONS:
        end=ends[address];raw=image.read(address,end-address);calls=[]
        if len(raw)%4:raise ValueError('Unaligned A32 function')
        for offset in range(0,len(raw),4):
            word=struct.unpack_from('<I',raw,offset)[0]
            if word&0xff000000!=0xeb000000:continue  # unconditional A32 BL only
            imm=word&0xffffff
            if imm&0x800000:imm-=0x1000000
            target=(address+offset+8+(imm<<2))&0xffffffff
            if target in names and (not names[target].startswith('runtime.') or names[target]=='runtime.memequal'):
                calls.append({'elf_va':hex(address+offset),'target_va':hex(target),'function':names[target]})
        rows.append({'function':names[address],'elf_va':hex(address),
                     'function_sha256':hashlib.sha256(raw).hexdigest(),'direct_calls':calls})
    return {'schema_version':1,'binary_sha256':BINARY_SHA256,'address_convention':'ELF VA; old Ghidra VA = ELF VA + 0x10000',
            'types':{name:image.datatype(address) for name,address in TYPES.items()},
            'functions':rows,'static_metadata_only':True,'complete_call_graph':False,
            'secret_material_exported':False,'hardware_write_supported':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary');p.add_argument('--output',required=True)
    args=p.parse_args()
    with open_evidence(args.binary) as stream:data=stream.read((12<<20)+1)
    if len(data)>12<<20:raise ValueError('Input size budget')
    result=inspect(data);write_json(args.output,result)
    print(json.dumps({'types':len(result['types']),'functions':len(result['functions']),
                      'static_metadata_only':True,'secret_material_exported':False}))


if __name__=='__main__':main()
