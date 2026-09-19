#!/usr/bin/env python3
"""Create a bounded PRIVATE diagnostic/panel bundle from existing copied p6/p7.

Reads fixed logs, rotations, metrics and consumable records only. No collector,
installer, database write, journal/WAL replay or device contact. Public output is
counts, schema classifications and provenance hashes; filenames with identity and
raw jobs/logs remain private. Host tool; deployed panel needs no msgpack dependency.
"""
import argparse,collections,csv,datetime,gzip,hashlib,io,json,os,re,sqlite3,stat,struct,sys
from pathlib import Path
from evidence_lib import ROOT,safe_output,write_json
sys.path.insert(0,str(ROOT/'owner-ui'))
from panel_data import SafeTree,consumable_view,field,number,strict_json
import msgpack

TEXT_NAMES={'CandyBus.log','Formule.log','Palantir.log','TankCartridgeDaemon.log',
 'PrinterLegitimacyChecker.log','RichardNixon.log','daguerre.log','sauron.log',
 'daguerreHeater_v1.csv','core-temperature.log','syslog','factory_reset.log',
 'daguerreSurfboard.log','logrotate-daguerreHeater.log','stallguard.csv','RollerBusChurnMonitor.log'}
METRIC_NAMES={'cpu','disk_io','memory','netif_eth0','netif_wlan0','thermal'}
PROCESS_NAMES={'bonsoir','candybus','connmand','dbus_daemon','fluent_bit','formule','galvatron',
 'palantir','python3','rfidbus_buildplatform','rfidbus_tank','richard_nixon','sauron',
 'tank_cartridge_daemon','wpa_supplicant','zerotier_one'}
METRIC_KEYS={'cpu_p','user_p','system_p','Mem.total','Mem.used','Mem.free','Swap.total','Swap.used','Swap.free',
 'temperature','temp','name','type','thermal_zone','cpu_thermal','gpu_thermal','core_thermal','dspeve_thermal','iva_thermal',
 'alive','proc_name','pid','VmPeak','VmSize','VmRSS','read_size','write_size','eth0.rx.bytes','eth0.tx.bytes','wlan0.rx.bytes','wlan0.tx.bytes'}
CATEGORIES={'error_293':rb'(?i)(?:error(?:code)?[= :"\t]+293\b|ResetWhilePrinting|reset while printing)',
 'error_statement':rb'(?i)(?:level=error\b|\bERROR\b|Traceback \(most recent call last\))',
 'warning_statement':rb'(?i)(?:level=warning\b|\bWARNING\b)',
 'heating_reference':rb'(?i)heater|heating|temperature',
 'lpu_reference':rb'(?i)\bLPU\b|optics|laser',
 'network_failure':rb'(?i)network is unreachable|connection refused|no such host|i/o timeout',
 'reset_reference':rb'(?i)factory.reset|watchdog|reset while printing',
 'kernel_boot':rb'Linux version |Kernel command line:'}


def decode_metrics(raw):
    if len(raw)>8<<20:raise ValueError('Metric input budget')
    unpacker=msgpack.Unpacker(raw=False,strict_map_key=False,max_buffer_size=8<<20,
        max_str_len=65536,max_bin_len=65536,max_array_len=4096,max_map_len=4096,max_ext_len=4096)
    unpacker.feed(raw);rows=[];last_end=0
    for i,item in enumerate(unpacker):
        if i>=100000:raise ValueError('Metric record budget')
        if not isinstance(item,(list,tuple)) or len(item)!=2 or not isinstance(item[1],dict):
            raise ValueError('Unexpected metric frame')
        stamp=item[0]
        if isinstance(stamp,msgpack.ExtType) and stamp.code==0 and len(stamp.data)==8:
            sec,nsec=struct.unpack('>II',stamp.data)
            if nsec>=1000000000:raise ValueError('Invalid EventTime nanoseconds')
            stamp=sec+nsec/1e9
        if number(stamp,0,1e11) is None:raise ValueError('Unknown metric time')
        # Drop unknown dictionary keys entirely; they can be secrets.
        values={k:v for k,v in item[1].items() if isinstance(k,str) and k in METRIC_KEYS and
                ((isinstance(v,(int,float)) and not isinstance(v,bool) and number(v,-1e12,1e12) is not None) or
                 (k in {'name','type','thermal_zone'} and v in {'cpu_thermal','gpu_thermal','core_thermal','dspeve_thermal','iva_thermal'}))}
        rows.append({'timestamp':stamp,'values':values});last_end=unpacker.tell()
    if last_end!=len(raw):raise ValueError('Truncated MessagePack tail')
    return rows


