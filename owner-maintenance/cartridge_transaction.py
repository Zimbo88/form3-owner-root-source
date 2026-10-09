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

from cartridge_codec import candidate, decode, parse_record, validate_legacy_material

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
            raise ValueError('Full idle required: stop jobs/calibration and wait for native preheat to be idle')
        return states

    def guard(self, require_idle=True):
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
        if require_idle:self.states()
        if self.stopped:
            self.exclusion()

    def preflight(self, preview_only=False):
        self.guard(require_idle=not preview_only)
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
        validate_legacy_material(a, record, self.plan['device_name'])
        if record.get('ResinID') != baseline_record.get('ResinID'):
            raise ValueError('Material changed since preview')
        if self.plan.get('material_target'):
            from cartridge_material import candidate as material_candidate
            from material_catalog import allowed_materials
            from read_ds2431_protection import read_memory
            if base64.b64decode(self.plan['material_before_b64'],validate=True)!=a:
                raise ValueError('Material rollback baseline mismatch')
            catalog=read_file('/data/settings/KnownConsumables.json',2<<20)
            if digest(catalog)!=self.plan['catalog_sha256'] or self.plan['material_target'] not in allowed_materials(catalog):
                raise ValueError('Material catalog or target eligibility changed')
            controls=read_memory(self.plan['device_name'],digest(a))
            if controls[128:]!=base64.b64decode(self.plan['protection_b64'],validate=True) or any(controls[i] in (0x55,0xaa) for i in (128,129)):
                raise ValueError('Material pages protected or protection state changed')
            target,revised,changes=material_candidate(a,record,self.plan['device_name'],self.plan['material_target'])
            decoded=decode(target,revised,self.plan['device_name'])
        else:
            target, rw, revised, decoded, changes = candidate(a, record, self.plan['device_name'], self.plan.get('restore_usage'))
        if target != base64.b64decode(self.plan['target_b64']) or digest(target) != self.plan['target_sha256']:
            raise ValueError('Target plan mismatch')
        # Assert exact non-usage JSON preservation, including unknown private fields.
        for key in record:
            if key not in (set(USAGE)|({'ResinID'} if self.plan.get('material_target') else set())) and record[key] != revised[key]:
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

    def write_material_rows(self, offset, data):
        self.exclusion()
        if not self.plan.get('material_target') or (offset,len(data)) not in ((24,16),(0,16)):
            raise ValueError('Unexpected material row write')
        target=base64.b64decode(self.plan['target_b64'],validate=True)
        before=base64.b64decode(self.plan['material_before_b64'],validate=True)
        if data not in (target[offset:offset+16],before[offset:offset+16]):
            raise ValueError('Unplanned material bytes')
        fd=os.open(self.image_path,os.O_WRONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size!=128 or os.lseek(fd,offset,os.SEEK_SET)!=offset or os.write(fd,data)!=16:
                raise ValueError('Material row write failed')
        finally:os.close(fd)

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



TANK_DRIVER = '/lib/modules/4.9.65+/extra/w1_ds28e36.ko'
TANK_DRIVER_SHA256 = '2549601cf7b059f1cad752234377d2270f1721c2a7a38b8ef27878c54732950a'


def commit_tank_records(io, before, target, original_file, target_file, event):
    """Material-only T/65 commit, native 32-byte page RMW, full readbacks.

    No identity, lifetime, protection or secret-page writes. There is no claim
    of power-fail atomicity. A durable transaction marker survives interruption.
    """
    allowed = set(range(33,37)) | set(range(61,69)) | set(range(129,133)) | set(range(157,165))
    if len(before)!=512 or len(target)!=512 or any(before[i]!=target[i] for i in range(512) if i not in allowed):
        raise ValueError('Unexpected tank target extent')
    attempted=[];file_attempted=False
    try:
        io.guard()
        if io.read_image()!=before or io.read_mirror()!=original_file:
            raise ValueError('Tank baseline changed before commit')
        file_attempted=True;io.write_mirror(target_file)
        if io.read_mirror()!=target_file:raise ValueError('Tank mirror readback mismatch')
        event('persistent_file','PASS');expected=bytearray(before)
        for label,offset in (('B',128),('A',32)):
            io.guard();attempted.append(offset)
            io.write_copy(offset,target[offset:offset+41])
            expected[offset:offset+41]=target[offset:offset+41]
            if io.read_image()!=bytes(expected):raise ValueError('Tank '+label+' full-image readback mismatch')
            event(label+'_write_readback','PASS')
        if io.read_image()!=target or io.read_mirror()!=target_file:
            raise ValueError('Tank target verification failed')
        event('full_target_comparison','PASS')
    except Exception:
        io.exclusion()
        for offset in sorted(set(attempted)):
            # Do not retry a protected/failed page if it never changed.
            if io.read_image()[offset:offset+41]!=before[offset:offset+41]:
                io.write_copy(offset,before[offset:offset+41])
            if io.read_image()[offset:offset+41]!=before[offset:offset+41]:
                event('rollback','FAIL');raise ValueError('Tank rollback record mismatch')
        if file_attempted:io.write_mirror(original_file)
        if io.read_image()!=before or io.read_mirror()!=original_file:
            event('rollback','FAIL');raise ValueError('Tank rollback full comparison failed')
        event('rollback','PASS')
        raise


class TankDevice(Device):
    """Pinned T/65 material assignment; lifetime is never reset or restored."""
    def __init__(self,plan):
        name=plan.get('device_name')
        if not isinstance(name,str) or not re.fullmatch(r'4c-[a-f0-9]{12}',name):
            raise ValueError('Unexpected tank identity syntax')
        if plan.get('kind')!='tank' or plan.get('operation') not in ('tank_material','tank_material_restore'):
            raise ValueError('Unexpected tank operation')
        self.plan=plan;self.image_path='/sys/bus/w1/devices/'+name+'/eeprom'
        self.mirror_path='/data/Tanks/'+name+'.json';self.metadata=None;self.stopped=False
        if plan.get('record_path')!=self.mirror_path:raise ValueError('Tank mirror identity mismatch')

    def read_image(self):
        if not os.path.realpath(self.image_path).startswith('/sys/devices/'):
            raise ValueError('Unexpected tank EEPROM filesystem')
        st=os.lstat(self.image_path)
        if not stat.S_ISREG(st.st_mode) or st.st_size!=512:raise ValueError('Unexpected tank EEPROM size')
        image=read_file(self.image_path,512)
        if len(image)!=512:raise ValueError('Short tank EEPROM read')
        return image

    def preflight(self, preview_only=False):
        from tank_codec import material_candidate,decode as tank_decode
        from package_format import unique_json
        from material_catalog import allowed_materials
        self.guard(require_idle=not preview_only)
        if os.path.realpath('/data')!='/data':raise ValueError('Unexpected persistent filesystem')
        space=os.statvfs('/data')
        if space.f_flag & os.ST_RDONLY or space.f_bavail*space.f_frsize < 1<<20:
            raise ValueError('Tank backup filesystem unavailable/full')
        # These required pins cannot be supplied/replaced by a browser or plan.
        from cartridge_broker import PINS
        if self.plan.get('source_hashes')!=PINS:raise ValueError('Tank plan source pins differ')
        for path,pin in list(PINS.items())+[(TANK_DRIVER,TANK_DRIVER_SHA256)]:
            if digest(read_file(path,64<<20))!=pin:raise ValueError('Tank runtime pin mismatch')
        catalog=read_file('/data/settings/KnownConsumables.json',2<<20)
        if digest(catalog)!=self.plan['catalog_sha256'] or self.plan['material_target'] not in allowed_materials(catalog):
            raise ValueError('Tank catalog changed or material is not a public Form 3 entry')
        image=self.read_image();raw=self.read_mirror();time.sleep(.25)
        if image!=self.read_image() or digest(image)!=self.plan['eeprom_sha256']:
            raise ValueError('Tank EEPROM baseline changed')
        record=unique_json(raw);baseline=base64.b64decode(self.plan['baseline_record_b64'],validate=True)
        if not self.stopped:
            from consumable_backup import selected,native_tank_material
            if selected('tank')!=self.plan['device_name'] or native_tank_material()!=record.get('LastResinUsed'):
                raise ValueError('Selected tank or native material differs from mirror')
        if digest(baseline)!=self.plan['record_sha256'] or mirror_semantic_pin(record)!=mirror_semantic_pin(unique_json(baseline)):
            raise ValueError('Tank mirror baseline changed')
        # The physical reference is 3.3; do not extend mechanical compatibility.
        if (record.get('TankVersionMajor'),record.get('TankVersionMinor'))!=(3,3):
            raise ValueError('Only the reviewed T/65 tank version 3.3 is supported')
        target,revised,decoded=material_candidate(image,record,self.plan['device_name'],self.plan['material_target'])
        if target!=base64.b64decode(self.plan['target_b64'],validate=True) or digest(target)!=self.plan['target_sha256']:
            raise ValueError('Tank target pin mismatch')
        if {k:v for k,v in record.items() if k!='LastResinUsed'}!={k:v for k,v in revised.items() if k!='LastResinUsed'}:
            raise ValueError('Tank non-material mirror field changed')
        target_file=(json.dumps(revised,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        st=os.lstat(self.mirror_path)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise ValueError('Unexpected tank mirror links/type')
        self.metadata={'uid':st.st_uid,'gid':st.st_gid,'mode':stat.S_IMODE(st.st_mode),
                       'mtime_ns':st.st_mtime_ns,'atime_ns':st.st_atime_ns,
                       'xattrs':{k:base64.b64encode(os.getxattr(self.mirror_path,k)).decode() for k in os.listxattr(self.mirror_path)}}
        return image,raw,target,target_file,decoded

    def write_copy(self,offset,data):
        self.exclusion()
        if offset not in (32,128) or not isinstance(data,bytes) or len(data)!=41:
            raise ValueError('Refusing non-RW tank write')
        target=base64.b64decode(self.plan['target_b64'],validate=True)
        before=base64.b64decode(self.plan['baseline_image_b64'],validate=True)
        if len(before)!=512 or digest(before)!=self.plan['eeprom_sha256'] or data not in (target[offset:offset+41],before[offset:offset+41]):
            raise ValueError('Unplanned tank record bytes')
        if not os.path.realpath(self.image_path).startswith('/sys/devices/'):
            raise ValueError('Tank EEPROM path changed')
        fd=os.open(self.image_path,os.O_WRONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size!=512 or os.lseek(fd,offset,os.SEEK_SET)!=offset:
                raise ValueError('Tank EEPROM attribute changed')
            if os.write(fd,data)!=41:raise ValueError('Short tank EEPROM write')
        finally:os.close(fd)

    def verify_reloaded(self,target,original):
        from tank_codec import decode as tank_decode
        from package_format import unique_json
        from consumable_backup import selected,native_tank_material
        if selected('tank')!=self.plan['device_name'] or native_tank_material()!=self.plan['material_target']:
            raise ValueError('Native tank re-recognition differs from target')
        image=self.read_image();raw=self.read_mirror();record=unique_json(raw)
        result=tank_decode(image,record,self.plan['device_name'])
        old=unique_json(original)
        expected=dict(old);expected['LastResinUsed']=self.plan['material_target']
        if image!=target or mirror_semantic_pin(record)!=mirror_semantic_pin(expected):
            raise ValueError('Tank post-start state changed; preserve recovery receipt')
        if not result['rw_equal'] or not all(all(c['record_matches'].values()) for c in result['copies']):
            raise ValueError('Tank reload mirror/copy mismatch')
        return image,raw,result['copies'][0]['values']


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
    tank=plan.get('kind')=='tank'
    device = TankDevice(plan) if tank else Device(plan)
    before, original, target, target_file, decoded = device.preflight()
    if not args.apply:
        print(json.dumps({'preflight':'PASS', 'writes':False, 'states':device.states(),
                          'baseline_sha256':digest(before), 'target_sha256':digest(target),
                          'target_usage':decoded['copies'][0]['values'] if tank else decoded['rw_copies'][0]['usage']}))
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
        if tank:
            commit_tank_records(device,before,target,original,target_file,event)
        elif plan.get('material_target'):
            from cartridge_material import commit_material
            commit_material(device,before,target,original,target_file,event)
        else:commit_records(device, before, target, original, target_file, event)
        actual = device.read_image()
        if tank:
            from tank_codec import decode as tank_decode
            from package_format import unique_json
            verified=tank_decode(actual,unique_json(device.read_mirror()),plan['device_name'])
        else:verified = decode(actual, parse_record(device.read_mirror()), plan['device_name'])
        if not all(all(c['record_matches'].values()) for c in verified['copies' if tank else 'rw_copies']):
            raise ValueError('Committed decode/mirror mismatch')
        durable_new(os.path.join(backup,'eeprom_after_write.bin'), actual)
        event('electronic_commit','PASS')
        device.service('start')
        event('daemon_restart','PASS')
        # Observe bounded native reload; no print/fill/power command is sent.
        observations = []
        for delay in (2, 3, 5, 10):
            time.sleep(delay)
            device.guard()
            if not device.processes():
                raise ValueError('Cartridge service exited after restart')
            if tank:
                actual,raw,values=device.verify_reloaded(target,original)
                observations.append({'epoch':time.time(),'sha256':digest(actual),'usage':values})
                continue
            actual = device.read_image()
            raw = device.read_mirror()
            rec = parse_record(raw)
            result = decode(actual, rec, plan['device_name'])
            allowed = set(range(64,80)) | set(range(96,112))
            reference=target if plan.get('material_target') else before
            if any(actual[i] != reference[i] for i in range(128) if i not in allowed):
                raise ValueError('Post-start non-RW bytes changed')
            expected_material=plan.get('material_target') or parse_record(original).get('ResinID')
            if rec.get('ResinID') != expected_material or rec.get('OriginalVolume_mL') != 1000:
                raise ValueError('Post-start material mismatch')
            for c in result['rw_copies']:
                usage = c['usage']
                desired = decoded['rw_copies'][0]['usage']
                if any(usage[f] != desired[f] for f in USAGE[:3]) or usage['WriteCount'] < plan['target_writecount']:
                    raise ValueError('Post-start usage restored/changed')
                if not all(c['record_matches'].values()):
                    raise ValueError('Post-start mirror mismatch')
            observations.append({'epoch':time.time(),'sha256':digest(actual),
                                 'usage':result['rw_copies'][0]['usage']})
        receipt['observations'] = observations
        receipt['material'] = plan.get('material_target') or parse_record(original)['ResinID']
        receipt['operation'] = plan['operation'] if tank else 'material_assignment' if plan.get('material_target') else ('usage_restore' if plan.get('restore_usage') else 'usage_reset')
        receipt['final_usage'] = observations[-1]['usage']
        receipt['status'] = 'CONSUMABLE TRANSACTION VERIFIED; DISPLAY NOT INDEPENDENTLY OBSERVED'
        durable_new(os.path.join(backup,'eeprom_after_reload.bin'), actual)
        durable_new(os.path.join(backup,'mirror_after_reload.private.json'), raw)
        event('post_start_merge','PASS')
    except Exception as exc:
        receipt['status'] = 'FAILED; inspect exact stage before further changes'
        receipt['failure_class'] = type(exc).__name__
        # Our error strings contain no cartridge identity/key or raw log content.
        receipt['failure'] = str(exc) if isinstance(exc, ValueError) else 'OS/timeout failure; private diagnosis required'
        if device.stopped and (receipt['stages'].get('rollback') == 'PASS' or (not receipt['stages'].get('quiesced_baseline') and not receipt['stages'].get('electronic_commit'))):
            device.service('start')
            event('daemon_restored_after_rollback','PASS')
        event('failure','FAIL')
        print(json.dumps(receipt,sort_keys=True))
        sys.exit(2)
    print(json.dumps(receipt,sort_keys=True))


if __name__ == '__main__':
    main()
