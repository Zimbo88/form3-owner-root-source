#!/usr/bin/env python3
"""One offline developer check: canonical links/assets, target syntax and isolated tests.

External links are NOT fetched. Default fixture scope needs no proprietary evidence.
An evidence run requires an explicit existing acquisition workspace.
"""
from python35_grammar import parse as parse_target
import argparse,ast,hashlib,json,os,re,subprocess,sys,xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote,urlsplit
from evidence_lib import ROOT,safe_output,write_json

# Project narrative uses the maintainer's first person or impersonal evidence prose.
# Names in copyright/credits and technical "owner service" terms remain legitimate.
NARRATIVE_THIRD_PERSON = re.compile(
    r"\bMathias(?: Zimmermann)? (?:started|wanted|opened|used|requested|credits|reports|confirmed)\b"
    r"|\b(?:the|this|reference) owner (?:reported|reports|requested|confirmed|selected|opened|wanted)\b"
    r"|\bin his account\b", re.I)

def narrative_issues(text):
    return [index for index, line in enumerate(text.splitlines(), 1)
            if NARRATIVE_THIRD_PERSON.search(line)]

def source_checks(root):
    root=Path(root).resolve();errors=[];links=0;external=0;historical=[]
    for p in sorted(root.rglob('*.md')):
        rel=p.relative_to(root)
        if any(x in rel.parts for x in ('.git','research-private','build','.venv','__pycache__')):continue
        for line in narrative_issues(p.read_text(errors='replace')):
            errors.append({'file':str(rel),'line':line,'reason':'Use first-person or impersonal project narrative'})
        for target in re.findall(r'\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)',p.read_text(errors='replace')):
            target=target.strip('<>');u=urlsplit(target)
            if u.scheme or target.startswith('//'):external+=1;continue
            if not u.path:continue
            dest=(p.parent/unquote(u.path)).resolve();links+=1
            if not dest.is_relative_to(root) or not dest.exists():
                item={'file':str(rel),'target':target,'reason':'missing/outside canonical tree'}
                if rel.parts[:2]==('research','prior'):historical.append(item)
                else:errors.append(item)
    svg_count=0
    for p in sorted((root/'docs').rglob('*.svg')):
        tree=ET.fromstring(p.read_bytes());svg_count+=1
        for node in tree.iter():
            tag=node.tag.split('}')[-1]
            if tag in ('script','foreignObject','image'):errors.append({'file':str(p.relative_to(root)),'reason':'active/external SVG content'})
            for key,value in node.attrib.items():
                if key.lower().startswith('on') or (key.split('}')[-1]=='href' and not value.startswith('#')):
                    errors.append({'file':str(p.relative_to(root)),'reason':'active/external SVG attribute'})
        if not any(n.tag.endswith('desc') for n in tree):errors.append({'file':str(p.relative_to(root)),'reason':'missing accessible figure description'})
    target_files=[]
    for area in ('owner-ui','owner-maintenance'):
        for p in sorted((root/area).glob('*.py')):
            try:parse_target(p.read_text());target_files.append(str(p.relative_to(root)))
            except SyntaxError:errors.append({'file':str(p.relative_to(root)),'reason':'Python3.5 grammar mismatch'})
    return {'passed':not errors,'errors':errors,'local_links_checked':links,'external_links_not_fetched':external,
            'historical_link_warnings':historical,'svg_files_checked':svg_count,'target_grammar_files':target_files,
            'runtime_compatibility_proven_by_grammar':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--scope',choices=('fixtures','evidence'),default='fixtures');p.add_argument('--evidence-root')
    p.add_argument('--source-only',action='store_true',help='Review authored links/figures/syntax without running suites')
    a=p.parse_args();out=safe_output(a.output);report=source_checks(ROOT)
    if not a.source_only:
        log=out.with_suffix(out.suffix+'.tests.log')
        args=[sys.executable,str(ROOT/'tools/run_offline_tests.py'),'--output',str(log),'--scope',a.scope]
        if a.evidence_root:args+=['--evidence-root',a.evidence_root]
        r=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=660)
        report['test_runner_exit']=r.returncode;report['test_log_sha256']=hashlib.sha256(log.read_bytes()).hexdigest() if log.exists() else None
        report['passed']=report['passed'] and r.returncode==0
        if log.exists():
            for line in log.read_text().splitlines():
                if line.startswith('{'):
                    try:x=json.loads(line)
                    except ValueError:continue
                    if 'tests_run' in x:report.setdefault('test_groups',[]).append(x)
        if r.returncode and not log.exists():report['runner_failure']='Required isolation/runtime input unavailable; tests not passed'
    report['scope']=a.scope;report['source_only']=a.source_only;report['hardware_contact']=False
    write_json(out,report);print(json.dumps({k:v for k,v in report.items() if k not in ('historical_link_warnings','target_grammar_files')},indent=2));raise SystemExit(not report['passed'])
if __name__=='__main__':main()
