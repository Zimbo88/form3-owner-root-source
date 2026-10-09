#!/usr/bin/env python3
"""Local-development read-only maintenance dashboard. Never deploys to a printer.

Default: synthetic sample data, loopback only, bearer authentication. --live-host
reads the development host's proc/sys files; it does not discover or contact printers.
"""
import argparse
import hmac
import json
import os
from pathlib import Path
import re
import base64
import collections
import datetime
import io
import csv
import socket
import ssl
import stat
import time
import ipaddress
import fcntl
import struct
import sys
from socketserver import ThreadingMixIn
from http.server import HTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lan_ipv4 import interface_assignment, interface_name
except ImportError:
    # Authored checkout only: deployment has its own signed panel copy.
    sys.path.append(str(Path(__file__).resolve().parents[1] / 'owner-maintenance'))
    from lan_ipv4 import interface_assignment, interface_name
from panel_data import (VERSION, CpuUsage, SafeTree, OwnerStore, HistoricalBundle, ERROR_REFERENCE, field,
    strict_json, validate_settings, policy_preview, DEFAULT_SETTINGS, SETTINGS_CATALOG,
    read_formule_capture, number, refill_preview, PrinterFiles, PassivePrinterSignals)
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from reset_client import ResetClient

ROOT=Path(__file__).resolve().parents[1]
ASSETS=Path(__file__).resolve().parent/'static'
SERVICES=['Formule','Palantir','Sauron','CandyBus','TankCartridgeDaemon','PrinterLegitimacyChecker',
          'richard-nixon','bonsoir','sshd','connmand','galvatron','fluent-bit','zerotier-one']

def write_all(stream, data):
    """Python 3.5 SocketIO.write may return a short count, including on assets."""
    view = memoryview(data)
    while view:
        count = stream.write(view)
        if not isinstance(count, int) or count <= 0 or count > len(view):
            raise OSError('Incomplete HTTP write')
        view = view[count:]


class BoundedHTTPServer(ThreadingMixIn, HTTPServer):
    """Bound concurrent development requests and slow-client lifetime."""
    daemon_threads=True
    request_queue_size=4
    allow_reuse_address=True
    def __init__(self,*args,**kwargs):
        self.request_slots=threading.BoundedSemaphore(4)
        super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        request.settimeout(3)
        if not self.request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except BaseException:
            self.request_slots.release()
            raise
    def process_request_thread(self,request,address):
        def expire():
            try: request.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        timer=threading.Timer(6,expire);timer.daemon=True;timer.start()
        try:
            if getattr(self,'tls_context',None):
                request=self.tls_context.wrap_socket(request,server_side=True)
            super().process_request_thread(request,address)
        except (OSError,ssl.SSLError):
            self.shutdown_request(request)
        finally:
            timer.cancel();self.request_slots.release()

class SampleProvider:
    def snapshot(self):
        return {'source':'sample','read_only':True,'platform':'Form 3 / AM5728',
                'thermal_zones':[{'name':n,'celsius':v} for n,v in [('cpu_thermal',43.2),('gpu_thermal',41.8),('core_thermal',42.1),('dspeve_thermal',40.7),('iva_thermal',41.4)]],
                'system':{'cpu_usage':{'percent':18.2,'observed_at':time.time(),'interval_seconds':5,'reason':'SYNTHETIC'},'uptime_seconds':7200,'load_1_5_15':[0.18,0.12,0.09],'memory_total_bytes':1073741824,'memory_available_bytes':612368384},
                'storage':[{'mount':'/','total_bytes':1048576000,'free_bytes':289775616},{'mount':'/data','total_bytes':13419675648,'free_bytes':12800000000}],
                'firmware':{'slot':6,'version':'2.5.6-2773'},
                'services':[{'name':n,'running':True} for n in SERVICES],
                'limitations':['Synthetic development values. No printer connected.','Peripheral sensors and fan RPM require a reviewed read-only adapter.']}

