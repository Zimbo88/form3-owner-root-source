#!/usr/bin/env python3
"""Recover selected embedded Qt tables from pinned Palantir without loading it.

Only a short constant setup sequence is modeled; no ARM instruction is executed.
The large embedded font bundle is explicitly excluded from the 4-MiB member scope.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from evidence_lib import open_evidence,safe_output,write_json
from inspect_qt_metadata import Elf32
from inspect_qt_resources import Resource,extract_selected,private_destination,MAX_MEMBER,MAX_TOTAL

PIN='b99e5a789589a6811f0a6cd7848b44f8a6571ae73b77f6953112cd53d96021bc'
SITES=[(0xd81b8,0xd81d4),(0x143a38,0x143a58),(0x143ad0,0x143af0),
       (0x143b68,0x143b88),(0x143c00,0x143c20),(0x143c98,0x143cb8),
       (0x1d4f5c,0x1d4f7c),(0x1d4ff4,0x1d5014),(0x1d508c,0x1d50ac),
       (0x1d5124,0x1d5144),(0x1d51bc,0x1d51dc),(0x1d5254,0x1d5274),
       (0x1d52ec,0x1d530c),(0x1d5384,0x1d53a0),(0x1d540c,0x1d542c),
       (0x1d54a4,0x1d54c4),(0x7747bc,0x7747dc)]

def setup_arguments(elf,start,call):
    import capstone as cs
    from capstone import arm as a
    if not 0<call-start<=128 or start%4 or call%4:raise ValueError('Setup range')
    engine=cs.Cs(cs.CS_ARCH_ARM,cs.CS_MODE_ARM);engine.detail=True
    regs={a.ARM_REG_SP:0x80000000};instructions=list(engine.disasm(elf.read(start,call-start+4),start))
    if len(instructions)!=(call-start)//4+1:raise ValueError('Truncated instruction setup')
    for ins in instructions:
        if ins.cc!=a.ARM_CC_AL or ins.update_flags:raise ValueError('Unsupported conditional setup')
        o=ins.operands
        def value(op):
            if op.type==a.ARM_OP_IMM:return op.imm&0xffffffff
            if op.type!=a.ARM_OP_REG or op.shift.type:raise ValueError('Unsupported setup operand')
            if op.reg==a.ARM_REG_PC:return ins.address+8
            if op.reg not in regs:raise ValueError('Unknown register in setup')
            return regs[op.reg]
        if ins.id==a.ARM_INS_PUSH:regs[a.ARM_REG_SP]-=4*len(o)
        elif ins.id==a.ARM_INS_STR:
            if o[1].mem.base!=a.ARM_REG_SP or o[1].mem.index:raise ValueError('Non-stack write refused')
            if ins.writeback:regs[a.ARM_REG_SP]+=o[1].mem.disp
        elif ins.id==a.ARM_INS_MOV:regs[o[0].reg]=value(o[1])
        elif ins.id==a.ARM_INS_LDR:
            m=o[1].mem
            if m.index or ins.writeback:raise ValueError('Unsupported indexed setup load')
            base=ins.address+8 if m.base==a.ARM_REG_PC else regs.get(m.base)
            if base is None:raise ValueError('Unknown setup load base')
            regs[o[0].reg]=struct.unpack('<I',elf.read(base+m.disp,4))[0]
        elif ins.id==a.ARM_INS_ADD:regs[o[0].reg]=(value(o[1])+value(o[2]))&0xffffffff
        elif ins.id==a.ARM_INS_BL:
            if ins.address!=call or value(o[0])!=0x5acd4:raise ValueError('Unexpected setup helper')
        else:raise ValueError('Unsupported setup instruction')
    if instructions[-1].id!=a.ARM_INS_BL:raise ValueError('Missing registration call')
    result=[regs.get(x) for x in (a.ARM_REG_R0,a.ARM_REG_R1,a.ARM_REG_R2,a.ARM_REG_R3)]
    if any(x is None for x in result) or result[0]!=2:raise ValueError('Unsupported resource arguments')
    return {'version':2,'tree':result[1],'names':result[2],'data':result[3]}

def reconstruct(elf,pointers):
    seen=set();sizes={'names':0,'data':0}
    def walk(index,depth):
        if not 0<=index<4096 or index in seen or depth>32:raise ValueError('Embedded tree cycle/bound')
        seen.add(index);node=elf.read(pointers['tree']+22*index,22);no,flags=struct.unpack_from('>IH',node)
        length=struct.unpack('>H',elf.read(pointers['names']+no,2))[0]
        if length>240 or no+6+length*2>1<<20:raise ValueError('Embedded name bound')
        sizes['names']=max(sizes['names'],no+6+length*2)
        if flags==2:
            count,first=struct.unpack_from('>II',node,6)
            if first+count>4096:raise ValueError('Embedded child bound')
            for child in range(first,first+count):walk(child,depth+1)
        else:
            if flags not in(0,1):raise ValueError('Unsupported embedded flags')
            offset=struct.unpack_from('>I',node,10)[0]
            if offset>MAX_TOTAL:raise ValueError('Embedded payload offset')
            size=struct.unpack('>I',elf.read(pointers['data']+offset,4))[0]
            if size>MAX_MEMBER or offset+4+size>MAX_TOTAL:raise ValueError('Embedded member expansion scope')
            sizes['data']=max(sizes['data'],offset+4+size)
    walk(0,0)
    if len(seen)!=max(seen)+1:raise ValueError('Unreachable embedded tree nodes')
    def block(va,size):return b''.join(elf.read(va+p,min(65536,size-p)) for p in range(0,size,65536))
    payload=block(pointers['data'],sizes['data']);names=block(pointers['names'],sizes['names']);tree=block(pointers['tree'],len(seen)*22)
    data=b'qres'+struct.pack('>4I',2,20+len(payload)+len(names),20,20+len(payload))+payload+names+tree
    return Resource(data)

def inspect(data,private_output=None):
    if hashlib.sha256(data).hexdigest()!=PIN:raise ValueError('Pinned acquired Palantir required')
    elf=Elf32(data);dest=None
    if private_output:
        dest=private_destination(private_output);dest.mkdir(mode=0o700)
    rows=[]
    for start,call in SITES:
        pointers=setup_arguments(elf,start,call);item={'initializer_elf_va':hex(start),'call_elf_va':hex(call),'pointers':{k:hex(v) if k!='version' else v for k,v in pointers.items()}}
        if start==0x1d4f5c:
            item.update({'status':'EXCLUDED_LARGE_FONT_BUNDLE','reason':'Contains an 18-MiB font, outside selected member size scope'})
        elif start==0x7747bc:
            item.update({'status':'EXCLUDED_AMBIGUOUS_BUNDLE','reason':'Duplicate resource identity; extraction intentionally refused'})
        else:
            resource=reconstruct(elf,pointers);inv=resource.inventory();item.update({'status':'INSPECTED','inventory':inv})
            if dest:
                tag=format(start,'x');(dest/(tag+'.rcc')).write_bytes(resource.data)
                names=[x['path'] for x in inv['files'] if x['path'].endswith(('.qml','.js','qmldir'))]
                if names:extract_selected(resource,names,dest/tag)
        rows.append(item)
    return {'schema':1,'artifact':'p6:/usr/bin/Palantir','artifact_sha256':PIN,'address_convention':'ELF link VA','native_execution':False,'rows':rows}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('elf');p.add_argument('--output',required=True);p.add_argument('--private-output');a=p.parse_args()
    with open_evidence(a.elf) as f:data=f.read((64<<20)+1)
    result=inspect(data,a.private_output);write_json(a.output,result)
    print(json.dumps({'passed':True,'inspected_bundles':sum(x['status']=='INSPECTED' for x in result['rows']),'excluded_bundles':sum(x['status']!='INSPECTED' for x in result['rows']),'native_execution':False}))
if __name__=='__main__':main()
