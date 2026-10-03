"""Python 3.5-compatible bounded file adapters and owner-only state.

Bounded local files and passive allowlisted D-Bus signals only. No vendor writes.
"""
from __future__ import division
import datetime
import hashlib
import json
import math
import os
import re
import stat
import threading
import select
import subprocess
import time

VERSION = '0.5.12-review'
MAX_FILE = 2 * 1024 * 1024


def strict_json(raw):
    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj:
                raise ValueError('Duplicate JSON member')
            obj[k] = v
        return obj
    def bad(_):
        raise ValueError('Non-finite JSON number')
    try:
        value = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw,
                           object_pairs_hook=pairs, parse_constant=bad)
    except RecursionError:
        raise ValueError('JSON nesting limit exceeded')
    def depth_check(item, depth=0):
        if depth > 32:
            raise ValueError('JSON nesting limit exceeded')
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('Non-finite JSON number')
        if isinstance(item, dict):
            if len(item) > 4096:
                raise ValueError('JSON member limit exceeded')
            for child in item.values():
                depth_check(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 20000:
                raise ValueError('JSON array limit exceeded')
            for child in item:
                depth_check(child, depth + 1)
    depth_check(value)
    return value


class SafeTree(object):
    """Open every directory component with O_NOFOLLOW; no evidence mutation."""
    def __init__(self, root):
        self.root = os.path.abspath(str(root))
        # Check ancestors too; resolve() would silently accept symlinks.
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.root.strip('/').split('/'):
                if not part:
                    continue
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read(self, relative, limit=MAX_FILE, with_info=False):
        parts = relative.split('/')
        if any(p in ('', '.', '..') for p in parts) or '\\' in relative:
            raise ValueError('Invalid relative path')
        fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            f = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                info = os.fstat(f)
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    raise ValueError('Non-regular or oversized input')
                chunks = []
                length = 0
                while True:
                    b = os.read(f, min(65536, limit + 1 - length))
                    if not b:
                        break
                    chunks.append(b)
                    length += len(b)
                    if length > limit:
                        raise ValueError('Input exceeds limit')
                raw = b''.join(chunks)
                return (raw, info) if with_info else raw
            finally:
                os.close(f)
        finally:
            os.close(fd)

    def optional(self, relative, limit=MAX_FILE):
        try:
            return self.read(relative, limit)
        except (OSError, ValueError, UnicodeError):
            return None


def field(value=None, state='UNAVAILABLE', source='No reviewed source', unit=None,
          timestamp=None, max_age=None):
    # A clock jump or missing timestamp cannot establish fresh telemetry.
    fresh = None
    if max_age is not None:
        valid_time = number(timestamp, 0, 1e11)
        valid_age = number(max_age, 0, 86400)
        age = time.time() - valid_time if valid_time is not None else None
        fresh = bool(age is not None and valid_age is not None and 0 <= age <= valid_age)
        if state == 'LIVE' and not fresh:
            state = 'CACHED'
    if value is None:
        state = 'UNAVAILABLE'
        fresh = False if max_age is not None else None
    return {'value': value, 'state': state, 'source': source, 'unit': unit,
            'timestamp': number(timestamp, 0, 1e11), 'fresh': fresh}


def number(value, minimum=0, maximum=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) and minimum <= value <= maximum else None
    except OverflowError:
        return None


class CpuUsage(object):
    """Aggregate non-idle CPU-time estimate from two /proc/stat snapshots.

    Guest counters are already included in user/nice and are not added again.
    iowait counts as non-busy here. Kernel counters can regress; invalidate then.
    No sleeps, threads, external calls or persistent state are introduced.
    """
    def __init__(self):
        self.previous = None
        self.last = None
        self.lock = threading.Lock()

    def sample(self, raw, monotonic_now, wall_now):
        with self.lock:
            unknown = {'percent':None,'observed_at':None,'interval_seconds':None,'reason':'NEEDS_TWO_SAMPLES'}
            try:
                if not isinstance(raw,str) or len(raw)>65536:
                    raise ValueError('Missing bounded proc stat')
                parts=raw.splitlines()[0].split()
                if parts[0]!='cpu' or not 5<=len(parts)<=11:
                    raise ValueError('Aggregate CPU counters required')
                if any(not re.match(r'^[0-9]{1,20}$',x) for x in parts[1:]):
                    raise ValueError('Invalid CPU counter')
                counters=[int(x) for x in parts[1:9]]
                counters += [0]*(8-len(counters))
                if any(x>2**64-1 for x in counters) or number(monotonic_now,0,1e12) is None or number(wall_now,0,1e11) is None:
                    raise ValueError('Invalid counter or time')
            except (ValueError,IndexError):
                self.previous=None;self.last=None;unknown['reason']='INVALID_SOURCE';return unknown
            old=self.previous
            if old is None:
                self.previous=(counters,monotonic_now);return unknown
            interval=monotonic_now-old[1]
            if interval<0 or interval>120 or any(a<b for a,b in zip(counters,old[0])):
                self.previous=(counters,monotonic_now);self.last=None
                unknown['reason']='DISCONTINUITY';return unknown
            if interval<0.25:
                return dict(self.last) if self.last else unknown
            self.previous=(counters,monotonic_now)
            delta=[a-b for a,b in zip(counters,old[0])];total=sum(delta)
            if not total:
                self.last=None;unknown['reason']='NO_COUNTER_PROGRESS';return unknown
            percent=100.0*(total-delta[3]-delta[4])/total
            self.last={'percent':percent,'observed_at':wall_now,'interval_seconds':interval,'reason':'COUNTER_DELTA'}
            return dict(self.last)


def refill_preview(consumables, entries):
    """Account for owner declarations without fabricating a physical fill level.

    A record hash identifies an exact historical snapshot, not a cartridge's
    lifetime identity. Entries for other snapshots cannot be silently merged.
    """
    if not isinstance(consumables, list) or len(consumables) > 128:
        raise ValueError('Consumable preview budget')
    if not isinstance(entries, list) or len(entries) > 256:
        raise ValueError('Refill preview budget')
    known = set()
    records = []
    for item in consumables:
        if not isinstance(item, dict) or item.get('kind') != 'cartridge':
            continue
        digest = item.get('record_sha256')
        if not isinstance(digest, str) or not re.match(r'^[a-f0-9]{64}$', digest) or digest in known:
            raise ValueError('Invalid or repeated cartridge snapshot fingerprint')
        known.add(digest)
        matches = [row for row in entries if isinstance(row, dict) and row.get('record_sha256') == digest]
        amounts = [number(row.get('quantity_ml'), 0.1, 5000) for row in matches]
        if any(x is None for x in amounts):
            raise ValueError('Invalid owner quantity in stored ledger')
        records.append({'record_sha256': digest, 'state': 'HISTORICAL',
                        'owner_declared_added_ml': sum(amounts), 'declarations': len(matches),
                        'same_material_asserted_for_all': bool(matches) and all(row.get('same_material_asserted') is True for row in matches),
                        'physical_remaining_ml': field(source='No measured current cartridge volume or reviewed refill baseline'),
                        'native_usage_changed': False, 'dispense_permission': False})
    unmatched = sum(1 for row in entries if not isinstance(row, dict) or row.get('record_sha256') not in known)
    return {'records': records, 'unmatched_declarations': unmatched,
            'applied': False, 'native_reset_enabled': False, 'safe_idle_proven': False,
            'identity_scope': 'Exact record snapshot SHA256; not a persistent cartridge identity',
            'gates': ['Current insertion and trustworthy level feedback',
                      'Model-specific dispense/stop/interlock acceptance',
                      'Native RAM/file/consumable merge and crash-safe writeback',
                      'Material/profile and physical valve compatibility'],
            'note': 'Owner bookkeeping cannot grant dispensing permission or reset lifetime usage.'}


CONSUMABLE_FIELDS = {
    'cartridge': ['OriginalVolume_mL', 'EstimatedVolumeDispensed_ml', 'DispenseCount',
                  'CumulativeDispenseTime_s', 'WriteCount', 'LastSuccessfulWritebackTime'],
    'tank': ['VolumePrinted_mm3', 'NumLayersPrinted', 'PrintTime_mS', 'LastResinLevel_mm',
             'LastPrintDate', 'DateFirstFill', 'LastSuccessfulWritebackTime']}


def consumable_view(raw, kind, timestamp=None):
    data = strict_json(raw)
    if not isinstance(data, dict) or kind not in CONSUMABLE_FIELDS:
        raise ValueError('Invalid consumable record')
    fields = {}
    for name in CONSUMABLE_FIELDS[kind]:
        value = data.get(name)
        # Timestamps can be ISO strings; bounded and not arbitrary map keys.
        if name in ('LastSuccessfulWritebackTime', 'LastPrintDate', 'DateFirstFill'):
            value = value if isinstance(value, str) and re.match(r'^\d{4}-\d\d-\d\d[T 0-9:.+Z-]{0,40}$', value) else number(value)
        else:
            value = number(value, -100 if name == 'LastResinLevel_mm' else 0)
        fields[name] = field(value, 'HISTORICAL', 'TKD persisted record / ' + name,
                             timestamp=timestamp)
    capacity = number(data.get('OriginalVolume_mL'))
    used = number(data.get('EstimatedVolumeDispensed_ml'))
    return {'kind': kind, 'record_sha256': hashlib.sha256(raw).hexdigest(), 'fields': fields,
            'estimated_remaining_ml': field(max(0, capacity - used) if capacity is not None and used is not None else None,
                'HISTORICAL', 'Nominal capacity minus estimated usage; NOT a physical measurement', 'mL', timestamp),
            'presence': field(), 'material': field(source='Material ID not resolved to a reviewed material catalog'),
            'native_reset_enabled': False}


POLICIES = {
    'NORMAL': {'requested_flags': None, 'cloud_printing': 'Vendor settings unchanged',
               'residual_data': 'Existing vendor behavior; no owner protection claim'},
    'CLOUD-MINIMIZED': {'requested_flags': {'AllowDataCollection': False,
        'AllowPrintImageCollection': False, 'RemoteAssistEnabled': False, 'RemotePrintEnabled': True},
        'cloud_printing': 'UNKNOWN: disabling collection gates shared ping steps; Dashboard/job continuity needs acceptance',
        'residual_data': 'Gateway authentication, printer/job/consumable status may remain; per-field omission unproved'},
    'LOCAL-ONLY': {'requested_flags': {'AllowDataCollection': False,
        'AllowPrintImageCollection': False, 'RemoteAssistEnabled': False, 'RemotePrintEnabled': False},
        'cloud_printing': 'Unavailable under independently enforced WAN isolation',
        'residual_data': 'Local logs and queues remain; later reconnection can transmit retained data'}
}


def policy_preview(name):
    if name not in POLICIES:
        raise ValueError('Unknown policy')
    out = dict(POLICIES[name])
    out.update({'policy': name, 'applied': False, 'verification': 'UNAVAILABLE',
                'vendor_writes_enabled': False, 'local_logging': 'Retained',
                'note': 'Preference only. No daemon, firewall or vendor file is changed.'})
    return out


DEFAULT_SETTINGS = {'display_alias': 'Owner maintenance', 'refresh_seconds': 10,
                    'privacy_preference': 'NORMAL', 'wlan_login_required': False}


def validate_settings(value):
    if isinstance(value, dict) and set(value) == set(DEFAULT_SETTINGS)-{'wlan_login_required'}:
        value = dict(value, wlan_login_required=False)
    if not isinstance(value, dict) or set(value) != set(DEFAULT_SETTINGS):
        raise ValueError('Settings schema mismatch')
    if type(value['wlan_login_required']) is not bool:
        raise ValueError('WLAN login preference must be boolean')
    alias = value['display_alias']
    if not isinstance(alias, str) or not re.match(r'^[A-Za-z0-9 ._-]{1,48}$', alias):
        raise ValueError('Invalid display alias')
    if type(value['refresh_seconds']) is not int or not 5 <= value['refresh_seconds'] <= 60:
        raise ValueError('Refresh must be 5..60 seconds')
    if value['privacy_preference'] not in POLICIES:
        raise ValueError('Invalid privacy preference')
    return dict(value)


class OwnerStore(object):
    """Writes only an owner-owned directory, atomically; never vendor counters."""
    def __init__(self, root):
        self.tree = SafeTree(root)
        st = os.fstat(self.tree.fd)
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            self.tree.close()
            raise ValueError('Owner state directory must be owned by this user, mode 700')
        self.lock = threading.RLock()

    def load(self, name, default):
        try:
            raw = self.tree.read(name, 262144)
        except FileNotFoundError:
            return default
        return strict_json(raw)

    def save(self, name, data):
        if name == 'settings.json' and isinstance(data,dict) and 'wlan_login_required' in data:
            # Preserve the old settings schema so a panel rollback can still read it.
            with self.lock:
                legacy={k:v for k,v in data.items() if k!='wlan_login_required'}
                self.save('settings.json',legacy)
                self.save('access-policy.json',{'wlan_login_required':data['wlan_login_required']})
            return
        if name not in ('settings.json', 'refills.json', 'access-policy.json'):
            raise ValueError('Unapproved owner state file')
        encoded = json.dumps(data, sort_keys=True, allow_nan=False).encode('utf-8')
        if len(encoded) > 262144:
            raise ValueError('Owner state budget exceeded')
        with self.lock:
            try:
                existing = os.stat(name, dir_fd=self.tree.fd, follow_symlinks=False)
                if not stat.S_ISREG(existing.st_mode) or existing.st_uid != os.getuid():
                    raise ValueError('Unsafe existing owner state')
            except FileNotFoundError:
                pass
            temp = '.new-' + os.urandom(12).hex()
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self.tree.fd)
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(encoded)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp, name, src_dir_fd=self.tree.fd, dst_dir_fd=self.tree.fd)
                os.fsync(self.tree.fd)
            finally:
                try:
                    os.unlink(temp, dir_fd=self.tree.fd)
                except FileNotFoundError:
                    pass

    def settings(self):
        with self.lock:
            legacy=self.load('settings.json',{k:v for k,v in DEFAULT_SETTINGS.items() if k!='wlan_login_required'})
            policy=self.load('access-policy.json',{'wlan_login_required':False})
            if not isinstance(legacy,dict) or not isinstance(policy,dict) or set(policy)!={'wlan_login_required'}:
                raise ValueError('Invalid owner access policy')
            return validate_settings(dict(legacy,wlan_login_required=policy['wlan_login_required']))

    def refills(self):
        with self.lock:
            result = self.load('refills.json', [])
            if not isinstance(result, list) or len(result) > 256:
                raise ValueError('Invalid refill ledger')
            return result

    def add_refill(self, entry):
        if not isinstance(entry, dict) or set(entry) != {'record_sha256', 'quantity_ml', 'same_material_asserted'}:
            raise ValueError('Refill schema mismatch')
        if not isinstance(entry['record_sha256'], str) or not re.match(r'^[a-f0-9]{64}$', entry['record_sha256']):
            raise ValueError('Record fingerprint required')
        if number(entry['quantity_ml'], 0.1, 5000) is None or type(entry['same_material_asserted']) is not bool:
            raise ValueError('Invalid owner quantity/assertion')
        with self.lock:
            rows = self.refills()
            if len(rows) >= 256:
                raise ValueError('Refill ledger full; export/review before adding')
            row = dict(entry)
            row.update({'recorded_at': time.time(), 'source': 'OWNER DECLARATION',
                        'native_usage_changed': False, 'dispense_permission': False})
            rows.append(row)
            self.save('refills.json', rows)
            return row


