#!/usr/bin/env python3
"""Build a PRIVATE offline touchscreen-clock RCC derivative; never install it.

Pins acquired 2.5.6-2773. Only BaseScreen.qml changes; all other resource contents,
locales and names must remain identical. The generic timer is authored separately.
"""
import argparse,hashlib,json
from pathlib import Path
from evidence_lib import ROOT,open_evidence
from inspect_qt_resources import Resource,replace_members,private_destination,MAX_INPUT
PIN='969cae93da58f0e2be6040b48eea071f678b12e55b592d4fd7298060d2e05150'
MEMBER='qml/BaseScreen.qml'
ORIGINAL='model.text_headerSubtitle !== "" ? model.text_headerSubtitle : PrinterStatusHelper.getLongPrinterStatus()'
REPLACEMENT='model.text_headerSubtitle !== "" ? model.text_headerSubtitle : ownerClockAppend(PrinterStatusHelper.getLongPrinterStatus(), !atomWatcher.activeAtom && !orchestrator.isStartingPrint)'

def patch_qml(data,fragment):
    text=data.decode('utf-8');addition=fragment.decode('utf-8')
    if len(fragment)>8192 or 'ownerClockEpochMs' in text:raise ValueError('Fragment bound/already modified')
    if text.count(ORIGINAL)!=1 or text.count('QtQuick.Item {')<1:raise ValueError('Unexpected source bindings')
    if not addition.strip() or '\x00' in addition:raise ValueError('Invalid fragment')
    text=text.replace('QtQuick.Item {','QtQuick.Item {\n'+addition,1)
    return text.replace(ORIGINAL,REPLACEMENT).encode('utf-8')

def build(data,fragment,output):
    if hashlib.sha256(data).hexdigest()!=PIN:raise ValueError('Unsupported acquired resource pin')
    src=Resource(data);rows=[r for r in src.rows if r['path']==MEMBER]
    if len(rows)!=1:raise ValueError('Expected unique BaseScreen')
    old=src.contents(rows[0]);new=patch_qml(old,fragment)
    result=replace_members(src,{MEMBER:new});dest=private_destination(output);dest.mkdir(mode=0o700)
    (dest/'Palantir-clock-review.rcc').write_bytes(result.data)
    report={'schema':1,'kind':'OFFLINE_REVIEW_ONLY','firmware':'2.5.6-2773',
        'source_path':'p6:/usr/share/Formlabs/Palantir-Form3/Palantir.rcc',
        'source_sha256':PIN,'candidate_sha256':hashlib.sha256(result.data).hexdigest(),
        'candidate_bytes':len(result.data),'changed_members':[MEMBER],
        'member_before_sha256':hashlib.sha256(old).hexdigest(),'member_after_sha256':hashlib.sha256(new).hexdigest(),
        'authored_fragment_sha256':hashlib.sha256(fragment).hexdigest(),
        'unchanged_members_verified':len(src.rows)-1,'clock_basis':'Europe/Berlin display-only conversion; current German DST rule; synchronization NOT established',
        'custom_subtitle_preserved':True,'display_only_idle_branch':False,
        'display_states':['Idle','Ready'],'date_format':'DD.MM.YY HH:mm',
        'active_atom_and_starting_print_excluded':True,'vendor_code_executed':False,
        'installed':False,'rollback':'Restore exact original RCC after separately approved installation; no install command generated',
        'open_gates':['Qt 5.9.6 target rendering','header width/localization on device','approved runtime source hash','atomic install/rollback transaction']}
    (dest/'manifest.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rcc');p.add_argument('--output',required=True);a=p.parse_args()
    with open_evidence(a.rcc) as f:data=f.read(MAX_INPUT+1)
    fragment=(ROOT/'owner-ui/native/idle-clock.qmlinc').read_bytes()
    r=build(data,fragment,a.output);print(json.dumps(r,indent=2))
if __name__=='__main__':main()
