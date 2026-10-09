#!/usr/bin/env python3
"""Root-only local broker for one reviewed legacy Clear usage adjustment.

The panel receives no EEPROM bytes, identity, keys, paths, commands or raw logs.
No network listener. No print/fill/power command. Python 3.5 compatible.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import signal
import socket
import stat
import struct
import subprocess
import threading
import time

from cartridge_codec import candidate, parse_record, validate_legacy_material
from cartridge_transaction import Device, read_file, durable_new, digest, sync_dir
from consumable_backup import Store, capture, selected

RUN = '/run/form3-cartridge-reset'
SOCKET = RUN + '/broker.sock'
ROOT = '/data/owner-maintenance/cartridge-reset'
PINS = {
    '/usr/bin/TankCartridgeDaemon': 'a2a5e3c47cf1c0c2cc627bcfcba10c0c20a843420fa46ca39290be27e861a8c1',
    '/usr/bin/Sauron': '025a21f7cdfaf2f10b2a40f2580d62992794a1d500643194e4606eb4e8676e34',
    '/etc/init.d/tank-cartridge-daemon': '5c4952be1e824b9f460910b187173e1649fcc92d2eda4aa09e789b2dabd8311c',
    '/usr/bin/tank-cartridge-daemon-launcher': 'ea10c6ce61979748b43cef5a25b8f9f1faf4655226541d3225aa33ce2b5c8815'}


def token():
    return __import__('binascii').hexlify(os.urandom(24)).decode('ascii')


def strict_request(value):
    if not isinstance(value, dict) or value.get('operation') not in ('status', 'prepare', 'apply', 'backup', 'backups', 'prepare_restore','materials','prepare_material','apply_material','prepare_tank_material','apply_tank_material'):
        raise ValueError('Unknown reset operation')
    required = {'operation', 'plan_id'} if value['operation'] in ('apply','apply_material','apply_tank_material') else {'operation'}
    if value['operation']=='backup':required={'operation','kind'}
    if value['operation']=='prepare_restore':required={'operation','backup_id'}
    if value['operation'] in ('prepare_material','prepare_tank_material'):required={'operation','material'}
    if set(value) != required:
        raise ValueError('Unknown reset request field')
    if 'plan_id' in value and (not isinstance(value['plan_id'], str) or not re.match(r'^[a-f0-9]{48}$', value['plan_id'])):
        raise ValueError('Invalid plan identifier')
    if 'kind' in value and value['kind'] not in ('cartridge','tank'):raise ValueError('Invalid backup kind')
    if 'backup_id' in value and (not isinstance(value['backup_id'],str) or not re.fullmatch(r'[a-f0-9]{32}',value['backup_id'])):
        raise ValueError('Invalid backup identifier')
    if 'material' in value and (not isinstance(value['material'],str) or not re.fullmatch(r'FL[A-Z0-9]{6}',value['material'])):raise ValueError('Invalid material code')
    return value


def private_directory(path, mode=0o700, gid=0):
    if not os.path.lexists(path):
        os.mkdir(path, mode)
        os.chown(path, 0, gid)
        os.chmod(path, mode)
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_gid != gid or stat.S_IMODE(st.st_mode) != mode:
        raise ValueError('Unexpected private directory ownership or mode')



def preview_readiness():
    try:
        object.__new__(Device).states()
        return {'apply_ready':True,'apply_blocker':None}
    except (ValueError,OSError,subprocess.TimeoutExpired):
        return {'apply_ready':False,'apply_blocker':'Read-only preview. Apply requires full native idle, including preheat, and no current job; prepare again when idle.'}


def prepare_plan(restore_id=None, store=None, material_target=None):
    if read_file('/proc/device-tree/model', 256).rstrip(b'\0\n') != b'Formlabs Daguerre':
        raise ValueError('Only the reviewed Form 3 platform is supported')
    for path, pin in PINS.items():
        if digest(read_file(path, 64 << 20)) != pin:
            raise ValueError('Unsupported firmware component; no reset')
    name=selected('cartridge')
    record_path = '/data/Cartridges/' + name + '.json'
    raw = read_file(record_path)
    record = parse_record(raw)
    plan = {'device_name': name, 'record_path': record_path, 'firmware':'2.5.6-2773',
            'boot_id':read_file('/proc/sys/kernel/random/boot_id',128).decode().strip(),
            'source_hashes':PINS, 'record_sha256':digest(raw),
            'baseline_record_b64':base64.b64encode(raw).decode('ascii')}
    device = Device(plan)
    device.guard(require_idle=False)
    image = device.read_image()
    time.sleep(0.25)
    if image != device.read_image():
        raise ValueError('Cartridge changed between reads')
    code=validate_legacy_material(image,record,name)
    if material_target is not None:
        from material_catalog import allowed_materials
        from cartridge_material import candidate as material_candidate
        from read_ds2431_protection import read_memory
        catalog=read_file('/data/settings/KnownConsumables.json',2<<20)
        if material_target not in allowed_materials(catalog):raise ValueError('Target is not an explicit public Form 3 catalog entry')
        if material_target==code:
            return {},{'already_fresh':True,'material':code,'nominal_ml':1000,'action':'material_assignment','before':{'material':code},'after':{'material':code}}
        control=read_memory(name,digest(image))
        if any(control[i] in (0x55,0xaa) for i in (128,129)):raise ValueError('Material pages are protected or one-way')
        target,revised,changes=material_candidate(image,record,name,material_target)
        plan.update(material_target=material_target,catalog_sha256=digest(catalog),protection_b64=base64.b64encode(control[128:]).decode(),material_before_b64=base64.b64encode(image).decode(),
                    eeprom_sha256=digest(image),target_sha256=digest(target),target_b64=base64.b64encode(target).decode(),initial_writecount=record['WriteCount'],target_writecount=record['WriteCount'])
        Device(plan).preflight(preview_only=True)
        preview={'already_fresh':False,'material':code,'nominal_ml':1000,'action':'material_assignment',
                     'before':{'material':code},'after':{'material':material_target},'usage_unchanged':True,'physical_resin_compatibility':'NOT ESTABLISHED'}
        preview.update(preview_readiness());return plan,preview
    restored=None
    if restore_id is not None:
        if store is None:raise ValueError('Private restore store unavailable')
        restored=store.restore_usage(restore_id,{'kind':'cartridge','device_name':name,'eeprom':image,'record':raw})
        plan['restore_usage']=restored
        plan['restore_backup_id']=restore_id
    target, rw, revised, decoded, changes = candidate(image, record, name, restored)
    before = {k:record[k] for k in ('EstimatedVolumeDispensed_ml','DispenseCount','CumulativeDispenseTime_s','WriteCount')}
    desired=restored or {k:0 for k in before if k!='WriteCount'}
    fresh = all(before[k] == desired[k] for k in before if k != 'WriteCount')
    plan.update(eeprom_sha256=digest(image), target_sha256=digest(target),
                target_b64=base64.b64encode(target).decode('ascii'),
                initial_writecount=record['WriteCount'], target_writecount=revised['WriteCount'])
    device = Device(plan)
    device.preflight(preview_only=True)
    preview = {'material':code,'nominal_ml':1000,'before':before,
               'after':dict(before) if fresh else decoded['rw_copies'][0]['usage'], 'already_fresh':fresh,
               'action':'restore_usage' if restored is not None else 'reset_usage',
               'identity_changed':False,'physical_volume_measured':False,
               'format':'C/0, RW/1, 128 bytes', 'estimated_remaining_after_ml':max(0,1000-desired['EstimatedVolumeDispensed_ml'])}
    preview.update(preview_readiness())
    return plan, preview



def prepare_tank_plan(material_target=None,restore_id=None,store=None):
    from package_format import unique_json
    from tank_codec import material_candidate
    from material_catalog import allowed_materials
    from cartridge_transaction import TankDevice
    if read_file('/proc/device-tree/model',256).rstrip(b'\0\n')!=b'Formlabs Daguerre':
        raise ValueError('Only the reviewed Form 3 platform is supported')
    value=capture('tank');name=value['device_name'];image=value['eeprom'];raw=value['record']
    if value['validation']!='CHECKSUMS_AND_MIRROR_VERIFIED':raise ValueError('Tank backup inputs disagree')
    record=unique_json(raw)
    if restore_id is not None:
        if store is None:raise ValueError('Tank restore store unavailable')
        material_target=store.restore_tank_material(restore_id,value)
    catalog=read_file('/data/settings/KnownConsumables.json',2<<20)
    if material_target not in allowed_materials(catalog):raise ValueError('Tank target is not an explicit public Form 3 catalog entry')
    target,revised,decoded=material_candidate(image,record,name,material_target)
    plan={'kind':'tank','operation':'tank_material_restore' if restore_id is not None else 'tank_material',
          'device_name':name,'record_path':'/data/Tanks/'+name+'.json','firmware':'2.5.6-2773',
          'boot_id':read_file('/proc/sys/kernel/random/boot_id',128).decode().strip(),'source_hashes':PINS,
          'record_sha256':digest(raw),'baseline_record_b64':base64.b64encode(raw).decode(),
          'eeprom_sha256':digest(image),'baseline_image_b64':base64.b64encode(image).decode(),
          'target_sha256':digest(target),'target_b64':base64.b64encode(target).decode(),
          'catalog_sha256':digest(catalog),'material_target':material_target}
    if restore_id is not None:plan['restore_backup_id']=restore_id
    TankDevice(plan).preflight(preview_only=True)
    preview={'kind':'tank','action':plan['operation'],'already_fresh':target==image,'material':record['LastResinUsed'],
             'before':{'material':record['LastResinUsed']},'after':{'material':material_target},
             'identity_changed':False,'lifetime_preserved':True,'physical_resin_compatibility':'NOT ESTABLISHED',
             'clean_tank_confirmation_required':True,'scope':'T/65 tank version 3.3; material only; lifetime unchanged'}
    preview.update(preview_readiness())
    return plan,preview


def prepare_saved_plan(identity,store):
    meta,_,_=store.load(identity)
    if meta['kind']=='tank':return prepare_tank_plan(restore_id=identity,store=store)
    return prepare_plan(identity,store)


class Broker(object):
    def __init__(self, root=ROOT, prepare=prepare_plan, execute=None):
        self.root, self.prepare_fn = root, prepare
        self.backups=Store(os.path.join(root,'backups'))
        self.execute_fn = execute or self.execute
        self.lock = threading.RLock()
        self.worker = None
        self.plan = None
        self.deadline = 0
        self.closing = False
        self.state = {'state':'AVAILABLE','supported_format':'1000 mL C/0 RW/1 with verified RO material', 'format':'C/0 RW/1',
                      'operation':'Electronic usage adjustment; not a physical refill'}
        if os.path.exists(os.path.join(root,'in-progress.json')):
            self.state = {'state':'RECOVERY_REQUIRED', 'error':'Previous transaction interrupted; review private backup before another reset'}

    def status(self):
        with self.lock:
            result = dict(self.state)
            if result.get('state') == 'READY' and time.monotonic() > self.deadline:
                result['state'] = 'EXPIRED'
            result['busy'] = bool(self.worker and self.worker.is_alive())
            return result

    def request(self, value):
        strict_request(value)
        if value['operation'] == 'status':
            return self.status()
        if value['operation']=='materials':
            from material_catalog import allowed_materials
            raw=read_file('/data/settings/KnownConsumables.json',2<<20)
            return {'state':'MATERIALS','codes':allowed_materials(raw),'tank_write_available':True,
                    'tank_reason':'T/65 version 3.3 only. Empty/clean tank confirmation, idle and checksum gates; lifetime and identity preserved',
                    'catalog_sha256':digest(raw)}
        if value['operation']=='backups':
            with self.lock:
                if self.worker and self.worker.is_alive():raise ValueError('Wait for the current operation')
                rows=self.backups.list()
                return {'state':'BACKUPS','backups':rows[:12],'total':len(rows),'raw_download_available':False,
                        'tank_restore_available':True,'restore_scope':'Same-cartridge usage or same-tank material only; current tank lifetime preserved'}
        with self.lock:
            if self.closing or self.state.get('state') == 'RECOVERY_REQUIRED':
                raise ValueError('Reset unavailable pending recovery or shutdown')
            if self.worker and self.worker.is_alive():
                raise ValueError('A reset operation is already running')
            if value['operation'] in ('prepare','prepare_restore','backup','prepare_material','prepare_tank_material'):
                self.plan = None
                self.state = {'state':'PREPARING'}
                if value['operation']=='backup':
                    self.state={'state':'BACKING_UP'}
                    target=lambda:self.backup_worker(value['kind'])
                elif value['operation']=='prepare_restore':
                    target=lambda:self.prepare_worker(lambda:prepare_saved_plan(value['backup_id'],self.backups))
                elif value['operation']=='prepare_material':
                    target=lambda:self.prepare_worker(lambda:prepare_plan(material_target=value['material']))
                elif value['operation']=='prepare_tank_material':
                    target=lambda:self.prepare_worker(lambda:prepare_tank_plan(material_target=value['material']))
                else:target = self.prepare_worker
            else:
                if self.state.get('state') != 'READY' or value['plan_id'] != self.state.get('plan_id') or time.monotonic() > self.deadline:
                    raise ValueError('A matching unexpired preview is required')
                if self.state.get('preview',{}).get('apply_ready') is False:
                    raise ValueError('Prepare a new preview after the printer reaches full idle')
                expected='apply_tank_material' if self.plan.get('kind')=='tank' else ('apply_material' if self.plan.get('material_target') else 'apply')
                if value['operation']!=expected:
                    raise ValueError('Operation does not match the prepared transaction')
                self.state = dict(self.state, state='APPLYING')
                target = self.apply_worker
            self.worker = threading.Thread(target=target)
            # Never kill a hardware transaction merely because the socket closes.
            self.worker.daemon = False
            self.worker.start()
            return dict(self.state)

    def backup_worker(self,kind):
        try:
            summary=self.backups.backup(kind)
            with self.lock:self.state={'state':'BACKUP_COMPLETE','backup':summary,'eeprom_written':False}
        except Exception as exc:
            with self.lock:self.state={'state':'UNAVAILABLE','error':str(exc) if type(exc) is ValueError else 'Backup failed; inspect private diagnostics'}

    def prepare_worker(self,prepare=None):
        try:
            if len(os.listdir(self.root)) >= 512:
                raise ValueError('Private transaction retention limit reached; archive records before another reset')
            plan, preview = (prepare or self.prepare_fn)()
            with self.lock:
                self.plan = plan
                self.deadline = time.monotonic() + 300
                self.state = {'state':'ALREADY_FRESH' if preview['already_fresh'] else 'READY',
                              'plan_id':token(), 'expires_in_seconds':300, 'preview':preview}
        except Exception as exc:
            with self.lock:
                self.state = {'state':'UNAVAILABLE', 'error':str(exc) if type(exc) is ValueError else 'Preflight failed; inspect private diagnostics'}

    def apply_worker(self):
        try:
            result = self.execute_fn(self.plan)
            with self.lock:
                self.state = result
        except Exception:
            with self.lock:
                self.state = {'state':'RECOVERY_REQUIRED', 'error':'Transaction failed; inspect private receipt before retrying'}
        finally:
            self.plan = None

    def execute(self, plan):
        identity = token()
        plan_path = os.path.join(self.root, identity+'.private.json')
        raw = (json.dumps(plan,sort_keys=True,indent=2)+'\n').encode()
        durable_new(plan_path, raw)
        marker = os.path.join(self.root,'in-progress.json')
        durable_new(marker, json.dumps({'transaction':identity}).encode())
        sync_dir(self.root)
        directory = os.path.dirname(os.path.abspath(__file__))
        output = os.path.join(self.root, identity+'.output.private.json')
        errors = os.path.join(self.root, identity+'.stderr.private')
        with open(output,'xb') as out, open(errors,'xb') as err:
            child = subprocess.Popen(['/usr/bin/python3','-E','-B','-S',
                directory+'/cartridge_transaction.py','--plan',plan_path,'--plan-sha256',digest(raw),
                '--apply','--accept','LIVE_RESET'],stdout=out,stderr=err)
            code = child.wait()  # The transaction owns rollback, not a timeout kill.
        receipt = json.loads(read_file(output,65536).decode())
        ok = code == 0 and receipt.get('stages',{}).get('post_start_merge') == 'PASS'
        summary = {'state':'COMPLETE' if ok else 'RECOVERY_REQUIRED', 'transaction_id':identity,
                   'operation':receipt.get('operation'),
                   'stages':receipt.get('stages',{}), 'material':receipt.get('material'),
                   'usage':receipt.get('final_usage'), 'backup_retained':True,
                   'physical_volume_measured':False,'reboot_performed':False}
        durable_new(os.path.join(self.root,identity+'.summary.json'),json.dumps(summary,sort_keys=True).encode())
        if ok:
            os.unlink(marker)
        sync_dir(self.root)
        return summary


def serve(uid, gid):
    if os.getuid() != 0 or not 64900 <= uid <= 65000 or not 64900 <= gid <= 65000:
        raise ValueError('Root and the enrolled panel UID/GID are required')
    os.umask(0o077)
    private_directory(RUN,0o750,gid)
    private_directory(ROOT)
    lock = os.open(RUN+'/lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    broker = Broker()
    stopping = [False]
    def stop(*_):
        stopping[0] = True
        broker.closing = True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    if os.path.lexists(SOCKET):
        info=os.lstat(SOCKET)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0:
            raise ValueError('Unexpected socket path')
        os.unlink(SOCKET)
    listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    listener.bind(SOCKET);os.chown(SOCKET,0,gid);os.chmod(SOCKET,0o660)
    listener.listen(4);listener.settimeout(0.5)
    try:
        while not stopping[0]:
            try:client,_=listener.accept()
            except socket.timeout:continue
            with client:
                client.settimeout(2)
                peer=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if peer[1] not in (0,uid):continue
                try:
                    raw=b''
                    while b'\n' not in raw and len(raw)<=4096:
                        part=client.recv(4097-len(raw))
                        if not part:break
                        raw+=part
                    if not raw.endswith(b'\n') or len(raw)>4096 or b'\n' in raw[:-1]:
                        raise ValueError('Invalid bounded request')
                    from package_format import unique_json
                    reply=broker.request(unique_json(raw))
                except (ValueError,OSError,UnicodeError):
                    reply={'state':'REFUSED','error':'Invalid, stale or concurrent request'}
                try:client.sendall((json.dumps(reply,sort_keys=True)+'\n').encode())
                except OSError:pass
    finally:
        listener.close()
        if broker.worker:broker.worker.join()
        os.unlink(SOCKET)
        os.close(lock)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid',type=int,required=True)
    parser.add_argument('--gid',type=int,required=True)
    args=parser.parse_args()
    serve(args.uid,args.gid)
