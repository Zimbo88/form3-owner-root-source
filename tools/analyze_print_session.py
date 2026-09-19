#!/usr/bin/env python3
"""Offline, bounded analysis of copied print-capture JSONL streams.

No SSH, D-Bus connection, vendor execution, repair or original-file write.
Only allowlisted numeric fields/categories leave this parser; log text, arbitrary
dictionary keys, bus identities, job names and consumable secrets never do.
Outputs remain private: timestamps and provenance can still identify a session.
"""
import argparse
import base64
import collections
import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'owner-ui'))
from panel_data import SafeTree, strict_json

MAX_LINE = 2 << 20
MAX_STREAM = 1 << 30
MAX_EVENTS = 1000000
MAX_FILE_BYTES = 64 << 20
MAX_SIGNALS = 1000000
THERMALS = ('cpu_thermal', 'gpu_thermal', 'core_thermal', 'dspeve_thermal', 'iva_thermal')
TEXT_NAMES = frozenset(('sauron.log', 'CandyBus.log', 'Palantir.log', 'Formule.log',
    'TankCartridgeDaemon.log', 'RichardNixon.log', 'daguerre.log', 'syslog'))
CSV_COLUMNS = ('Timestamp Setpoint_C HeaterDutyCycleSetpoint HeaterResinMeasuredDutyCycle '
    'HeaterResinCurrent_mA HeaterResinFault FanHeaterMeasuredDutyCycle FanHeaterRPM '
    'FanHeaterFault TowerTemperature_C TowerTemperatureFault ForceSenseTemperature_C '
    'ForceSenseTemperatureFault LevelsenseTemperature_C LevelsenseTemperatureFault').split()
STATE_NAMES = frozenset(('HIGH_LEVEL_IDLE', 'HIGH_LEVEL_PREPRINT', 'HIGH_LEVEL_FILLING_TANK',
    'HIGH_LEVEL_LEVELSENSE_RECALIBRATION_HEATUP', 'HIGH_LEVEL_LEVELSENSE_RECALIBRATION',
    'HIGH_LEVEL_HOMING', 'SAURON_IDLE', 'SAURON_WAIT_FOR_TASK', 'LEVELSENSE_WAIT_FOR_RESOLUTION',
    'PRINT_WAIT_FOR_FLX', 'PRINT_WAIT_FOR_PREPRINT', 'PR_ERROR_MIX'))
KINDS = frozenset(('identity', 'observer_started', 'observer_exit', 'coverage_gap',
    'coverage_boundary', 'dbus', 'file', 'sample', 'processes', 'kernel', 'heartbeat', 'complete'))
PATTERNS = {
    'mixer_check_failed': rb'(?i)mixer check failed',
    'filling_tank': rb'(?i)\bfilling tank\b',
    'waiting_for_resolution': rb'\bLEVELSENSE_WAIT_FOR_RESOLUTION\b',
    'print_dispatch': rb'\bStarting print\b',
    'print_abort': rb'(?i)\babort(?:ed|ing)?(?: the)? print\b|\bprint(?:ing)? abort(?:ed)?\b',
    'network_failure': rb'(?i)network is unreachable|connection refused|no such host|i/o timeout',
    'error_293': rb'(?i)\bPR_ERROR_RESET_WHILE_PRINTING\b|\berror(?:code)?[= :"\t]+293\b',
}
STAMP = re.compile(rb'(?<!\d)(20\d\d-\d\d-\d\d)[T ](\d\d:\d\d:\d\d(?:\.\d{1,6})?)(?:Z|\+00:00)?')
HEADER = re.compile(r'^signal time=([0-9]+\.[0-9]+) .* path=([^;\s]+); interface=([^;\s]+); member=([A-Za-z0-9_]+)$')
SIGNALS = {
    ('com.formlabs.Sauron', 'statesChanged'), ('com.formlabs.Sauron', 'aborted'),
    ('com.formlabs.Sauron', 'finished'), ('com.formlabs.Sauron', 'currentlyPrintingLayerChanged'),
    ('com.formlabs.Temperature', 'temperature'), ('com.formlabs.Loadcell', 'reading'),
    ('com.formlabs.Loadcell', 'weight_g'), ('com.formlabs.Inductance', 'inductance'),
    ('com.formlabs.GPIO', 'gpioState'), ('com.formlabs.SystemHeartbeat', 'heartbeat'),
    ('com.formlabs.SegmentStepper', 'motorStatus'),
    ('com.formlabs.InductancesAndMotorStatuses', 'inductancesAndMotorStatus'),
    ('com.formlabs.Tensioner', 'state'), ('com.formlabs.Inclinometer', 'state'),
    ('com.formlabs.TankController', 'tankUpdated'), ('com.formlabs.CartridgeController', 'cartridgeUpdated'),
    ('com.formlabs.CartridgeController', 'cartridgeInserted'),
    ('com.formlabs.Orchestrator', 'readyToPrintNowChanged'),
    ('com.formlabs.Orchestrator', 'buildPlatformContentsChanged'),
}


