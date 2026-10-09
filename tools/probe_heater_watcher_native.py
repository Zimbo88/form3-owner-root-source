#!/usr/bin/env python3
"""Run bounded, hash-pinned heater watcher ARM slices against synthetic memory.

No vendor process, hardware, D-Bus, Linux syscall emulation or actuator output.
Qt notifications/timer/meta invocation are intercepted observation boundaries.
Requires an existing local Unicorn installation, as the other native probes do.
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
    if not (libs / 'unicorn/__init__.py').is_file(): p.error('Unicorn unavailable')
    command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
               '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib',
               '--ro-bind', '/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev',
               '--tmpfs', '/tmp', '--ro-bind', str(binary), '/input/Sauron',
               '--ro-bind', str(libs), '/libs', '--clearenv', '--chdir', '/tmp',
               '/usr/bin/python3', '-B', '-c', PROBE]
    r = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
    if r.returncode:
        raise RuntimeError('Isolated probe failed: ' + r.stderr.decode(errors='replace')[:2000])
    receipt = json.loads(r.stdout)
    receipt.update(binary_sha256=PIN,
                   probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   environment='Unprivileged bubblewrap; separate network/PID namespaces; read-only inputs; synthetic ARM memory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as f:
        json.dump(receipt, f, indent=2, sort_keys=True, allow_nan=False); f.write('\n')
    print(json.dumps({'passed': receipt['passed'], 'cases': len(receipt['cases']), 'hardware_contact': False}))


PROBE = r'''
import sys, struct, json, math, hashlib
from pathlib import Path
sys.path.insert(0, '/libs')
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_INTR
from unicorn.arm_const import *
data = Path('/input/Sauron').read_bytes()
assert hashlib.sha256(data).hexdigest() == '025a21f7cdfaf2f10b2a40f2580d62992794a1d500643194e4606eb4e8676e34'
u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
u.mem_map(0x10000, 0x2000000)
ph = struct.unpack_from('<I', data, 28)[0]
width, count = struct.unpack_from('<HH', data, 42)
for i in range(count):
    kind, offset, va, _, size, _, _, _ = struct.unpack_from('<8I', data, ph+i*width)
    if kind == 1: u.mem_write(va, data[offset:offset+size])
u.mem_map(0x40000000, 0x100000)
OBJ, SP, STOP = 0x40001000, 0x40080000, 0x400f0000
u.reg_write(UC_ARM_REG_C1_C0_2, 0x00f00000)
u.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
events, invocations, visited = [], [], set()
def word(a): return struct.unpack('<I', bytes(u.mem_read(a, 4)))[0]
def put(a, x): u.mem_write(a, struct.pack('<I', x & 0xffffffff))
def dbl(a): return struct.unpack('<d', bytes(u.mem_read(a, 8)))[0]
def text(a): return bytes(u.mem_read(a, 64)).split(b'\0')[0].decode('ascii')
def ret(): u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))
def hook(uc, a, size, _):
    visited.add(a)
    if a in (0x133658, 0x13367c, 0xd684c):
        events.append({0x133658:'temperature_changed', 0x13367c:'functional_changed', 0xd684c:'timer_start'}[a]); ret()
    elif a == 0xd4d10:
        invocations.append({'member':text(u.reg_read(UC_ARM_REG_R1)),
                            'connection_type':u.reg_read(UC_ARM_REG_R2),
                            'return_type':text(word(u.reg_read(UC_ARM_REG_SP)))})
        u.reg_write(UC_ARM_REG_R0, 1); ret()
    elif a == STOP: uc.emu_stop()
    elif not (0x44ac50 <= a < 0x44ad78 or 0x39f79c <= a < 0x39f828):
        raise RuntimeError('Unmodeled branch '+hex(a))
def interrupt(uc, n, _): raise RuntimeError('Unexpected ARM interrupt '+str(n))
u.hook_add(UC_HOOK_CODE, hook); u.hook_add(UC_HOOK_INTR, interrupt)
def reset(previous=20.0, functional=1, timer=1):
    events.clear(); invocations.clear(); visited.clear()
    u.mem_write(0x40000000, bytes(0x100000))
    u.mem_write(OBJ+0x20, struct.pack('<d', previous))
    u.mem_write(OBJ+0x28, bytes([functional])); put(OBJ+0x34, timer)
def call(entry, error=0, value=0.0):
    for reg in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
                UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,
                UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_R12):
        u.reg_write(reg, 0)
    u.reg_write(UC_ARM_REG_R0, OBJ); u.reg_write(UC_ARM_REG_R2, error)
    u.reg_write(UC_ARM_REG_SP, SP); u.reg_write(UC_ARM_REG_LR, STOP)
    u.reg_write(UC_ARM_REG_D0, struct.unpack('<Q', struct.pack('<d', value))[0])
    u.mem_write(SP, struct.pack('<d', value))
    u.emu_start(entry, STOP, count=2000)
    assert u.reg_read(UC_ARM_REG_PC) == STOP, 'Instruction budget exhausted'
def finite(x): return x if math.isfinite(x) else ('NaN' if math.isnan(x) else 'Infinity' if x > 0 else '-Infinity')
results=[]
def record(name):
    results.append({'case':name,'passed':True,'notifications':list(events),
      'property_value':finite(dbl(OBJ+0x20)), 'functional':bool(bytes(u.mem_read(OBJ+0x28,1))[0]),
      'count':word(OBJ+0x44),'sum':finite(dbl(OBJ+0x48)),'native_instruction_addresses':len(visited)})
# Exact threshold uses an initial zero to avoid a subtraction-rounding claim.
for value, changed in ((0.0,False),(0.009,False),(0.01,False),(0.010001,True),(-0.02,True),(float('nan'),False),(float('inf'),True)):
    reset(previous=0.0); call(0x44ac50, value=value)
    assert ('temperature_changed' in events) == changed
    assert (dbl(OBJ+0x20)==value) if changed else (dbl(OBJ+0x20)==0)
    record('threshold_'+str(finite(value)))
reset(); call(0x44ace4,value=30); call(0x44ace4,value=34)
assert word(OBJ+0x44)==2 and dbl(OBJ+0x48)==64
call(0x44ac80); assert dbl(OBJ+0x20)==32 and word(OBJ+0x44)==0 and dbl(OBJ+0x48)==0
record('two_valid_samples_average_and_clear')
reset(); call(0x44ace4,error=1,value=99)
assert word(OBJ+0x44)==0 and dbl(OBJ+0x48)==0 and bytes(u.mem_read(OBJ+0x28,1))==b'\0'
record('fault_excluded_and_functional_false')
reset(); call(0x44ace4,value=30); call(0x44ace4,error=1,value=99); call(0x44ac80)
assert dbl(OBJ+0x20)==30 and bytes(u.mem_read(OBJ+0x28,1))==b'\0'
assert events==['functional_changed','temperature_changed']
record('fault_does_not_clear_prior_valid_accumulation')
reset(); call(0x44ac80); assert events==[] and dbl(OBJ+0x20)==20
record('empty_timer_retains_property')
reset(timer=-1); call(0x44ace4,error=1,value=99)
assert events==['functional_changed','timer_start']; record('fault_can_start_inactive_timer')
reset(functional=0); call(0x44ace4,value=21)
assert events==['functional_changed']; record('valid_sample_restores_functional')
for value in (float('nan'),float('inf')):
    reset(); call(0x44ace4,value=value)
    assert word(OBJ+0x44)==1 and not math.isfinite(dbl(OBJ+0x48))
    record('native_unflagged_'+str(finite(value))+'_is_accumulated')
# Observe the native wrapper's ABI arguments, without invoking Qt or the getter.
reset(); put(OBJ+4,OBJ+0x100); put(OBJ+0x108,OBJ+0x200)
u.reg_write(UC_ARM_REG_R0,OBJ+0x300);u.reg_write(UC_ARM_REG_R1,OBJ)
u.reg_write(UC_ARM_REG_SP,SP);u.reg_write(UC_ARM_REG_LR,STOP)
u.emu_start(0x39f79c,STOP,count=2000)
assert u.reg_read(UC_ARM_REG_PC)==STOP
assert invocations==[{'member':'GetCurrentState','connection_type':0,'return_type':'QVariantMap'}], invocations
record('getter_wrapper_argument_capture')
print(json.dumps({'passed':True,'cases':results,'getter_invocation':invocations,
    'address_convention':'ELF link VA','instruction_limit_per_call':2000,
    'modeled':['synthetic watcher initial fields','Qt notifications intercepted','QTimer start intercepted','QMetaObject invocation intercepted'],
    'not_proven':['sensor hardware','native initial member values','native timer period','Qt delivery','getter implementation behind invocation','Linux 4.9 runtime'],
    'hardware_contact':False,'vendor_process_started':False},allow_nan=False))
'''


if __name__ == '__main__': main()