PRINT_CHANNELS = {
    'Setpoint_C': ('Heater target', 'C'),
    'HeaterDutyCycleSetpoint': ('Requested heater duty', 'fraction'),
    'HeaterResinMeasuredDutyCycle': ('Reported heater duty', 'fraction'),
    'HeaterResinCurrent_mA': ('Reported heater current', 'mA'),
    'HeaterResinFault': ('Heater fault field', 'raw flag'),
    'FanHeaterMeasuredDutyCycle': ('Reported heater-fan duty', 'fraction'),
    'FanHeaterRPM': ('Heater fan speed', 'RPM'),
    'FanHeaterFault': ('Heater fan fault field', 'raw flag'),
    'TowerTemperature_C': ('Tower temperature', 'C'),
    'TowerTemperatureFault': ('Tower fault field', 'raw flag'),
    'ForceSenseTemperature_C': ('ForceSense temperature', 'C'),
    'ForceSenseTemperatureFault': ('ForceSense fault field', 'raw flag'),
    'LevelsenseTemperature_C': ('LevelSense temperature', 'C'),
    'LevelsenseTemperatureFault': ('LevelSense fault field', 'raw flag')}
PRINT_EVENTS = {
    'mixer_check_failed': 'Mixer check failed; inspect the required mixer before another attempt',
    'filling_tank': 'Filling-tank state reported; not proof of resin flow',
    'waiting_for_resolution': 'Waiting for fault resolution',
    'print_dispatch': 'Print dispatched; initiating user or automation is not established',
    'error_293': 'Reset-while-printing reference; underlying cause unknown',
    'aborted': 'Task aborted', 'finished': 'Task finished; not proof of a successful print',
    'HIGH_LEVEL_IDLE': 'Idle state observed; not an all-interlocks safety clearance',
    'HIGH_LEVEL_PREPRINT': 'Print preparation', 'HIGH_LEVEL_FILLING_TANK': 'Tank filling phase',
    'HIGH_LEVEL_LEVELSENSE_RECALIBRATION_HEATUP': 'LevelSense calibration heatup',
    'HIGH_LEVEL_LEVELSENSE_RECALIBRATION': 'LevelSense calibration phase'}