def thermal_history(rows):
    """Bounded acquired thermal history; device-clock gaps are not interpolated.

    300 seconds is an owner display segmentation threshold, not a printer safety
    limit or proof of an NTP adjustment. No conclusions about heater/LPU health.
    """
    if not isinstance(rows,list) or len(rows)>100000:raise ValueError('Thermal record budget')
    channels={n:[] for n in ('cpu_thermal','gpu_thermal','core_thermal','dspeve_thermal','iva_thermal')}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('values'),dict):raise ValueError('Invalid thermal row')
        values=row['values'];name=values.get('type')
        if name not in channels:continue
        timestamp=number(row.get('timestamp'),0,1e11);value=number(values.get('temp'),-273.15,1000)
        if timestamp is None or value is None:continue
        channels[name].append({'timestamp':timestamp,'celsius':value})
    result=[]
    for name,samples in sorted(channels.items()):
        if not samples:continue
        deltas=[b['timestamp']-a['timestamp'] for a,b in zip(samples,samples[1:])]
        points=[]
        for i,sample in enumerate(samples[-60:]):
            delta=sample['timestamp']-points[-1]['timestamp'] if points else None
            points.append(dict(sample,continuous_from_previous=delta is not None and 0<delta<=300))
        result.append({'name':name,'state':'HISTORICAL','unit':'C','samples':len(samples),
            'min_celsius':min(x['celsius'] for x in samples),'max_celsius':max(x['celsius'] for x in samples),
            'backward_clock_steps':sum(x<0 for x in deltas),'duplicate_timestamps':sum(x==0 for x in deltas),
            'gaps_over_300_seconds':sum(x>300 for x in deltas),'largest_gap_seconds':max(deltas) if deltas else None,
            'points':points,'timestamps_verified_against_external_clock':False,'safety_assessment':'UNKNOWN'})
    return result


def allowed_log(path):
    base=path.split('/')[-1]
    if path.count('/')>2 or not path.startswith('logs/') or ('/' in path[5:] and not path.startswith('logs/old/')):return False
    stem=re.sub(r'(?:\.[0-9]{1,3})?(?:\.gz)?$','',base)
    return stem in TEXT_NAMES or base in TEXT_NAMES


