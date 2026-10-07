#!/usr/bin/env python3
"""Render authored numbered DOT figures and equivalent Mermaid, never firmware.

Graphviz is a host-only optional dependency. DOT is authoritative; the supported
subset is explicitly declared nodes and directed edges with literal labels.
"""
import argparse
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = 'http://www.w3.org/2000/svg'
SCOPES = {
 '01':'Historical reference boot paths; not proof for a different board or source revision.',
 '02':'Reference layout only. All offsets are bytes; ranges are end-exclusive.',
 '03':'Conceptual power boundary, not an identified pinout or permission to supply power.',
 '04':'Conceptual measurement points. Physical contacts and supply suffix remain identification gates.',
 '05':'Historical isolated Rescue V2 acquisition topology, not a normal LAN deployment.',
 '06':'Installation sequence and recovery gates; each target requires fresh acceptance.',
 '07':'Owner SSH trust design; first enrollment requires an independently isolated sole-peer link.',
 '08':'Current source privilege design, including the explicit narrow Clear reset broker. No generic root proxy.',
 '09':'Source and fixture transaction design; not a guarantee of atomic power-loss recovery.',
 '10':'API domain distinction; listener observations do not prove every method or authorization path.',
 '11':'Unconfirmed stock network-boot candidate; not an executable stock-root recipe.',
 '12':'Conceptual privacy dependencies; no proven field-filtering policy or applied vendor settings.'}


def mermaid(source):
    direction = re.search(r'rankdir=(TB|LR)', source).group(1)
    lines = ['flowchart '+('TD' if direction=='TB' else 'LR')]
    for line in source.splitlines():
        n = re.fullmatch(r'(\w+) \[label="((?:[^"\\]|\\.)*)"\];',line)
        e = re.fullmatch(r'(\w+) -> (\w+) \[label="((?:[^"\\]|\\.)*)"(,style=dashed)?\];',line)
        if n:
            lines.append('  '+n[1]+'["'+n[2].replace(r'\n','<br/>')+'"]')
        elif e:
            arrow = ' -.-> ' if e[4] else ' --> '
            label = '|"'+e[3].replace(r'\n','<br/>')+'"| ' if e[3] else ''
            lines.append('  '+e[1]+arrow+label+e[2])
        elif '->' in line and 'style=invis' not in line:
            raise ValueError('Unsupported edge syntax')
    return '\n'.join(lines)+'\n'


def render(path):
    source = path.read_text()
    raw = subprocess.check_output(['dot','-Tsvg',str(path)],timeout=20)
    tree = ET.fromstring(raw)
    ET.register_namespace('',NS);ET.register_namespace('xlink','http://www.w3.org/1999/xlink')
    title = re.search(r'graph \[.*?label="([^"]+)"', source).group(1).replace(r'\n',' ')
    tree.set('role','img');tree.set('aria-labelledby','figure-title figure-description')
    t=ET.Element('{'+NS+'}title',{'id':'figure-title'});t.text=title
    d=ET.Element('{'+NS+'}desc',{'id':'figure-description'})
    labels=re.findall(r'^\w+ \[label="([^"]+)"\];',source,re.M)
    d.text=SCOPES[path.name[:2]]+' Solid arrows show the stated sequence or relationship; dashed arrows are conditional or unconfirmed. '+ '; '.join(x.replace(r'\n',' ') for x in labels)+'.'
    tree.insert(0,t);tree.insert(1,d)
    return ET.tostring(tree,encoding='utf-8',xml_declaration=True)+b'\n',mermaid(source)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();bad=[]
    for path in sorted((ROOT/'docs/figures').glob('*.dot')):
        svg,mmd=render(path)
        for suffix,body in (('.svg',svg),('.mmd',mmd.encode())):
            dest=path.with_suffix(suffix)
            if a.check:
                if not dest.exists() or dest.read_bytes()!=body:bad.append(dest.name)
            else:dest.write_bytes(body)
    if bad:raise SystemExit('Regenerate with the recorded Graphviz version: '+', '.join(bad))
    print('12 authored figures '+('verified' if a.check else 'rendered')+'; no hardware contact')
if __name__=='__main__':main()
