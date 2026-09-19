"""Pure offline parsers and invariants shared by build tools (no device access)."""
from pathlib import Path
import hashlib
import stat
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / 'hardware/qspi/original/form3_qspi_FACTORY.bin'
FACTORY_SHA = '8a09d540d683c96227b875be1462bb0e6f9ab1ee4d0717be787e3cd1dcb4fedf'
IMAGE_SIZE = 0x400000
ENV_START, ENV_SIZE, PAYLOAD_START = 0xC0000, 0x4000, 0x100000
REQUIRED_APPLETS = set('sh ash mount umount mkdir mdev ip ifconfig telnetd nc dd tee mkfifo sha256sum blockdev cat ls fdisk blkid dmesg uname hexdump sync reboot poweroff sleep hostname setsid cttyhack mknod ln rm mktemp wc test true false kill'.split())


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Not a regular non-symlink file: {path}')
    return path.read_bytes()


def parse_env(image):
    raw = image[ENV_START:ENV_START + ENV_SIZE]
    require(len(raw) == ENV_SIZE, 'Truncated environment')
    stored, = struct.unpack('<I', raw[:4])
    calculated = zlib.crc32(raw[4:])
    require(stored == calculated, 'Environment CRC mismatch')
    body, separator, padding = raw[4:].partition(b'\0\0')
    require(bool(separator), 'Missing environment terminator')
    pairs = []
    for entry in body.split(b'\0'):
        key, sep, value = entry.partition(b'=')
        require(bool(key) and bool(sep), 'Malformed environment entry')
        pairs.append((key.decode('ascii'), value.decode('ascii')))
    require(len(dict(pairs)) == len(pairs), 'Duplicate environment variable')
    return dict(pairs), stored


def verified_factory(path=FACTORY):
    data = read_regular(path)
    require(len(data) == IMAGE_SIZE, 'STOP: factory size mismatch')
    require(sha256(data) == FACTORY_SHA, 'STOP: factory SHA256 mismatch')
    parse_env(data)
    require(data[PAYLOAD_START:] == b'\xff' * (IMAGE_SIZE - PAYLOAD_START), 'Payload area is not entirely FF')
    return data


def newc(entries, epoch):
    """Canonical newc with fixed uid/gid/mtime, sorted names, no host device nodes."""
    output = bytearray()
    for ino, (name, mode, data, major, minor) in enumerate(sorted(entries) + [('TRAILER!!!', 0, b'', 0, 0)], 1):
        encoded = name.encode() + b'\0'
        fields = (ino, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1, epoch, len(data), 0, 0, major, minor, len(encoded), 0)
        output += b'070701' + ''.join(f'{v:08x}' for v in fields).encode() + encoded
        output += b'\0' * (-len(output) % 4)
        output += data
        output += b'\0' * (-len(output) % 4)
    output += b'\0' * (-len(output) % 512)
    return bytes(output)


def parse_newc(data):
    pos, entries = 0, {}
    while True:
        require(data[pos:pos + 6] == b'070701', 'Not newc cpio')
        fields = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16) for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        pos += 110
        namebytes = data[pos:pos + namesize]
        require(namebytes.endswith(b'\0'), 'Unterminated cpio path')
        name = namebytes[:-1].decode()
        require(name and not name.startswith('/') and '..' not in name.split('/'), 'Unsafe cpio path')
        pos = (pos + namesize + 3) & ~3
        body = data[pos:pos + size]
        require(len(body) == size, 'Truncated cpio entry')
        pos = (pos + size + 3) & ~3
        if name == 'TRAILER!!!':
            require(not any(data[pos:]), 'Unexpected trailing cpio data')
            return entries
        require(name not in entries, 'Duplicate cpio path')
        entries[name] = {'mode': mode, 'data': body, 'uid': fields[2], 'gid': fields[3], 'major': fields[9], 'minor': fields[10]}


def validate_elf(data):
    require(data[:7] == b'\x7fELF\x01\x01\x01', 'BusyBox must be ELF32 little endian')
    require(struct.unpack_from('<HH', data, 16) == (2, 40), 'BusyBox must be ARM ET_EXEC')
    flags, = struct.unpack_from('<I', data, 36)
    require(flags & 0xFF000000 == 0x05000000 and bool(flags & 0x400), 'Requires EABI5 hard-float')
    phoff, = struct.unpack_from('<I', data, 28)
    phsize, phnum = struct.unpack_from('<HH', data, 42)
    types = [struct.unpack_from('<I', data, phoff + i * phsize)[0] for i in range(phnum)]
    require(2 not in types and 3 not in types, 'Dynamic or interpreted ELF refused')


def diff_ranges(a, b):
    require(len(a) == len(b), 'Cannot compare unequal images')
    ranges, start = [], None
    for offset, (old, new) in enumerate(zip(a, b)):
        if old != new and start is None:
            start = offset
        elif old == new and start is not None:
            ranges.append((start, offset))
            start = None
    if start is not None:
        ranges.append((start, len(a)))
    return ranges