ERROR_REFERENCE = [
    {'code': 85, 'name': 'PR_ERROR_MIX', 'meaning': 'Mixer check failed; the code alone does not prove why'},
    {'code': 164, 'name': 'PR_ERROR_LEVELSENSE_FILLING_TANK', 'meaning': 'Filling state in this trace; not proof of an empty cartridge or physical resin flow'},
    {'code': 292, 'name': 'PR_ERROR_TENSIONER_MOVE_TIMEOUT', 'meaning': 'Tensioner move timeout; cause requires context'},
    {'code': 293, 'name': 'PR_ERROR_RESET_WHILE_PRINTING', 'meaning': 'Reset while printing; no specific LPU/heater cause established'},
    {'code': 294, 'name': 'PR_ERROR_LASER_OFFSET_SLOW_AXIS_OUTSIDE_RANGE', 'meaning': 'Slow-axis laser offset outside range; cause requires context'}]


def print_session_view(raw, demo=False):
    """Validate and project an offline capture report, never raw log text.

    The input may have secret keys/values in unknown fields. Rebuild every output
    object from an allowlist. Historical data never authorizes a physical action.
    """
    value = strict_json(raw)
    state = 'DEMO' if demo else 'HISTORICAL'
    if (not isinstance(value, dict) or value.get('schema_version') != 1 or
            value.get('state') != 'HISTORICAL' or value.get('firmware_scope') != '2.5.6-2773'):
        raise ValueError('Unsupported print report')
    sources = value.get('sources'); csv = value.get('heater_csv'); timeline = value.get('timeline')
    if (not isinstance(sources, list) or not 1 <= len(sources) <= 16 or
            not isinstance(csv, dict) or not isinstance(timeline, list) or len(timeline) > 20000):
        raise ValueError('Invalid print report shape')
    pins = []
    for item in sources:
        sha = item.get('sha256') if isinstance(item, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha):
            raise ValueError('Invalid capture provenance')
        pins.append(sha)
    channels = csv.get('channels')
    if not isinstance(channels, list) or len(channels) > 14:
        raise ValueError('Invalid heater channel budget')
    safe = []; names = set()
    for item in channels:
        if not isinstance(item, dict) or item.get('name') not in PRINT_CHANNELS:
            continue
        name = item['name']
        if name in names:
            raise ValueError('Duplicate heater channel')
        names.add(name)
        lo = number(item.get('min'), -1e9, 1e9); hi = number(item.get('max'), -1e9, 1e9)
        count = item.get('samples'); first = number(item.get('first'), 0, 1e11); last = number(item.get('last'), 0, 1e11)
        points = item.get('points')
        if (lo is None or hi is None or lo > hi or type(count) is not int or not 1 <= count <= 100000 or
                first is None or last is None or last < first or not isinstance(points, list) or len(points) > 60):
            raise ValueError('Invalid heater history')
        clean_points = []
        for point in points:
            if not isinstance(point, dict):
                raise ValueError('Invalid heater point')
            t = number(point.get('timestamp'), first, last); v = number(point.get('value'), lo, hi)
            if t is None or v is None:
                raise ValueError('Invalid heater point')
            clean_points.append({'timestamp': t, 'value': v})
        safe.append({'name': name, 'label': PRINT_CHANNELS[name][0], 'unit': PRINT_CHANNELS[name][1],
                     'state': state, 'samples': count, 'min': lo, 'max': hi, 'first': first, 'last': last,
                     'points': clean_points, 'source': 'Captured daguerreHeater_v1.csv; no current measurement'})
    events = []; seen = set(); last_state = None
    for row in sorted(timeline, key=lambda r: r.get('timestamp') or 0 if isinstance(r, dict) else 0):
        if not isinstance(row, dict):
            raise ValueError('Invalid timeline row')
        stamp = number(row.get('timestamp'), 0, 1e11); kind = row.get('kind'); code = row.get('value')
        if kind not in ('state_signal', 'task_signal', 'log_category') or not isinstance(code, str) or code not in PRINT_EVENTS or stamp is None:
            continue
        # Display grouping only: native reports remain in the private full report.
        group = (kind, code, int(stamp))
        if group in seen:
            continue
        seen.add(group)
        if kind == 'state_signal':
            if code == last_state:
                continue
            last_state = code
        events.append({'timestamp': stamp, 'kind': kind, 'code': code, 'description': PRINT_EVENTS[code], 'state': state})
    quality = value.get('coverage', {})
    if not isinstance(quality, dict):
        raise ValueError('Invalid coverage')
    counts = {k: number(quality.get(k), 0, 1000000) for k in
              ('boot_count', 'file_byte_gaps', 'partial_final_signals_omitted', 'coverage_boundary_records', 'coverage_gap_records')}
    return {'state': state, 'firmware': '2.5.6-2773', 'source_sha256': pins,
            'channels': safe, 'events': events[-200:], 'events_omitted': max(0, len(events)-200),
            'coverage': counts, 'safe_idle_proven': False, 'print_success_proven': False,
            'note': 'Copied session only. One-second display grouping is not a fault count. Finished is not print success; no continuous coverage or current safety claim.'}


