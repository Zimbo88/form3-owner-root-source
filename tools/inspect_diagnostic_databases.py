#!/usr/bin/env python3
"""Classify copied diagnostic SQLite MAIN files, with identifiers/payloads excluded.

Reads a private byte copy using immutable/query-only SQLite. WAL/journal contents
are not replayed. Counts are task/event records, never a successful-print count.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from evidence_lib import open_evidence, write_json

SCHEMAS={
 'durations':('Durations',('Timestamp','GUID','Print_GUID','Print_Layer','Name','Duration_ms','Context','Data')),
 'consumables':('TankCartridgeDaemon',('Id','AutoTimestamp','DeviceID','ConsumableType','EventName'))}


def inspect(path,kind):
    if kind not in SCHEMAS:raise ValueError('Known database class required')
    with open_evidence(path) as f:raw=f.read((8<<20)+1)
    if len(raw)>8<<20 or not raw.startswith(b'SQLite format 3\0'):raise ValueError('Bounded SQLite main file required')
    table,columns=SCHEMAS[kind]
    with tempfile.TemporaryDirectory(prefix='owner-diagnostic-db-') as directory:
        copy=Path(directory)/'main.sqlite';copy.write_bytes(raw);copy.chmod(0o400)
        con=sqlite3.connect(copy.as_uri()+'?mode=ro&immutable=1',uri=True)
        budget=[0]
        def progress():
            budget[0]+=1
            return int(budget[0]>10000)
        con.set_progress_handler(progress,1000)
        try:
            con.execute('PRAGMA query_only=ON');con.execute('PRAGMA trusted_schema=OFF')
            typ=con.execute('SELECT type FROM sqlite_master WHERE name=?',(table,)).fetchall()
            if typ!=[('table',)]:raise ValueError('Expected reviewed physical table')
            actual=tuple(r[1] for r in con.execute('PRAGMA table_info("'+table+'")'))
            if actual!=columns:raise ValueError('Unreviewed database schema')
            count=con.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]
            if count>10000:raise ValueError('Row budget')
            out={'schema_version':1,'class':kind,'input_sha256':hashlib.sha256(raw).hexdigest(),
                'input_bytes':len(raw),'rows':count,'state':'HISTORICAL','wal_replayed':False,
                'consistent_live_snapshot_proven':False,'successful_print_count':None}
            if kind=='durations':
                data=list(con.execute('SELECT Print_Layer, Duration_ms FROM Durations'))
                valid=[duration for _,duration in data if type(duration) is int and 0<=duration<=864000000]
                out.update(rows_with_layer=sum(type(layer) is int and layer>=0 for layer,_ in data),
                    rows_without_nonnegative_layer=sum(type(layer) is not int or layer<0 for layer,_ in data),
                    valid_duration_records=len(valid),duration_min_ms=min(valid) if valid else None,
                    duration_max_ms=max(valid) if valid else None)
            else:
                classes=collections.Counter()
                for (kind_value,) in con.execute('SELECT ConsumableType FROM TankCartridgeDaemon'):
                    value=kind_value.lower() if isinstance(kind_value,str) else ''
                    classes[value if value in ('tank','cartridge') else 'unknown']+=1
                out['record_types']=dict(classes)
            return out
        finally:con.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('--kind',choices=SCHEMAS,required=True);p.add_argument('--output',required=True)
    a=p.parse_args();out=inspect(a.input,a.kind);write_json(a.output,out)
    print(json.dumps({'class':a.kind,'rows':out['rows'],'successful_print_count':None,'wal_replayed':False}))


if __name__=='__main__':main()
