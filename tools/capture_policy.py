"""Host-only capture policy. Retry transport loss, never relax target/SSH trust."""
import ast
import re

VERSION_MARKER = b"EXPECTED_OWNER_VERSION = '0.5.8-review'"


def bind_source(source, owner_version):
    if not isinstance(owner_version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-review', owner_version):
        raise ValueError('Explicit reviewed owner version required')
    if source.count(VERSION_MARKER) != 1:
        raise ValueError('Target source version marker changed')
    result = source.replace(VERSION_MARKER, ('EXPECTED_OWNER_VERSION = '+repr(owner_version)).encode('ascii'))
    ast.parse(result.decode('utf-8'), feature_version=(3, 5))
    return result


def transport_failure(returncode, stderr, timed_out=False):
    """Return a fixed reason and retry permission; never export raw stderr."""
    if not isinstance(stderr, bytes) or len(stderr) > 65536:
        return False, 'INVALID_SSH_DIAGNOSTIC'
    text = stderr.decode('utf-8', errors='replace').lower()
    trust = ('host identification has changed', 'host key verification failed',
             'permission denied', 'no such identity:', 'authentication failed',
             'too many authentication failures', 'bad permissions')
    if any(s in text for s in trust):
        return False, 'SSH_TRUST_OR_CREDENTIAL_FAILURE'
    if timed_out:
        return True, 'CAPTURE_TIMEOUT'
    if returncode != 255:
        return False, 'TARGET_OR_UNKNOWN_FAILURE'
    transient = ('connection timed out', 'operation timed out', 'connection refused',
                 'connection reset', 'connection closed', 'broken pipe',
                 'no route to host', 'network is unreachable')
    if any(s in text for s in transient):
        return True, 'TRANSPORT_INTERRUPTED'
    return False, 'UNCLASSIFIED_SSH_FAILURE'


class RetryBudget:
    def __init__(self, maximum=12):
        self.maximum = maximum
        self.consecutive = 0

    def failure(self, returncode, stderr, timed_out=False):
        retry, reason = transport_failure(returncode, stderr, timed_out)
        self.consecutive += 1
        if retry and self.consecutive >= self.maximum:
            return False, 'CONSECUTIVE_RETRY_BUDGET', 0
        return retry, reason, min(30, 5*self.consecutive) if retry else 0

    def success(self):
        self.consecutive = 0