class HistoricalBundle(object):
    """Consumes an authored, bounded export, never arbitrary rootfs paths."""
    def __init__(self, root):
        self.tree = SafeTree(root)

    def summary(self):
        value = strict_json(self.tree.read('panel_snapshot.json'))
        if not isinstance(value, dict) or value.get('schema_version') != 1:
            raise ValueError('Unsupported historical bundle')
        # A missing/corrupt optional report does not suppress other status sources.
        value['print_session'] = {'state': 'UNAVAILABLE', 'channels': [], 'events': []}
        try:
            raw = self.tree.optional('print_session.json')
            if raw is not None:
                value['print_session'] = print_session_view(raw, demo=value.get('state') == 'DEMO')
        except (ValueError, TypeError, OSError):
            value['print_session']['reason'] = 'INVALID_CAPTURE_REPORT'
        return value

    def logs(self):
        value = strict_json(self.tree.read('diagnostics.json'))
        if not isinstance(value, list) or len(value) > 20000:
            raise ValueError('Invalid diagnostic summary')
        return value

    def raw_log(self, file_id):
        # Opaque fixed exporter-generated IDs, never user paths.
        if not isinstance(file_id, str) or not re.match(r'^log-[0-9]{3}$', file_id):
            raise ValueError('Invalid log identifier')
        return self.tree.read('raw/' + file_id + '.log', 8 * 1024 * 1024)

