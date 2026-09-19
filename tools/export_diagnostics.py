#!/usr/bin/env python3
"""Copy allowlisted plaintext diagnostics into NEW ignored private output.

Publishes only hashes, timestamps and category counts; never raw log lines.
No vendor collectors/commands are executed. Journal/WAL recovery is not performed.
"""
import argparse,hashlib,json,os,re,stat
from pathlib import Path
from evidence_lib import ROOT,open_evidence,safe_output,write_json
ALLOW=('CandyBus.log','Formule.log','Palantir.log','TankCartridgeDaemon.log','PrinterLegitimacyChecker.log','RichardNixon.log','daguerre.log','sauron.log','daguerreHeater_v1.csv','core-temperature.log','syslog','factory_reset.log')
EVENTS={
 'heating':rb'heater|heating|temperature', 'optics_lpu':rb'\bLPU\b|optics|laser',
 'dispensing':rb'dispens|cartridge|resin level', 'error':rb'\berror\b|\bfailed\b|exception',
 'network_attempt':rb'dial tcp|connect: network is unreachable|no such host|connection refused|i/o timeout',
 'upload_reference':rb'upload|formlogs|telemetry', 'privacy_reference':rb'privacy|AllowDataCollection',
}
def historical_counts(data):
 """Fixed message/status categories only; never return captured text/identifiers."""
 allowed=('http request','http response','pingservice ping succeeded without errors','could not read settings file')
 messages=re.findall(rb'\bmsg="([^"]*)"',data)
 statuses=re.findall(rb'(?:status(?: code)?|status_code|code)[=: ]+(\d{3})\b',data)
 return {'messages':{k:messages.count(k.encode()) for k in allowed},
         'http_status':{str(k):statuses.count(str(k).encode()) for k in range(100,600) if str(k).encode() in statuses},
         'scope':'Historical local log statements, not independently observed delivery'}
def export(root,private_output):
 root=Path(root).absolute()
 if root.is_symlink() or (root/'logs').is_symlink():raise ValueError('Symlinked source directory refused')
 out=safe_output(private_output)
 if not out.resolve().is_relative_to(ROOT/'research-private'):raise ValueError('Raw logs require research-private output')
 out.mkdir(mode=0o700);rows=[];total=0
 for name in ALLOW:
  p=root/'logs'/name
  if not p.exists() and not p.is_symlink():continue
  with open_evidence(p) as f:
   st=os.fstat(f.fileno())
   if st.st_size>32<<20:raise ValueError('Individual diagnostic exceeds 32 MiB')
   data=f.read((32<<20)+1)
  if len(data)>32<<20:raise ValueError('Diagnostic grew past limit')
  total+=len(data)
  if total>128<<20:raise ValueError('Export exceeds 128 MiB')
  dst=out/name
  with dst.open('xb') as f:f.write(data)
  dst.chmod(0o600);os.utime(dst,ns=(st.st_atime_ns,st.st_mtime_ns))
  rows.append({'source':'p7:/logs/'+name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'copied_source_mtime_ns':st.st_mtime_ns,'events':{k:len(re.findall(v,data,re.I)) for k,v in EVENTS.items()},'line_count':data.count(b'\n')})
  if name=='RichardNixon.log':rows[-1]['historical_counts']=historical_counts(data)
 report={'schema_version':1,'files':rows,'bytes':total,'limitations':['No journal replay; p2/p7 need recovery, so visible files may be incomplete/stale.','mtime is copied-tree metadata; compare original filesystem inventory when exact provenance is needed.','Category counts are search evidence, not diagnoses or transmission proof.','Private raw logs may contain identity or credentials; never publish them.']}
 write_json(out/'provenance.json',report);return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('copied_p7');p.add_argument('--private-output',required=True);p.add_argument('--summary',required=True);a=p.parse_args()
 r=export(a.copied_p7,a.private_output);write_json(a.summary,r);print(json.dumps({'files':len(r['files']),'bytes':r['bytes']}))
if __name__=='__main__':main()
