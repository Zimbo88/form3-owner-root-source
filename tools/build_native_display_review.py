#!/usr/bin/env python3
"""Build/test private native clock and root-splash candidates; NO deployment.

Uses only pinned copied evidence, authored QML/SVG and network-isolated host Qt.
The printer, vendor daemons, framebuffer, normal init and installers are never run.
"""
import argparse,hashlib,json,os,shutil,subprocess,sys,xml.etree.ElementTree as ET
from pathlib import Path
from evidence_lib import ROOT,open_evidence
from inspect_qt_resources import private_destination,MAX_INPUT
from build_native_clock_review import build as clock_build,PIN as RCC_PIN
from inspect_psplash_image import PIN as SPLASH_PIN
from build_psplash_review import build as splash_build

def validate_svg(data):
    if not isinstance(data,bytes) or len(data)>65536 or any(t in data.lower() for t in (b'<!doctype',b'<!entity')):
        raise ValueError('Bounded standalone SVG required')
    try:root=ET.fromstring(data)
    except ET.ParseError:raise ValueError('Malformed SVG')
    allowed={'svg','title','desc','rect','g','path'}
    attributes={'width','height','viewBox','role','id','aria-labelledby','fill','stroke','stroke-width','stroke-linecap','stroke-linejoin','d','x','y','rx','transform'}
    nodes=list(root.iter())
    if len(nodes)>64:raise ValueError('SVG node bound')
    for node in nodes:
        if node.tag not in {'{http://www.w3.org/2000/svg}'+t for t in allowed}:raise ValueError('Unsupported SVG element')
        if any(k not in attributes or 'url(' in v.lower() or len(v)>8192 for k,v in node.attrib.items()):raise ValueError('External/active SVG attribute refused')
    if root.tag!='{http://www.w3.org/2000/svg}svg' or root.get('width')!='1280' or root.get('height')!='720' or root.get('viewBox')!='0 0 1280 720':
        raise ValueError('Exact native SVG canvas required')
    return True

def read_pinned(path,limit,pin):
    with open_evidence(path) as f:data=f.read(limit+1)
    if len(data)>limit or hashlib.sha256(data).hexdigest()!=pin:raise ValueError('Native source pin/size failed')
    return data

def isolated(driver,args,output,log):
    if not shutil.which('bwrap'):raise ValueError('Missing mandatory bwrap isolation')
    cmd=['bwrap','--unshare-user','--unshare-net','--unshare-pid','--new-session','--die-with-parent','--clearenv',
         '--setenv','PATH','/usr/bin','--setenv','QT_QPA_PLATFORM','offscreen','--setenv','QT_QUICK_BACKEND','software',
         '--setenv','QSG_RENDER_LOOP','basic','--setenv','XDG_RUNTIME_DIR','/tmp/qt-runtime',
         '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--symlink','usr/bin','/bin',
         '--dir','/etc','--ro-bind','/etc/fonts','/etc/fonts','--tmpfs','/home','--tmpfs','/root','--tmpfs','/tmp','--dev','/dev','--proc','/proc',
         '--ro-bind','/var/cache/fontconfig','/var/cache/fontconfig','--setenv','XDG_CACHE_HOME','/tmp/font-cache',
         '--ro-bind',str(ROOT),'/work','--bind',str(output),'/review','/usr/bin/python3','-B','/work/tests/'+driver]+args
    with log.open('x') as stream:result=subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,timeout=60)
    if result.returncode:raise ValueError('Isolated authored Qt driver failed; inspect private log')

def build(rootfs,output):
    os.umask(0o077)
    rootfs=Path(rootfs)
    resource=read_pinned(rootfs/'usr/share/Formlabs/Palantir-Form3/Palantir.rcc',MAX_INPUT,RCC_PIN)
    splash=read_pinned(rootfs/'usr/bin/psplash-default',8<<20,SPLASH_PIN)
    out=private_destination(output);out.mkdir(mode=0o700)
    before={}
    for area in ('tools','tests','owner-ui/native'):
        for p in (ROOT/area).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:before[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    receipt={'kind':'OFFLINE_REVIEW_ONLY','installed':False,'native_vendor_execution':False,'external_network':False,'passed':False}
    try:
        receipt['clock']=clock_build(resource,(ROOT/'owner-ui/native/idle-clock.qmlinc').read_bytes(),out/'clock')
        from build_signature_brand import native
        signature=(ROOT/'owner-ui/native/signature-mark.svg').read_bytes()
        if (ROOT/'owner-ui/native/root-mark.svg').read_text()!=native(signature):raise ValueError('Stale native branding source')
        isolated('signature_render_driver.py',['--source','/work/owner-ui/native/signature-mark.svg','--output','/review/rendered-logo'],out,out/'logo-test.log')
        receipt['splash']=splash_build(splash,(out/'rendered-logo/signature-boot.rgba').read_bytes(),out/'splash')
        isolated('native_clock_driver.py',['--fragment','/work/owner-ui/native/idle-clock.qmlinc','--rcc','/review/clock/Palantir-clock-review.rcc','--output','/review/clock-tests'],out,out/'clock-test.log')
        receipt['clock_tests']=json.loads((out/'clock-tests/receipt.json').read_text())
        receipt['logo_render']=json.loads((out/'rendered-logo/receipt.json').read_text())
        receipt['sources_stable']=all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h for n,h in before.items())
        if not receipt['sources_stable']:raise ValueError('Authored source changed during review build')
        receipt['passed']=True
    finally:
        receipt['authored_source_sha256']=before
        (out/'review-receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    return receipt

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--rootfs',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    r=build(a.rootfs,a.output);print(json.dumps({'passed':r['passed'],'clock_sha256':r['clock']['candidate_sha256'],'splash_sha256':r['splash']['candidate_sha256'],'host_qt_checks':len(r['clock_tests']['checks']),'installed':False},indent=2))
if __name__=='__main__':main()