SETTINGS_CATALOG = [
 {'id':'wlan_login_required','type':'boolean','default':False,'range':[False,True],
  'source':'owner access-policy.json','side_effects':'Require login on secondary owner LAN HTTP; primary HTTPS and SSH retain authentication',
  'reboot_required':False,'update_persistence':'Owner p7 settings','classification':'OWNER WRITE'},
 {'id':'display_alias','type':'string','default':'Owner maintenance','range':'ASCII letters/digits/space/._-; 1..48 characters',
  'source':'owner settings.json','side_effects':'Panel label only; no hostname or identity change','reboot_required':False,
  'update_persistence':'Owner p7 state can persist; startup hook persistence unproved','classification':'OWNER WRITE'},
 {'id':'refresh_seconds','type':'integer','default':10,'range':[5,60],'source':'owner settings.json',
  'side_effects':'Browser poll frequency','reboot_required':False,'update_persistence':'Owner p7 state only','classification':'OWNER WRITE'},
 {'id':'privacy_preference','type':'enum','default':'NORMAL','range':['NORMAL','CLOUD-MINIMIZED','LOCAL-ONLY'],
  'source':'owner settings.json','side_effects':'Preview only; no vendor setting/firewall/service change','reboot_required':False,
  'update_persistence':'Owner p7 preference only','classification':'OWNER WRITE'},
 {'id':'RefillableCartridgeMode','type':'vendor boolean','default':None,'range':None,
  'source':'SysV apply-customer-modifications -> compiled daguerre_cmds.apply',
  'side_effects':'Changes native lockout/flush settings; complete semantics unresolved','reboot_required':None,
  'update_persistence':'Unknown vendor policy','classification':'VENDOR WRITE DISABLED'},
 {'id':'FLOPEN01','type':'capability identifier','default':None,'range':None,
  'source':'Acquired Palantir/Formule/Sauron/CandyBus literal; active entitlement not verified',
  'side_effects':'License issuance/activation is separate from inspection','reboot_required':None,
  'update_persistence':'Not yet established','classification':'READ ONLY / VALIDITY UNKNOWN'}
]


