#!/usr/bin/env python3
"""Stream a sealed multi-boot print capture into a bounded, redacted progress review.

Checks each consumed stream/chunk hash. Does not reconstruct models or infer print
success from a task finish, and never promotes a temperature into a level reading.
No network, firmware execution, repair or device command.
"""
import argparse
import base64
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from analyze_print_session import SignalReader, HEADER, numeric, STATE_NAMES
from record_print_session import validate_event
from evidence_lib import write_json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-ui'))
from panel_data import SafeTree, strict_json

MAX_BYTES=4 << 30
MAX_EVENTS=2000000


class Progress:
    def __init__(self):
        self.boots={};self.current=None;self.seen=set();self.duplicates=0
    def boot(self,identity):
        if identity not in self.boots:
            if len(self.boots)>=64:raise ValueError('Boot budget')
            self.boots[identity]={'index':len(self.boots)+1,'layer_events':0,'layer_indices':set(),
                'first_positive_layer_epoch':None,'last_positive_layer_epoch':None,
                'tasks':{},'states':{},'unknown_state_values_omitted':0,'temperatures':{},'finished_events':0,'aborted_events':0}
        self.current=self.boots[identity]
    def signal(self,raw):
        lines=raw.decode('utf-8',errors='replace').splitlines()
        m=HEADER.fullmatch(lines[0]) if lines else None
        if not m:return
        stamp,path,interface,member=m.groups();stamp=float(stamp)
        if not numeric(stamp):return
        b=self.current;body='\n'.join(lines[1:])
        if interface=='com.formlabs.Sauron' and path=='/com/formlabs/Sauron':
            if member not in ('currentlyPrintingLayerChanged','statesChanged','finished','aborted'):return
            signature=(b['index'],hashlib.sha256(raw).digest())
            if signature in self.seen:self.duplicates+=1;return
            if len(self.seen)>=100000:raise ValueError('State-event budget')
            self.seen.add(signature)
            strings=re.findall(r'^\s*string "([A-Za-z0-9{}_\-]{0,128})"\s*$',body,re.M)
            task=hashlib.sha256(strings[0].encode()).hexdigest() if strings else None
            if member=='currentlyPrintingLayerChanged':
                nums=re.findall(r'^\s*(?:int32|uint32) ([0-9]{1,7})\s*$',body,re.M)
                if len(nums)!=1 or task is None:return
                index=int(nums[0])
                if index>1000000:raise ValueError('Layer index budget')
                b['layer_events']+=1;b['layer_indices'].add(index)
                if len(b['tasks'])>=128 and task not in b['tasks']:raise ValueError('Task budget')
                t=b['tasks'].setdefault(task,{'first_layer_epoch':stamp,'last_layer_epoch':stamp,'max_layer_index':index,'finish_after_layer':False})
                t['last_layer_epoch']=stamp;t['max_layer_index']=max(t['max_layer_index'],index)
                if index>0:
                    if b['first_positive_layer_epoch'] is None:b['first_positive_layer_epoch']=stamp
                    b['last_positive_layer_epoch']=stamp
            elif member in ('finished','aborted'):
                b[member+'_events']+=1
                if member=='finished' and task in b['tasks'] and stamp>=b['tasks'][task]['last_layer_epoch']:
                    b['tasks'][task]['finish_after_layer']=True
            elif member=='statesChanged':
                b['unknown_state_values_omitted'] += sum(s not in STATE_NAMES for s in strings)
                for state in set(s for s in strings if s in STATE_NAMES):
                    if len(b['states'])>=256 and state not in b['states']:raise ValueError('State label budget')
                    item=b['states'].setdefault(state,{'first':stamp,'last':stamp,'events':0})
                    item['last']=stamp;item['events']+=1
        elif interface=='com.formlabs.Temperature' and member=='temperature':
            allowed={'/com/formlabs/momo/temperatures/'+n:n for n in ('Tower','ForceSense','Levelsense')}
            if path not in allowed:return
            match=re.fullmatch(r'\s*struct \{\s*boolean (true|false)\s+double (-?[0-9.eE+]+)\s*\}\s*',body)
            if not match:return
            try:value=float(match[2])
            except ValueError:return
            t=b['temperatures'].setdefault(allowed[path],{'samples':0,'flagged':0,'min_celsius':None,'max_celsius':None})
            if match[1]=='true':t['flagged']+=1;return
            if not numeric(value,-50,150):return
            t['samples']+=1;t['min_celsius']=value if t['min_celsius'] is None else min(value,t['min_celsius'])
            t['max_celsius']=value if t['max_celsius'] is None else max(value,t['max_celsius'])
    def result(self):
        rows=[]
        for b in self.boots.values():
            row={k:v for k,v in b.items() if k not in ('layer_indices','tasks')}
            indices=sorted(b['layer_indices'])
            row.update(max_layer_index=max(indices) if indices else None,unique_layer_indices=len(indices),
                missing_indices_between_observed_extremes=(indices[-1]-indices[0]+1-len(indices)) if indices else 0,
                tasks_with_layers=len(b['tasks']),tasks_with_matching_finish=sum(t['finish_after_layer'] for t in b['tasks'].values()),
                print_success_proven=False,physical_fault_cause='UNKNOWN')
            rows.append(row)
        return rows


