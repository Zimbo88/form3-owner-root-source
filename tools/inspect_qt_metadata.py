#!/usr/bin/env python3
"""Inspect selected Qt 5 revision-7 metadata in copied ARM ELF32 files.

Never loads the executable, calls D-Bus or treats metadata as a safety policy.
Addresses are ELF link virtual addresses, not Ghidra's optional image rebase.
Only bounded identifiers, types and table coordinates are emitted. Class-info
values (including embedded XML), properties' values and executable bytes are not.
Layout references: Qt qtbase v5.9.6 qmetaobject_p.h, qarraydata.h and moc generator.
"""
import argparse
import hashlib
import re
import struct
from evidence_lib import open_evidence, write_json


class MetadataError(ValueError):
    pass


class Elf32:
    def __init__(self, data):
        self.data = data
        if (not 52 <= len(data) <= 64 << 20 or data[:7] != b'\x7fELF\x01\x01\x01'
                or struct.unpack_from('<HH', data, 16) != (2, 40)):
            raise MetadataError('Expected bounded little-endian ARM ELF32')
        off = struct.unpack_from('<I', data, 28)[0]
        width, count = struct.unpack_from('<HH', data, 42)
        if width != 32 or not 1 <= count <= 128 or off + width * count > len(data):
            raise MetadataError('Invalid program headers')
        self.segments = []
        for i in range(count):
            kind, pos, va, _, size, memsize, _, _ = struct.unpack_from('<8I', data, off + i * width)
            if kind == 1:
                if size > memsize or pos + size > len(data) or va + memsize > 1 << 32:
                    raise MetadataError('Invalid load segment')
                self.segments.append((va, pos, size))

    def read(self, va, length):
        if not 0 <= va <= 0xffffffff or not 0 <= length <= 65536:
            raise MetadataError('Address/length budget')
        matches = [(pos + va - start) for start, pos, size in self.segments
                   if start <= va and va + length <= start + size]
        if len(matches) != 1:
            raise MetadataError('Unmapped or ambiguous file-backed virtual address')
        return self.data[matches[0]:matches[0] + length]

    def words(self, va, count):
        return struct.unpack('<' + 'I' * count, self.read(va, count * 4))

    def meta(self, address):
        parent, strings, table, dispatch, _, _ = self.words(address, 6)
        header = self.words(table, 14)
        revision, class_index, ci_count, ci_start, count, start = header[:6]
        if revision != 7 or count > 256 or ci_count > 128 or header[13] > count:
            raise MetadataError('Unsupported revision or metadata budget')

        def identifier(index, allow_type=False):
            if index > 4096:
                raise MetadataError('String index budget')
            entry = strings + index * 16  # 32-bit QArrayData, signed qptrdiff at +12
            _, length, _, relative = struct.unpack('<iiIi', self.read(entry, 16))
            if not 0 <= length <= 256:
                raise MetadataError('Identifier length budget')
            raw = self.read(entry + relative, length + 1)
            if raw[-1:] != b'\0':
                raise MetadataError('Identifier is not NUL terminated')
            try:
                value = raw[:-1].decode('ascii')
            except UnicodeError:
                raise MetadataError('Identifier encoding')
            pattern = r'[A-Za-z_][A-Za-z0-9_:<> ,*&.]*' if allow_type else r'[A-Za-z_][A-Za-z0-9_:]*'
            if not re.fullmatch(pattern, value):
                raise MetadataError('Identifier grammar')
            return value

        def type_name(value):
            return {'name': identifier(value & 0x7fffffff, True)} if value & 0x80000000 else {'qt_builtin_id': value}

        rows = []
        for i in range(count):
            va = table + (start + i * 5) * 4
            name, argc, params, _, flags = self.words(va, 5)
            if argc > 16:
                raise MetadataError('Argument budget')
            types = self.words(table + params * 4, argc + 1)
            rows.append({'index': i, 'name': identifier(name), 'table_va': hex(va),
                         'argument_types': [type_name(x) for x in types[1:]],
                         'return_type': type_name(types[0]),
                         'kind': ['method', 'signal', 'slot', 'constructor'][(flags >> 2) & 3],
                         'access_bits': flags & 3, 'flags': hex(flags),
                         'side_effects': 'UNKNOWN: inspect implementation and dispatch separately'})
        return {'class': identifier(class_index), 'meta_va': hex(address),
                'parent_meta_va': hex(parent), 'static_dispatch_va': hex(dispatch),
                'metadata_va': hex(table), 'revision': revision, 'methods': rows,
                'signal_count': header[13], 'property_count': header[6],
                'class_info_values_excluded': True, 'live_interface_proven': False}


def inspect(path, addresses):
    if not 1 <= len(addresses) <= 32:
        raise MetadataError('Select 1..32 metadata objects')
    with open_evidence(path) as f:
        data = f.read((64 << 20) + 1)
    elf = Elf32(data)
    return {'schema_version': 1, 'artifact_sha256': hashlib.sha256(data).hexdigest(),
            'artifact_size': len(data), 'address_convention': 'ELF link VA',
            'objects': [elf.meta(a) for a in addresses], 'vendor_execution': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    parser.add_argument('--meta', action='append', type=lambda x: int(x, 0), required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = inspect(args.binary, args.meta)
    write_json(args.output, result)
    print('Inspected %d selected metadata objects; no program or D-Bus execution.' % len(result['objects']))


if __name__ == '__main__':
    main()
