#!/usr/bin/env python3
"""Decode a private copied T/65 tank snapshot without target access.

The output contains usage/history, but no secret key, ROM ID or raw RO payload.
Keep it private unless its individual fields have been reviewed for publication.
"""
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'owner-maintenance'))
from package_format import unique_json
from tank_codec import decode


def bounded(path,limit):
    with open(path,'rb') as source:value=source.read(limit+1)
    if len(value)>limit:raise ValueError('Input exceeds bound')
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',required=True,help='Private snapshot directory produced by the backup store')
    p.add_argument('--output',required=True,help='New private JSON report')
    a=p.parse_args();base=Path(a.snapshot)
    meta=unique_json(bounded(base/'manifest.private.json',8192))
    image=bounded(base/'eeprom.bin',512);raw=bounded(base/'record.private.json',65536)
    if meta.get('kind')!='tank' or hashlib.sha256(image).hexdigest()!=meta.get('eeprom_sha256') or hashlib.sha256(raw).hexdigest()!=meta.get('record_sha256'):
        raise ValueError('Snapshot manifest mismatch')
    result=decode(image,unique_json(raw),meta.get('device_name'))
    result.update(eeprom_sha256=meta['eeprom_sha256'],source_state='HISTORICAL SNAPSHOT',
                  level_meaning='Last saved resin level in mm; not a fresh measurement or tank volume',
                  live_write_performed=False)
    fd=os.open(a.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as target:json.dump(result,target,sort_keys=True,indent=2);target.write('\n')
    print(json.dumps({'decoded':True,'ro_checksum_valid':result['ro_checksum_valid'],'rw_equal':result['rw_equal'],
                      'mirror_fields_match':all(all(x['record_matches'].values()) for x in result['copies'])}))
if __name__=='__main__':main()