def review(session, model=None):
    tree=SafeTree(session)
    try:
        raw=tree.read('SESSION_SHA256.json',4<<20);manifest=strict_json(raw)
        if not isinstance(manifest,dict) or not isinstance(manifest.get('files'),list) or len(manifest['files'])>20000:
            raise ValueError('Invalid seal')
        sources=[];seen=set()
        for row in manifest['files']:
            if not isinstance(row,dict) or not isinstance(row.get('path'),str):raise ValueError('Invalid sealed row')
            path=row['path']
            if not re.fullmatch(r'raw/stream-[0-9]{4,6}\.jsonl',path):continue
            if path in seen:raise ValueError('Repeated sealed source')
            seen.add(path)
            if type(row.get('bytes')) is not int or not 0<=row['bytes']<=1<<30:raise ValueError('Stream byte bound')
            if not isinstance(row.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',row['sha256']):raise ValueError('Invalid stream pin')
            sources.append(row)
        if not 1<=len(sources)<=64 or sum(x['bytes'] for x in sources)>MAX_BYTES:raise ValueError('Session budget')
        if model is None:model=Progress()
        events=0;partial=0;gaps=0;checked=[]
        # Open each component without symlink following, then stream with fixed buffers.
        directory=os.open('raw',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=tree.fd)
        try:
            for source in sorted(sources,key=lambda x:x['path']):
                fd=os.open(source['path'].split('/')[1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
                import stat
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size!=source['bytes']:
                    os.close(fd);raise ValueError('Stream type/size changed')
                h=hashlib.sha256();count=0;total=0;reader=SignalReader(model.signal);boot=None
                with os.fdopen(fd,'rb') as f:
                    while True:
                        line=f.readline((2<<20)+1)
                        if not line:break
                        total+=len(line);h.update(line)
                        if len(line)>2<<20 or not line.endswith(b'\n'):raise ValueError('Truncated/oversize envelope')
                        if total>source['bytes']:raise ValueError('Growing source')
                        wrapper=strict_json(line)
                        if not isinstance(wrapper,dict) or not isinstance(wrapper.get('event'),dict):raise ValueError('Invalid envelope')
                        event=validate_event(json.dumps(wrapper['event']))
                        events+=1;count+=1
                        if events>MAX_EVENTS:raise ValueError('Event budget')
                        if boot is None:
                            if event['kind']!='identity':raise ValueError('Identity must precede data')
                            p=event['payload']
                            if p.get('kernel')!='4.9.65+' or p.get('firmware')!='2.5.6-2773' or p.get('selected_slot')!=6:
                                raise ValueError('Unsupported captured target')
                            boot=event['boot_id'];model.boot(boot)
                        if event['boot_id']!=boot:raise ValueError('Boot changed inside stream')
                        if event['kind']=='coverage_gap':gaps+=1
                        p=event['payload']
                        if event['kind']=='dbus' and p.get('channel')=='stdout':reader.feed(base64.b64decode(p['data_b64'],validate=True))
                if total!=source['bytes'] or h.hexdigest()!=source['sha256']:raise ValueError('Sealed stream mismatch')
                reader.finish();partial+=reader.partial
                checked.append({'sha256':h.hexdigest(),'bytes':total,'events':count})
        finally:os.close(directory)
        return {'schema_version':1,'state':'HISTORICAL','manifest_sha256':hashlib.sha256(raw).hexdigest(),
            'source_streams':checked,'events':events,'boots':model.result(),'coverage_gaps_reported':gaps,
            'undelimited_tail_frames_omitted':partial,'duplicate_state_frames_omitted':model.duplicates,
            'print_quality_proven':False,'continuous_sensor_coverage_proven':False,
            'measurement_units':{'layer':'native index; not count','temperature':'C'},
            'hardware_commands':False}
    finally:tree.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();out=Path(a.output).absolute()
    if 'research-private' not in out.parts or out.resolve().is_relative_to(Path(a.session).resolve()):raise ValueError('New private output outside captured session required')
    os.umask(0o077);result=review(a.session);write_json(out,result)
    print(json.dumps({'streams':len(result['source_streams']),'events':result['events'],'boots':len(result['boots']),
        'max_layer_indices':[x['max_layer_index'] for x in result['boots']], 'print_quality_proven':False}))


if __name__=='__main__':main()