def read_formule_capture(path, demo=False):
    """Parse one explicit copied stream; never a socket, polling source or safe-idle proof."""
    from formule_codec import FrameDecoder, MAX_CHUNK
    tree=SafeTree(os.path.dirname(os.path.abspath(path)))
    try:raw=tree.read(os.path.basename(path),2*1024*1024)
    finally:tree.close()
    decoder=FrameDecoder(max_frames=128,provenance='DEMO' if demo else 'HISTORICAL')
    frames=[]
    for offset in range(0,len(raw),MAX_CHUNK):frames.extend(decoder.feed(raw[offset:offset+MAX_CHUNK]))
    decoder.finish()
    status=next((frame['status'] for frame in reversed(frames) if 'status' in frame),{})
    return {'state':'DEMO' if demo else 'HISTORICAL','source_sha256':hashlib.sha256(raw).hexdigest(),
            'frames':len(frames),'status':status,'timestamp':None,'fresh':False,
            'safe_idle_proven':False,'live_connection':False,
            'note':'Copied Formule stream; no collection timestamp or current-state proof. Failed replies excluded.'}


MATERIAL_NAMES = {'FLGPWH41': 'White V4.1', 'FLGPWH04': 'White',
                  'FLGPCL04': 'Clear V4', 'FLGPCL05': 'Clear V5'}


def material_code(value):
    return value if isinstance(value, str) and re.match(r'^FL[A-Z0-9]{4,16}$', value) else None


