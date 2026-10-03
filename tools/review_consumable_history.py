#!/usr/bin/env python3
"""Review sealed filesystem-mirror captures offline; never read/write consumable chips.

Verify the sealed snapshot index and each referenced content-addressed object.
Private output contains allowlisted numerical history. Public summary contains
coverage/counts only. File publication/receipt time is not measurement time.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'owner-ui'))
from panel_data import SafeTree, strict_json, number
from evidence_lib import write_json

FIELDS = ('OriginalVolume_mL', 'EstimatedVolumeDispensed_ml', 'CumulativeDispenseTime_s',
          'DispenseCount', 'WriteCount', 'VolumePrinted_mm3', 'NumLayersPrinted',
          'PrintTime_mS', 'LastResinLevel_mm')
INDEX = 'consumable-state/snapshots.private.jsonl'
HEX = re.compile(r'[a-f0-9]{64}')


def review(session, index_path=INDEX):
    # A continuation is sealed by the original session manifest. Never accept
    # arbitrary paths or use a sibling object's bytes as a substitute.
    if not isinstance(index_path, str) or not re.fullmatch(
            r'(?:continuations/[A-Za-z0-9_-]{1,128}/)?' + re.escape(INDEX), index_path):
        raise ValueError('Expected root or named continuation snapshot index')
    prefix = index_path[:-len(INDEX)]
    tree = SafeTree(session)
    try:
        manifest_raw = tree.read('SESSION_SHA256.json', 4 << 20)
        manifest = strict_json(manifest_raw)
        entries = manifest.get('files') if isinstance(manifest, dict) else None
        if not isinstance(entries, list) or len(entries) > 20000:
            raise ValueError('Invalid sealed manifest')
        sealed = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
                raise ValueError('Invalid manifest row')
            path = entry['path']
            if path in sealed: raise ValueError('Duplicate manifest path')
            if (not isinstance(entry.get('sha256'), str) or not HEX.fullmatch(entry['sha256'])
                    or type(entry.get('bytes')) is not int or entry['bytes'] < 0):
                raise ValueError('Invalid manifest pin')
            sealed[path] = entry

        def read(relative, limit):
            if relative not in sealed: raise ValueError('Unsealed input')
            raw = tree.read(relative, limit)
            row = sealed[relative]
            if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('Capture integrity mismatch')
            return raw

        index = read(index_path, 16 << 20)
        if index and not index.endswith(b'\n'): raise ValueError('Truncated snapshot index')
        lines = index.splitlines()
        if not 1 <= len(lines) <= 10000: raise ValueError('Snapshot count bound')
        objects = {}; records = {}; snapshots = []; total = 0; unstable = 0
        for line in lines:
            if len(line) > 256 << 10: raise ValueError('Snapshot line bound')
            row = strict_json(line)
            if not isinstance(row, dict) or not isinstance(row.get('files'), list) or len(row['files']) > 520:
                raise ValueError('Invalid snapshot')
            epoch = number(row.get('device_epoch'), 0, 1e11)
            mono = number(row.get('device_monotonic'), 0, 1e12)
            if epoch is None or mono is None: raise ValueError('Invalid snapshot time')
            snapshots.append((epoch, mono))
            seen = set()
            for file in row['files']:
                if not isinstance(file, dict): raise ValueError('Invalid file row')
                path = file.get('path')
                if not isinstance(path, str) or len(path) > 512: raise ValueError('Invalid file path')
                if path in seen: raise ValueError('Duplicate snapshot file')
                seen.add(path)
                match = re.fullmatch(r'/data/(Cartridges|Tanks)/[A-Za-z0-9_-]{1,128}\.json', path)
                if not match: continue  # No arbitrary path, database or unknown secret key export.
                sha = file.get('sha256')
                if not isinstance(sha, str) or not HEX.fullmatch(sha): raise ValueError('Invalid object pin')
                if sha not in objects:
                    raw = read(prefix+'consumable-state/objects/'+sha, 65536)
                    total += len(raw)
                    if len(objects) >= 4096 or total > 64 << 20: raise ValueError('Object budget')
                    if hashlib.sha256(raw).hexdigest() != sha: raise ValueError('Object name mismatch')
                    obj = strict_json(raw)
                    if not isinstance(obj, dict): raise ValueError('Expected consumable object')
                    values = {key:number(obj.get(key), -100 if key=='LastResinLevel_mm' else 0, 1e12) for key in FIELDS}
                    objects[sha] = (len(raw), values)
                size, values = objects[sha]
                if type(file.get('bytes')) is not int or file['bytes'] != size: raise ValueError('Object length mismatch')
                if type(file.get('stable_metadata')) is not bool: raise ValueError('Missing stability evidence')
                unstable += not file['stable_metadata']
                group = hashlib.sha256(path.encode('utf-8')).hexdigest()
                record = records.setdefault(group, {'kind':'tank' if match[1]=='Tanks' else 'cartridge',
                    'record_name_sha256':group, 'observations':[]})
                record['observations'].append({'receipt_epoch':epoch, 'receipt_monotonic':mono,
                    'file_mtime':number(file.get('mtime'), 0, 1e11), 'stable_metadata':file['stable_metadata'],
                    'source_sha256':sha, 'values':values, 'state':'HISTORICAL',
                    'measurement_time':None, 'physical_volume_proven':False})
        result = {'schema_version':1, 'state':'HISTORICAL',
            'index_path':index_path,
            'manifest_sha256':hashlib.sha256(manifest_raw).hexdigest(),
            'index_sha256':hashlib.sha256(index).hexdigest(),
            'snapshots':len(snapshots), 'unique_objects':len(objects), 'verified_object_bytes':total,
            'first_receipt_epoch':snapshots[0][0], 'last_receipt_epoch':snapshots[-1][0],
            'largest_snapshot_gap_seconds':max([b[0]-a[0] for a,b in zip(snapshots,snapshots[1:])] or [0]),
            'monotonic_discontinuities':sum(b[1]<a[1] for a,b in zip(snapshots,snapshots[1:])),
            'unstable_file_observations':unstable, 'records':list(records.values()),
            'device_chip_image':False, 'full_print_coverage_proven':False,
            'measurement_age_proven':False, 'native_counter_reset_performed':False}
        for record in result['records']:
            changes = collections.Counter(); decreases = collections.Counter()
            for a,b in zip(record['observations'], record['observations'][1:]):
                for key in FIELDS:
                    av,bv = a['values'][key],b['values'][key]
                    if av is not None and bv is not None:
                        changes[key] += av != bv
                        decreases[key] += bv < av
            record['changed_observations'] = dict(changes)
            record['decreasing_observations'] = dict(decreases)
        summary = {key:result[key] for key in ('schema_version','manifest_sha256','index_sha256','snapshots',
            'unique_objects','verified_object_bytes','monotonic_discontinuities','unstable_file_observations',
            'device_chip_image','full_print_coverage_proven','measurement_age_proven','native_counter_reset_performed')}
        summary['record_counts'] = dict(collections.Counter(r['kind'] for r in records.values()))
        return result, summary
    finally:
        tree.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',required=True);p.add_argument('--output',required=True)
    p.add_argument('--summary',required=True)
    p.add_argument('--index', default=INDEX,
                   help='Sealed root or continuations/NAME/consumable-state/snapshots.private.jsonl')
    a=p.parse_args();os.umask(0o077)
    target=Path(a.output).absolute()
    if 'research-private' not in target.parts or target.resolve().is_relative_to(Path(a.session).resolve()):
        raise ValueError('New private output outside captured session required')
    result,summary=review(a.session,a.index)
    write_json(target,result);write_json(a.summary,summary)
    print(json.dumps(summary,sort_keys=True))


if __name__=='__main__':main()
