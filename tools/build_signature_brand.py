#!/usr/bin/env python3
"""Materialize the reviewed Signature mark for native boot and inline panel use.

Host source-only tool. No printer, package signing or filesystem mounts.
The standalone geometry is shared; boot artwork scales 1.30x on a fixed canvas.
"""
import argparse,copy,hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path
from evidence_lib import ROOT
from build_native_display_review import validate_svg

NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
def elements(data):
    if len(data)>32768 or b'<!' in data:raise ValueError('Bounded standalone geometry required')
    root=ET.fromstring(data)
    if root.tag!='{'+NS+'}svg' or root.get('viewBox')!='0 0 540 140':raise ValueError('Exact signature canvas required')
    groups=[]
    for child in root:
        if child.tag in ('{'+NS+'}title','{'+NS+'}desc'):continue
        groups.append(copy.deepcopy(child))
    probe=ET.Element('{'+NS+'}svg',{'width':'1280','height':'720','viewBox':'0 0 1280 720'})
    probe.extend(copy.deepcopy(groups));validate_svg(ET.tostring(probe))
    if len(groups)!=4 or [x.get('id') for x in groups]!=['signature-symbol','signature-divider','signature-rooted','signature-caption']:
        raise ValueError('Exact reviewed signature components required')
    if groups[2].get('fill')!='#e58b38':raise ValueError('Reviewed rooted orange required')
    return groups

def native(data):
    root=ET.Element('{'+NS+'}svg',{'width':'1280','height':'720','viewBox':'0 0 1280 720','role':'img','aria-labelledby':'title desc'})
    ET.SubElement(root,'{'+NS+'}title',{'id':'title'}).text='Owner Root boot mark'
    ET.SubElement(root,'{'+NS+'}desc',{'id':'desc'}).text='Original terminal/root symbol, orange rooted and OWNER. Independent owner branding, 130 percent scale, fixed native canvas.'
    ET.SubElement(root,'{'+NS+'}rect',{'width':'1280','height':'720','fill':'#000000'})
    g=ET.SubElement(root,'{'+NS+'}g',{'transform':'translate(289 269) scale(1.3)','fill':'#ffffff'})
    for e in elements(data):
        for n in e.iter():
            if n.get('fill')=='currentColor':n.set('fill','#ffffff')
        g.append(e)
    result=ET.tostring(root,encoding='unicode')+'\n';validate_svg(result.encode());return result

def panel(data):
    root=ET.Element('{'+NS+'}svg',{'viewBox':'0 0 540 140','class':'signature-brand','role':'img','aria-labelledby':'brand-title brand-desc','focusable':'false'})
    ET.SubElement(root,'{'+NS+'}title',{'id':'brand-title'}).text='Owner Root'
    ET.SubElement(root,'{'+NS+'}desc',{'id':'brand-desc'}).text='Independent owner repair and maintenance logo.'
    root.extend(elements(data));return ET.tostring(root,encoding='unicode')

def project(data):
    root=ET.Element('{'+NS+'}svg',{'width':'580','height':'180','viewBox':'0 0 580 180','role':'img','aria-labelledby':'title desc'})
    ET.SubElement(root,'{'+NS+'}title',{'id':'title'}).text='Owner Root'
    ET.SubElement(root,'{'+NS+'}desc',{'id':'desc'}).text='Original open-terminal/root symbol by Mathias Zimmermann, orange rooted lettering and OWNER. Independent repair and maintenance project.'
    ET.SubElement(root,'{'+NS+'}rect',{'width':'580','height':'180','fill':'#080808','rx':'4'})
    g=ET.SubElement(root,'{'+NS+'}g',{'transform':'translate(20 20)','fill':'#ffffff'})
    for e in elements(data):
        for n in e.iter():
            if n.get('fill')=='currentColor':n.set('fill','#ffffff')
        g.append(e)
    return ET.tostring(root,encoding='unicode')+'\n'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--write',action='store_true',help='Update the three authored source destinations; otherwise check only')
    a=p.parse_args();source=ROOT/'owner-ui/native/signature-mark.svg';data=source.read_bytes()
    boot=ROOT/'owner-ui/native/root-mark.svg';index=ROOT/'owner-ui/static/index.html';html=index.read_text()
    begin='  <!-- OWNER SIGNATURE BEGIN -->';end='  <!-- OWNER SIGNATURE END -->'
    if html.count(begin)!=1 or html.count(end)!=1:raise ValueError('Unique authored panel brand boundaries required')
    start=html.index(begin);stop=html.index(end)+len(end)
    intended=html[:start]+begin+'\n  <div class="brand">'+panel(data)+'</div>\n'+end+html[stop:]
    image=native(data);overview=ROOT/'assets/signature-brand.svg';overview_image=project(data)
    if a.write:
        boot.write_text(image);index.write_text(intended)
        overview.parent.mkdir(exist_ok=True);overview.write_text(overview_image)
    elif boot.read_text()!=image or html!=intended or overview.read_text()!=overview_image:raise ValueError('Generated branding differs; review and run --write')
    print(json.dumps({'shared_svg_sha256':hashlib.sha256(data).hexdigest(),'native_width':1280,'native_height':720,'artwork_scale':1.3,'artwork_width':702,'source_only':True,'hardware_contact':False}))
if __name__=='__main__':main()