class PrinterFiles(object):
    """Local prepared status, NOT an outbound request or measured safety state.

    Only exact reviewed fields leave this adapter. Serial joins stay internal;
    no raw map keys, job names, device identifiers or SecretKey reach the API.
    Cached file mtimes are publication times, not sensor measurement times.
    """
    def __init__(self, tree):
        self.tree = tree

    def snapshot(self):
        result = {'printer_state': field(), 'consumables': [], 'jobs': [],
                  'tank_level': field(unit='mm'), 'job_layer': field(),
                  'automatic_refill_pause': {'enabled': False, 'available': False,
                      'reason': 'No verified pre-motor pause gate; panel polling cannot prevent motor actuation.'},
                  'safe_idle_proven': False}
        try:
            raw, info = self.tree.read('data/printernet_client/ping.json', 512*1024, True)
            status = strict_json(raw)['payload']['device_status']
            if not isinstance(status, dict):
                return result
        except (OSError, ValueError, KeyError, TypeError):
            return result
        stamp = info.st_mtime
        source = 'Local prepared gateway status; file mtime is publication time, not measurement time'
        enum = status.get('status')
        if enum not in ('IDLE', 'READY', 'PRINTING', 'PAUSED', 'PAUSING', 'PREPRINT',
                        'PREPARING', 'ERROR', 'FINISHED', 'OFFLINE', 'BUSY'):
            enum = None
        result['printer_state'] = field(enum, 'CACHED', source, timestamp=stamp, max_age=60)
        jobs = status.get('print_jobs')
        if isinstance(jobs, list):
            for index, job in enumerate(jobs[:64]):
                if not isinstance(job, dict):
                    continue
                result['jobs'].append({'index': index+1, 'state': 'CACHED',
                    'source': source, 'timestamp': stamp, 'current_job_proven': False,
                    'material': material_code(job.get('material')),
                    'layer_count': number(job.get('layer_count'), 0, 1000000),
                    'layer_thickness_mm': number(job.get('layer_thickness_mm'), 0, 10),
                    'volume_ml': number(job.get('volume_ml'), 0, 100000),
                    'estimated_duration_ms': number(job.get('estimated_duration_ms'), 0, 1e12)})
        carts = status.get('cartridges')
        candidates = [('cartridge', c) for c in carts[:2]] if isinstance(carts, list) else []
        if isinstance(status.get('tank'), dict):
            candidates.append(('tank', status['tank']))
        for kind, item in candidates:
            if not isinstance(item, dict):
                continue
            present = item.get('type') == ('CARTRIDGE_PRESENT' if kind == 'cartridge' else 'TANK_PRESENT')
            if not present:
                continue  # Do not turn unknown or absent records into an inserted consumable.
            code = material_code(item.get('material'))
            view = {'kind': kind, 'fields': {}, 'native_reset_enabled': False,
                    'estimated_remaining_ml': field(unit='mL')}
            serial = item.get('serial')
            if isinstance(serial, str) and re.match(r'^[A-Za-z0-9_-]{1,128}$', serial):
                directory = 'Cartridges' if kind == 'cartridge' else 'Tanks'
                try:
                    data, meta = self.tree.read('data/'+directory+'/'+serial+'.json', 65536, True)
                    view = consumable_view(data, kind, meta.st_mtime)
                    for val in view['fields'].values():
                        if val['value'] is not None:
                            val['state'] = 'CACHED'
                        val['source'] += '; persisted, measurement time unknown'
                    if view['estimated_remaining_ml']['value'] is not None:
                        view['estimated_remaining_ml']['state'] = 'CACHED'
                    if kind == 'tank':
                        level = view['fields']['LastResinLevel_mm']
                        # Negative sentinels must not be presented as physical resin height.
                        result['tank_level'] = field(number(level['value'], 0, 100), 'CACHED',
                            'TankCartridgeDaemon LastResinLevel_mm; last saved reading, measurement age UNKNOWN',
                            'mm', meta.st_mtime)
                except (OSError, ValueError, TypeError):
                    pass
            view['material'] = field(MATERIAL_NAMES.get(code, code), 'CACHED', source+' / material', timestamp=stamp, max_age=60)
            view['material_code'] = code
            view['presence'] = field(True, 'CACHED', source+' / type', timestamp=stamp, max_age=60)
            result['consumables'].append(view)
        return result


