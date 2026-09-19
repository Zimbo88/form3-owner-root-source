"""Bounded Linux interface observation shared by separately signed trust domains.

Python 3.5. No network packets, configuration changes or privileged operations.
The builder copies this authored module into both bootstrap and panel packages;
root never imports its implementation from a panel-updateable release.
"""
import fcntl
import ipaddress
import re
import socket
import struct

RFC1918 = tuple(ipaddress.IPv4Network(x) for x in
                ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def interface_name(name):
    if not isinstance(name, str) or not re.match(r'^[A-Za-z][A-Za-z0-9_.-]{0,14}$', name) or name == 'lo':
        raise ValueError('Explicit non-loopback Linux interface required')
    return name


def private_assignment(address, mask):
    """Require a usable host and the entire connected network inside RFC1918."""
    ip = ipaddress.IPv4Address(address)
    if not isinstance(mask, str) or '.' not in mask:
        raise ValueError('Dotted contiguous IPv4 netmask required')
    # ipaddress also accepts host masks; reject those explicitly.
    bits = int(ipaddress.IPv4Address(mask))
    inverted = bits ^ 0xffffffff
    if bits == 0 or inverted & (inverted + 1):
        raise ValueError('Non-contiguous netmask')
    net = ipaddress.IPv4Network(address + '/' + mask, strict=False)
    if net.prefixlen > 30 or ip in (net.network_address, net.broadcast_address):
        raise ValueError('Usable connected LAN host required')
    if not any(net.network_address in block and net.broadcast_address in block for block in RFC1918):
        raise ValueError('Entire connected subnet must be RFC1918')
    return (str(ip), str(net))


def interface_assignment(name):
    interface_name(name)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            request = struct.pack('256s', name.encode('ascii'))
            def query(code):
                return fcntl.ioctl(s.fileno(), code, request)
            if not struct.unpack_from('H', query(0x8913), 16)[0] & 1:  # IFF_UP
                return None
            address = socket.inet_ntoa(query(0x8915)[20:24])
            mask = socket.inet_ntoa(query(0x891b)[20:24])
            # Reject an address change during the two separate ioctls.
            if socket.inet_ntoa(query(0x8915)[20:24]) != address:
                return None
            return private_assignment(address, mask)
    except (OSError, ValueError, struct.error):
        return None
