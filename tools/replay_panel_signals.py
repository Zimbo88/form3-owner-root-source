#!/usr/bin/env python3
"""Replay sealed historical D-Bus frames through the panel parser, without IPC.

Reuse the bounded session/envelope/hash verifier. Export counts and provenance
only, never captured identifiers, state strings, sensor values or raw messages.
Every frame is tested independently; freshness/reconnect are separate fixtures.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import sys
from evidence_lib import write_json
from review_print_progress import HEADER, review

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'owner-ui'))
from panel_data import PassivePrinterSignals


class PanelReplay:
    def __init__(self):
        self.reader = PassivePrinterSignals()
        self.counts = collections.Counter()
        self.boots = set()
        self.duplicates = 0  # Required model interface; omitted from our report.

    def boot(self, identity):
        if len(self.boots) >= 64 and identity not in self.boots:
            raise ValueError('Boot budget')
        self.boots.add(identity)
        self.reader.clear()

    def signal(self, raw):
        lines = raw.decode('ascii', errors='replace').splitlines()
        m = HEADER.fullmatch(lines[0]) if lines else None
        if not m:
            return
        _, path, interface, member = m.groups()
        if (path, interface, member) == ('/com/formlabs/Sauron', 'com.formlabs.Sauron', 'statesChanged'):
            kind, key = 'states', 'job_state'
        elif (path, interface, member) == ('/com/formlabs/Sauron', 'com.formlabs.Sauron', 'currentlyPrintingLayerChanged'):
            kind, key = 'layers', 'job_layer'
        elif interface == 'com.formlabs.Temperature' and member == 'temperature' and path in self.reader.CHANNELS:
            kind, key = 'temperatures', None
        else:
            return
        self.reader.clear()
        self.reader.accept(raw, 10, 20)
        snapshot = self.reader.snapshot(11)
        view = snapshot.get(key, {}) if key else next((s['observation'] for s in snapshot['sensors']), {})
        self.counts[kind+'_frames'] += 1
        self.counts[kind+'_value_available'] += int(view.get('value') is not None)
        if kind == 'states' and view.get('value') is not None:
            self.counts['states_incomplete_projection'] += int(not view['complete_projection'])

    def result(self):
        return [{'unique_boots': len(self.boots), 'counts': dict(self.counts)}]


def replay(session):
    result = review(session, model=PanelReplay())
    result['observations'] = result.pop('boots')[0]
    result.pop('duplicate_state_frames_omitted')
    result.update(parser_sha256=hashlib.sha256((ROOT/'owner-ui/panel_data.py').read_bytes()).hexdigest(),
                  replay_tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  duplicate_handling='Repeated captured frames are counted, not independent events',
                  scope='HISTORICAL parser replay; no current device or timing acceptance',
                  hardware_contact=False, exported_raw_values=False)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    out = Path(a.output).absolute()
    if 'research-private' not in out.parts or out.resolve().is_relative_to(Path(a.session).resolve()):
        p.error('New private output outside the captured session required')
    if out.exists():p.error('New output required')
    os.umask(0o077)
    result = replay(a.session)
    write_json(out, result)
    print(json.dumps({'streams': len(result['source_streams']), 'events': result['events'],
                      'observations': result['observations'], 'hardware_contact': False}))


if __name__ == '__main__':
    main()