class PassivePrinterSignals(object):
    """Fixed signal subscriptions, no device method calls or writable IPC.

    Legacy eavesdrop fallback is permitted by the inspected system bus for the
    unprivileged panel UID. BecomeMonitor denial alone does not imply no signals.
    Pipe buffers, parser state, cache and reconnect rate are bounded. A disconnect
    invalidates cached live values. No event grants safe-idle/dispense permission.
    """
    FILTERS = [
        "type='signal',sender='com.formlabs.Sauron',path='/com/formlabs/Sauron',interface='com.formlabs.Sauron',member='statesChanged'",
        "type='signal',sender='com.formlabs.Sauron',path='/com/formlabs/Sauron',interface='com.formlabs.Sauron',member='currentlyPrintingLayerChanged'",
        "type='signal',sender='com.formlabs.CandyBus',interface='com.formlabs.Temperature',member='temperature'",
        "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='com.formlabs.Sauron'",
        "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='com.formlabs.CandyBus'"]
    CHANNELS = {'/com/formlabs/momo/temperatures/'+n: n for n in ('Tower', 'ForceSense', 'Levelsense')}

    def __init__(self):
        self.lock = threading.Lock()
        self.values = {}
        self.stop = threading.Event()
        self.worker = None
        self.pending = b''

    def clear(self):
        with self.lock:
            self.values.clear()

    def accept(self, block, mono=None, wall=None):
        if not isinstance(block, bytes) or len(block) > 65536:
            return
        try:
            lines = block.decode('ascii').strip().splitlines()
        except UnicodeError:
            return
        if not lines:
            return
        header = re.match(r'^signal time=[0-9.]+ sender=[:A-Za-z0-9_.-]+ -> destination=[^\r\n]{1,100} serial=[0-9]+ path=([^; ]+); interface=([^; ]+); member=([A-Za-z0-9_]+)$', lines[0])
        if not header:
            return
        path, interface, member = header.groups()
        if interface == 'org.freedesktop.DBus' and member == 'NameOwnerChanged':
            self.clear()
            return
        body = '\n'.join(lines[1:])
        key, value = None, None
        if interface == 'com.formlabs.Temperature' and member == 'temperature' and path in self.CHANNELS:
            match = re.match(r'^\s*struct \{\s*boolean (true|false)\s+double (-?[0-9.eE+]+)\s*\}\s*$', body)
            if match:
                key = 'temperature/'+self.CHANNELS[path]
                try:
                    value = number(float(match.group(2)), -50, 150) if match.group(1) == 'false' else None
                except ValueError:
                    pass
        elif interface == 'com.formlabs.Sauron' and path == '/com/formlabs/Sauron':
            if member == 'currentlyPrintingLayerChanged':
                match = re.match(r'^\s*string "[A-Za-z0-9{}_-]{0,128}"\s+int32 ([0-9]{1,7})\s*$', body)
                if match:
                    key, value = 'job_layer', number(int(match.group(1)), 0, 1000000)
            elif member == 'statesChanged':
                match = re.match(r'^\s*string "[A-Za-z0-9{}_-]{0,128}"\s+array \[([\s\S]*)\]\s*$', body)
                if match and len(match.group(1)) < 8192:
                    values = re.findall(r'^\s*string "((?:HIGH_LEVEL|SAURON|PRINT|LEVELSENSE|PREHEAT|PR_ERROR)_[A-Z_0-9]{1,90})"\s*$', match.group(1), re.M)
                    if 0 < len(values) <= 64:
                        key, value = 'job_state', sorted(set(values))
        if key is not None:
            with self.lock:
                self.values[key] = (value, time.monotonic() if mono is None else mono,
                                    time.time() if wall is None else wall)

    def snapshot(self, mono=None):
        now = time.monotonic() if mono is None else mono
        with self.lock:
            values = dict(self.values)
        result = {'sensors': []}
        for key, (value, observed, stamp) in values.items():
            limit = 10 if key.startswith('temperature/') else 60
            fresh = 0 <= now-observed <= limit
            view = field(value if fresh else None, 'LIVE',
                'Passive system-bus '+key+'; no method call or safety clearance',
                'C' if key.startswith('temperature/') else None, stamp)
            view['fresh'] = bool(fresh and value is not None)
            if key.startswith('temperature/'):
                result['sensors'].append({'name': key.split('/')[1], 'celsius': view['value'], 'observation': view})
            else:
                result[key] = view
        return result

    def feed(self, chunk):
        # dbus-monitor does NOT promise blank lines between messages.
        # Complete the preceding frame at the next header; partial pipe reads
        # must not manufacture truncated values. Temperature events bound latency.
        self.pending += chunk
        if len(self.pending) > 65536:
            self.pending = b''
            self.clear()
            raise ValueError('Signal frame limit')
        while True:
            start = self.pending.find(b'signal time=')
            if start < 0:
                return
            self.pending = self.pending[start:]
            end = self.pending.find(b'\nsignal time=', 1)
            if end < 0:
                return
            self.accept(self.pending[:end])
            self.pending = self.pending[end+1:]

    def start(self):
        if self.worker is None:
            self.worker = threading.Thread(target=self._run)
            self.worker.daemon = True
            self.worker.start()

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(4)
        self.clear()

    def _run(self):
        while not self.stop.is_set():
            process = None
            try:
                process = subprocess.Popen(['/usr/bin/dbus-monitor', '--system']+self.FILTERS,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    close_fds=True, env={'PATH':'/usr/bin:/bin', 'LC_ALL':'C'})
                self.pending = b''
                while not self.stop.is_set() and process.poll() is None:
                    ready, _, _ = select.select([process.stdout], [], [], 1)
                    if not ready:
                        continue
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    self.feed(chunk)
            except (OSError, ValueError):
                pass  # No raw messages, paths or credentials in service logs.
            finally:
                if process:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill(); process.wait(timeout=1)
                    process.stdout.close()
                self.clear()
            self.stop.wait(30)
