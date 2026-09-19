"""Bounded, receive-only Formule frame inspection (Python 3.5 standard library).

No sockets, discovery, device requests or vendor code execution. Frame layout is
established from Formule 2.5.6-2773 code and isolated ARM QtCore serialization.
Captured JSON/attachments can contain secrets: public output is allowlisted.
"""
import hashlib
import json
import math
import struct

MAX_METADATA = 65536
MAX_ATTACHMENT = 4 * 1024 * 1024
MAX_CHUNK = 65536
MAX_FRAMES = 4096
METHODS = (
    'GET_INFORMATION', 'GET_STATUS', 'GET_CALIBRATION', 'START_IDLE_ROUTINE',
    'ABORT_IDLE_ROUTINE', 'ABORT_JOB', 'UPLOAD_FILE', 'UPLOAD_LAYER', 'START_JOB',
    'RESUME_JOB', 'SECURE_HANDSHAKE', 'START_FORM2_JOB', 'UPDATE',
    'GENERATE_FORMLOGS', 'GET_FORMLOGS_CHUNK', 'DELETE_FORMLOGS', 'LOCAL_FORWARD',
    'HEARTBEAT', 'GET_SNAPSHOT', 'REGISTER_USER_TO_DASHBOARD', 'UNKNOWN')
KNOWN_METHODS = frozenset('PROTOCOL_METHOD_' + x for x in METHODS)
STATUS_BOOL_FIELDS = (
    'isPrinting', 'isOpenMode', 'isRemotePrintEnabled', 'isPrimed',
    'readyToPrintNow_v2', 'isPrePrint', 'isDashboardRegistrationAllowed')
STATUS_TIME_FIELDS = ('estimatedTotalPrintTime_ms', 'estimatedPrintTimeRemaining_ms')

class ProtocolError(ValueError):
    """Rejected input. Messages intentionally never include captured values."""

def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ProtocolError('duplicate JSON field')
        out[key] = value
    return out

def _constant(value):
    raise ProtocolError('nonfinite JSON number')

