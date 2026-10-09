#!/usr/bin/env python3
"""Run pinned ARM state callbacks with synthetic objects, never a vendor process.

Qt logging/material/cover providers and transition destinations are modeled.
Only callback decisions execute natively. No actuator, Linux syscall or D-Bus.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PIN = '025a21f7cdfaf2f10b2a40f2580d62992794a1d500643194e4606eb4e8676e34'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--unicorn-dir', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    binary, libs, output = [Path(x).resolve() for x in (a.binary, a.unicorn_dir, a.output)]
    if output.exists(): p.error('New output required')
    if not binary.is_file() or binary.stat().st_size > 64 << 20:
        p.error('Bounded regular firmware copy required')
    if hashlib.sha256(binary.read_bytes()).hexdigest() != PIN: p.error('Unreviewed Sauron hash')
    if not (libs/'unicorn/__init__.py').is_file(): p.error('Unicorn unavailable')
    command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
               '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib',
               '--ro-bind', '/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev',
               '--tmpfs', '/tmp', '--ro-bind', str(binary), '/input/Sauron',
               '--ro-bind', str(libs), '/libs', '--clearenv', '--chdir', '/tmp',
               '/usr/bin/python3', '-B', '-c', PROBE]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
    if result.returncode:
        raise RuntimeError('Isolated probe failed: ' + result.stderr.decode(errors='replace')[:2000])
    receipt = json.loads(result.stdout)
    receipt.update(binary_sha256=PIN, probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   environment='unprivileged bubblewrap; isolated network/PID; synthetic objects; read-only inputs')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as f: json.dump(receipt, f, indent=2, sort_keys=True); f.write('\n')
    print(json.dumps({'passed': receipt['passed'], 'cases': len(receipt['cases']), 'hardware_contact': False}))


PROBE = r'''
import sys,struct,json,hashlib,itertools
from pathlib import Path
sys.path.insert(0,'/libs')
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_INTR
from unicorn.arm_const import *
data=Path('/input/Sauron').read_bytes()
assert hashlib.sha256(data).hexdigest()=='025a21f7cdfaf2f10b2a40f2580d62992794a1d500643194e4606eb4e8676e34'
ph=struct.unpack_from('<I',data,28)[0];width,count=struct.unpack_from('<HH',data,42)
u=Uc(UC_ARCH_ARM,UC_MODE_ARM)
u.mem_map(0x10000,0x2000000)
for i in range(count):
 t,o,v,_,s,m,_,_=struct.unpack_from('<8I',data,ph+i*width)
 if t==1: u.mem_write(v,data[o:o+s])
u.mem_map(0x40000000,0x100000)
sp=0x40080000;stop=0x400f0000;obj=0x40001000;cover=0x40002000;config=0x40003000
# Two reviewed virtual dispatch entries are read from the real ELF vtables.
def word(a):return struct.unpack('<I',bytes(u.mem_read(a,4)))[0]
def put(a,v):u.mem_write(a,struct.pack('<I',v))
assert word(0x174bdf8+8+0x50)==0x99d238
assert word(0x174be5c+8+0x4c)==0x9bbb54
assert word(0x174be5c+8+0x48)==0x9bd6f4
# Mock objects only; cover getter and preheat destination live at synthetic PCs.
COVER=0x400e0000;TIMER=0x400e0004
ranges=[(0x99c3c0,0x99cadc),(0x99d238,0x99d804),(0x9b2e38,0x9b2e7c),
        (0x4f3748,0x4f3750),(0x9bec3c,0x9c0940),(0x9bd6f4,0x9bea80)]
noops={0xe4d94,0xd5358,0xd66e4,0x110b51c,0xe4ddc,0xd5394,0xd6b70}
destinations={0x9bebe0:'stop_until_cover_closed',0x9bd698:'stop_then_preheat',
              0x9b6c14:'begin_preheat',0x9b43dc:'return_idle',0x9bbb54:'abort_preheat'}
case={};events=[];visited=set()
def ret(value=0):u.reg_write(UC_ARM_REG_R0,value);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
def hook(u,a,size,_):
 visited.add(a)
 if a==COVER:ret(case['cover_open'])
 elif a==TIMER:events.append('restart_timer');ret()
 elif a==0x9bd6f4 and case['kind']=='idle_cover':events.append('request_preheat');ret(1)
 elif a in destinations:events.append(destinations[a]);ret()
 elif a in noops:ret()
 elif a==0x1106a6c:ret(10)  # logging disabled; no Qt allocation path executed
 elif a==0x9b98f4:
  dest=u.reg_read(UC_ARM_REG_R0);u.mem_write(dest,struct.pack('<IB',0,case.get('material_present',0)));ret(dest)
 elif a==0x5a1bf0:ret(case.get('material_allows',0))
 elif a==stop:u.emu_stop()
 elif not any(lo<=a<hi for lo,hi in ranges):raise RuntimeError('Unmodeled branch '+hex(a))
def interrupt(u,n,_):raise RuntimeError('Unexpected ARM interrupt '+str(n))
u.hook_add(UC_HOOK_CODE,hook);u.hook_add(UC_HOOK_INTR,interrupt)
results=[]
def run(c,entry,expect,flag=None):
 global case,events,visited
 case=c;events=[];visited=set()
 u.mem_write(0x40000000,bytes(0x100000))
 # Default concrete IdleRoutine vtable. Cover getter uses synthetic interface.
 put(obj,0x174bdf8+8 if c['kind']=='idle_cover' else 0x174be5c+8)
 put(obj+0x10,c.get('state',0));put(obj+0x30,cover);put(obj+0x2c,cover)
 put(cover,cover+0x100);put(cover+0x100+0x34,COVER)
 put(obj+0x40,config);u.mem_write(config+0x14,bytes([c.get('enabled',1)]))
 u.mem_write(obj+0x64,bytes([c.get('aborting',0)]))
 # IdleRoutine +0x40 is its preheat resource, not configuration.
 if c['kind']=='idle_cover':put(config,0x174be5c+8)
 put(obj+0x14,0x40004000);put(0x40004000,0x40004100);put(0x40004100+0x48,TIMER)
 for r in [UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_R12]:u.reg_write(r,0)
 u.reg_write(UC_ARM_REG_R0,obj);u.reg_write(UC_ARM_REG_SP,sp);u.reg_write(UC_ARM_REG_LR,stop)
 u.emu_start(entry,stop,count=20000)
 assert u.reg_read(UC_ARM_REG_PC)==stop, 'Instruction budget exhausted'
 assert events==expect,(c,events,expect)
 if flag is not None:assert bytes(u.mem_read(obj+0x4d,1))[0]==flag
 results.append(dict(c,entry=hex(entry),observed_destinations=events,passed=True,native_instruction_addresses=len(visited)))
for state,opened in itertools.product(range(5),(0,1)):
 run({'kind':'idle_cover','state':state,'cover_open':opened},0x99c3c0,
     ['request_preheat'] if state==2 and not opened else [],1 if state in (0,1) and not opened else 0)
for enabled in (0,1):
 run({'kind':'enabled_changed','enabled':enabled,'cover_open':0},0x9b2e38,[] if enabled else ['abort_preheat'])
for state,opened,present,allowed in itertools.product(range(6),(0,1),(0,1),(0,1)):
 expect=(['stop_until_cover_closed'] if state in (1,3) else []) if opened else (
   ['stop_then_preheat' if state==4 else 'begin_preheat'] if state in (4,5) and present and allowed else
   ['return_idle'] if state in (4,5) else [])
 run({'kind':'preheat_cover','state':state,'cover_open':opened,'material_present':present,'material_allows':allowed},0x9bec3c,expect)
for state,enabled,aborting,present,allowed in itertools.product(range(6),(0,1),(0,1),(0,1),(0,1)):
 expect=[]
 if enabled and not aborting and (not present or allowed):
  expect={0:['begin_preheat'],1:['restart_timer'],2:['stop_then_preheat']}.get(state,[])
 run({'kind':'preheat_start','state':state,'enabled':enabled,'aborting':aborting,'cover_open':0,
      'material_present':present,'material_allows':allowed},0x9bd6f4,expect)
print(json.dumps({'passed':True,'cases':results,'address_convention':'ELF link VA',
 'modeled':['Qt logging disabled','cover getter','material lookup/policy predicate','transition destinations/timer'],
 'not_proven':['heater output','Qt signal delivery','complete event loop','runtime concurrency','material lookup implementation'],
 'hardware_contact':False,'instruction_limit_per_case':20000,'vendor_process_started':False}))
'''

if __name__ == '__main__': main()