def read_bounded(tree,path,limit=8<<20):
    raw=tree.read(path,limit)
    if path.endswith('.gz'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
            decoded=f.read(limit+1)
        if len(decoded)>limit:raise ValueError('Decompression budget exceeded')
        return raw,decoded
    return raw,raw


def build(p6,p7,output,view="unreplayed"):
    if view not in ("unreplayed","clone-reconstructed"):raise ValueError("Unknown view")
    p6=Path(p6).absolute();p7=Path(p7).absolute();out=safe_output(output)
    if not out.resolve().is_relative_to(ROOT/'research-private'):raise ValueError('Private output required')
    out.mkdir(mode=0o700);(out/'raw').mkdir(mode=0o700)
    trees={k:SafeTree(v) for k,v in [('p6',p6),('p7',p7)]}
    provenance=[];diagnostics=[];metrics=[];sqlite_rows=[];raw_id=0;total=0
    try:
        # os.walk never follows links; SafeTree enforces every path component again.
        paths=[]
        for d,dirs,files in os.walk(p7/'logs',followlinks=False):
            if len(paths)>256:raise ValueError('Log enumeration budget')
            for n in files:
                if len(paths)>=256:raise ValueError('Log enumeration budget')
                paths.append(str((Path(d)/n).relative_to(p7)))
        for path in sorted(paths):
            if not allowed_log(path):continue
            src,raw=read_bounded(trees['p7'],path);total+=len(raw)
            if total>64<<20:raise ValueError('Total plaintext budget exceeded')
            file_id='log-%03d'%raw_id;raw_id+=1;dst=out/'raw'/(file_id+'.log');dst.write_bytes(raw);dst.chmod(0o600)
            digest=hashlib.sha256(src).hexdigest();service=re.sub(r'(?:\.[0-9]+)?(?:\.gz)?$','',path.split('/')[-1])
            st=(p7/path).stat();per_day=collections.Counter()
            for line in raw.splitlines():
                m=re.search(rb'(?<!\d)(20\d\d-\d\d-\d\d)[T ]',line)
                date=m[1].decode() if m else None
                for category,pattern in CATEGORIES.items():
                    if re.search(pattern,line):per_day[(date,category)]+=1
            for (date,category),count in sorted(per_day.items(),key=lambda x:(x[0][0] or '',x[0][1])):
                diagnostics.append({'file_id':file_id,'service':service,'date':date,'category':category,
                    'count':count,'source_sha256':digest,'state':'HISTORICAL'})
            provenance.append({'file_id':file_id,'path_class':path,'source_sha256':digest,'size':len(src),
                'decoded_size':len(raw),'mtime_copied_tree':st.st_mtime,'lines':raw.count(b'\n'),
                'raw_export_excludes_key_stores':True})
        for path in sorted(paths):
            name=path.split('/')[-1]
            if name not in {'fluentbit_system_'+k+'.msgpack' for k in METRIC_NAMES}|{'fluentbit_process_health_'+k+'.msgpack' for k in PROCESS_NAMES}:continue
            raw=trees['p7'].read(path,8<<20)
            row={'path':path,'source_sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
            try:
                decoded=decode_metrics(raw);row.update(records=len(decoded),first_time=decoded[0]['timestamp'] if decoded else None,last_time=decoded[-1]['timestamp'] if decoded else None)
                # Full allowlisted numeric metrics are private; published summary has counts only.
                (out/(name+'.json')).write_text(json.dumps(decoded));(out/(name+'.json')).chmod(0o600)
                row['latest']=decoded[-1] if decoded else None
                if name=='fluentbit_system_thermal.msgpack':
                    last={}
                    for sample in decoded:
                        kind=sample['values'].get('type')
                        if kind:last[kind]=sample
                    row['channels']=[{'name':k,'observation':field(v['values'].get('temp'),'HISTORICAL','p7:/'+path,'C',v['timestamp'])} for k,v in sorted(last.items())]
                    row['thermal_history']=thermal_history(decoded)
            except (ValueError,msgpack.UnpackException,TypeError):row['decode']='invalid_or_unsupported'
            metrics.append(row)
        for name in ['Durations_v1.sqlite','TankCartridgeDaemon_v1.sqlite']:
            path='logs/'+name;raw=trees['p7'].optional(path,8<<20)
            if raw is None:continue
            target=out/name;target.write_bytes(raw);target.chmod(0o600)
            row={'path':path,'source_sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),
                 'wal_present':trees['p7'].optional(path+'-wal',8<<20) is not None,'tables':[]}
            # immutable=1 explicitly ignores WAL; copied main file remains baseline.
            conn=sqlite3.connect(target.as_uri()+'?mode=ro&immutable=1',uri=True)
            try:
                conn.execute('PRAGMA query_only=ON')
                for table, in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                    if table not in {'Durations','TankCartridgeDaemon','Events','durations','events'}:
                        row['tables'].append({'name_sha256':hashlib.sha256(table.encode()).hexdigest(),'row_count':None});continue
                    count=conn.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]
                    row['tables'].append({'name':table,'row_count':count})
            finally:conn.close()
            sqlite_rows.append(row)
        consumables=[]
        for folder,kind in [('Cartridges','cartridge'),('Tanks','tank')]:
            entries=list((p7/folder).iterdir()) if (p7/folder).is_dir() else []
            if len(entries)>128:raise ValueError('Consumable record budget')
            for path in entries:
                raw=trees['p7'].read(folder+'/'+path.name,65536)
                consumables.append(consumable_view(raw,kind,path.stat().st_mtime))
        jobs=[];private_jobs=[];job_bytes=0
        for d,ds,fs in os.walk(p7/'jobs',followlinks=False):
            if len(Path(d).relative_to(p7).parts)>4:raise ValueError('Job directory depth budget')
            for name in fs:
                if len(jobs)>=256:raise ValueError('Job file count budget')
                path=Path(d)/name;rel=str(path.relative_to(p7));raw=trees['p7'].read(rel,16<<20)
                job_bytes+=len(raw)
                if job_bytes>64<<20:raise ValueError('Job total byte budget')
                digest=hashlib.sha256(raw).hexdigest();kind='unknown';metadata=None
                if raw.startswith(b'PK\x03\x04'):kind='zip_container_unvalidated'
                elif raw.lstrip().startswith((b'{',b'[')):
                    try:metadata=strict_json(raw);kind='json_metadata'
                    except ValueError:kind='invalid_json'
                if b'UntaredReading_adc\tTaredWeight_state' in raw[:2048]:kind='historical_weight_sensor_tsv'
                elif b'LayerNumber\tState\tFault\tChannel0' in raw[:4096]:kind='historical_force_sensor_tsv'
                row={'file_sha256':digest,'size':len(raw),'kind':kind,'state':'HISTORICAL',
                     'complete_job_payload':False,'original_mesh_recovered':False,'preview_available':False}
                jobs.append(row);private_jobs.append(dict(row,source_path=rel,metadata=metadata,mtime_copied_tree=path.stat().st_mtime))
        ping_raw=trees['p7'].optional('printernet_client/ping.json',2<<20)
        ping_jobs=[]
        if ping_raw:
            ping=strict_json(ping_raw)
            if not isinstance(ping,dict):raise ValueError('Invalid prepared ping container')
            payload=ping.get('payload',{})
            if not isinstance(payload,dict):raise ValueError('Invalid prepared payload container')
            status=payload.get('device_status',{})
            if not isinstance(status,dict):raise ValueError('Invalid prepared status container')
            entries=status.get('print_jobs',[])
            if not isinstance(entries,list) or len(entries)>512:raise ValueError('Job metadata budget')
            for i,entry in enumerate(entries):
                if not isinstance(entry,dict):continue
                job_view={'index':i+1,'state':'HISTORICAL','source':'p7:/printernet_client/ping.json payload.device_status.print_jobs','source_sha256':hashlib.sha256(ping_raw).hexdigest(),
                    'name':'Private name retained in private-jobs-catalog.json','complete_job_payload':False,'original_mesh_recovered':False,
                    'layer_count':number(entry.get('layer_count')),'volume_ml':number(entry.get('volume_ml')),
                    'estimated_duration_ms':number(entry.get('estimated_duration_ms'))}
                ping_jobs.append(job_view)
                private_jobs.append({'source_class':'prepared_ping_job_metadata','source_sha256':hashlib.sha256(ping_raw).hexdigest(),'metadata':entry})
        version=strict_json(trees['p6'].read('etc/formlabs/version.json',65536)).get('build',{}).get('name')
        summary={'schema_version':1,'state':'HISTORICAL','scope':view+' filesystem view; copied files only',
                 'version':field(version,'HISTORICAL','p6:/etc/formlabs/version.json'),
                 'selected_slot':field(6,'HISTORICAL','Authenticated factory environment + acquired kernel command line'),
                 'consumables':consumables,'jobs':jobs,'print_history':ping_jobs,'sensors':metrics,
                 'faults':[r for r in diagnostics if r['category'] in {'error_293','error_statement','warning_statement'}],
                 'logs':provenance,'sqlite':sqlite_rows,'plaintext_bytes':total,
                 'live_job_state':field(),'safety_idle':field()}
        for name,value in [('panel_snapshot.json',summary),('diagnostics.json',diagnostics),('private-jobs-catalog.json',private_jobs)]:
            p=out/name;p.write_text(json.dumps(value,indent=2,sort_keys=True));p.chmod(0o600)
        safe={'schema_version':1,'plaintext_files':len(provenance),'plaintext_bytes':total,
            'sources':provenance,'metric_files':[{k:([{a:b for a,b in c.items() if a!='points'} for c in v]
                if k=='thermal_history' else v) for k,v in r.items() if k!='latest'} for r in metrics],
            'sqlite':sqlite_rows,'jobs':jobs,'print_history_metadata_count':len(ping_jobs),'consumable_records':len(consumables),
            'event_counts':dict(collections.Counter({c:sum(r['count'] for r in diagnostics if r['category']==c) for c in CATEGORIES})),
            'original_journal_replayed':False,'clone_recovery_performed':view=='clone-reconstructed','view':view,
            'limitations':['Copied/unreplayed state may be incomplete.','Keyword categories are not root-cause diagnoses.','Job names and all raw metadata remain private.','No carving or original mesh recovery performed.']}
        return safe
    finally:
        for tree in trees.values():tree.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--p6',required=True);p.add_argument('--p7',required=True);p.add_argument('--output',required=True);p.add_argument('--report',required=True);p.add_argument('--view',choices=['unreplayed','clone-reconstructed'],default='unreplayed')
    a=p.parse_args();report=build(a.p6,a.p7,a.output,a.view);write_json(a.report,report)
    print(json.dumps({k:report[k] for k in ['plaintext_files','plaintext_bytes','event_counts']}))
if __name__=='__main__':main()