class LinuxProvider:
    """Read-only adapter for Linux proc/sys and the recovered version-file convention."""
    def __init__(self,root=Path('/'),passive=False):
        self.root=Path(root);self.tree=SafeTree(root);self.cpu_usage=CpuUsage()
        self.printer_files=PrinterFiles(self.tree);self.signals=PassivePrinterSignals()
        if passive and self.root == Path('/'):
            try:version=strict_json(self.tree.read('etc/formlabs/version.json',65536))['build']['name']
            except (OSError,ValueError,KeyError,TypeError):version=None
            if version == '2.5.6-2773':self.signals.start()
    def close(self):
        self.signals.close();self.tree.close()
    def read(self,path):
        raw=self.tree.optional(path.lstrip('/'),65536)
        try:return raw.decode('utf-8').strip() if raw is not None else None
        except UnicodeError:return None
    def snapshot(self):
        result={'source':'local_linux','read_only':True,'platform':'Local Linux file adapter','thermal_zones':[],
                'system':{},'storage':[],'firmware':{'slot':None,'version':None},'services':[],
                'limitations':['Reads the local operating system; device identity is verified separately by ownerctl.','Missing fields are unavailable, not zero.']}
        for zone in sorted((self.root/'sys/class/thermal').glob('thermal_zone*'))[:64]:
            resolved=zone.resolve()
            base=(self.root/'sys').resolve()
            try:relative=resolved.relative_to(base)
            except ValueError:continue
            temp=self.read('sys/'+str(relative/'temp'));name=self.read('sys/'+str(relative/'type'))
            try:temperature=number(int(temp)/1000, -273.15, 1000)
            except (ValueError,TypeError,OverflowError):temperature=None
            result['thermal_zones'].append({'name':name or zone.name,'celsius':temperature,
                'source':'sys/'+str(relative/'temp'), 'quality':'VALID_NUMBER' if temperature is not None else 'UNAVAILABLE_OR_INVALID',
                'safety_limit':False})
        try:result['system']['uptime_seconds']=number(float((self.read('/proc/uptime') or '').split()[0]))
        except (ValueError,IndexError):result['system']['uptime_seconds']=None
        try:
            loads=[number(float(x)) for x in (self.read('/proc/loadavg') or '').split()[:3]]
            result['system']['load_1_5_15']=loads if len(loads)==3 and all(x is not None for x in loads) else None
        except ValueError:result['system']['load_1_5_15']=None
        result['system']['cpu_usage']=self.cpu_usage.sample(self.read('/proc/stat'),time.monotonic(),time.time())
        mem=dict(re.findall(r'^(MemTotal|MemAvailable):\s+(\d+) kB',self.read('/proc/meminfo') or '',re.M))
        result['system']['memory_total_bytes']=int(mem['MemTotal'])*1024 if 'MemTotal' in mem else None
        result['system']['memory_available_bytes']=int(mem['MemAvailable'])*1024 if 'MemAvailable' in mem else None
        match=re.search(r'(?:^|\s)root=/dev/mmcblk0p([56])(?:\s|$)',self.read('/proc/cmdline') or '')
        if match:result['firmware']['slot']=int(match.group(1))
        try:result['firmware']['version']=json.loads(self.read('/etc/formlabs/version.json') or '{}').get('build',{}).get('name')
        except (ValueError,AttributeError):pass
        for mount in ['/','/data']:
            path=self.root/mount.lstrip('/')
            try:
                s=os.statvfs(str(path));result['storage'].append({'mount':mount,'total_bytes':s.f_blocks*s.f_frsize,'free_bytes':s.f_bavail*s.f_frsize})
            except OSError:pass
        # SysV platform: report observed process names, never call systemctl or expose command lines.
        names=set()
        for proc_index,proc in enumerate((self.root/'proc').glob('[0-9]*')):
            if proc_index>=4096:break
            comm=self.read(str(proc.relative_to(self.root)/'comm'))
            if comm:names.add(comm)
        result['services']=[{'name':n,'running':n[:15] in names} for n in SERVICES]
        if result['firmware']['version']=='2.5.6-2773':
            result['printer']=self.printer_files.snapshot()
            result['printer'].update(self.signals.snapshot())
        return result


def random_token():
    return base64.urlsafe_b64encode(os.urandom(32)).decode('ascii').rstrip('=')


def interface_address(name):
    if name not in ('eth0', 'wlan0'):
        raise ValueError('Only reviewed physical LAN interfaces are eligible')
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        result = fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s', name.encode('ascii')))
        return socket.inet_ntoa(result[20:24])
    except OSError:
        return None
    finally:
        s.close()


class CaptureProvider(object):
    def __init__(self,provider,capture):self.provider=provider;self.capture=capture
    def snapshot(self):
        data=self.provider.snapshot();data['protocol_observation']=self.capture
        return data


