"""Private same-consumable snapshots; no EEPROM writes or public raw exports.

The reviewed T/65 tank snapshot is decoded and checksum checked. Its live
restore transaction is not validated. Cartridge restore recovers usage only, preserving current identity,
material and a monotonic write count. It is not arbitrary EEPROM replacement.
"""
import base64
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import time

from cartridge_codec import decode, parse_record, validate_legacy_material
from cartridge_transaction import read_file, durable_new, sync_dir, mirror_semantic_pin

BASE = '/data/owner-maintenance/consumable-backups'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def selected(kind):
    if kind not in ('cartridge', 'tank'):
        raise ValueError('Unknown consumable kind')
    controller='Cartridge' if kind=='cartridge' else 'Tank'
    result=subprocess.run(['/usr/bin/dbus-send','--system','--print-reply','--reply-timeout=3000',
                           '--dest=com.formlabs.'+controller+'Controller','/com/Formlabs/TankCartridgeController/'+controller,
                           'com.formlabs.'+controller+'Controller.GetConnected'+controller+'ID'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
    if result.returncode or len(result.stdout)>4096:
        raise ValueError('Connected consumable identity unavailable')
    values=re.findall(r'string "([^"\n]*)"',result.stdout.decode('ascii'))
    name=values[0] if len(values)==1 else None
    family='2d' if kind=='cartridge' else '4c'
    if not isinstance(name,str) or not re.fullmatch(family+r'-[a-f0-9]{12}',name):
        raise ValueError('Unsupported connected consumable identity format')
    return name



def parse_tank_material_reply(raw):
    if not isinstance(raw,bytes) or len(raw)>65536:raise ValueError('Unbounded tank status reply')
    text=raw.decode('utf-8')
    values=re.findall(r'dict entry\(\s*string "LastResinUsed"\s*variant\s+string "(FL[A-Z0-9]{6})"\s*\)',text)
    if len(values)!=1:raise ValueError('Native tank material is unavailable or ambiguous')
    return values[0]


def native_tank_material():
    result=subprocess.run(['/usr/bin/dbus-send','--system','--print-reply','--reply-timeout=3000',
                           '--dest=com.formlabs.TankController','/com/Formlabs/TankCartridgeController/Tank',
                           'com.formlabs.TankController.GetConnectedTank'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
    if result.returncode:raise ValueError('Native tank status query failed')
    return parse_tank_material_reply(result.stdout)


def capture(kind):
    name=selected(kind)
    expected=128 if kind=='cartridge' else 512
    eeprom='/sys/bus/w1/devices/'+name+'/eeprom'
    mirror='/data/'+('Cartridges' if kind=='cartridge' else 'Tanks')+'/'+name+'.json'
    if not os.path.realpath(eeprom).startswith('/sys/devices/') or os.path.realpath(mirror)!=mirror:
        raise ValueError('Unexpected consumable path')
    first=read_file(eeprom,expected)
    raw=read_file(mirror)
    second=read_file(eeprom,expected)
    again=read_file(mirror)
    if len(first)!=expected or first!=second or selected(kind)!=name:
        raise ValueError('Consumable changed during snapshot')
    if kind=='cartridge':
        rec=parse_record(raw);other=parse_record(again)
        material=validate_legacy_material(first,rec,name)
        result=decode(first,rec,name)
        matched=all(all(c['record_matches'].values()) for c in result['rw_copies'])
        validation='CHECKSUMS_AND_MIRROR_VERIFIED' if matched else 'CHECKSUMS_VALID; MIRROR_MISMATCH'
    else:
        from package_format import unique_json
        rec=unique_json(raw);other=unique_json(again)
        if not isinstance(rec,dict) or rec.get('DataVersionRO')!=65 or rec.get('DataVersionRW')!=65:
            raise ValueError('Unknown tank record format')
        material=rec.get('LastResinUsed')
        from tank_codec import decode as decode_tank
        result=decode_tank(first,rec,name)
        matched=result['rw_equal'] and all(all(c['record_matches'].values()) for c in result['copies'])
        validation='CHECKSUMS_AND_MIRROR_VERIFIED' if matched else 'CHECKSUMS_VALID; MIRROR_MISMATCH'
    if mirror_semantic_pin(rec)!=mirror_semantic_pin(other):
        raise ValueError('Mirror changed during snapshot')
    if not isinstance(material,str) or not re.fullmatch(r'FL[A-Z0-9]{6}',material):
        raise ValueError('Unknown material projection')
    return {'kind':kind,'device_name':name,'material':material,'validation':validation,
            'eeprom':first,'record':raw}


class Store(object):
    def __init__(self,root=BASE,capture_fn=capture):
        self.root,self.capture_fn=root,capture_fn

    def directory(self):
        if not os.path.exists(self.root):os.mkdir(self.root,0o700)
        st=os.lstat(self.root)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o700:
            raise ValueError('Untrusted private backup directory')

    def load(self,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[a-f0-9]{32}',identity):
            raise ValueError('Invalid backup identifier')
        self.directory()
        directory=os.path.join(self.root,identity)
        if os.path.realpath(directory)!=directory:
            raise ValueError('Unexpected backup path')
        st=os.lstat(directory)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o700:
            raise ValueError('Untrusted backup directory')
        from package_format import unique_json
        meta=unique_json(read_file(directory+'/manifest.private.json',8192))
        if not isinstance(meta,dict) or meta.get('schema')!=1 or meta.get('id')!=identity or meta.get('kind') not in ('cartridge','tank'):
            raise ValueError('Invalid backup manifest')
        expected=128 if meta['kind']=='cartridge' else 512
        if meta.get('bytes')!=expected or not isinstance(meta.get('created'),(int,float)) or not math.isfinite(meta['created']):
            raise ValueError('Invalid backup size/time')
        if not isinstance(meta.get('material'),str) or not re.fullmatch(r'FL[A-Z0-9]{6}',meta['material']):
            raise ValueError('Invalid backup material')
        for field in ('eeprom_sha256','record_sha256'):
            if not isinstance(meta.get(field),str) or not re.fullmatch(r'[a-f0-9]{64}',meta[field]):
                raise ValueError('Invalid backup digest')
        if meta.get('validation') not in ('CHECKSUMS_AND_MIRROR_VERIFIED','CHECKSUMS_VALID; MIRROR_MISMATCH','STABLE_RAW_COPY; TANK_CODEC_NOT_VALIDATED'):
            raise ValueError('Unknown backup validation')
        eeprom=read_file(directory+'/eeprom.bin',512)
        raw=read_file(directory+'/record.private.json')
        if sha(eeprom)!=meta.get('eeprom_sha256') or sha(raw)!=meta.get('record_sha256') or len(eeprom)!=meta.get('bytes'):
            raise ValueError('Backup integrity check failed')
        return meta,eeprom,raw

    def public(self,meta):
        return {key:meta[key] for key in ('id','kind','created','material','bytes','eeprom_sha256','record_sha256','validation')}

    def list(self):
        self.directory()
        names=os.listdir(self.root)
        if len(names)>128:raise ValueError('Backup retention bound exceeded')
        rows=[]
        for identity in names:
            if not re.fullmatch(r'[a-f0-9]{32}',identity):
                raise ValueError('Unfinished or unexpected backup; inspect privately')
            meta,image,raw=self.load(identity)
            rows.append(self.public(meta))
        return sorted(rows,key=lambda r:r['created'],reverse=True)

    def backup(self,kind):
        self.directory()
        if len(os.listdir(self.root))>=128:raise ValueError('Backup retention limit reached; archive privately')
        value=self.capture_fn(kind)
        identity=__import__('binascii').hexlify(os.urandom(16)).decode()
        temporary=os.path.join(self.root,'.pending-'+identity)
        os.mkdir(temporary,0o700)
        meta={'schema':1,'id':identity,'kind':kind,'created':time.time(),
              'device_name':value['device_name'],'material':value['material'],
              'bytes':len(value['eeprom']),'eeprom_sha256':sha(value['eeprom']),
              'record_sha256':sha(value['record']),'validation':value['validation'],
              'scope':'Main EEPROM and persistent mirror only; no ROM/control/protection-page programming'}
        durable_new(temporary+'/eeprom.bin',value['eeprom'])
        durable_new(temporary+'/record.private.json',value['record'])
        durable_new(temporary+'/manifest.private.json',json.dumps(meta,sort_keys=True).encode())
        sync_dir(temporary)
        os.rename(temporary,os.path.join(self.root,identity));sync_dir(self.root)
        return self.public(meta)

    def restore_usage(self,identity,current):
        meta,image,raw=self.load(identity)
        if meta['kind']!='cartridge':
            raise ValueError('Tank restore is unavailable: live transaction and rollback not validated')
        if meta['device_name']!=current['device_name'] or current['kind']!='cartridge':
            raise ValueError('Backup belongs to a different physical consumable')
        if image[:64]!=current['eeprom'][:64] or image[80:96]!=current['eeprom'][80:96] or image[112:]!=current['eeprom'][112:]:
            raise ValueError('Restore cannot change material, identity or unrelated EEPROM bytes')
        saved=parse_record(raw);live=parse_record(current['record'])
        validate_legacy_material(image,saved,meta['device_name'])
        validate_legacy_material(current['eeprom'],live,meta['device_name'])
        result=decode(image,saved,meta['device_name'])
        if not result['rw_usage_equal'] or not all(all(c['record_matches'].values()) for c in result['rw_copies']):
            raise ValueError('Backup memory/mirror mismatch')
        ignored={'WriteCount','DispenseCount','EstimatedVolumeDispensed_ml','CumulativeDispenseTime_s','LastSuccessfulWritebackTime'}
        if {k:v for k,v in saved.items() if k not in ignored}!={k:v for k,v in live.items() if k not in ignored}:
            raise ValueError('Backup identity or non-usage fields differ')
        return {key:result['rw_copies'][0]['usage'][key] for key in ('DispenseCount','EstimatedVolumeDispensed_ml','CumulativeDispenseTime_s')}

    def restore_tank_material(self,identity,current):
        """Restore only the saved material label; retain current tank lifetime."""
        from tank_codec import decode as tank_decode
        from package_format import unique_json
        meta,image,raw=self.load(identity)
        if meta['kind']!='tank' or current['kind']!='tank' or meta['device_name']!=current['device_name']:
            raise ValueError('Backup belongs to a different physical tank')
        live_image=current['eeprom']
        regions=set(range(32,73))|set(range(128,169))
        if len(live_image)!=512 or any(image[i]!=live_image[i] for i in range(512) if i not in regions):
            raise ValueError('Tank identity or non-RW memory differs')
        saved=unique_json(raw);live=unique_json(current['record'])
        ignored={'VolumePrinted_mm3','NumLayersPrinted','PrintTime_mS','LastPrintDate',
                 'LastResinLevel_mm','LastResinUsed','DateFirstFill','LastSuccessfulWritebackTime'}
        if {k:v for k,v in saved.items() if k not in ignored}!={k:v for k,v in live.items() if k not in ignored}:
            raise ValueError('Tank backup identity/unknown fields differ')
        for memory,record in ((image,saved),(live_image,live)):
            result=tank_decode(memory,record,meta['device_name'])
            if not result['rw_equal'] or not all(all(c['record_matches'].values()) for c in result['copies']):
                raise ValueError('Tank backup/current memory and mirror disagree')
        return saved['LastResinUsed']
