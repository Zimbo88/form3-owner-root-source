#!/usr/bin/env python3
"""Read 16 KiB from the uniquely identified environment MTD; never write hardware.

Python 3.5, intended for a separately approved Rescue V2 observation only. Does not
infer a fixed /dev/mtd number. Output is a NEW private RAM file, never an image.
"""
import argparse,hashlib,json,os,re,stat,struct,zlib

def select(text):
    rows=[]
    for line in text.splitlines():
        m=re.match(r'^mtd([0-9]+): ([0-9a-fA-F]+) ([0-9a-fA-F]+) "([^"]+)"$',line)
        if m and m.group(4)=='uboot environment':
            if int(m.group(2),16)!=0x40000:raise ValueError('Unexpected environment partition length')
            rows.append((int(m.group(1)),int(m.group(3),16)))
    if len(rows)!=1:raise ValueError('Exactly one reviewed environment label required')
    return rows[0]

def validate(raw):
    if len(raw)!=0x4000 or struct.unpack('<I',raw[:4])[0]!=(zlib.crc32(raw[4:])&0xffffffff):raise ValueError('Environment size/CRC mismatch')
    data=raw[4:].split(b'\0\0',1)
    if len(data)!=2:raise ValueError('Missing environment terminator')
    values={}
    for item in data[0].split(b'\0'):
        if b'=' not in item:raise ValueError('Malformed environment entry')
        name,value=item.split(b'=',1)
        if name in values:raise ValueError('Duplicate environment entry')
        values[name]=value
    return {'crc32':'%08x'%struct.unpack('<I',raw[:4])[0],
            'fl_bootpart':values.get(b'fl_bootpart',b'').decode('ascii'),
            'fl_bootflip':values.get(b'fl_bootflip',b'').decode('ascii'),
            'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    if os.getuid()!=0 or not os.uname().machine.startswith('armv7'):p.error('Approved ARM rescue context required')
    if 'rdinit=/init' not in open('/proc/cmdline').read().split():p.error('Expected Rescue V2 kernel command line')
    if b'Formlabs' not in open('/proc/device-tree/model','rb').read(4096):p.error('Unexpected device model')
    out=os.path.abspath(a.output)
    if os.path.dirname(out)!='/run' or not re.match(r'^owner-active-env-[a-zA-Z0-9-]+\.bin$',os.path.basename(out)):p.error('New /run/owner-active-env-NAME.bin required')
    index,erase=select(open('/proc/mtd').read(65536));name='/dev/mtd%d'%index
    major,minor=map(int,open('/sys/class/mtd/mtd%d/dev'%index).read().strip().split(':'))
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        st=os.fstat(fd)
        if not stat.S_ISCHR(st.st_mode) or (os.major(st.st_rdev),os.minor(st.st_rdev))!=(major,minor):raise ValueError('MTD device identity mismatch')
        raw=b''
        while len(raw)<0x4000:
            b=os.read(fd,0x4000-len(raw))
            if not b:break
            raw+=b
    finally:os.close(fd)
    r=validate(raw);r.update(read_only=True,source=name,partition_label='uboot environment',erase_bytes=erase)
    fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    print(json.dumps(r,sort_keys=True,indent=2))
if __name__=='__main__':main()
