#!/usr/bin/env python3
"""Bounded DS2431 Read Memory inspection over the Linux W1 connector.

No EEPROM programming or protection-register writes are implemented. The W1
WRITE command sends only the device's Read Memory opcode and address. Linux
v4.9 w1_process_cb holds bus_mutex across slave selection and both commands.
All 144 bytes are private: callers must not log them or the ROM identifier.
Python 3.5 compatible. Importing this module performs no I/O.
"""
import hashlib
import os
import re
import socket
import struct
import time


def crc8(data):
    value = 0
    for byte in data:
        value ^= byte
        for unused in range(8):
            value = (value >> 1) ^ (0x8c if value & 1 else 0)
    return value


def validate_rom(rom):
    if not isinstance(rom, bytes) or len(rom) != 8 or rom[0] != 0x2d or crc8(rom):
        raise ValueError('Invalid DS2431-family ROM identifier')


def request(rom, port, seq):
    validate_rom(rom)
    # W1_CMD_WRITE(1): transmit F0 00 00 (Read Memory from address zero).
    # W1_CMD_READ(0): receive exactly 144 bytes; never send programming opcodes.
    commands = struct.pack('<BBH', 1, 0, 3) + b'\xf0\x00\x00'
    commands += struct.pack('<BBH', 0, 0, 144) + bytes(144)
    msg = struct.pack('<BBH8s', 5, 0, len(commands), rom) + commands
    cn = struct.pack('<IIIIHH', 3, 1, seq, 0, len(msg), 0) + msg
    return struct.pack('<IHHII', 16 + len(cn), 3, 0, seq, port) + cn


def parse_reply(packet, rom, seq):
    """Return bounded read payload and command status entries; fail on ambiguity."""
    validate_rom(rom)
    if not isinstance(packet, bytes) or not 16 <= len(packet) <= 4096:
        raise ValueError('Invalid netlink packet size')
    result = []
    pos = 0
    while pos < len(packet):
        if len(packet) - pos < 16:
            raise ValueError('Truncated netlink header')
        size, kind, flags, nseq, pid = struct.unpack_from('<IHHII', packet, pos)
        if size < 16 or pos + size > len(packet) or kind != 3:
            raise ValueError('Invalid netlink envelope')
        cnpos, end = pos + 16, pos + size
        while cnpos < end:
            if end - cnpos < 20:
                raise ValueError('Truncated connector header')
            idx, val, cseq, ack, clen, cflags = struct.unpack_from('<IIIIHH', packet, cnpos)
            cend = cnpos + 20 + clen
            if (idx, val, cseq, cflags) != (3, 1, seq, 0) or cend > end or clen < 12:
                raise ValueError('Wrong connector response')
            mpos = cnpos + 20
            while mpos < cend:
                if cend - mpos < 12:
                    raise ValueError('Truncated W1 message')
                mtype, status, mlen, identity = struct.unpack_from('<BBH8s', packet, mpos)
                mend = mpos + 12 + mlen
                if mtype != 5 or identity != rom or mend > cend or status:
                    raise ValueError('W1 error or wrong target (status {0})'.format(status))
                if mlen < 4:
                    raise ValueError('Missing W1 command result')
                cursor = mpos + 12
                while cursor < mend:
                    if mend - cursor < 4:
                        raise ValueError('Truncated W1 command')
                    cmd, reserved, count = struct.unpack_from('<BBH', packet, cursor)
                    last = cursor + 4 + count
                    if reserved or cmd not in (0, 1) or last > mend:
                        raise ValueError('Unexpected W1 command')
                    if count == 0 and ack == 0:
                        result.append(('status', cmd))
                    elif cmd == 0 and count == 144 and ack == seq + 1:
                        result.append(('data', packet[cursor + 4:last]))
                    else:
                        raise ValueError('Unexpected read length or acknowledgement')
                    cursor = last
                mpos = mend
            cnpos = cend
        pos += (size + 3) & ~3
        if pos > len(packet) and any(packet[pos - ((4 - size % 4) % 4):]):
            raise ValueError('Malformed padding')
    return result


def read_memory(device_name, expected_sha256):
    if not re.fullmatch(r'2d-[0-9a-f]{12}', device_name):
        raise ValueError('Invalid device name')
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise ValueError('Expected a pinned main-memory hash')
    base = '/sys/bus/w1/devices/' + device_name
    with open(base + '/id', 'rb') as source:
        rom = source.read(9)
    validate_rom(rom)
    if '{0:012x}'.format(int.from_bytes(rom[1:7], 'little')) != device_name[3:]:
        raise ValueError('ROM and sysfs name disagree')
    with open(base + '/eeprom', 'rb') as source:
        before = source.read(129)
    if len(before) != 128 or hashlib.sha256(before).hexdigest() != expected_sha256:
        raise ValueError('Live baseline changed')
    seq = int.from_bytes(os.urandom(3), 'little') + 1
    sock = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 11)
    try:
        sock.bind((0, 0))
        sock.settimeout(3.0)
        sock.sendto(request(rom, sock.getsockname()[0], seq), (0, 0))
        deadline = time.monotonic() + 3.0
        values, statuses = [], []
        for unused in range(6):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('W1 read deadline exceeded')
            sock.settimeout(remaining)
            packet, sender = sock.recvfrom(4097)
            if sender[0] != 0:
                raise ValueError('Non-kernel response')
            for kind, value in parse_reply(packet, rom, seq):
                (values if kind == 'data' else statuses).append(value)
            if len(values) == 1 and sorted(statuses) == [0, 1]:
                break
        if len(values) != 1 or sorted(statuses) != [0, 1]:
            raise ValueError('Incomplete or duplicate W1 replies')
        result = values[0]
    finally:
        sock.close()
    with open(base + '/eeprom', 'rb') as source:
        after = source.read(129)
    if result[:128] != before or after != before:
        raise ValueError('Read Memory data does not match sysfs baseline')
    return result


def protection_summary(data):
    if not isinstance(data, bytes) or len(data) != 144:
        raise ValueError('Expected the entire main memory and register page')
    modes = {0x55: 'WRITE_PROTECTED', 0xaa: 'EPROM_ONE_WAY'}
    return {
        'main_sha256': hashlib.sha256(data[:128]).hexdigest(),
        'pages': [{'page': i, 'control_hex': '{0:02x}'.format(data[128+i]),
                   'mode': modes.get(data[128+i], 'NO_PROTECTION_CODE')}
                  for i in range(4)],
        'copy_protection_active': data[132] in (0x55, 0xaa),
        'interpretation': 'DS2431 datasheet; family alone does not prove silicon provenance',
        'eeprom_programming_performed': False}
