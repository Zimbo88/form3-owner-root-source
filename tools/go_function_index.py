#!/usr/bin/env python3
"""Recover Go 1.16+ function names/addresses from ELF32 little-endian pclntab.

Static metadata only. No binary execution. Rejects unsupported layouts.
"""
import argparse
import hashlib
import json
import re
import struct
from evidence_lib import open_evidence,write_json,safe_output

def parse(data):
    if len(data)<52 or data[:6]!=b'\x7fELF\x01\x01':raise ValueError('Expected ELF32 little-endian')
    shoff=struct.unpack_from('<I',data,32)[0];size,count,names=struct.unpack_from('<HHH',data,46)
    if size!=40 or shoff+count*size>len(data) or names>=count:raise ValueError('Invalid ELF section table')
    sections=[struct.unpack_from('<10I',data,shoff+i*size) for i in range(count)]
    s=sections[names];strings=data[s[4]:s[4]+s[5]]
    tables=[]
    for s in sections:
        name=strings[s[0]:].split(b'\0',1)[0].decode(errors='replace')
        if 'gopclntab' in name:tables.append((s,name))
    if len(tables)==1:
        s,name=tables[0];base=s[4];blob=data[base:base+s[5]]
    elif not tables:
        # External linking can merge the named Go section into .data.rel.ro.
        hits=list(re.finditer(rb'[\xfa\xf0\xf1]\xff\xff\xff\x00\x00\x04\x04',data))
        if len(hits)!=1:raise ValueError('Unique Go pclntab header not found')
        base=hits[0].start()
        containing=[s for s in sections if s[1]==1 and s[4]<=base<s[4]+s[5]]
        if len(containing)!=1:raise ValueError('pclntab is not inside one PROGBITS section')
        s=containing[0];name=strings[s[0]:].split(b'\0',1)[0].decode();blob=data[base:s[4]+s[5]]
    else:raise ValueError('Ambiguous Go sections')
    if len(blob)<40 or blob[:4] not in (b'\xfa\xff\xff\xff',b'\xf0\xff\xff\xff',b'\xf1\xff\xff\xff') or blob[4:8]!=b'\0\0\x04\x04':
        raise ValueError('Only Go 1.16+ ARM32 pclntab is supported')
    # Go 1.17.3 src/debug/gosym/pclntab.go: ver116 uses absolute PCs,
    # seven uintptr header fields, and a 2*nfunc+1 uintptr functab.
    old=blob[0]==0xfa
    if old:
        nfunc,nfiles,funcnames,cu,filetab,pctab,pcln=struct.unpack_from('<7I',blob,8);text=0
    else:
        nfunc,nfiles,text,funcnames,cu,filetab,pctab,pcln=struct.unpack_from('<8I',blob,8)
    if not nfunc or nfunc>1000000 or pcln+nfunc*8+4>len(blob):raise ValueError('Function table out of bounds')
    if not (36<=funcnames<=cu<=filetab<=pctab<=pcln<len(blob)):raise ValueError('Invalid metadata offsets')
    result=[]
    for i in range(nfunc):
        entry,funcoff=struct.unpack_from('<II',blob,pcln+i*8)
        pos=pcln+funcoff
        if pos+8>len(blob):raise ValueError('Function record out of bounds')
        nameoff=struct.unpack_from('<i',blob,pos+4)[0];p=funcnames+nameoff
        if p<funcnames or p>=cu:raise ValueError('Function name out of bounds')
        end=blob.find(b'\0',p)
        if end<0 or end>=cu or end-p>4096:raise ValueError('Invalid function name')
        fn=blob[p:end].decode('utf-8')
        result.append(dict(address=f'{text+entry:08x}',name=fn,metadata_file_offset=base+pos))
    if any(int(a['address'],16)>int(b['address'],16) for a,b in zip(result,result[1:])):raise ValueError('Non-monotonic function addresses')
    return dict(section=name,magic=blob[:4].hex(),address_encoding='absolute' if old else 'text_relative',text_start=hex(text),functions=result)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('elf');p.add_argument('--output',required=True);p.add_argument('--tsv')
    a=p.parse_args()
    with open_evidence(a.elf) as f:data=f.read()
    r=parse(data);r['sha256']=hashlib.sha256(data).hexdigest();r['schema_version']=1;write_json(a.output,r)
    if a.tsv:
        with safe_output(a.tsv).open('x') as out:
            for row in r['functions']:out.write(row['address']+'\t'+row['name']+'\n')
    print(json.dumps(dict(functions=len(r['functions']),section=r['section'],text_start=r['text_start'])))

if __name__=='__main__':main()