def decorate_snapshot(data, bundle=None):
    now = time.time()
    state = 'DEMO' if data['source'] == 'sample' else 'LIVE'
    fields = {'uptime': field(data['system'].get('uptime_seconds'), state, '/proc/uptime', 's', now, 30),
              'load': field(data['system'].get('load_1_5_15'), state, '/proc/loadavg', None, now, 30),
              'memory_available': field(data['system'].get('memory_available_bytes'), state, '/proc/meminfo', 'bytes', now, 30),
              'version': field(data['firmware'].get('version'), state, '/etc/formlabs/version.json', timestamp=now),
              'slot': field(data['firmware'].get('slot'), state, '/proc/cmdline', timestamp=now),
              'board': field(), 'job_state': field(), 'pending_update': field(), 'owner_ssh': field(),
              'safe_idle': field(source='No authoritative combined printing/actuator safety adapter')}
    cpu=data['system'].get('cpu_usage') or {}
    fields['cpu_usage']=field(cpu.get('percent'),state,'/proc/stat aggregate non-idle delta; idle + iowait excluded','%',cpu.get('observed_at'),120)
    fields['gpu_usage']=field(source='No reviewed GPU utilization counter; GPU temperature is a separate reading',unit='%')
    fields['memory_total']=field(data['system'].get('memory_total_bytes'),state,'/proc/meminfo','bytes',now,30)
    data.setdefault('protocol_observation', {'state':'UNAVAILABLE','status':{},'safe_idle_proven':False,'live_connection':False})
    printer=data.get('printer',{})
    fields['printer_state']=printer.get('printer_state',field())
    fields['job_state']=printer.get('job_state',field(source='No fresh passive Sauron state signal; prepared printer status is separate'))
    fields['preheat_state']=printer.get('preheat_state',field(source='No fresh passive Sauron state signal; heater output is not inferred'))
    fields['tank_process_state']=printer.get('tank_process_state',field(source='No fresh passive Sauron state signal; pump activity and measured height are not inferred'))
    fields['job_layer']=printer.get('job_layer',field())
    fields['tank_level']=printer.get('tank_level',field(unit='mm'))
    data['fields'] = fields
    data['observed_at'] = now
    data['sensors'] = [dict(z, observation=field(z['celsius'], state, z.get('source', '/sys/class/thermal'), 'C', now, 30)) for z in data['thermal_zones']]
    data['sensors'].extend(data.get('printer',{}).get('sensors',[]))
    data['package_version'] = VERSION
    data['settings_catalog'] = SETTINGS_CATALOG
    data['vendor_writes_enabled'] = False
    data['power_actions_enabled'] = False
    data['error_reference'] = {'firmware': '2.5.6-2773', 'state': 'REFERENCE', 'codes': ERROR_REFERENCE}
    data['historical'] = bundle.summary() if bundle else {'state': 'UNAVAILABLE', 'consumables': [], 'jobs': [], 'sensors': [], 'faults': []}
    for row in data['storage']:
        row['observation'] = field(row['free_bytes'], state, 'statvfs ' + row['mount'], 'bytes', now, 30)
    for row in data['services']:
        row['observation'] = field(row['running'], state, '/proc/*/comm: presence only, NOT health', timestamp=now, max_age=30)
    return data