def numeric(value, lo=0, hi=1e12):
    return type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi


def source_class(path):
    if not isinstance(path, str) or len(path) > 256:
        return None
    parts = path.split('/')
    if any(p in ('.', '..') for p in parts) or '\\' in path:
        return None
    if path.rsplit('/', 1)[0] not in ('/data/logs', '/var/volatile/log'):
        return None
    name = parts[-1]
    stem = re.sub(r'\.[0-9]{1,3}$', '', name)
    if stem in TEXT_NAMES:
        return stem
    if name == 'daguerreHeater_v1.csv':
        return name
    if re.fullmatch(r'fluentbit_(system_[a-z_0-9]+|process_health_[a-z_0-9]+)\.msgpack', name):
        # Only enumerated sources are allowed; do not echo unknown names/keys.
        if name in {'fluentbit_system_' + n + '.msgpack' for n in
                    ('cpu', 'disk_io', 'memory', 'netif_eth0', 'netif_wlan0', 'thermal')}:
            return name
        if name in {'fluentbit_process_health_' + n + '.msgpack' for n in
                    ('bonsoir', 'candybus', 'connmand', 'dbus_daemon', 'fluent_bit', 'formule',
                     'galvatron', 'palantir', 'python3', 'rfidbus_buildplatform', 'rfidbus_tank',
                     'richard_nixon', 'sauron', 'tank_cartridge_daemon', 'wpa_supplicant', 'zerotier_one')}:
            return name
    return None


class Series:
    def __init__(self):
        self.count = 0; self.minimum = None; self.maximum = None; self.first = None
        self.last = None; self.previous = None; self.max_gap = 0; self.backward = 0
        self.points = collections.deque(maxlen=60)

    def add(self, stamp, value):
        if not numeric(stamp) or not numeric(value, -1e9, 1e9):
            raise ValueError('Invalid numeric observation')
        if self.previous is not None:
            self.max_gap = max(self.max_gap, stamp - self.previous)
            self.backward += stamp < self.previous
        self.previous = stamp
        self.count += 1; self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        self.first = stamp if self.first is None else min(stamp, self.first)
        self.last = stamp if self.last is None else max(stamp, self.last)
        self.points.append({'timestamp': stamp, 'value': value})

    def view(self):
        return {'samples': self.count, 'min': self.minimum, 'max': self.maximum,
                'first': self.first, 'last': self.last, 'largest_gap_seconds': self.max_gap,
                'out_of_order_input_steps': self.backward, 'points': list(self.points), 'state': 'HISTORICAL'}


class SignalReader:
    """dbus-monitor output is a byte stream: neither a chunk nor a line is a signal."""
    def __init__(self, callback):
        self.buffer = b''; self.callback = callback; self.partial = 0

    def feed(self, raw):
        self.buffer += raw
        while b'\nsignal ' in self.buffer:
            block, self.buffer = self.buffer.split(b'\nsignal ', 1)
            self.buffer = b'signal ' + self.buffer
            self.callback(block)
        if len(self.buffer) > MAX_LINE:
            raise ValueError('Signal frame bound')

    def finish(self):
        # A disconnected stream's last frame has no next-header delimiter.
        # Do not promote it to a complete signal, even if it ends in a newline.
        if self.buffer:
            self.partial += 1


