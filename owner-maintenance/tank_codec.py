"""Authored T/65 tank codec, no hardware I/O or programming on import.

Pinned Form 3 2.5.6-2773 TankRO/TankRW path, not SeniorTankRW or all tanks.
RO: 32 bytes; RW A/B: 41 bytes at 32/128 in the 512-byte main memory.
Checksums are not manufacturer signatures. No lifetime reset is provided.
"""
from datetime import datetime, timedelta
import hashlib
import math
import re
import struct
from cartridge_codec import _block


FIELDS=('VolumePrinted_mm3','NumLayersPrinted','PrintTime_mS','LastPrintDate_epochS',
        'LastResinLevel_mm','LastResinUsed','DateFirstFill_epochS')


def key_for(record,name):
    secret=record.get('SecretKey')
    if not isinstance(secret,str) or not 1<=len(secret)<=1024 or not isinstance(name,str) or not re.fullmatch(r'4c-[a-f0-9]{12}',name):
        raise ValueError('Unsupported tank key/identity format')
    try:return hashlib.sha256((secret+name).encode('latin-1')).hexdigest()[::4].encode('ascii')
    except UnicodeError:raise ValueError('Unsupported tank key encoding') from None


def crypt(key,iv,value,skip=0):
    if not isinstance(value,bytes) or len(value) not in (22,36) or len(iv)!=8 or skip not in (0,10):
        raise ValueError('Unsupported T/65 stream dimensions')
    out=b''
    while len(out)<len(value)+skip:
        iv=_block(key,iv);out+=iv
    return bytes(a^b for a,b in zip(value,out[skip:]))


def checksum(value):
    if not isinstance(value,bytes) or len(value) not in (22,36):raise ValueError('Unsupported tank payload')
    a=b=0
    for v in value:a=(a+v)&65535;b=(b+a)&65535
    return a|(b<<16)


def projection(plain):
    values=list(struct.unpack('<fIQIf8sI',plain))
    try:values[5]=values[5].decode('ascii')
    except UnicodeError:raise ValueError('Invalid tank material encoding') from None
    if not re.fullmatch(r'FL[A-Z0-9]{6}',values[5]):raise ValueError('Unassigned/unknown tank material')
    if not math.isfinite(values[0]) or values[0]<0 or not math.isfinite(values[4]):
        raise ValueError('Non-finite tank accounting')
    return dict(zip(FIELDS,values))


def mirror_matches(values,record):
    result={}
    for name in ('VolumePrinted_mm3','NumLayersPrinted','PrintTime_mS','LastResinLevel_mm','LastResinUsed'):
        value=record.get(name)
        if name in ('VolumePrinted_mm3','LastResinLevel_mm'):
            try:
                value=struct.unpack('<f',struct.pack('<f',value))[0] if type(value) in (int,float) and math.isfinite(value) else None
            except (OverflowError,struct.error):value=None
        result[name]=values[name]==value
    for field in ('LastPrintDate','DateFirstFill'):
        projected=(datetime(1970,1,1)+timedelta(seconds=values[field+'_epochS'])).strftime('%Y-%m-%dT%H:%M:%S')
        result[field]=record.get(field)==projected
    return result


def decode(image,record,name):
    if not isinstance(image,bytes) or len(image)!=512 or image[:2]!=b'TA' or not isinstance(record,dict):
        raise ValueError('Expected the reviewed 512-byte T/65 envelope')
    if record.get('DataVersionRO')!=65 or record.get('DataVersionRW')!=65:
        raise ValueError('Unsupported tank record versions')
    key=key_for(record,name);iv=image[2:6]*2
    ro=crypt(key,iv,image[10:32],10)
    if checksum(ro)!=struct.unpack_from('<I',image,6)[0]:raise ValueError('Tank RO checksum mismatch')
    for field,offset in (('TankVersionMajor',18),('TankVersionMinor',19),('MixerVersion',20),('FloatVersion',21)):
        if record.get(field)!=ro[offset]:raise ValueError('Tank RO mirror mismatch')
    copies=[]
    for label,offset in (('A',32),('B',128)):
        if image[offset]!=65:raise ValueError('Unsupported tank RW version')
        raw=crypt(key,iv,image[offset+5:offset+41])
        if checksum(raw)!=struct.unpack_from('<I',image,offset+1)[0]:raise ValueError('Tank RW checksum mismatch')
        values=projection(raw)
        copies.append({'copy':label,'offset':offset,'checksum_valid':True,'values':values,
                       'record_matches':mirror_matches(values,record)})
    return {'format':'T/65; TankRW; 512-byte main memory','ro_checksum_valid':True,
            'copies':copies,'rw_equal':copies[0]['values']==copies[1]['values'],
            'identity_or_key_exported':False,'hardware_write_supported':False}


def material_candidate(image,record,name,material):
    """Offline candidate only: preserve all lifetime fields and non-RW bytes."""
    before=decode(image,record,name)
    if not before['rw_equal'] or not all(all(x['record_matches'].values()) for x in before['copies']):
        raise ValueError('Tank baseline copies/mirror disagree')
    if not isinstance(material,str) or not re.fullmatch(r'FL[A-Z0-9]{6}',material):
        raise ValueError('Invalid tank material')
    key=key_for(record,name);iv=image[2:6]*2
    raw=crypt(key,iv,image[37:73]);raw=raw[:24]+material.encode('ascii')+raw[32:]
    encoded=b'A'+struct.pack('<I',checksum(raw))+crypt(key,iv,raw)
    target=bytearray(image)
    for offset in (32,128):target[offset:offset+41]=encoded
    revised=dict(record);revised['LastResinUsed']=material
    decoded=decode(bytes(target),revised,name)
    for old,new in zip(before['copies'],decoded['copies']):
        if any(old['values'][f]!=new['values'][f] for f in FIELDS if f!='LastResinUsed'):
            raise ValueError('Tank candidate changed accounting')
    return bytes(target),revised,decoded
