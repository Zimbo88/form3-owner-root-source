#!/usr/bin/env python3
"""Explicitly pinned legacy Clear C/0 usage transaction; Python 3.5 compatible.

No print, dispensing, GPIO, motor, identity or firmware commands.
Default is preflight only. Apply requires both --apply and --accept LIVE_RESET.
This is an owner usage adjustment, not evidence of physically available resin.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time

from cartridge_codec import candidate, decode, parse_record

SERVICE = '/etc/init.d/tank-cartridge-daemon'
DAEMON = '/usr/bin/TankCartridgeDaemon'
USAGE = ('EstimatedVolumeDispensed_ml', 'DispenseCount',
         'CumulativeDispenseTime_s', 'WriteCount')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def mirror_semantic_pin(record):
    stable = dict(record)
    stable.pop('LastSuccessfulWritebackTime', None)
    # Typed values avoid interpreter-dependent JSON float formatting. Preserve
    # every unknown field and its type, without exporting its name or value.
    def canonical(value):
        if value is None:
            return ['null']
        if type(value) is bool:
            return ['bool', 'true' if value else 'false']
        if type(value) is int:
            return ['int', str(value)]
        if type(value) is float:
            return ['float', value.hex()]
        if type(value) is str:
            return ['str', value]
        if type(value) is list:
            return ['list', [canonical(v) for v in value]]
        if type(value) is dict:
            return ['dict', [[k, canonical(value[k])] for k in sorted(value)]]
        raise ValueError('Unsupported record type')
    return digest(json.dumps(canonical(stable), ensure_ascii=True,
                             separators=(',', ':'), allow_nan=False).encode('ascii'))


def read_file(path, limit=65536):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise ValueError('Unbounded/nonregular input')
        data = b''
        while len(data) <= limit:
            part = os.read(fd, min(65536, limit + 1 - len(data)))
            if not part:
                break
            data += part
        if len(data) > limit:
            raise ValueError('Input grew beyond bound')
        return data
    finally:
        os.close(fd)


def durable_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_file(path, data, metadata):
    """Same-directory atomic replacement, preserving owner/mode and xattrs."""
    directory = os.path.dirname(path)
    if os.path.realpath(path) != path:
        raise ValueError('Mirror path changed')
    fd, temporary = tempfile.mkstemp(prefix='.owner-usage-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            os.fchown(f.fileno(), metadata['uid'], metadata['gid'])
            os.fchmod(f.fileno(), metadata['mode'])
            for key, value in metadata['xattrs'].items():
                os.setxattr(f.fileno(), key, base64.b64decode(value))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        sync_dir(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def commit_records(io, before, target, original_file, target_file, event):
    """Bounded ordered commit. Caller must exclude the native writer first.

    At most one write per copy; on failure restore attempted copies A then B,
    followed by the original file. No automatic retries of an EEPROM write.
    """
    if len(before) != 128 or len(target) != 128:
        raise ValueError('Expected exact image size')
    allowed = set(range(64, 80)) | set(range(96, 112))
    if any(before[i] != target[i] for i in range(128) if i not in allowed):
        raise ValueError('Target modifies protected identity/other bytes')
    attempted = []
    file_attempted = False
    try:
        io.guard()
        if io.read_image() != before or io.read_mirror() != original_file:
            raise ValueError('Baseline changed before commit')
        file_attempted = True
        io.write_mirror(target_file)
        if io.read_mirror() != target_file:
            raise ValueError('Mirror readback mismatch')
        event('persistent_file', 'PASS')
        expected = bytearray(before)
        for name, offset in [('B', 96), ('A', 64)]:
            io.guard()
            attempted.append(offset)
            io.write_copy(offset, target[offset:offset+16])
            expected[offset:offset+16] = target[offset:offset+16]
            actual = io.read_image()
            if actual != bytes(expected):
                raise ValueError(name + ' full-image readback mismatch')
            event(name + '_write_readback', 'PASS')
        if io.read_image() != target or io.read_mirror() != target_file:
            raise ValueError('Final commit comparison failed')
        event('full_target_comparison', 'PASS')
    except Exception:
        # Exclusion is essential during rollback as well; do not race a new writer.
        io.exclusion()
        for offset in sorted(set(attempted)):
            io.write_copy(offset, before[offset:offset+16])
            if io.read_image()[offset:offset+16] != before[offset:offset+16]:
                event('rollback', 'FAIL')
                raise ValueError('Rollback copy readback failed')
        if file_attempted:
            io.write_mirror(original_file)
        if io.read_image() != before or io.read_mirror() != original_file:
            event('rollback', 'FAIL')
            raise ValueError('Rollback full verification failed')
        event('rollback', 'PASS')
        raise


class Device(object):
    def __init__(self, plan):
        self.plan = plan
        name = plan['device_name']
        if not re.match(r'^2d-[a-f0-9]{12}$', name):
            raise ValueError('Unexpected identity syntax')
        self.image_path = '/sys/bus/w1/devices/' + name + '/eeprom'
        self.mirror_path = '/data/Cartridges/' + name + '.json'
        if plan['record_path'] != self.mirror_path:
            raise ValueError('Mirror identity mismatch')
        self.metadata = None
        self.stopped = False

    def read_image(self):
        if not os.path.realpath(self.image_path).startswith('/sys/devices/'):
            raise ValueError('Unexpected EEPROM filesystem')
        st = os.lstat(self.image_path)
        if not stat.S_ISREG(st.st_mode) or st.st_size != 128:
            raise ValueError('Unexpected EEPROM size or type')
        data = read_file(self.image_path, 128)
        if len(data) != 128:
            raise ValueError('Short EEPROM read')
        return data

    def read_mirror(self):
        if os.path.realpath(self.mirror_path) != self.mirror_path:
            raise ValueError('Unexpected mirror filesystem')
        return read_file(self.mirror_path)

    def processes(self):
        result = []
        for pid in os.listdir('/proc'):
            if not pid.isdigit():
                continue
            try:
                exe = os.readlink('/proc/' + pid + '/exe')
                args = read_file('/proc/' + pid + '/cmdline', 4096).split(b'\0')
                if exe == DAEMON or b'/usr/bin/tank-cartridge-daemon-launcher' in args:
                    result.append(int(pid))
            except OSError:
                pass
        return result

    def exclusion(self):
        if self.processes():
            raise ValueError('Native cartridge writer is still running')

    def states(self):
        results = {}
        for method in ['GetStates', 'GetCurrentPrintGuid']:
            args = ['/usr/bin/dbus-send', '--system', '--print-reply',
                    '--reply-timeout=3000', '--dest=com.formlabs.Sauron',
                    '/com/formlabs/Sauron', 'com.formlabs.Sauron.' + method]
            proc = subprocess.run(args, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=5)
            if proc.returncode or len(proc.stdout) > 8192:
                raise ValueError('Current state query failed')
            results[method] = re.findall(r'string "([^"\n]*)"', proc.stdout.decode('ascii'))
        if results['GetCurrentPrintGuid'] != ['']:
            raise ValueError('A current print is present')
        states = results['GetStates']
        if set(states) != set(['PREHEAT_IDLE', 'PRINT_IDLE', 'PAUSE_NONE', 'SAURON_IDLE', 'HIGH_LEVEL_IDLE']):
            raise ValueError('Expected observed idle state set')
        return states

    def guard(self):
        if os.getuid() != 0 or os.uname().machine != 'armv7l' or os.uname().release != '4.9.65+':
            raise ValueError('Wrong target context')
        if read_file('/proc/sys/kernel/random/boot_id', 128).decode().strip() != self.plan['boot_id']:
            raise ValueError('Boot context changed')
        cmdline = read_file('/proc/cmdline', 4096).decode().split()
        if 'root=/dev/mmcblk0p6' not in cmdline or 'rdinit=/init' in cmdline:
            raise ValueError('Wrong root slot')
        version = json.loads(read_file('/etc/formlabs/version.json').decode())
        if version.get('build', {}).get('name') != self.plan['firmware']:
            raise ValueError('Firmware mismatch')
        if os.path.exists('/data/owner-maintenance/pending.json'):
            raise ValueError('Pending owner transaction')
        self.states()
        if self.stopped:
            self.exclusion()

    def preflight(self):
        self.guard()
        if os.path.realpath('/data') != '/data' or not os.path.isdir('/data'):
            raise ValueError('Persistent backup parent unavailable')
        space = os.statvfs('/data')
        if space.f_flag & os.ST_RDONLY or space.f_bavail * space.f_frsize < (1 << 20):
            raise ValueError('Persistent backup filesystem unavailable/full')
        for path, pin in self.plan['source_hashes'].items():
            if digest(read_file(path, 64 << 20)) != pin:
                raise ValueError('Reference binary/script changed')
        raw = self.read_mirror()
        a = self.read_image()
        time.sleep(1)
        if a != self.read_image() or digest(a) != self.plan['eeprom_sha256']:
            raise ValueError('EEPROM baseline mismatch')
        record = parse_record(raw)
        baseline_raw = base64.b64decode(self.plan['baseline_record_b64'], validate=True)
        if digest(baseline_raw) != self.plan['record_sha256']:
            raise ValueError('Baseline record pin mismatch')
        baseline_record = parse_record(baseline_raw)
        if mirror_semantic_pin(record) != mirror_semantic_pin(baseline_record):
            raise ValueError('Mirror fields changed beyond writeback timestamp')
        if record.get('ResinID') != 'FLGPCL02' or record.get('OriginalVolume_mL') != 1000:
            raise ValueError('Wrong material or nominal volume')
        target, rw, revised, decoded, changes = candidate(a, record, self.plan['device_name'])
        if target != base64.b64decode(self.plan['target_b64']) or digest(target) != self.plan['target_sha256']:
            raise ValueError('Target plan mismatch')
        # Assert exact non-usage JSON preservation, including unknown private fields.
        for key in record:
            if key not in USAGE and record[key] != revised[key]:
                raise ValueError('Non-usage field changed')
        target_file = (json.dumps(revised, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
        st = os.lstat(self.mirror_path)
        if st.st_nlink != 1:
            raise ValueError('Unexpected mirror links')
        self.metadata = {'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode),
                         'mtime_ns': st.st_mtime_ns, 'atime_ns': st.st_atime_ns,
                         'xattrs': {k: base64.b64encode(os.getxattr(self.mirror_path, k)).decode()
                                    for k in os.listxattr(self.mirror_path)}}
        return a, raw, target, target_file, decoded

    def write_mirror(self, data):
        self.exclusion()
        replace_file(self.mirror_path, data, self.metadata)

    def write_copy(self, offset, data):
        self.exclusion()
        if offset not in (64, 96) or len(data) != 16:
            raise ValueError('Refusing non-RW write')
        fd = os.open(self.image_path, os.O_WRONLY | os.O_NOFOLLOW)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size != 128:
                raise ValueError('EEPROM attribute changed')
            if os.lseek(fd, offset, os.SEEK_SET) != offset:
                raise ValueError('EEPROM seek failed')
            if os.write(fd, data) != 16:
                raise ValueError('EEPROM short write')
        finally:
            os.close(fd)

    def service(self, action):
        if action not in ('stop', 'start'):
            raise ValueError('Unsupported service action')
        if action == 'stop':
            pid = read_file('/var/run/tank-cartridge-daemon.pid', 32).decode().strip()
            if not pid.isdigit() or b'/usr/bin/tank-cartridge-daemon-launcher' not in read_file('/proc/'+pid+'/cmdline',4096).split(b'\0'):
                raise ValueError('Launcher PID file does not match process')
        proc = subprocess.run([SERVICE, action], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=10)
        if proc.returncode:
            raise ValueError('Cartridge service command failed')
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            active = bool(self.processes())
            if active == (action == 'start'):
                if action == 'start' and not any(
                        os.path.exists('/proc/'+str(pid)+'/exe') and
                        os.path.realpath('/proc/'+str(pid)+'/exe') == DAEMON
                        for pid in self.processes()):
                    time.sleep(0.2)
                    continue
                self.stopped = action == 'stop'
                return
            time.sleep(0.2)
        raise ValueError('Cartridge service state timeout')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--accept')
    args = parser.parse_args()
    if args.apply != (args.accept == 'LIVE_RESET') or (args.accept and not args.apply):
        parser.error('Apply requires exactly --apply --accept LIVE_RESET')
    os.umask(0o077)
    raw_plan = read_file(args.plan)
    if digest(raw_plan) != args.plan_sha256:
        raise ValueError('Plan pin mismatch')
    plan = json.loads(raw_plan.decode())
    lock_fd = None
    if args.apply:
        lock_fd = os.open('/run/form3-clear-reset.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Share the installed ownerctl lock: an update/rollback must not replace
        # the helper while it is adjusting EEPROM or restarting the daemon.
        maintenance_lock = os.open('/data/owner-maintenance/.transaction-lock',
                                   os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,0o600)
        st = os.fstat(maintenance_lock)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077 or st.st_size:
            raise ValueError('Untrusted maintenance lock')
        fcntl.flock(maintenance_lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    device = Device(plan)
    before, original, target, target_file, decoded = device.preflight()
    if not args.apply:
        print(json.dumps({'preflight':'PASS', 'writes':False, 'states':device.states(),
                          'baseline_sha256':digest(before), 'target_sha256':digest(target),
                          'target_usage':decoded['rw_copies'][0]['usage']}))
        return
    backup = tempfile.mkdtemp(prefix='form3-clear-reset-'+time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())+'-', dir='/data')
    receipt = {'schema':1, 'status':'BACKUP', 'stages':{}, 'plan_sha256':args.plan_sha256,
               'backup_path':backup, 'baseline_sha256':digest(before), 'target_sha256':digest(target),
               'hardware_repair_not_tested_by_software':True, 'reboot_performed':False,
               'physical_supply':'Not measured; electronic usage adjustment only',
               'actuator_inhibit_installed':False}
    def event(stage, result):
        receipt['stages'][stage] = result
        receipt['updated_epoch'] = time.time()
        temp = os.path.join(backup, 'receipt.next')
        durable_new(temp, (json.dumps(receipt, sort_keys=True, indent=2)+'\n').encode())
        os.replace(temp, os.path.join(backup, 'receipt.json'))
        sync_dir(backup)
    durable_new(os.path.join(backup,'eeprom_before.bin'), before)
    durable_new(os.path.join(backup,'mirror_before.private.json'), original)
    durable_new(os.path.join(backup,'mirror_metadata.private.json'), json.dumps(device.metadata,sort_keys=True).encode())
    durable_new(os.path.join(backup,'target.bin'), target)
    durable_new(os.path.join(backup,'plan.private.json'), raw_plan)
    event('backup','PASS')
    # A lost SSH connection must not interrupt a started transaction halfway.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        device.guard()
        device.service('stop')
        event('daemon_stop','PASS')
        # Vendor timestamp may advance between preflight and stop. Re-capture
        # the exact quiesced baseline; every other record field remains pinned.
        before, original, target, target_file, decoded = device.preflight()
        durable_new(os.path.join(backup,'mirror_before_commit.private.json'), original)
        durable_new(os.path.join(backup,'mirror_metadata_before_commit.private.json'), json.dumps(device.metadata,sort_keys=True).encode())
        receipt['mirror_before_commit_sha256'] = digest(original)
        event('quiesced_baseline','PASS')
        commit_records(device, before, target, original, target_file, event)
        actual = device.read_image()
        verified = decode(actual, parse_record(device.read_mirror()), plan['device_name'])
        if not all(all(c['record_matches'].values()) for c in verified['rw_copies']):
            raise ValueError('Committed decode/mirror mismatch')
        durable_new(os.path.join(backup,'eeprom_after_write.bin'), actual)
        event('electronic_reset','PASS')
        device.service('start')
        event('daemon_restart','PASS')
        # Observe bounded native reload; no print/fill/power command is sent.
        observations = []
        for delay in (2, 3, 5, 10):
            time.sleep(delay)
            device.guard()
            if not device.processes():
                raise ValueError('Cartridge service exited after restart')
            actual = device.read_image()
            raw = device.read_mirror()
            rec = parse_record(raw)
            result = decode(actual, rec, plan['device_name'])
            allowed = set(range(64,80)) | set(range(96,112))
            if any(actual[i] != before[i] for i in range(128) if i not in allowed):
                raise ValueError('Post-start non-RW bytes changed')
            if rec.get('ResinID') != 'FLGPCL02' or rec.get('OriginalVolume_mL') != 1000:
                raise ValueError('Post-start material mismatch')
            for c in result['rw_copies']:
                usage = c['usage']
                if any(usage[f] != 0 for f in USAGE[:3]) or usage['WriteCount'] < plan['target_writecount']:
                    raise ValueError('Post-start usage restored/changed')
                if not all(c['record_matches'].values()):
                    raise ValueError('Post-start mirror mismatch')
            observations.append({'epoch':time.time(),'sha256':digest(actual),
                                 'usage':result['rw_copies'][0]['usage']})
        receipt['observations'] = observations
        receipt['material'] = 'FLGPCL02'
        receipt['final_usage'] = observations[-1]['usage']
        receipt['status'] = 'ELECTRONIC RESET VERIFIED; DISPLAY NOT INDEPENDENTLY OBSERVED'
        durable_new(os.path.join(backup,'eeprom_after_reload.bin'), actual)
        durable_new(os.path.join(backup,'mirror_after_reload.private.json'), raw)
        event('post_start_merge','PASS')
    except Exception as exc:
        receipt['status'] = 'FAILED; inspect exact stage before further changes'
        receipt['failure_class'] = type(exc).__name__
        # Our error strings contain no cartridge identity/key or raw log content.
        receipt['failure'] = str(exc) if isinstance(exc, ValueError) else 'OS/timeout failure; private diagnosis required'
        if device.stopped and receipt['stages'].get('rollback') == 'PASS':
            device.service('start')
            event('daemon_restored_after_rollback','PASS')
        event('failure','FAIL')
        print(json.dumps(receipt,sort_keys=True))
        sys.exit(2)
    print(json.dumps(receipt,sort_keys=True))


if __name__ == '__main__':
    main()