def merge_segments(segments):
    """Combine identical overlap only; never fill holes or choose conflicting bytes."""
    out = []
    for start, data, ref in sorted(segments, key=lambda x: x[0]):
        if not data:
            continue
        if not out or start > out[-1][0] + len(out[-1][1]):
            out.append([start, data, [(start, len(data), ref)]])
            continue
        previous = out[-1]; overlap = previous[0] + len(previous[1]) - start
        n = min(overlap, len(data)); pos = start - previous[0]
        if previous[1][pos:pos+n] != data[:n]:
            raise ValueError('Conflicting file overlap; possible truncate/reuse requires separate review')
        if len(data) > overlap:
            previous[1] += data[overlap:]
            previous[2].append((start + overlap, len(data) - overlap, ref))
    return out


def timestamp(raw):
    m = STAMP.search(raw)
    if not m:
        return None
    try:
        dt = datetime.datetime.fromisoformat((m[1] + b'T' + m[2]).decode())
        return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


class Analysis:
    def __init__(self):
        self.counts = collections.Counter(); self.files = {}; self.file_bytes = 0
        self.signal_counts = collections.Counter(); self.signal_seen = set(); self.signal_duplicates = 0
        self.samples_seen = set(); self.samples_duplicates = 0
        self.thermals = {n: Series() for n in THERMALS}; self.bus_temperatures = {}
        self.events = []; self.sources = []; self.partial_signals = 0; self.unknown_signals = 0
        self.capture_first = None; self.capture_last = None; self.csv_rows = 0
        self.csv_series = {n: Series() for n in CSV_COLUMNS[1:]}; self.csv_invalid = 0
        self.boots = set(); self.partial_lines = 0; self.file_gaps = 0

    def observation(self, stamp, kind, value, ref):
        if len(self.events) >= 20000:
            raise ValueError('Timeline bound')
        self.events.append({'timestamp': stamp, 'kind': kind, 'value': value, 'source': ref})

    def signal(self, block, ref, boot):
        key = hashlib.sha256(boot.encode() + b'\0' + block).digest()
        if key in self.signal_seen:
            self.signal_duplicates += 1; return
        if len(self.signal_seen) >= MAX_SIGNALS:
            raise ValueError('Signal count bound')
        self.signal_seen.add(key)
        lines = block.decode('utf-8', errors='replace').splitlines()
        m = HEADER.fullmatch(lines[0]) if lines else None
        if not m:
            self.unknown_signals += 1; return
        stamp, path, interface, member = m.groups(); stamp = float(stamp)
        if not numeric(stamp) or (interface, member) not in SIGNALS:
            self.unknown_signals += 1; return
        name = interface + '.' + member; self.signal_counts[name] += 1
        body = '\n'.join(lines[1:])
        if interface == 'com.formlabs.Sauron':
            if member == 'statesChanged':
                states = [s for s in re.findall(r'^\s*string "([A-Z_0-9]+)"$', body, re.M) if s in STATE_NAMES]
                for state in sorted(set(states)):
                    self.observation(stamp, 'state_signal', state, ref)
            elif member in ('aborted', 'finished'):
                self.observation(stamp, 'task_signal', member, ref)
            elif member == 'currentlyPrintingLayerChanged':
                nums = re.findall(r'^\s*(?:uint32|int32) ([0-9]{1,7})$', body, re.M)
                if len(nums) == 1:
                    self.observation(stamp, 'layer_signal', int(nums[0]), ref)
        if interface == 'com.formlabs.Temperature':
            sensor = path.rsplit('/', 1)[-1]
            if path != '/com/formlabs/momo/temperatures/' + sensor or sensor not in ('Tower', 'ForceSense', 'Levelsense'):
                return
            m = re.fullmatch(r'\s*struct \{\s*boolean (true|false)\s*double ([-+0-9.eE]+)\s*\}\s*', body)
            if not m:
                return
            stats = self.bus_temperatures.setdefault(sensor, {'valid': Series(), 'error_flag_count': 0})
            if m[1] == 'true':
                stats['error_flag_count'] += 1; return
            val = float(m[2])
            if numeric(val, -273.15, 1000):
                stats['valid'].add(stamp, val)

    def stream(self, path):
        path = Path(os.path.abspath(path)); tree = SafeTree(path.parent)
        # SafeTree bounds reads, but the JSONL stream is deliberately processed
        # incrementally so hundreds of MB do not become one JSON allocation.
        import stat
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=tree.fd)
        tree.close()
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_size > MAX_STREAM:
            os.close(fd); raise ValueError('Input must be a bounded regular stream')
        h = hashlib.sha256(); index = len(self.sources); record = 0; reader = None; boot = None
        with os.fdopen(fd, 'rb') as f:
            while True:
                line = f.readline(MAX_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_LINE or not line.endswith(b'\n'):
                    raise ValueError('Oversized or truncated JSONL record')
                record += 1
                if sum(self.counts.values()) >= MAX_EVENTS:
                    raise ValueError('Event count bound')
                h.update(line); wrap = strict_json(line)
                e = wrap.get('event') if isinstance(wrap, dict) else None
                if not isinstance(e, dict) or e.get('kind') not in KINDS or not isinstance(e.get('payload'), dict):
                    raise ValueError('Invalid event envelope')
                if not numeric(e.get('device_epoch')) or not numeric(e.get('device_monotonic')):
                    raise ValueError('Invalid clock')
                b = e.get('boot_id')
                if not isinstance(b, str) or not re.fullmatch(r'[0-9a-f-]{36}', b):
                    raise ValueError('Invalid boot identity')
                if boot is not None and b != boot:
                    raise ValueError('Boot changed inside a stream; split at the connection boundary')
                boot = b; self.boots.add(b)
                now = e['device_epoch']; self.capture_first = now if self.capture_first is None else min(now, self.capture_first)
                self.capture_last = now if self.capture_last is None else max(now, self.capture_last)
                k = e['kind']; self.counts[k] += 1; p = e['payload']; raw = b''
                if record == 1 and k != 'identity':
                    raise ValueError('Stream must start with its captured identity')
                if k == 'identity' and (p.get('firmware'), p.get('kernel'), p.get('selected_slot')) != ('2.5.6-2773', '4.9.65+', 6):
                    raise ValueError('Unreviewed captured firmware context')
                ref = {'stream': index, 'record': record}
                if 'data_b64' in p:
                    if not isinstance(p['data_b64'], str):
                        raise ValueError('Invalid chunk encoding')
                    raw = base64.b64decode(p['data_b64'], validate=True)
                    if hashlib.sha256(raw).hexdigest() != p.get('sha256') or ('bytes' in p and p['bytes'] != len(raw)):
                        raise ValueError('Chunk checksum/length mismatch')
                if k in ('file', 'dbus', 'kernel') and 'data_b64' not in p:
                    raise ValueError('Missing byte chunk')
                if k == 'file':
                    cls = source_class(p.get('path'))
                    if cls is None:
                        continue
                    if any(type(p.get(n)) is not int or not 0 <= p[n] <= 1 << 40 for n in ('offset', 'inode', 'device', 'generation', 'initial_size')):
                        raise ValueError('Invalid file coordinates')
                    self.file_bytes += len(raw)
                    if self.file_bytes > MAX_FILE_BYTES:
                        raise ValueError('File byte budget')
                    # tmpfs can reuse retired inodes for a different named log.
                    # Never merge those classes; same-class conflicting bytes
                    # still fail below rather than inventing continuity.
                    # Fluent Bit rewrites/rotates its queue files. Generation
                    # numbers restart at a new observer connection: keep those
                    # views separate rather than merging potentially reused data.
                    key = (boot, p['device'], p['inode'], p['generation'], cls,
                           index if cls.endswith('.msgpack') else -1)
                    row = self.files.setdefault(key, {'class': cls, 'segments': []})
                    if row['class'] != cls:
                        raise ValueError('Inode source class changed')
                    # Source initial_size retained for baseline/new-byte review.
                    row['segments'].append((p['offset'], raw, dict(ref, initial_size=p['initial_size'])))
                elif k == 'sample':
                    key = (boot, e['device_monotonic'])
                    if key in self.samples_seen:
                        self.samples_duplicates += 1; continue
                    self.samples_seen.add(key)
                    values = p.get('thermal', {})
                    if not isinstance(values, dict):
                        raise ValueError('Invalid thermal map')
                    for name in THERMALS:
                        entry = values.get(name, {})
                        value = entry.get('celsius') if isinstance(entry, dict) else None
                        if numeric(value, -273.15, 1000):
                            self.thermals[name].add(now, value)
                elif k == 'dbus' and p.get('channel') == 'stdout':
                    if reader is None:
                        reader = SignalReader(lambda block: self.signal(block, dict(ref), boot))
                    # A signal reference is the record completing it; its start
                    # can be in an earlier chunk of this same stream.
                    reader.feed(raw)
        if reader:
            reader.finish(); self.partial_signals += reader.partial
        if not record:
            raise ValueError('Empty capture stream')
        self.sources.append({'stream': index, 'sha256': h.hexdigest(), 'records': record})

    def finish(self):
        files = []; counters = collections.Counter(); pattern_events = []; metrics = []
        for key, item in sorted(self.files.items()):
            blocks = merge_segments(item['segments']); self.file_gaps += max(0, len(blocks) - 1)
            file_id = len(files); byte_count = sum(len(b[1]) for b in blocks)
            files.append({'file': file_id, 'class': item['class'], 'segments': len(blocks), 'bytes': byte_count,
                          'complete_prefix': bool(blocks and blocks[0][0] == 0),
                          'ranges': [{'offset': b[0], 'bytes': len(b[1]), 'sha256': hashlib.sha256(b[1]).hexdigest()} for b in blocks]})
            for start, raw, refs in blocks:
                if item['class'] == 'daguerreHeater_v1.csv':
                    self.csv(raw, start)
                if item['class'].endswith('.msgpack'):
                    row = {'file': file_id, 'class': item['class'], 'sha256': hashlib.sha256(raw).hexdigest(),
                           'records': None, 'decode': 'unavailable', 'connection_views_may_overlap': True}
                    if start == 0:
                        from build_diagnostic_bundle import decode_metrics, msgpack
                        try:
                            values = decode_metrics(raw)
                            row.update(decode='complete', records=len(values),
                                       first=values[0]['timestamp'] if values else None,
                                       last=values[-1]['timestamp'] if values else None)
                        except (ValueError, TypeError, msgpack.UnpackException):
                            row['decode'] = 'invalid_or_truncated'
                    metrics.append(row)
                if item['class'] not in TEXT_NAMES:
                    continue
                offset = start
                for i, line in enumerate(raw.splitlines(keepends=True)):
                    pos = offset; offset += len(line)
                    if (i == 0 and start != 0) or not line.endswith(b'\n'):
                        self.partial_lines += 1; continue
                    stamp = timestamp(line)
                    origin = next((r for s, n, r in refs if s <= pos < s+n), refs[0][2])
                    for category, pattern in PATTERNS.items():
                        if re.search(pattern, line):
                            counters[(item['class'], category)] += 1
                            if len(pattern_events) >= 20000:
                                raise ValueError('Text observation bound')
                            pattern_events.append({'timestamp': stamp, 'kind': 'log_category', 'value': category,
                                'source': dict(origin, file=file_id, offset=pos, line_sha256=hashlib.sha256(line).hexdigest(),
                                               baseline_at_first_capture=pos < origin['initial_size'])})
        if len(self.events) + len(pattern_events) > 20000:
            raise ValueError('Combined timeline bound')
        self.events.extend(pattern_events)
        self.events.sort(key=lambda x: (x['timestamp'] is None, x['timestamp'] or 0, x['kind']))
        return {'schema_version': 1, 'state': 'HISTORICAL', 'firmware_scope': '2.5.6-2773',
            'sources': self.sources, 'files': files, 'capture_first': self.capture_first, 'capture_last': self.capture_last,
            'event_counts': dict(self.counts), 'signal_counts': dict(self.signal_counts), 'metric_views': metrics,
            'coverage': {'boot_count': len(self.boots), 'file_byte_gaps': self.file_gaps,
                'partial_text_lines_omitted': self.partial_lines, 'partial_final_signals_omitted': self.partial_signals,
                'duplicate_signals_removed': self.signal_duplicates, 'duplicate_samples_removed': self.samples_duplicates,
                'unknown_signals_not_decoded': self.unknown_signals,
                'coverage_boundary_records': self.counts['coverage_boundary'], 'coverage_gap_records': self.counts['coverage_gap'],
                'continuous_capture_proven': False},
            'soc_temperatures': [{'name': n, 'unit': 'C', **v.view()} for n, v in self.thermals.items()],
            'bus_temperatures': [{'name': n, 'unit': 'native temperature value; compare *_C CSV columns',
                'error_flag_count': v['error_flag_count'], **v['valid'].view()} for n, v in sorted(self.bus_temperatures.items())],
            'heater_csv': {'rows': self.csv_rows, 'invalid_rows': self.csv_invalid,
                'channels': [{'name': n, **v.view()} for n, v in self.csv_series.items() if v.count]},
            'log_categories': [{'service': s, 'category': c, 'matching_lines': n} for (s, c), n in sorted(counters.items())],
            'timeline': self.events, 'safe_idle_proven': False, 'print_success_proven': False,
            'limitations': ['Historical observations only; no current printer state.',
                'Repeated log lines, signal observers and caller reports are not independent fault episodes.',
                'Signal counts are monitor receipts, not necessarily unique hardware measurements.',
                'Out-of-order inputs can be overlapping observer connections; they do not prove clock reversal.',
                'Finished is a task signal, not a successful-print verdict.',
                'File holes are not filled; incomplete text and final signal frames are omitted.',
                'Device timestamps and log UTC interpretation need external clock correlation.',
                'Units and names do not establish sensor calibration, safety or physical resin volume.']}

    def csv(self, raw, start):
        if start != 0:
            self.csv_invalid += 1; return
        lines = raw.decode('ascii', errors='replace').splitlines()
        if not lines or lines[0].split('\t') != CSV_COLUMNS:
            self.csv_invalid += 1; return
        for line in lines[1:]:
            columns = line.split('\t')
            if len(columns) != len(CSV_COLUMNS):
                self.csv_invalid += 1; continue
            stamp = timestamp(columns[0].encode())
            try:
                vals = [float(x) for x in columns[1:]]
            except ValueError:
                self.csv_invalid += 1; continue
            if stamp is None or any(not numeric(v, -1e9, 1e9) for v in vals):
                self.csv_invalid += 1; continue
            self.csv_rows += 1
            for name, value in zip(CSV_COLUMNS[1:], vals):
                self.csv_series[name].add(stamp, value)


def analyze(paths):
    if not 1 <= len(paths) <= 16:
        raise ValueError('One to sixteen explicit streams required')
    a = Analysis()
    for path in paths:
        a.stream(path)
    return a.finish()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stream', action='append', required=True, help='Copied stream; repeat for ordered continuations')
    p.add_argument('--output', required=True, help='New private JSON file under research-private')
    p.add_argument('--bundle-output', help='Optional NEW private panel bundle directory; never installs it')
    args = p.parse_args(); os.umask(0o077)
    target = Path(os.path.abspath(args.output))
    if 'research-private' not in target.parts or target.exists() or target.is_symlink():
        raise ValueError('New private output required')
    bundle = None
    if args.bundle_output:
        bundle = Path(os.path.abspath(args.bundle_output))
        if 'research-private' not in bundle.parts or bundle.exists() or bundle.is_symlink():
            raise ValueError('New private bundle required')
        check = SafeTree(bundle.parent); check.close()
    guard = SafeTree(target.parent)
    try:
        result = analyze(args.stream)
        if bundle is not None:
            from panel_data import print_session_view
            encoded = json.dumps(result, sort_keys=True, allow_nan=False).encode()
            if len(encoded) > 2 << 20:
                raise ValueError('Panel report size budget')
            print_session_view(encoded)
            bundle.mkdir(mode=0o700)
            for name, data in [('print_session.json', result), ('diagnostics.json', []),
                               ('panel_snapshot.json', {'schema_version': 1, 'state': 'HISTORICAL',
                                'scope': 'Copied live-capture session; no filesystem journal recovery',
                                'consumables': [], 'jobs': [], 'sensors': [], 'faults': []})]:
                with (bundle/name).open('x') as f:
                    json.dump(data, f, sort_keys=True, allow_nan=False); f.write('\n')
        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=guard.fd)
        with os.fdopen(fd, 'w') as f:
            json.dump(result, f, indent=2, sort_keys=True, allow_nan=False); f.write('\n')
    finally:
        guard.close()
    print(json.dumps({'streams': len(result['sources']), 'records': sum(result['event_counts'].values()),
                      'file_identities': len(result['files']), 'heater_csv_rows': result['heater_csv']['rows'],
                      'network_contact': False, 'state': 'HISTORICAL'}))


if __name__ == '__main__':
    main()