def metadata_object(data):
    """Validate a bounded JSON metadata object without printing keys/values."""
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_METADATA:
        raise ProtocolError('metadata size outside policy')
    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                            parse_constant=_constant)
    except (ValueError, UnicodeError, RuntimeError):
        raise ProtocolError('invalid JSON metadata')
    if not isinstance(result, dict):
        raise ProtocolError('metadata must be an object')
    queue = [(result, 0)]
    nodes = 0
    while queue:
        item, depth = queue.pop()
        nodes += 1
        if depth > 32 or nodes > 4096:
            raise ProtocolError('JSON structure outside policy')
        if isinstance(item, dict):
            queue.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            queue.extend((v, depth + 1) for v in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ProtocolError('nonfinite JSON number')
    return result

def status_projection(parameters, provenance='HISTORICAL'):
    """Only proven shared status fields; never turns printing=false into safe idle.

    Transport decoding proves no freshness. A saved capture remains HISTORICAL.
    Identity, material IDs, job names and arbitrary keys are omitted.
    """
    if provenance not in ('HISTORICAL', 'DEMO', 'CACHED'):
        raise ProtocolError('unsupported offline provenance')
    if not isinstance(parameters, dict):
        raise ProtocolError('parameters must be an object')
    result = {}
    for name in STATUS_BOOL_FIELDS + STATUS_TIME_FIELDS:
        value = parameters.get(name)
        ok = (type(value) is bool if name in STATUS_BOOL_FIELDS else
              type(value) in (int, float) and 0 <= value <= 315576000000 and
              math.isfinite(value))
        result[name] = {'value': value if ok else None,
                        'availability': provenance if ok else 'UNAVAILABLE',
                        'unit': 'boolean' if name in STATUS_BOOL_FIELDS else 'ms',
                        'source': 'Formule.GetStatusResponse',
                        'freshness': 'not established by offline frame decoding'}
    return result

def metadata_summary(meta, raw, provenance='HISTORICAL'):
    """A value-redacted projection. Unknown dictionary keys are never emitted."""
    direction = 'reply' if 'ReplyToMethod' in meta else 'request' if 'Method' in meta else 'unknown'
    method = meta.get('ReplyToMethod' if direction == 'reply' else 'Method')
    known = isinstance(method, str) and method in KNOWN_METHODS
    version = meta.get('Version')
    version_ok = type(version) is int and 0 <= version <= 65535
    identifier = meta.get('Id')
    parameters = meta.get('Parameters')
    result = {'direction': direction, 'method': method if known else 'UNKNOWN',
              'method_known': known, 'version': version if version_ok else None,
              'metadata_sha256': hashlib.sha256(raw).hexdigest(),
              'metadata_bytes': len(raw), 'parameter_count': len(parameters) if isinstance(parameters, dict) else None,
              'request_id_sha256': hashlib.sha256(identifier.encode('utf-8')).hexdigest() if isinstance(identifier, str) else None,
              'provenance': provenance, 'authorization': 'NOT ESTABLISHED BY FRAME PARSING'}
    if direction == 'reply':
        result['success'] = meta.get('Success') if type(meta.get('Success')) is bool else None
        result['error_present'] = isinstance(meta.get('Error'), str) and bool(meta['Error'])
    if direction == 'reply' and meta.get('Success') is True and method == 'PROTOCOL_METHOD_GET_STATUS' and isinstance(parameters, dict):
        result['status'] = status_projection(parameters, provenance)
    return result

class FrameDecoder(object):
    """Incremental receive-only parser; attachments are hashed then discarded.

    Conservative policy bounds are authored, not claimed as vendor limits. No
    resynchronization after corruption: call reset() for a NEW stream/session.
    """
    def __init__(self, max_attachment=MAX_ATTACHMENT, max_frames=MAX_FRAMES,
                 provenance='HISTORICAL'):
        if type(max_attachment) is not int or not 0 <= max_attachment <= MAX_ATTACHMENT:
            raise ProtocolError('attachment limit outside policy')
        if type(max_frames) is not int or not 1 <= max_frames <= MAX_FRAMES:
            raise ProtocolError('frame limit outside policy')
        if provenance not in ('HISTORICAL', 'DEMO', 'CACHED'):
            raise ProtocolError('unsupported offline provenance')
        self.max_attachment = max_attachment
        self.max_frames = max_frames
        self.provenance = provenance
        self.reset()

    def reset(self):
        self.buffer = bytearray()
        self.pending = None
        self.remaining = 0
        self.digest = None
        self.failed = False
        self.count = 0

    def _error(self, message):
        self.failed = True
        self.buffer = bytearray()
        self.pending = None
        self.digest = None
        raise ProtocolError(message)

    def feed(self, data):
        if self.failed:
            raise ProtocolError('stream rejected; reset for a new session')
        if not isinstance(data, bytes) or len(data) > MAX_CHUNK:
            self._error('input chunk outside policy')
        self.buffer.extend(data)
        if len(self.buffer) > MAX_METADATA + 12 + MAX_CHUNK:
            self._error('receive buffer outside policy')
        completed = []
        while True:
            if self.pending is None:
                if len(self.buffer) < 4:
                    break
                n = struct.unpack_from('<I', self.buffer)[0]
                if not 1 <= n <= MAX_METADATA:
                    self._error('metadata length outside policy')
                if len(self.buffer) < 4 + n + 8:
                    break
                raw = bytes(self.buffer[4:4+n])
                attachment = struct.unpack_from('<q', self.buffer, 4+n)[0]
                if not 0 <= attachment <= self.max_attachment:
                    self._error('attachment length outside policy')
                try:
                    parsed = metadata_object(raw)
                    self.pending = metadata_summary(parsed, raw, self.provenance)
                except (ProtocolError, UnicodeError, OverflowError):
                    self._error('invalid metadata projection')
                self.pending['attachment_bytes'] = attachment
                self.remaining = attachment
                self.digest = hashlib.sha256()
                del self.buffer[:4+n+8]
            n = min(len(self.buffer), self.remaining)
            if n:
                self.digest.update(self.buffer[:n])
                del self.buffer[:n]
                self.remaining -= n
            if self.remaining:
                break
            self.count += 1
            if self.count > self.max_frames:
                self._error('frame count outside policy')
            self.pending['attachment_sha256'] = self.digest.hexdigest()
            self.pending['frame_index'] = self.count
            completed.append(self.pending)
            self.pending = None
            self.digest = None
        return completed

    def finish(self):
        if self.failed:
            raise ProtocolError('stream rejected')
        if self.pending is not None or self.buffer:
            self._error('truncated frame at end of stream')
        return self.count
