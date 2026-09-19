#!/usr/bin/env python3
"""Replay authored state-event fixtures; no D-Bus connection or command exists.

An observer-envelope model, not a wire decoder or deployed printer-state adapter.
The known Sauron labels do not establish an all-interlocks safe-idle predicate.
"""
import argparse,hashlib,json,math,re
from evidence_lib import open_evidence,write_json

LABELS=frozenset(['SAURON_NONE','SAURON_WAIT_FOR_TASK','SAURON_IDLE','HIGH_LEVEL_IDLE','UNKNOWN'])

class StateObservation:
    def __init__(self,max_age=10):
        if type(max_age) not in (int,float) or not math.isfinite(max_age) or not 0<max_age<=60:
            raise ValueError('Observer freshness bound')
        self.max_age=max_age;self.clock=None;self.owner=None;self.labels=None;self.observed=None;self.generation=0
    def invalidate(self):self.labels=None;self.observed=None
    def advance(self,now):
        if type(now) not in (float,int) or not math.isfinite(now) or now<0:raise ValueError('Invalid fixture time')
        if self.clock is not None and now<self.clock:
            self.invalidate();self.owner=None;self.clock=now
            raise ValueError('Clock moved backwards; owner and state invalidated')
        self.clock=now
    def event(self,event):
        if type(event) is not dict:raise ValueError('Event object required')
        kind=event.get('kind');fields={'kind','time'}
        if kind in ('owner','states'):fields.add('owner')
        if kind=='states':fields.add('states')
        if kind not in ('owner','states','disconnect','snapshot') or set(event)!=fields:raise ValueError('Unsupported event envelope')
        self.advance(event['time'])
        if kind in ('owner','states'):
            owner=event['owner']
            if not isinstance(owner,str) or not re.fullmatch(r':[0-9]{1,10}\.[0-9]{1,10}',owner):
                self.invalidate();raise ValueError('Invalid unique bus-owner name')
        if kind=='owner':
            if owner!=self.owner:
                self.invalidate();self.owner=owner;self.generation+=1
        elif kind=='disconnect':self.invalidate();self.owner=None;self.generation+=1
        elif kind=='states':
            if self.owner is None or owner!=self.owner:
                return self.snapshot(event['time'],'WRONG_OR_MISSING_OWNER')
            states=event['states']
            if type(states) is not list or len(states)>32 or any(not isinstance(x,str) or len(x)>96 for x in states):
                self.invalidate();raise ValueError('State-list bound')
            # Unknown labels can change the interpretation of the entire state set.
            if not states or any(x not in LABELS for x in states):
                self.invalidate();return self.snapshot(event['time'],'UNKNOWN_NATIVE_STATE')
            self.labels=sorted(set(states));self.observed=event['time']
        return self.snapshot(event['time'])
    def snapshot(self,now,reason=None):
        self.advance(now);age=None if self.observed is None else now-self.observed
        quality='UNAVAILABLE' if self.labels is None else ('RECENT_RECEIPT' if age<=self.max_age else 'STALE')
        return {'quality':quality,'labels':self.labels,'receipt_age_seconds':age,'generation':self.generation,
                'ignored_event_reason':reason,'safe_idle_proven':False,'measurement_time_known':False,
                'source':'OFFLINE_OBSERVER_MODEL','native_state_read_or_changed':False}

def replay(raw):
    if not isinstance(raw,bytes) or len(raw)>1048576:raise ValueError('Fixture size bound')
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('Duplicate event field')
            out[key]=value
        return out
    try:events=json.loads(raw.decode(),object_pairs_hook=pairs)
    except (UnicodeError,RecursionError):raise ValueError('Malformed event document')
    if type(events) is not list or len(events)>4096:raise ValueError('Event count bound')
    model=StateObservation();rows=[model.event(event) for event in events]
    return {'schema':1,'source_sha256':hashlib.sha256(raw).hexdigest(),'fixture_only':True,
            'network_contact':False,'dbus_messages_sent':0,'snapshots':rows}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('fixture');p.add_argument('--output',required=True);a=p.parse_args()
    with open_evidence(a.fixture) as f:result=replay(f.read(1048577))
    write_json(a.output,result)
    print(json.dumps({'passed':True,'events':len(result['snapshots']),'dbus_messages_sent':0}))
if __name__=='__main__':main()