def make_server(provider, token, port=1328, store=None, bundle=None, bind='127.0.0.1',
                tls_context=None, interface=None, client_networks=None, listen_fd=None,
                owner_lan_http=False, assignment=None, reset_client=None):
    if len(token) < 24:
        raise ValueError('Access secret must contain at least 24 characters')
    if owner_lan_http:
        if tls_context or listen_fd is not None or port != 1328 or not interface:
            raise ValueError('Secondary owner LAN HTTP requires its own IPv4 port 1328 socket')
        if not assignment or interface_assignment(interface) != assignment or assignment[0] != bind:
            raise ValueError('Current private connected LAN assignment required')
        client_networks = [ipaddress.IPv4Network(assignment[1])]
    if not owner_lan_http and bind != '127.0.0.1' and (not tls_context or not interface or not client_networks):
        raise ValueError('LAN requires HTTPS, explicit interface and allowed client networks')
    if not owner_lan_http and interface and interface_address(interface) != bind:
        raise ValueError('Address is not currently assigned to the reviewed interface')
    sessions = {}
    failures = collections.deque(maxlen=12)
    lock = threading.RLock()

    def login_required():
        try:
            return store.settings()['wlan_login_required'] if store else True
        except (ValueError, OSError, TypeError):
            return True  # Invalid policy must never silently open access.

    class Handler(BaseHTTPRequestHandler):
        server_version = 'OwnerPanel'
        sys_version = ''
        def log_message(self, *args):
            pass

        def flush_headers(self):
            if hasattr(self, '_headers_buffer'):
                write_all(self.wfile, b''.join(self._headers_buffer))
                self._headers_buffer = []

        def reply(self, status, body, kind='application/json', extra=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, sort_keys=True, allow_nan=False).encode('utf-8')
            self.send_response(status)
            for name, value in [('Content-Type', kind), ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                    ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'),
                    ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
                    ('Connection', 'close')]:
                self.send_header(name, value)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.close_connection = True
            try:
                self.end_headers()
                write_all(self.wfile, body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

        def boundary(self, mutation=False):
            hosts = {self.server.server_address[0] + ':' + str(self.server.server_port)}
            if bind == '127.0.0.1':
                hosts.add('localhost:' + str(self.server.server_port))
            host = self.headers.get('Host')
            origin = self.headers.get('Origin')
            expected = ('https://' if tls_context else 'http://') + (host or '')
            if len(self.headers.get_all('Origin', [])) > 1 or len(self.headers.get_all('Host', [])) != 1 or host not in hosts or (origin and origin != expected) or (mutation and origin != expected):
                self.reply(403, {'error': 'Invalid host/origin'})
                return False
            if owner_lan_http and interface_assignment(interface) != assignment:
                self.reply(503, {'error': 'Owner LAN assignment changed; listener disabled'})
                return False
            if not owner_lan_http and interface and interface_address(interface) != bind:
                self.reply(503, {'error': 'LAN assignment changed; listener disabled'})
                return False
            if client_networks and not any(ipaddress.ip_address(self.client_address[0]) in n for n in client_networks):
                self.reply(403, {'error': 'Client outside owner LAN allowlist'})
                return False
            if self.headers.get('Transfer-Encoding') or len(self.path) > 1024:
                self.reply(400, {'error': 'Unsupported framing'})
                return False
            return True

        def secret_ok(self, value):
            return isinstance(value, str) and hmac.compare_digest(value.encode('utf-8'), token.encode('utf-8'))

        def session(self):
            # No credentials in URLs. Reject duplicate/conflicting cookies.
            cookies = [x.strip().split('=', 1) for x in self.headers.get('Cookie', '').split(';')]
            ids = [x[1] for x in cookies if len(x) == 2 and x[0] == 'owner_session']
            if len(ids) != 1:
                return None
            now = time.monotonic()
            with lock:
                for key in list(sessions):
                    if now - sessions[key]['used'] > 600 or now - sessions[key]['created'] > 3600:
                        del sessions[key]
                value = sessions.get(ids[0])
                if value:
                    value['used'] = now
                    return value
            return None

        def authenticated(self, mutation=False):
            session = self.session()
            if session and (not login_required() or session.get('authenticated',False)):
                if mutation and not hmac.compare_digest(self.headers.get('X-CSRF-Token', '').encode(), session['csrf'].encode()):
                    self.reply(403, {'error': 'CSRF token required'})
                    return None
                return session
            # Legacy token interface remains READ-ONLY for isolated tooling.
            if not mutation and self.secret_ok(self.headers.get('Authorization', '')[7:]) and self.headers.get('Authorization', '').startswith('Bearer '):
                return {'csrf': None}
            self.reply(401, {'error': 'Authentication required'})
            return None

        def json_body(self):
            sizes = self.headers.get_all('Content-Length', [])
            if len(sizes) != 1 or not re.match(r'^[0-9]{1,6}$', sizes[0]) or int(sizes[0]) > 16384:
                raise ValueError('Body length required; maximum 16384 bytes')
            if self.headers.get('Content-Type') != 'application/json':
                raise ValueError('JSON content type required')
            raw = self.rfile.read(int(sizes[0]))
            if len(raw) != int(sizes[0]):
                raise ValueError('Truncated body')
            obj = strict_json(raw)
            if not isinstance(obj, dict):
                raise ValueError('Object required')
            return obj

        def do_GET(self):
            if not self.boundary():
                return
            # Query strings are not used, including for authentication or file paths.
            assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/reset.js': ('reset.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if self.path in assets:
                name, kind = assets[self.path]
                return self.reply(200, (ASSETS / name).read_bytes(), kind)
            if self.path == '/api/access-policy':
                return self.reply(200, {'authentication_required':login_required(), 'owner_lan_http':owner_lan_http,
                    'power_actions_enabled':False, 'power_reason':'Authoritative idle and safety state unavailable'})
            auth = self.authenticated()
            if auth is None:
                return
            try:
                if self.path == '/api/cartridge-reset':
                    if reset_client is None:
                        return self.reply(200, {'state':'UNAVAILABLE','error':'Reviewed root helper not enabled in this runtime'})
                    try:result=reset_client.request('status')
                    except (ValueError,OSError):result={'state':'UNAVAILABLE','error':'Reviewed root helper unavailable; no write attempted'}
                    return self.reply(200,result)
                if self.path == '/api/power':
                    return self.reply(200, {'enabled':False,'state':'UNAVAILABLE',
                        'actions':['reboot','shutdown'],'reason':'Authoritative idle and safety state unavailable'})
                if self.path == '/api/session':
                    return self.reply(200, {'csrf': auth['csrf'], 'idle_timeout_seconds': 600, 'absolute_timeout_seconds': 3600})
                if self.path == '/api/settings':
                    value = store.settings() if store else dict(DEFAULT_SETTINGS)
                    return self.reply(200, {'settings': value, 'writable': bool(store), 'authentication_required':login_required(), 'policy': policy_preview(value['privacy_preference'])})
                if self.path == '/api/refills':
                    entries = store.refills() if store else []
                    consumables = bundle.summary().get('consumables', []) if bundle else []
                    return self.reply(200, {'entries': entries, 'native_reset_enabled': False,
                        'dispense_permission': False, 'preview': refill_preview(consumables, entries)})
                if self.path == '/api/diagnostics':
                    return self.reply(200, {'state': 'HISTORICAL' if bundle else 'UNAVAILABLE', 'records': bundle.logs()[:200] if bundle else [], 'limit': 200})
                allowed = {'/api/status': None, '/api/thermal': 'thermal_zones', '/api/system': 'system', '/api/storage': 'storage', '/api/firmware': 'firmware', '/api/services': 'services'}
                if self.path not in allowed:
                    return self.reply(404, {'error': 'Unknown endpoint'})
                data = decorate_snapshot(provider.snapshot(), bundle)
                data['network'] = {'listener_address': self.server.server_address[0], 'port': self.server.server_port,
                    'transport': 'HTTPS' if tls_context else ('OWNER LAN HTTP' if owner_lan_http else 'ISOLATED DEVELOPMENT HTTP'),
                    'interface': interface, 'ipv6_listener': False, 'hostname_alias': field()}
                key = allowed[self.path]
                return self.reply(200, data if key is None else {'source': data['source'], 'read_only': True, key: data[key]})
            except (ValueError, OSError, UnicodeError):
                return self.reply(503, {'error': 'Reviewed data unavailable or invalid; no fallback values'})

        def do_POST(self):
            allowed = {'/api/login', '/api/logout', '/api/settings', '/api/refills', '/api/export', '/api/power', '/api/cartridge-reset/prepare', '/api/cartridge-reset/apply', '/api/cartridge-reset/backup', '/api/cartridge-reset/backups', '/api/cartridge-reset/restore-preview', '/api/cartridge-reset/materials', '/api/cartridge-reset/material-preview', '/api/cartridge-reset/material-apply', '/api/cartridge-reset/tank-material-preview', '/api/cartridge-reset/tank-material-apply'}
            if self.path not in allowed:
                return self.reply(405, {'error': 'No approved write action'})
            if not self.boundary(mutation=True):
                return
            try:
                body = self.json_body()
                if self.path == '/api/login':
                    now = time.monotonic()
                    with lock:
                        while failures and now - failures[0] > 60:
                            failures.popleft()
                        if len(failures) >= 6:
                            return self.reply(429, {'error': 'Authentication temporarily rate limited'})
                        verified_secret = set(body) == {'secret'} and self.secret_ok(body.get('secret'))
                        anonymous_allowed = not body and not login_required()
                        if not verified_secret and not anonymous_allowed:
                            failures.append(now)
                            return self.reply(401, {'error': 'Invalid credentials'})
                        # Bound state even when many authenticated clients connect.
                        for key in list(sessions):
                            if now - sessions[key]['used'] > 600 or now - sessions[key]['created'] > 3600:
                                del sessions[key]
                        if len(sessions) >= 32:
                            return self.reply(429, {'error': 'Session limit reached'})
                        sid = random_token()
                        sessions[sid] = {'authenticated':verified_secret, 'csrf': random_token(), 'created': now, 'used': now, 'sid': sid}
                    cookie = 'owner_session=' + sid + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600' + ('; Secure' if tls_context else '')
                    return self.reply(200, {'csrf': sessions[sid]['csrf']}, extra={'Set-Cookie': cookie})
                session = self.authenticated(mutation=True)
                if session is None:
                    return
                if self.path.startswith('/api/cartridge-reset/'):
                    if login_required() and not session.get('authenticated'):
                        return self.reply(403, {'error':'Owner login is required for consumable maintenance'})
                    if reset_client is None:
                        return self.reply(409, {'error':'Reviewed root helper is not enabled'})
                    if self.path.endswith('/materials'):
                        if body:raise ValueError('Material listing takes no paths')
                        result=reset_client.request('materials')
                    elif self.path.endswith(('/material-preview','/tank-material-preview')):
                        if set(body)!={'material'} or not isinstance(body['material'],str) or not re.fullmatch(r'FL[A-Z0-9]{6}',body['material']):raise ValueError('Invalid material code')
                        result=reset_client.request('prepare_tank_material' if self.path.endswith('/tank-material-preview') else 'prepare_material',material=body['material'])
                    elif self.path.endswith('/backup'):
                        if set(body)!={'kind'} or body['kind'] not in ('cartridge','tank'):raise ValueError('Choose cartridge or tank')
                        result=reset_client.request('backup',kind=body['kind'])
                    elif self.path.endswith('/backups'):
                        if body:raise ValueError('Backup listing takes no paths')
                        result=reset_client.request('backups')
                    elif self.path.endswith('/restore-preview'):
                        if set(body)!={'backup_id'} or not isinstance(body['backup_id'],str) or not re.fullmatch(r'[a-f0-9]{32}',body['backup_id']):raise ValueError('Invalid backup identifier')
                        result=reset_client.request('prepare_restore',backup_id=body['backup_id'])
                    elif self.path.endswith('/prepare'):
                        if body:raise ValueError('Preview takes no device paths or settings')
                        result=reset_client.request('prepare')
                    else:
                        tank_apply=self.path.endswith('/tank-material-apply')
                        material_apply=self.path.endswith('/material-apply')
                        phrases=('CHANGE CLEAN TANK MATERIAL',) if tank_apply else ('CHANGE CARTRIDGE MATERIAL',) if material_apply else ('APPLY CARTRIDGE USAGE','RESET CLEAR USAGE')
                        required={'plan_id','confirmation'}|({'tank_empty_clean'} if tank_apply else set())
                        if not required <= set(body) or set(body)-required-{'secret'} or body.get('confirmation') not in phrases or (tank_apply and body.get('tank_empty_clean') is not True):
                            raise ValueError('Typed confirmation and the required tank acknowledgement are missing')
                        now=time.monotonic()
                        with lock:
                            while failures and now-failures[0]>60:failures.popleft()
                            if len(failures)>=6:
                                return self.reply(429, {'error':'Authentication temporarily rate limited'})
                            if login_required() and not self.secret_ok(body.get('secret')):
                                failures.append(now)
                                return self.reply(403, {'error':'Re-enter the owner access secret'})
                        result=reset_client.request('apply_tank_material' if tank_apply else 'apply_material' if material_apply else 'apply',body['plan_id'])
                    return self.reply(409 if result.get('state')=='REFUSED' else 202,result)
                if self.path == '/api/logout':
                    with lock:
                        sessions.pop(session['sid'], None)
                    return self.reply(200, {'logged_out': True}, extra={'Set-Cookie': 'owner_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if tls_context else '')})
                if self.path == '/api/power':
                    if set(body) != {'action'} or body.get('action') not in ('reboot','shutdown'):
                        raise ValueError('Unknown power action')
                    return self.reply(409, {'enabled':False,'error':'Power action blocked: authoritative idle and safety state unavailable'})
                if self.path == '/api/settings':
                    if not store:
                        return self.reply(409, {'error': 'Owner state store not configured'})
                    # Old clients must not accidentally switch off an enabled login policy.
                    if 'wlan_login_required' not in body:
                        body=dict(body,wlan_login_required=store.settings()['wlan_login_required'])
                    value = validate_settings(body)
                    store.save('settings.json', value)
                    return self.reply(200, {'settings': value, 'policy': policy_preview(value['privacy_preference']), 'vendor_state_changed': False})
                if self.path == '/api/refills':
                    if not store:
                        return self.reply(409, {'error': 'Owner ledger not configured'})
                    return self.reply(201, {'entry': store.add_refill(body), 'native_reset_enabled': False})
                if self.path == '/api/export':
                    return self.export(body)
            except (ValueError, OSError, UnicodeError, TypeError):
                return self.reply(400, {'error': 'Invalid request or unavailable bounded input'})

        def export(self, body):
            if not bundle:
                return self.reply(409, {'error': 'No reviewed diagnostic bundle'})
            if set(body) - {'format', 'start', 'end', 'service', 'private', 'file_id', 'secret', 'confirm_private'}:
                raise ValueError('Unknown export field')
            if body.get('private') is True:
                if body.get('confirm_private') != 'DOWNLOAD PRIVATE LOG' or (login_required() and not self.secret_ok(body.get('secret'))):
                    return self.reply(403, {'error': 'Explicit private-log confirmation and reauthentication required'})
                raw = bundle.raw_log(body.get('file_id'))
                return self.reply(200, raw, 'text/plain; charset=utf-8', {'Content-Disposition': 'attachment; filename="owner-private-log.txt"', 'X-Content-SHA256': __import__('hashlib').sha256(raw).hexdigest()})
            if body.get('private') not in (False, None) or body.get('format', 'json') not in ('json', 'csv'):
                raise ValueError('Invalid export type')
            start = body.get('start') or '1970-01-01'
            end = body.get('end') or '2100-01-01'
            for value in (start, end):
                datetime.datetime.strptime(value, '%Y-%m-%d')
            if start > end:
                raise ValueError('Date range reversed')
            service = body.get('service', '')
            if not isinstance(service, str) or len(service) > 64 or not re.match(r'^[A-Za-z0-9_. -]*$', service):
                raise ValueError('Invalid service filter')
            records = [r for r in bundle.logs() if (not service or r.get('service') == service) and
                       (r.get('date') is None or start <= r['date'] <= end)]
            if len(records) > 2000:
                return self.reply(413, {'error': 'Narrow date/service filter; maximum 2000 records'})
            manifest = {'schema_version': 1, 'state': 'HISTORICAL', 'sanitized': True, 'records': len(records),
                        'filters': {'start': start, 'end': end, 'service': service},
                        'filesystem_view': bundle.summary().get('scope', 'UNAVAILABLE'),
                        'clock_warning': 'Source view recorded separately. Unknown dates retained and labeled. No fault-cause inference.',
                        'source_manifest_sha256': __import__('hashlib').sha256(bundle.tree.read('panel_snapshot.json')).hexdigest()}
            if body.get('format') == 'csv':
                buf = io.StringIO()
                keys = ['file_id', 'service', 'date', 'category', 'count', 'source_sha256']
                writer = csv.DictWriter(buf, fieldnames=keys, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(records)
                raw = buf.getvalue().encode()
                return self.reply(200, raw, 'text/csv; charset=utf-8', {'Content-Disposition': 'attachment; filename="owner-diagnostics.csv"', 'X-Export-Manifest': json.dumps(manifest, sort_keys=True)})
            return self.reply(200, {'manifest': manifest, 'records': records}, extra={'Content-Disposition': 'attachment; filename="owner-diagnostics.json"'})

        def unsupported(self):
            self.reply(405, {'error': 'No approved write action'})
        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = unsupported

    server = BoundedHTTPServer((bind, port), Handler, bind_and_activate=False)
    try:
        if listen_fd is not None:
            server.socket.close()
            server.socket = socket.fromfd(listen_fd, socket.AF_INET, socket.SOCK_STREAM)
            actual = server.socket.getsockname()
            if actual != (bind, port) or not server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
                raise ValueError('Inherited socket does not match reviewed listener')
            if interface:
                device=server.socket.getsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,32).rstrip(b'\0')
                if device != interface.encode('ascii'):
                    raise ValueError('Inherited socket is not restricted to the reviewed interface')
            server.server_address=actual
            server.server_name=bind
            server.server_port=port
        elif interface and not owner_lan_http:
            # Binding an IP alone does not constrain the incoming interface.
            # Fail closed if an unprivileged target cannot bind the device.
            server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode('ascii') + b'\0')
        if listen_fd is None:
            server.server_bind()
            server.server_activate()
    except BaseException:
        server.server_close()
        raise
    server.tls_context = tls_context
    server.owner_sessions = sessions  # Testable expiry; never serialized.
    return server


class SecondaryHTTP(object):
    """Independent bounded listener lifecycle; no primary socket or SSH ownership."""
    def __init__(self, interface, provider, token, store=None, bundle=None, reset_client=None):
        self.interface = interface_name(interface)
        self.provider, self.token, self.store, self.bundle = provider, token, store, bundle
        self.reset_client=reset_client
        self.current = None
        self.server = None
        self.worker = None
        self.retry_after = 0

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.worker.join(7)
        self.server = self.worker = self.current = None

    def poll(self):
        observed = interface_assignment(self.interface)
        if observed != self.current:
            self.close()
            self.current = observed
            self.retry_after = 0
        if observed and self.server is None and time.monotonic() >= self.retry_after:
            try:
                server = make_server(self.provider, self.token, 1328, self.store, self.bundle,
                                     observed[0], interface=self.interface,
                                     owner_lan_http=True, assignment=observed,reset_client=self.reset_client)
                worker = threading.Thread(target=server.serve_forever)
                worker.daemon = True
                worker.start()
                self.current, self.server, self.worker = observed, server, worker
            except (OSError, ValueError):
                self.retry_after = time.monotonic() + 10
        return self.server is not None


def read_secret(path):
    tree = SafeTree(os.path.dirname(os.path.abspath(path)))
    try:
        name = os.path.basename(path)
        st = os.stat(name, dir_fd=tree.fd, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError('Secret must be a private regular owner file')
        return tree.read(name, 256).decode('ascii').strip()
    finally:
        tree.close()


def main():
    p = argparse.ArgumentParser(description='Owner panel review candidate; no installation or hardware contact.')
    p.add_argument('--port', type=int, default=1328)
    p.add_argument('--live-host', action='store_true', help='Read THIS host proc/sys, never discover printers')
    p.add_argument('--formule-capture', help='Explicit copied stream, bounded historical projection; no network client')
    p.add_argument('--capture-demo', action='store_true', help='Label synthetic copied stream DEMO')
    p.add_argument('--bundle', help='Reviewed local historical export directory')
    p.add_argument('--state', required=True, help='Existing private owner-owned directory; vendor paths forbidden')
    p.add_argument('--secret-file', required=True, help='Existing random owner access secret, mode 600')
    p.add_argument('--dev-http', action='store_true', help='Explicit loopback isolated-development HTTP')
    p.add_argument('--tls-cert');p.add_argument('--tls-key')
    p.add_argument('--interface', choices=['eth0', 'wlan0'], help='STAGING: explicit target physical owner LAN only')
    p.add_argument('--allow-client-network', action='append', default=[])
    p.add_argument('--owner-lan-only', action='store_true', help='Reviewed launcher: secondary HTTP while primary interface has no address')
    p.add_argument('--owner-lan-http-interface', help='Explicit secondary RFC1918 HTTP interface; requires installed owner firewall policy')
    p.add_argument('--listen-fd', type=int, help='Prebound socket from the reviewed privilege-dropping launcher')
    a = p.parse_args()
    if os.getuid() == 0:
        p.error('Run status service as an unprivileged owner-maintenance account')
    if not 1024 <= a.port <= 65535 or a.port != 1328:
        p.error('This candidate serves port 1328')
    if a.owner_lan_only and (not a.owner_lan_http_interface or a.interface or a.listen_fd is not None or a.dev_http or a.tls_cert or a.tls_key):
        p.error('Standalone owner LAN HTTP accepts no primary/development/TLS arguments')
    if a.owner_lan_http_interface:
        interface_name(a.owner_lan_http_interface)
        if not a.owner_lan_only and (not a.interface or a.owner_lan_http_interface == a.interface or a.listen_fd is None):
            p.error('Secondary HTTP requires a separate interface and inherited primary HTTPS')
    if a.interface and a.dev_http:
        p.error('LAN HTTP is prohibited')
    if a.listen_fd is not None and (a.listen_fd < 3 or not a.interface or a.dev_http):
        p.error('Inherited socket requires the reviewed HTTPS LAN launcher')
    if a.dev_http and (a.tls_cert or a.tls_key):
        p.error('Choose development HTTP or HTTPS')
    if any(x in os.path.abspath(a.state).split('/') for x in ('original', 'settings', 'Cartridges', 'Tanks', 'calibration')):
        p.error('State must be a separate owner directory')
    context = None
    if not a.dev_http and not a.owner_lan_only:
        if not (a.tls_cert and a.tls_key):
            p.error('HTTPS requires an owner certificate/key, or explicit --dev-http on loopback')
        # Read safely before loading; key never displayed.
        for path in (a.tls_cert, a.tls_key):
            t = SafeTree(os.path.dirname(os.path.abspath(path)))
            try:t.read(os.path.basename(path), 32768)
            finally:t.close()
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        context.options |= ssl.OP_NO_COMPRESSION
        context.set_ciphers('ECDHE+AESGCM:!aNULL:!eNULL:!MD5:!DSS')
        context.load_cert_chain(a.tls_cert, a.tls_key)
    store = OwnerStore(a.state)
    bundle = HistoricalBundle(a.bundle) if a.bundle else None
    token = read_secret(a.secret_file)
    provider = LinuxProvider(passive=True) if a.live_host else SampleProvider()
    live_provider = provider
    if a.capture_demo and not a.formule_capture:p.error('--capture-demo requires --formule-capture')
    if a.formule_capture:provider=CaptureProvider(provider,read_formule_capture(a.formule_capture,a.capture_demo))
    networks = [ipaddress.ip_network(x, strict=True) for x in a.allow_client_network]
    if a.interface and (not networks or any(n.version != 4 or n.prefixlen < 16 or not n.is_private for n in networks)):
        p.error('LAN requires narrow private IPv4 client networks; no IPv6 listener in this candidate')
    reset_client=ResetClient() if a.live_host and not a.dev_http else None
    secondary = SecondaryHTTP(a.owner_lan_http_interface, provider, token, store, bundle,reset_client) if a.owner_lan_http_interface else None
    current = None
    server = None
    worker = None
    try:
        while True:
            address = None if a.owner_lan_only else (interface_address(a.interface) if a.interface else '127.0.0.1')
            if address != current:
                if server:
                    server.shutdown();server.server_close();worker.join(7)
                    server = None
                    if a.listen_fd is not None:
                        break  # Root supervisor must bind a fresh socket after DHCP changes.
                current = address
                if address:
                    server = make_server(provider, token, a.port, store, bundle, address, context, a.interface, networks, a.listen_fd,reset_client=reset_client)
                    if a.listen_fd is not None:
                        os.close(a.listen_fd)
                    worker = threading.Thread(target=server.serve_forever)
                    worker.daemon = True;worker.start()
                    print('Owner panel ' + VERSION + ': ' + ('https' if context else 'http') + '://' + address + ':1328')
            if secondary:
                secondary.poll()
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        if secondary:
            secondary.close()
        if server:
            server.shutdown();server.server_close()
        if hasattr(live_provider,'close'):live_provider.close()
        store.tree.close()
        if bundle:
            bundle.tree.close()


if __name__ == '__main__':
    main()
