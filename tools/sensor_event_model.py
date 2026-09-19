#!/usr/bin/env python3
"""Offline model of the recovered heater watcher, NOT a sensor/control adapter.

Input is a bounded authored/copied event fixture. No D-Bus, device or network I/O.
The recovered TemperatureState flag is an error flag: false permits accumulation.
Units/real hardware objects and the native timer period remain unverified here.
"""
import argparse
import json
import math
from evidence_lib import open_evidence, write_json


class HeaterEvidence(object):
    def __init__(self, max_age=10.0):
        if type(max_age) not in (int, float) or not math.isfinite(max_age) or not 0 < max_age <= 3600:
            raise ValueError('Invalid observer freshness bound')
        self.max_age = max_age
        self.reset()

    def reset(self):
        self.clock = None
        self.sample_time = None
        self.validity_time = None
        self.functional = None
        self.total = 0.0
        self.count = 0
        self.property_value = None
        self.property_time = None

    def advance(self, now):
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('Invalid monotonic fixture time')
        if self.clock is not None and now < self.clock:
            self.reset()
            raise ValueError('Clock discontinuity: evidence invalidated')
        self.clock = now

    def sample(self, now, error, value):
        self.advance(now)
        if type(error) is not bool or type(value) not in (int, float) or not math.isfinite(value):
            self.reset()
            raise ValueError('Malformed TemperatureState')
        # This is an offline resource bound, not a native safety threshold.
        if abs(value) > 1e6 or self.count >= 4096:
            self.reset()
            raise ValueError('Sample accumulation bound exceeded')
        self.functional = not error
        self.validity_time = now
        if not error:
            self.total += value
            self.count += 1
            self.sample_time = now

    def timer(self, now):
        self.advance(now)
        if not self.count:
            return False
        average = self.total / self.count
        self.total = 0.0
        self.count = 0
        # Native initial member value was not recovered: the first modeled
        # notification is explicitly an observer initialization assumption.
        changed = self.property_value is None or abs(average - self.property_value) > .01
        if changed:
            self.property_value = average
            self.property_time = now
        return changed

    def snapshot(self, now):
        self.advance(now)
        age = None if self.sample_time is None else now - self.sample_time
        validity_age = None if self.validity_time is None else now - self.validity_time
        fresh = age is not None and age <= self.max_age and validity_age <= self.max_age
        quality = 'UNAVAILABLE'
        if self.functional is False:
            quality = 'INVALID'
        elif self.property_value is not None:
            quality = 'FRESH_SAMPLE_EVIDENCE' if fresh else 'STALE'
        return {'provenance': 'OFFLINE_MODEL', 'quality': quality,
                'unit': 'UNKNOWN_NATIVE_UNIT', 'value': self.property_value,
                'sample_time': self.sample_time, 'property_change_time': self.property_time,
                'functional_flag': self.functional, 'age_seconds': age,
                'safe_for_actuation': False, 'live_adapter_implemented': False}


def replay(raw):
    if len(raw) > 1048576:
        raise ValueError('Fixture size limit')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate field')
            result[key] = value
        return result
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
    if type(data) is not list or len(data) > 4096:
        raise ValueError('Expected bounded event list')
    model = HeaterEvidence()
    result = []
    for event in data:
        if type(event) is not dict:
            raise ValueError('Malformed event')
        kind = event.get('event')
        expected = {'event', 'time', 'error', 'value'} if kind == 'sample' else {'event', 'time'}
        if set(event) != expected or kind not in ('sample', 'timer', 'owner_changed', 'snapshot'):
            raise ValueError('Unknown event/field')
        if kind == 'owner_changed':
            model.reset()
        elif kind == 'sample':
            model.sample(event['time'], event['error'], event['value'])
        elif kind == 'timer':
            model.timer(event['time'])
        result.append(model.snapshot(event['time']))
    return {'schema': 1, 'fixture_only': True, 'samples': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    with open_evidence(args.fixture) as stream:
        result = replay(stream.read(1048577))
    write_json(args.output, result)


if __name__ == '__main__':
    main()
