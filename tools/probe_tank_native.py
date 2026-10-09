#!/usr/bin/env python3
"""Probe pinned TankRW merge and crypto in isolated ARM instruction emulation.

Requires locally acquired firmware and an existing Unicorn Python installation.
No vendor Linux startup, system-call emulation, sockets or physical devices.
"""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',required=True)
    parser.add_argument('--unicorn-dir',required=True,help='Directory containing the installed unicorn module')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    binary=Path(args.binary).resolve();libraries=Path(args.unicorn_dir).resolve()
    output=Path(args.output).resolve()
    if output.exists():parser.error('Output must be new')
    if not binary.is_file() or binary.stat().st_size>32*1024*1024:parser.error('Invalid bounded firmware input')
    digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    if digest!='a2a5e3c47cf1c0c2cc627bcfcba10c0c20a843420fa46ca39290be27e861a8c1':parser.error('Unreviewed firmware hash')
    if not (libraries/'unicorn/__init__.py').is_file():parser.error('Unicorn installation unavailable')
    root=Path(__file__).resolve().parents[1]
    cmd=['bwrap','--unshare-all','--die-with-parent','--ro-bind','/usr','/usr',
         '--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc',
         '--dev','/dev','--tmpfs','/tmp','--dir','/input','--ro-bind',str(binary),'/input/daemon',
         '--ro-bind',str(libraries),'/work/python-libs','--ro-bind',str(root/'owner-maintenance'),'/authored',
         '--clearenv','--setenv','PATH','/usr/bin','--chdir','/tmp','/usr/bin/python3','-B','-c',PROBE]
    result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
    if result.returncode:raise RuntimeError('Isolated probe failed; no hardware contacted: '+result.stderr.decode(errors='replace')[:2048])
    receipt=json.loads(result.stdout)
    receipt.update(binary_sha256=digest,probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   tank_codec_sha256=hashlib.sha256((root/'owner-maintenance/tank_codec.py').read_bytes()).hexdigest(),
                   environment='Unprivileged bubblewrap; isolated network/PID; read-only inputs; synthetic ARM memory')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as target:json.dump(receipt,target,sort_keys=True,indent=2);target.write('\n')
    print(json.dumps({'passed':receipt['passed'],'merge_cases':receipt['merge_cases'],'crypto_stream_cases':receipt['crypto_stream_cases']}))

PROBE = r'''
import sys,struct,json,hashlib
from pathlib import Path
sys.path.insert(0,'/work/python-libs')
sys.path.insert(0,'/authored')
import tank_codec
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import *
data=Path('/input/daemon').read_bytes()
assert hashlib.sha256(data).hexdigest()=='a2a5e3c47cf1c0c2cc627bcfcba10c0c20a843420fa46ca39290be27e861a8c1'
u=Uc(UC_ARCH_ARM,UC_MODE_ARM)
u.mem_map(0,0x2000000)
phoff=struct.unpack_from('<I',data,28)[0];ents,count=struct.unpack_from('<HH',data,42)
for i in range(count):
 typ,off,va,_,size,ms,_,_=struct.unpack_from('<8I',data,phoff+i*ents)
 if typ==1:u.mem_write(va,data[off:off+size])
u.mem_map(0x40000000,0x1000000);u.mem_map(0x50000000,0x1000000);u.mem_map(0x70000000,4096)
heap=0x50001000;sp0=0x40800000;stop=0x70000000
u.reg_write(UC_ARM_REG_SP,sp0);u.reg_write(UC_ARM_REG_LR,stop);u.reg_write(UC_ARM_REG_R10,0x50000000)
def rd(p,n=4):return bytes(u.mem_read(p,n))
def word(p):return struct.unpack('<I',rd(p))[0]
def wr(p,v):u.mem_write(p,struct.pack('<I',v&0xffffffff))
def alloc(b):
 global heap
 p=heap;heap+=(len(b)+15)//16*16+16;u.mem_write(p,b);return p
def sarg(s,k):return rd(word(s+k),word(s+k+4))
def ret():u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
def stack():return u.reg_read(UC_ARM_REG_SP)




def invoke(address,args):
 u.reg_write(UC_ARM_REG_SP,sp0);u.reg_write(UC_ARM_REG_LR,stop)
 u.mem_write(sp0,bytes(256))
 for i,v in enumerate(args):wr(sp0+4+i*4,v)
 u.emu_start(address,stop,count=20000)
 assert u.reg_read(UC_ARM_REG_PC)==stop

def hook(u,a,n,_):
 if a==stop:u.emu_stop()
u.hook_add(UC_HOOK_CODE,hook)
# Same-type merge returns nil without copying/resetting either object.
typeptr=0x4e8910+word(0x4e8a54)
merge=[]
for left,right in [(bytes(256),bytes([255])*256),(bytes(range(256)),bytes(256)),(bytes([1])*256,bytes([2])*256)]:
 a,b=alloc(left),alloc(right)
 invoke(0x4e88f0,[a,typeptr,b,123,456])
 assert word(sp0+16)==0 and word(sp0+20)==0
 assert rd(a,256)==left and rd(b,256)==right
 merge.append(True)
# Native block cipher and key expansion; no crypto/runtime hook.
crypto=[]
for key in (bytes(range(16)),b'0123456789abcdef',bytes([255])*16):
 c=alloc(bytes(256));kp=alloc(key)
 invoke(0x1db458,[c,kp,16,16])
 iv=b'ABCDABCD';out=b''
 for index in range(6):
  src,dst=alloc(iv),alloc(bytes(8))
  invoke(0x1daf98,[c,dst,8,8,src,8,8])
  actual=rd(dst,8)
  assert actual==tank_codec._block(key,iv)
  out+=actual;iv=actual
 for length,skip in ((22,10),(36,0)):
  plain=bytes(range(length));expect=bytes(a^b for a,b in zip(plain,out[skip:]))
  assert tank_codec.crypt(key,b'ABCDABCD',plain,skip)==expect
  crypto.append(True)
print(json.dumps({'passed':True,'merge_cases':len(merge),'crypto_stream_cases':len(crypto),'native_functions':['main.daguerreTank.Merge ELF 0x4e88f0','XTEA key expansion ELF 0x1db458','XTEA.Encrypt ELF 0x1daf98'],'modeled':[],'native_instructions_only':True,'same_type_merge':'both objects unchanged; nil error','hardware_contact':False,'instruction_limit_per_invocation':20000}))
'''

if __name__=='__main__':main()
