#!/usr/bin/env python3
"""Bounded Qt RCC v2 inventory and optional private extraction; never execute QML.

Implements the Qt 5.9.6 binary resource layout, not an archive repair facility.
Only explicitly selected regular members are extracted to a NEW private directory.
"""
import argparse,hashlib,json,os,re,struct,zlib
from pathlib import Path
from evidence_lib import open_evidence,safe_output,write_json

MAX_INPUT=64<<20
MAX_MEMBER=4<<20
MAX_TOTAL=64<<20

def private_destination(output):
    """Check the lexical ancestry before creating a new private output tree.

    This is a local single-user tool, not a defense against a concurrent hostile
    process renaming the owner's private ancestors during extraction.
    """
    dest=Path(os.path.abspath(output))
    if 'research-private' not in dest.parts:raise ValueError('Private extraction directory required')
    parts=dest.parts
    if any(parts[i:i+3] in (('hardware','emmc','original'),('hardware','qspi','original')) for i in range(len(parts)-2)):
        raise ValueError('Output inside original acquisition evidence refused')
    if any(p.is_symlink() for p in (dest,)+tuple(dest.parents)):
        raise ValueError('Symlink output ancestry refused')
    return safe_output(dest)

class Resource:
    def __init__(self,data):
        if not isinstance(data,bytes) or not 42<=len(data)<=MAX_INPUT or data[:4]!=b'qres':
            raise ValueError('Bounded RCC input required')
        version,self.tree,self.payload,self.names=struct.unpack_from('>4I',data,4)
        if version!=2 or not 20<=self.payload<self.names<self.tree<len(data) or (len(data)-self.tree)%22:
            raise ValueError('Unsupported RCC v2 section layout')
        self.data=data;self.count=(len(data)-self.tree)//22;self.rows=[];self.visited=set();self.paths=set()
        if not 1<=self.count<=4096:raise ValueError('RCC node limit')
        self.walk(0,'',0)
        if len(self.visited)!=self.count:raise ValueError('Unreachable RCC nodes')
    def name(self,offset):
        p=self.names+offset
        if not self.names<=p<=self.tree-6:raise ValueError('Name bounds')
        size=struct.unpack_from('>H',self.data,p)[0]
        if not 1<=size<=240 or p+6+size*2>self.tree:raise ValueError('Name length')
        try:name=self.data[p+6:p+6+size*2].decode('utf-16-be')
        except UnicodeError:raise ValueError('Invalid resource name encoding')
        # Names are one component, never paths. Reject traversal and controls.
        if name in ('.','..') or not re.fullmatch(r'[A-Za-z0-9_ .@()+-]+',name):
            raise ValueError('Unsupported resource name')
        return name
    def walk(self,index,parent,depth):
        if not 0<=index<self.count or index in self.visited or depth>32:raise ValueError('Cycle/depth/node bound')
        self.visited.add(index);p=self.tree+index*22;nameoff,flags=struct.unpack_from('>IH',self.data,p)
        if flags not in (0,1,2):raise ValueError('Unsupported node flags')
        name=self.name(nameoff) if index else ''
        path=parent+'/'+name if parent else name
        if len(path)>1024 or (index==0 and flags!=2):raise ValueError('Root/path bound')
        if flags==2:
            count,first=struct.unpack_from('>II',self.data,p+6)
            if count>self.count or first+count>self.count:raise ValueError('Child range')
            for child in range(first,first+count):self.walk(child,path,depth+1)
        else:
            country,language,offset=struct.unpack_from('>HHI',self.data,p+6)
            identity=(path,country,language)
            if identity in self.paths:raise ValueError('Duplicate resource member')
            self.paths.add(identity);q=self.payload+offset
            if not self.payload<=q<=self.names-4:raise ValueError('Payload offset')
            size=struct.unpack_from('>I',self.data,q)[0]
            if size>MAX_MEMBER or q+4+size>self.names:raise ValueError('Payload bounds')
            self.rows.append({'path':path,'country':country,'language':language,'compressed':flags==1,
                              'offset':q+4,'stored_bytes':size,'node':index})
    def contents(self,row):
        raw=self.data[row['offset']:row['offset']+row['stored_bytes']]
        if not row['compressed']:return raw
        if len(raw)<4:raise ValueError('Compressed header truncated')
        expected=struct.unpack_from('>I',raw)[0]
        if expected>MAX_MEMBER:raise ValueError('Expansion limit')
        dec=zlib.decompressobj()
        try:out=dec.decompress(raw[4:],expected+1)
        except zlib.error:raise ValueError('Invalid zlib stream')
        if len(out)!=expected or not dec.eof or dec.unconsumed_tail or dec.unused_data:
            raise ValueError('Truncated/trailing/oversized compressed stream')
        return out
    def inventory(self):
        rows=[];total=0
        for row in self.rows:
            data=self.contents(row);total+=len(data)
            if total>MAX_TOTAL:raise ValueError('Total expansion limit')
            rows.append(dict(row,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        return {'schema':1,'format':'Qt RCC v2','source_sha256':hashlib.sha256(self.data).hexdigest(),
                'source_bytes':len(self.data),'nodes':self.count,'files':sorted(rows,key=lambda x:(x['path'],x['country'],x['language'])),
                'total_member_bytes':total,'vendor_code_executed':False}

def extract_selected(resource,names,output):
    if not names or len(names)>256 or len(set(names))!=len(names):raise ValueError('Explicit member count required')
    selected=[];total=0
    for name in names:
        matches=[r for r in resource.rows if r['path']==name]
        if len(matches)!=1:raise ValueError('Missing or locale-ambiguous member')
        data=resource.contents(matches[0]);total+=len(data)
        if total>MAX_TOTAL:raise ValueError('Selected expansion limit')
        selected.append((name,data))
    dest=private_destination(output);dest.mkdir(mode=0o700)
    # Only validated member components enter this newly created private tree.
    for name,data in selected:
        p=dest/name;p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with p.open('xb') as f:f.write(data)
    return len(selected)

def replace_members(resource,replacements):
    """Append bounded replacement payloads; preserve all other names/contents.

    No members may be added or removed. Replacements are uncompressed to avoid
    depending on the host zlib version. The returned archive is revalidated.
    """
    if not isinstance(replacements,dict) or not 1<=len(replacements)<=16:
        raise ValueError('Replacement count')
    payload=bytearray(resource.data[resource.payload:resource.names])
    names=resource.data[resource.names:resource.tree]
    tree=bytearray(resource.data[resource.tree:])
    for name,value in sorted(replacements.items()):
        matches=[r for r in resource.rows if r['path']==name]
        if len(matches)!=1:raise ValueError('Missing or locale-ambiguous replacement')
        if not isinstance(value,bytes) or len(value)>MAX_MEMBER:raise ValueError('Replacement bound')
        row=matches[0];offset=len(payload)
        payload.extend(struct.pack('>I',len(value))+value)
        struct.pack_into('>H',tree,row['node']*22+4,0)
        struct.pack_into('>I',tree,row['node']*22+10,offset)
    data=b'qres'+struct.pack('>4I',2,20+len(payload)+len(names),20,20+len(payload))+payload+names+tree
    result=Resource(bytes(data));result.inventory()
    before={(r['path'],r['country'],r['language']):resource.contents(r) for r in resource.rows}
    after={(r['path'],r['country'],r['language']):result.contents(r) for r in result.rows}
    if before.keys()!=after.keys():raise ValueError('Member set changed')
    for key,old in before.items():
        if after[key]!=replacements.get(key[0],old):raise ValueError('Unexpected member change')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rcc');p.add_argument('--output',required=True)
    p.add_argument('--member',action='append',default=[]);p.add_argument('--extract-output');a=p.parse_args()
    if bool(a.member)!=bool(a.extract_output):p.error('--member and --extract-output must be supplied together')
    with open_evidence(a.rcc) as f:resource=Resource(f.read(MAX_INPUT+1))
    result=resource.inventory()
    if a.member:extract_selected(resource,a.member,a.extract_output)
    write_json(a.output,result)
    print(json.dumps({'passed':True,'resources':len(result['files']),'member_bytes':result['total_member_bytes'],'extracted':len(a.member),'vendor_code_executed':False}))
if __name__=='__main__':main()
