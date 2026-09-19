#!/usr/bin/env python3
"""Explicit owner SSH observation into PRIVATE laptop files; never starts a print.

run persists only for its bounded lifetime. status/mark/stop affect local capture
files only. Secrets/raw logs never appear in summaries. No discovery or cloud I/O.
"""
import argparse
import ast
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

MAX_RECORD = 2 << 20
MAX_BYTES = 4 << 30
MARKERS = {'tank_insertion_start','tank_inserted','resin_added','print_start_requested',
           'error_displayed','print_aborted','print_complete','operator_note'}


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic(path, obj):
    tmp=path.with_name('.'+path.name+'.new')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(obj,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def session_path(value):
    p=Path(os.path.abspath(value))
    if 'research-private' not in p.parts or not p.is_dir():raise ValueError('Existing private session required')
    for item in (p,)+tuple(p.parents):
        if item.is_symlink():raise ValueError('Session symlink forbidden')
    if p.stat().st_uid!=os.getuid() or p.stat().st_mode&0o077:raise ValueError('Session must be private and owned by invoking user')
    return p


def validate_event(line):
    if len(line)>MAX_RECORD:raise ValueError('Record bound')
    event=json.loads(line)
    if not isinstance(event,dict) or event.get('kind') not in ('identity','observer_started','observer_exit','coverage_gap','coverage_boundary','dbus','file','sample','processes','kernel','heartbeat','complete'):
        raise ValueError('Unknown event')
    for key in ('device_epoch','device_monotonic'):
        v=event.get(key)
        if type(v) not in (int,float) or not 0<=v<1e12:raise ValueError('Invalid event timestamp')
    if not isinstance(event.get('payload'),dict):raise ValueError('Invalid payload')
    if not isinstance(event.get('boot_id'),str) or not re.fullmatch(r'[a-f0-9-]{36}',event['boot_id']):raise ValueError('Invalid boot identity')
    p=event['payload']
    if 'data_b64' in p:
        if not isinstance(p['data_b64'],str):raise ValueError('Invalid data encoding')
        data=base64.b64decode(p['data_b64'],validate=True)
        if hashlib.sha256(data).hexdigest()!=p.get('sha256'):raise ValueError('Chunk hash mismatch')
        if 'bytes' in p and p['bytes']!=len(data):raise ValueError('Chunk length mismatch')
    return event


def run(base, config, alias, seconds):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',alias):raise ValueError('Explicit SSH alias required')
    if not 60<=seconds<=24*3600:raise ValueError('Duration must be bounded to 1 minute–24 hours')
    config=Path(config).resolve(strict=True)
    source=Path(__file__).with_name('print_capture_agent.py').read_bytes()
    ast.parse(source.decode(),feature_version=(3,5))
    tools=base/'tools';tools.mkdir(exist_ok=True,mode=0o700)
    saved=tools/'print_capture_agent.accepted.py'
    with saved.open('xb') as f:f.write(source)
    # Preserve the host collector matching this session before running it.
    with (tools/'record_print_session.accepted.py').open('xb') as f:f.write(Path(__file__).read_bytes())
    raw=base/'raw';raw.mkdir(exist_ok=True,mode=0o700)
    (base/'metadata').mkdir(exist_ok=True,mode=0o700)
    status={'schema':1,'state':'starting','pid':os.getpid(),'started_utc':utc(),'deadline_seconds':seconds,
            'source_sha256':hashlib.sha256(source).hexdigest(),'bytes':0,'connections':0,'events':0,
            'event_counts':{},'coverage_gaps':0,'automatic_printer_writes':False,'printing_commands':False,
            'capture_scope':'selected regular logs, proc/sys snapshots and selected passive D-Bus signals'}
    atomic(base/'metadata/capture-config.private.json',{'ssh_config':str(config),'ssh_alias':alias,'seconds':seconds,'max_bytes':MAX_BYTES})
    start=time.monotonic();stop=False;sequence=0;last_write=0;identities=[]
    def request_stop(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,request_stop);signal.signal(signal.SIGINT,request_stop)
    try:
        while not stop and time.monotonic()-start<seconds and status['bytes']<MAX_BYTES:
            if (base/'STOP').exists():break
            sequence+=1;status['connections']=sequence;status['state']='connecting';atomic(base/'status.json',status)
            path=raw/('stream-%04d.jsonl'%sequence);err=raw/('ssh-%04d.stderr'%sequence)
            cmd=['ssh','-F',str(config),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                 '-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no',
                 '-o','ConnectTimeout=8','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2',alias,
                 'env -i PATH=/usr/bin:/bin LC_ALL=C /usr/bin/python3 -E -B -S -u -']
            seen_identity=False;connection_start=time.monotonic();last_data=connection_start;buf=b''
            with err.open('xb') as error_log, path.open('xb') as output:
                process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=error_log,start_new_session=True)
                status['ssh_pid']=process.pid
                try:
                    process.stdin.write(source);process.stdin.close()
                    sel=selectors.DefaultSelector();sel.register(process.stdout,selectors.EVENT_READ)
                    while not stop and time.monotonic()-start<seconds and time.monotonic()-connection_start<1860:
                        if (base/'STOP').exists():stop=True;break
                        if status['bytes']>=MAX_BYTES:stop=True;status['stop_reason']='4-GiB capture bound';break
                        if not seen_identity and time.monotonic()-connection_start>25:break
                        if seen_identity and time.monotonic()-last_data>30:
                            status['coverage_gaps']+=1;break
                        ready=sel.select(1)
                        if not ready:
                            if process.poll() is not None:break
                            continue
                        data=os.read(process.stdout.fileno(),65536)
                        if not data:break
                        last_data=time.monotonic()
                        buf+=data
                        if len(buf)>MAX_RECORD and b'\n' not in buf:raise ValueError('Unbounded remote record')
                        while b'\n' in buf:
                            line,buf=buf.split(b'\n',1)
                            event=validate_event(line)
                            if not seen_identity:
                                p=event['payload']
                                if event['kind']!='identity' or p.get('uid')!=0 or p.get('firmware')!='2.5.6-2773' or p.get('kernel')!='4.9.65+' or p.get('selected_slot')!=6 or p.get('owner_version')!='0.5.8-review':
                                    raise ValueError('Live identity invariant failed')
                                seen_identity=True;status['state']='recording'
                                identities.append({'connection':sequence,'boot_id':event['boot_id'],'host_utc':utc()})
                                status['boot_count']=len(set(x['boot_id'] for x in identities))
                            received={'laptop_received_utc':utc(),'laptop_monotonic':time.monotonic(),'connection':sequence,'event':event}
                            row=(json.dumps(received,sort_keys=True,separators=(',',':'))+'\n').encode()
                            if status['bytes']+len(row)>MAX_BYTES:stop=True;status['stop_reason']='4-GiB capture bound';break
                            output.write(row);status['bytes']+=len(row);status['events']+=1
                            kind=event['kind'];status['event_counts'][kind]=status['event_counts'].get(kind,0)+1
                            status['last_event_utc']=received['laptop_received_utc'];status['last_event_monotonic']=received['laptop_monotonic']
                            if kind=='heartbeat':status['remote_heartbeat']=event['payload']
                            if kind=='sample':status['temperatures_celsius']={n:v['celsius'] for n,v in event['payload'].get('thermal',{}).items()}
                            if kind=='observer_started':status.setdefault('observers',{})[event['payload']['observer']]='started'
                            if kind=='observer_exit':status.setdefault('observers',{})[event['payload']['observer']]='exited'
                            if kind=='coverage_gap':status['coverage_gaps']+=1
                            if kind=='dbus':
                                p=event['payload'];chunk=base64.b64decode(p['data_b64'])
                                if p.get('channel')=='stderr':status['dbus_stderr_bytes']=status.get('dbus_stderr_bytes',0)+len(chunk)
                                else:status['dbus_stdout_bytes']=status.get('dbus_stdout_bytes',0)+len(chunk)
                            if time.monotonic()-last_write>=2:
                                output.flush();os.fsync(output.fileno());status['saved_through_utc']=received['laptop_received_utc'];atomic(base/'status.json',status);last_write=time.monotonic()
                    sel.close()
                    if buf:
                        (raw/('partial-%04d.private'%sequence)).write_bytes(buf);status['coverage_gaps']+=1
                finally:
                    if process.poll() is None:process.terminate()
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                    output.flush();os.fsync(output.fileno())
            status['last_ssh_exit']=process.returncode
            error_text=err.read_text(errors='replace')
            if any(token in error_text for token in ('REMOTE HOST IDENTIFICATION HAS CHANGED','Host key verification failed','Permission denied (publickey','no such identity:')):
                status['state']='blocked';status['stop_reason']='SSH trust/credentials failure; verification unchanged';break
            if not seen_identity and process.returncode not in (255,-15):
                status['state']='blocked';status['stop_reason']='Remote observer failed before validated identity';break
            if stop:break
            status['state']='reconnecting';status['coverage_gaps']+=1;atomic(base/'status.json',status)
            for _ in range(5):
                if stop or (base/'STOP').exists():stop=True;break
                time.sleep(1)
        if status['state']!='blocked':status['state']='stopped'
        status.setdefault('stop_reason','operator stop or bounded duration')
    except Exception as e:
        status['state']='blocked';status['stop_reason']=type(e).__name__+'; inspect private runner log'
        raise
    finally:
        status['ended_utc']=utc();status['elapsed_seconds']=time.monotonic()-start;atomic(base/'status.json',status)
        atomic(base/'metadata/connections.private.json',identities)
        files=[]
        for path in sorted(raw.iterdir()):
            if not path.is_file() or path.is_symlink():continue
            h=hashlib.sha256()
            with path.open('rb') as f:
                for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
            files.append({'path':str(path.relative_to(base)),'bytes':path.stat().st_size,'sha256':h.hexdigest()})
        atomic(base/'metadata/raw-sha256.json',{'files':files,'originals_retained':True})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('run','status','mark','stop'))
    p.add_argument('--session',required=True);p.add_argument('--ssh-config');p.add_argument('--ssh-alias')
    p.add_argument('--seconds',type=int,default=12*3600);p.add_argument('--event',choices=sorted(MARKERS));p.add_argument('--note',default='')
    args=p.parse_args();os.umask(0o077);base=session_path(args.session)
    if args.command=='run':run(base,args.ssh_config,args.ssh_alias,args.seconds)
    elif args.command=='status':
        obj=json.loads((base/'status.json').read_text());obj['data_age_seconds']=time.monotonic()-obj.get('last_event_monotonic',time.monotonic())
        print(json.dumps(obj,indent=2,sort_keys=True))
    elif args.command=='stop':
        with (base/'STOP').open('x') as f:f.write(utc()+'\n')
        print('Requested local capture stop; no printer command sent.')
    else:
        if not args.event or len(args.note)>500:raise ValueError('Bounded named marker required')
        with (base/'metadata/operator-markers.private.jsonl').open('a') as f:
            f.write(json.dumps({'event':args.event,'note':args.note,'laptop_utc':utc(),'laptop_monotonic':time.monotonic()})+'\n');f.flush();os.fsync(f.fileno())
        print('Saved private operator marker; no printer action sent.')


if __name__=='__main__':
    main()
