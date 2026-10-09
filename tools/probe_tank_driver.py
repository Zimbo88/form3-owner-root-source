#!/usr/bin/env python3
"""Run the pinned tank eeprom_write function with synthetic bus callbacks.

No kernel module is loaded. No physical device, network or host credential is
available inside the unprivileged disposable instruction-emulation process.
"""
import argparse,hashlib,json,subprocess
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module',required=True)
    p.add_argument('--unicorn-dir',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args();module=Path(args.module).resolve();libs=Path(args.unicorn_dir).resolve();out=Path(args.output).resolve()
    if out.exists():p.error('Output must be new')
    if not module.is_file() or module.stat().st_size>4<<20:p.error('Invalid module input')
    if hashlib.sha256(module.read_bytes()).hexdigest()!='2549601cf7b059f1cad752234377d2270f1721c2a7a38b8ef27878c54732950a':p.error('Unreviewed driver hash')
    if not (libs/'unicorn/__init__.py').is_file():p.error('Unicorn dependency unavailable')
    cmd=['bwrap','--unshare-all','--die-with-parent','--new-session','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib',
         '--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
         '--ro-bind',str(module),'/input/module','--ro-bind',str(libs),'/libs','--clearenv',
         '/usr/bin/python3','-B','-c',PROBE]
    r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    if r.returncode:raise RuntimeError('Isolated driver probe failed; no hardware contacted')
    receipt=json.loads(r.stdout);receipt['probe_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x') as f:json.dump(receipt,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({'passed':receipt['passed'],'native_driver_cases':len(receipt['cases']),'hardware_contact':False}))

PROBE = r'''
import sys,struct,json,hashlib
from pathlib import Path
sys.path.insert(0,'/libs')
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_INTR
from unicorn.arm_const import *
data=Path('/input/module').read_bytes();assert hashlib.sha256(data).hexdigest()=='2549601cf7b059f1cad752234377d2270f1721c2a7a38b8ef27878c54732950a'
off=struct.unpack_from('<I',data,32)[0];size,names,index=struct.unpack_from('<HHH',data,46)
sections=[struct.unpack_from('<10I',data,off+i*size) for i in range(names)];st=sections[index];strings=data[st[4]:st[4]+st[5]]
text=next(s for s in sections if strings[s[0]:].split(b'\0')[0]==b'.text');code=data[text[4]:text[4]+text[5]]
results=[]
def run(offset,length,fail_read=None,fail_write=None,commit_on_error=False):
 u=Uc(UC_ARCH_ARM,UC_MODE_ARM);base=0x100000;u.mem_map(base,0x10000);u.mem_write(base,code);u.mem_map(0x400000,0x10000)
 sp=0x408000;stop=0x40f000;u.reg_write(UC_ARM_REG_SP,sp);u.reg_write(UC_ARM_REG_LR,stop)
 image=bytearray(i%256 for i in range(512));before=bytes(image);payload=bytes((0xa5+i)%256 for i in range(length));buf=0x401000
 if payload:u.mem_write(buf,payload)
 writes=[];reads=[];attempts=[];locks=[]
 u.reg_write(UC_ARM_REG_R1,0x405000);u.mem_write(0x405000-20,struct.pack('<I',0x406000));u.reg_write(UC_ARM_REG_R3,buf);u.mem_write(sp,struct.pack('<III',offset,0,length))
 def ret(value=0):u.reg_write(UC_ARM_REG_R0,value & 0xffffffff);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
 def hook(u,a,n,_):
  rel=a-base
  if rel in (0x1710,0x17e0,0x1804):
   locks.append('lock' if rel==0x1710 else 'unlock');u.reg_write(UC_ARM_REG_PC,a+4)
  elif rel==0x1758:
   dst=u.reg_read(UC_ARM_REG_R0);src=u.reg_read(UC_ARM_REG_R1);count=u.reg_read(UC_ARM_REG_R2);u.mem_write(dst,bytes(u.mem_read(src,count)));u.reg_write(UC_ARM_REG_PC,a+4)
  elif rel==0x558:
   page=u.reg_read(UC_ARM_REG_R1);dst=u.reg_read(UC_ARM_REG_R2);assert 0<=page<16
   reads.append(page)
   if fail_read==len(reads)-1:ret(-5)
   else:u.mem_write(dst,bytes(image[page*32:page*32+32]));ret()
  elif rel==0xfbc:
   page=u.reg_read(UC_ARM_REG_R1);src=u.reg_read(UC_ARM_REG_R2);assert 0<=page<16
   attempts.append(page);failed=fail_write==len(attempts)-1
   if not failed or commit_on_error:image[page*32:page*32+32]=u.mem_read(src,32);writes.append(page)
   ret(-5 if failed else 0)
  elif a==stop:u.emu_stop()
  elif not 0x169c<=rel<0x1814:raise RuntimeError('Unmodeled instruction '+hex(rel))
 def interrupt(uc,n,_):raise RuntimeError('Unexpected interrupt '+str(n))
 u.hook_add(UC_HOOK_CODE,hook);u.hook_add(UC_HOOK_INTR,interrupt)
 u.emu_start(base+0x169c,stop,count=20000);assert u.reg_read(UC_ARM_REG_PC)==stop
 result=u.reg_read(UC_ARM_REG_R0);result=result if result<2**31 else result-2**32
 expected=bytearray(before)
 for page in writes:
  lo=max(offset,page*32);hi=min(offset+length,(page+1)*32,512)
  expected[lo:hi]=payload[lo-offset:hi-offset]
 assert image==expected, 'Neighbor bytes changed or committed bytes differ'
 if fail_read is None and fail_write is None:
  assert result==max(0,min(512-offset,length))
  count=max(0,min(512-offset,length))
  expected_pages=list(range(offset//32,(offset+count-1)//32+1)) if count else []
  assert writes==expected_pages
 else:assert result==-5
 assert image[:32]==before[:32]
 assert locks==(['lock','unlock'] if offset<512 and length else [])
 record={'offset':offset,'length':length,'injected_read_error':fail_read,
  'injected_write_error':fail_write,'modeled_commit_on_error':commit_on_error,
  'return':result,'pages_read':reads,'pages_attempted':attempts,'pages_written':writes,
  'changed_bytes':sum(a!=b for a,b in zip(image,before)),'neighbor_bytes_preserved':True,
  'mutex_balanced':True,'passed':True}
 results.append(record);return record
# Cover A/B, aligned/full versus unaligned/partial pages, zero length and EOF.
# Fault callbacks do not model the electrical behavior or bus implementation.
for offset in (32,63,64,72,128,159,160,168,480,500,511,512,513):
 for length in (0,1,9,20,31,32,41,64):
  baseline=run(offset,length)
  for idx in range(len(baseline['pages_read'])):run(offset,length,fail_read=idx)
  for idx in range(len(baseline['pages_attempted'])):
   run(offset,length,fail_write=idx)
   run(offset,length,fail_write=idx,commit_on_error=True)
print(json.dumps({'passed':True,'module_sha256':hashlib.sha256(data).hexdigest(),
 'native_function':'.text+0x169c eeprom_write','instruction_limit_per_case':20000,
 'modeled':['mutex','memcpy','readpage','writepage','optional whole-page commit despite error'],
 'not_proven':['physical bus writes','kernel concurrency','torn bytes within one page','power loss','native service reload'],
 'cases':results,'hardware_contact':False}))
'''

if __name__=='__main__':main()
