#!/usr/bin/env python3
"""Create a NEW local QSPI image, strictly preserving authenticated evidence."""
import argparse
import difflib
import gzip
import json
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import zlib

from rescue_common import (ROOT, FACTORY, FACTORY_SHA, IMAGE_SIZE, ENV_START, ENV_SIZE,
                           PAYLOAD_START, REQUIRED_APPLETS, require, read_regular,
                           verified_factory, parse_env, parse_newc, validate_elf, sha256, diff_ranges)

RESCUE_BOOT = ('setenv mmcdev 1 && setenv mmcpart ${fl_bootpart} && run load_mmc && '
               'sf probe && sf read ${rdaddr} 0x100000 ${rescue_size} && '
               'setenv bootargs console=ttyS2,115200n8 rdinit=/init ro mem=${memsize} ip=off panic=0 && '
               'bootz ${loadaddr} ${rdaddr}:${rescue_size} ${fdtaddr}')
IMAGE_NAME = 'form3_qspi_RESCUE_V2.bin'


def inspect_factory(data):
    env, crc = parse_env(data)
    expected = {'console': 'ttyS2,115200n8', 'fl_bootpart': '6', 'fl_bootflip': '0',
                'silent': '1', 'bootdelay': '0', 'loadaddr': '0x82000000', 'kernel_addr_r': '0x82000000',
                'fdtaddr': '0x88000000', 'fdt_addr_r': '0x88000000', 'rdaddr': '0x88080000',
                'ramdisk_addr_r': '0x88080000', 'fdtfile': 'formlabs-daguerre-salsa-dual.dtb',
                'kernel': 'zImage', 'bootdir': '/boot', 'memsize': '1G',
                'load_mmc': 'mmc dev ${mmcdev} && mmc rescan && run mmcloadkernel && run mmcloadfdt',
                'mmcloadkernel': 'load mmc ${mmcdev}:${mmcpart} ${loadaddr} ${bootdir}/${kernel}',
                'mmcloadfdt': 'load mmc ${mmcdev}:${mmcpart} ${fdtaddr} ${bootdir}/${fdtfile} || load mmc ${mmcdev}:${mmcpart} ${fdtaddr} ${bootdir}/${fdtfile_legacy_20190327} || load mmc ${mmcdev}:${mmcpart} ${fdtaddr} ${bootdir}/${fdtfile_legacy_20190217}'}
    for key, value in expected.items():
        require(env.get(key) == value, f'Unexpected factory boot logic: {key}')
    header = data[0x40000:0x40040]
    magic, hcrc, timestamp, size, load, entry, dcrc, os_id, arch, kind, comp, name = struct.unpack('>7I4B32s', header)
    require((magic, arch, kind, comp) == (0x27051956, 2, 5, 0), 'Invalid U-Boot legacy image header')
    require(zlib.crc32(header[:4] + b'\0' * 4 + header[8:]) == hcrc, 'U-Boot header CRC mismatch')
    require(zlib.crc32(data[0x40040:0x40040 + size]) == dcrc, 'U-Boot payload CRC mismatch')
    require(0x40040 + size < ENV_START, 'U-Boot overlaps environment')
    # TI GP image follows the 512-byte configuration header.
    spl_size, spl_load = struct.unpack_from('<II', data, 0x200)
    require(data[20:30] == b'CHSETTINGS' and spl_size + 0x208 < 0x40000, 'Unexpected SPL header')
    require(data[ENV_START + ENV_SIZE:PAYLOAD_START] == b'\xff' * (PAYLOAD_START - ENV_START - ENV_SIZE), 'Environment partition tail not FF')
    uboot = data[0x40040:0x40040 + size]
    snippets = [b'probe [[bus:]cs] [hz] [mode]', b'sf read addr offset|partition len',
                b'mmc dev [dev] [part]', b'load binary file from a filesystem',
                b'[addr [initrd[:size]] [fdt]]', b'specifying the size of RAW initrd.']
    help_evidence = {}
    for snippet in snippets:
        require(snippet in uboot, f'Required embedded help missing: {snippet!r}')
        help_evidence[snippet.decode()] = f'0x{data.index(snippet, 0x40040):06x}'
    # Actual Thumb instructions: strchr(select, ':'), then simple_strtoul(end+1, NULL, 16).
    require(sha256(data[0x5280e:0x5282a]) == '17d5fa852ae7ecca5b23c3697549e61425d6c2cb58c92ae39c32518743c9cf87', 'Raw-initrd parser code changed')
    command_records = {}
    for command, offset in [('bootz', 0x87AAC), ('sf', 0x88158), ('mmc', 0x87F7C), ('load', 0x87E48)]:
        pointer, maxargs, repeatable, function, usage, help_ptr, complete = struct.unpack_from('<7I', data, offset)
        string_offset = pointer - load + 0x40040
        require(data[string_offset:string_offset + len(command) + 1] == command.encode() + b'\0', 'Command registration mismatch')
        function_offset = (function & ~1) - load + 0x40040
        require(0x40040 <= function_offset < 0x40040 + size and maxargs >= 4, 'Invalid command handler')
        command_records[command] = {'table_qspi_offset': f'0x{offset:06x}', 'name_qspi_offset': f'0x{string_offset:06x}',
                                    'handler_qspi_offset': f'0x{function_offset:06x}', 'maxargs': maxargs}
    return {'environment_crc': f'0x{crc:08x}', 'uboot_version': env['ver'],
            'uboot_payload_bytes': size, 'uboot_load': f'0x{load:08x}', 'uboot_header_crc': f'0x{hcrc:08x}',
            'uboot_payload_crc': f'0x{dcrc:08x}', 'spl_payload_bytes': spl_size, 'spl_load': f'0x{spl_load:08x}',
            'help_offsets': help_evidence, 'raw_initrd_parser_qspi_range': '0x05280e-0x052829 (inclusive)',
            'registered_commands': command_records,
            'environment_candidate_crcs': {f'0x{n:x}': f'0x{zlib.crc32(data[ENV_START + 4:ENV_START + n]):08x}' for n in (0x2000, 0x4000, 0x8000, 0x10000, 0x20000, 0x40000)}}


def encode_env(env):
    payload = b'\0'.join(f'{k}={v}'.encode('ascii') for k, v in env.items()) + b'\0\0'
    require(len(payload) <= ENV_SIZE - 4, 'Environment overflow')
    payload = payload.ljust(ENV_SIZE - 4, b'\0')
    return struct.pack('<I', zlib.crc32(payload)) + payload


def make_image(factory, payload):
    require(0 < len(payload) < 0x300000, 'Initramfs must be nonempty and below 3 MiB')
    original, _ = parse_env(factory)
    env = original.copy()
    del env['silent']
    env['bootcmd'] = 'run rescue_boot'
    env['rescue_size'] = f'0x{len(payload):x}'
    env['rescue_boot'] = RESCUE_BOOT
    output = bytearray(factory)
    output[ENV_START:ENV_START + ENV_SIZE] = encode_env(env)
    output[PAYLOAD_START:PAYLOAD_START + len(payload)] = payload
    return bytes(output)


def validate(factory, rescue, payload):
    require(len(factory) == IMAGE_SIZE and sha256(factory) == FACTORY_SHA, 'Factory identity failed')
    original, original_crc = parse_env(factory)
    env, rescue_crc = parse_env(rescue)
    require(len(rescue) == IMAGE_SIZE, 'Output size changed')
    require(rescue[:0x40000] == factory[:0x40000], 'SPL changed')
    require(rescue[0x40000:ENV_START] == factory[0x40000:ENV_START], 'U-Boot changed')
    ranges = diff_ranges(factory, rescue)
    end = PAYLOAD_START + len(payload)
    require(all((ENV_START <= a < b <= ENV_START + ENV_SIZE) or (PAYLOAD_START <= a < b <= end) for a, b in ranges), 'Changes outside permitted regions')
    require(rescue[end:] == b'\xff' * (IMAGE_SIZE - end), 'Payload tail is not FF')
    require(rescue[PAYLOAD_START:end] == payload, 'Payload bytes differ')
    require(0 < len(payload) < 0x300000, 'Oversize payload')
    require('silent' not in env and b'silent=' not in rescue[ENV_START + 4:ENV_START + ENV_SIZE], 'silent was not fully removed')
    expected_env = original.copy()
    del expected_env['silent']
    expected_env.update(bootcmd='run rescue_boot', rescue_size=f'0x{len(payload):x}', rescue_boot=RESCUE_BOOT)
    require(list(env.items()) == list(expected_env.items()), 'Unexpected environment changes/order')
    raw = gzip.decompress(payload)
    entries = parse_newc(raw)
    for name in ('init', 'bin/busybox', 'bin/form3-backup', 'bin/form3-readonly', 'bin/form3-nc-listen', 'bin/form3-nc-status'):
        require(name in entries and stat.S_ISREG(entries[name]['mode']) and entries[name]['mode'] & 0o111, f'Missing executable {name}')
    validate_elf(entries['bin/busybox']['data'])
    for applet in REQUIRED_APPLETS | {'id'}:
        entry = entries.get('bin/' + applet, {})
        require(entry.get('data') == b'busybox' and stat.S_ISLNK(entry.get('mode', 0)), f'Missing BusyBox link {applet}')
    with tempfile.TemporaryDirectory(prefix='form3-elf-check-') as temp:
        binary = Path(temp) / 'busybox'
        binary.write_bytes(entries['bin/busybox']['data'])
        file_text = subprocess.check_output(['file', '-b', str(binary)], text=True).strip()
        readelf = subprocess.check_output(['readelf', '-h', '-l', '-A', str(binary)], text=True)
    require('Tag_CPU_arch: v7' in readelf and 'statically linked' in file_text, 'Not static ARMv7')
    changes = {key: {'original': original.get(key), 'rescue': env.get(key)} for key in dict.fromkeys([*original, *env]) if original.get(key) != env.get(key)}
    return {'factory_sha256': sha256(factory), 'rescue_sha256': sha256(rescue), 'image_bytes': len(rescue),
            'original_environment_crc': f'0x{original_crc:08x}', 'rescue_environment_crc': f'0x{rescue_crc:08x}',
            'initramfs_uncompressed_bytes': len(raw), 'initramfs_compressed_bytes': len(payload),
            'busybox_bytes': len(entries['bin/busybox']['data']), 'busybox_file': file_text,
            'payload_start': f'0x{PAYLOAD_START:06x}', 'payload_end_exclusive': f'0x{end:06x}',
            'changed_bytes': sum(b - a for a, b in ranges), 'exact_changed_range_count': len(ranges),
            'changed_ranges': [{'start': f'0x{a:06x}', 'end_exclusive': f'0x{b:06x}', 'bytes': b - a} for a, b in ranges],
            'environment_changes': changes, 'silent_fully_deleted': True,
            'binary_sha256': {IMAGE_NAME: sha256(rescue), 'form3-rescue.cpio.gz': sha256(payload),
                              'form3-rescue.cpio': sha256(raw), 'busybox': sha256(entries['bin/busybox']['data'])},
            'validation': {key: 'PASS' for key in 'ABCDEFGHIJKLMN'},
            'uncertainties': ['V1 telnet connections close on hardware; the exact failure remains unproven. The recovered kernel enables UNIX98 PTYs; the primary nc service does not require them.',
                              'UART fallback remains unverified. V2 root shell, eMMC identity/read-only state and complete acquisition are owner-confirmed.',
                              'Software read-only flags are not a hardware write blocker; root can override them. Controller-internal maintenance is outside their scope.',
                              'Pi configuration and helper scripts have not been inspected or executed during V2 work.']}


def report(manifest, original_text, rescue_text, ranges_text):
    env_diff = ''.join(difflib.unified_diff(original_text.splitlines(True), rescue_text.splitlines(True), fromfile='environment_original.txt', tofile='environment_rescue.txt'))
    table = '\n'.join(f'| {name} | `{manifest[name]}` |' for name in ['factory_sha256', 'rescue_sha256', 'image_bytes', 'busybox_file', 'busybox_bytes', 'initramfs_uncompressed_bytes', 'initramfs_compressed_bytes', 'original_environment_crc', 'rescue_environment_crc', 'payload_start', 'payload_end_exclusive', 'changed_bytes', 'exact_changed_range_count', 'silent_fully_deleted'])
    return f'''# Rescue V2 offline QSPI validation

**Artifacts for manual review only. No hardware was accessed or flashed during V2 work.**
Hardware results below are attributed to the owner, not an offline simulation.

| Measurement | Value |
| --- | --- |
{table}

Structural invariants A–N: PASS (factory identity, CRCs, immutable SPL/U-Boot,
change boundaries, FF tail, sizes, static ARMv7 ELF, newc files, removal of silent).
O: exact environment diff below. P: exact maximal changed-byte intervals below.
Q: SHA256 for all four deliverable binary artifacts is in `manifest.json`.
The independent test run is recorded separately in `OFFLINE_TEST_RESULTS.txt`.

`bootcmd`: `{manifest['environment_changes']['bootcmd']['rescue']}`

Expanded `rescue_boot`:

```text
{RESCUE_BOOT}
```

The eMMC partition comes from the authenticated current `fl_bootpart=6`.
The original three DTB fallbacks and `load_mmc` are unchanged. Normal boot scripts,
partition-flip logic, environment saving and the normal rootfs boot are bypassed.
The genuine kernel and DTB are loaded from eMMC, never bundled or replaced.
All conditions in the rescue command use `&&`; failure returns to U-Boot.

## Primary network shell

```sh
{manifest['nc_listener_command']}
```

The final shell has socket-backed stdin/stdout/stderr. A recorded BusyBox patch
adds explicit `-s` listen binding and duplicates the accepted socket onto fd 2.
`-ll` keeps the listener alive across connections. `form3-nc-status` checks the
listener PID and kernel LISTEN table; logs are in RAM under `/run/form3-nc.*`.
Port 2323 remains an optional telnet diagnostic; its failure cannot stop 2324.
Offline connection transcripts and syscall proof are in `NC_SHELL_TEST.json`.

## Hardware results reported by the owner

''' + '\n'.join('- CONFIRMED: ' + item for item in manifest['hardware_results']['confirmed']) + f'''

{manifest['hardware_results'].get('historical_v1_failure', manifest['hardware_results'].get('observed_failure', 'No failure description supplied.'))}

Not confirmed: ''' + '; '.join(manifest['hardware_results']['not_confirmed']) + f'''.

## Exact environment differences

```diff
{env_diff}```

## Exact changed QSPI byte ranges

Intervals are **half-open**: start included, end excluded. Every byte in each
listed range differs; matching bytes split intervals. Payload bytes that are
already FF therefore do not appear as changes. No coarse enclosing interval is
being substituted for the exact comparison.

```text
{ranges_text}```

## Remaining uncertainties

''' + '\n'.join('- ' + item for item in manifest['uncertainties']) + '''

## Restoration concept

The known-good evidence is `hardware/qspi/original/form3_qspi_FACTORY.bin`,
4,194,304 bytes, SHA256 `''' + FACTORY_SHA + '''`.
Manual restoration would return the QSPI to these exact factory bytes using an
independently reviewed procedure, then verify a fresh readback against the hash.
No hardware restore operation or flashing command is provided.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory', type=Path, default=FACTORY)
    parser.add_argument('--initramfs', type=Path, default=ROOT / 'build/rescue-v2/form3-rescue.cpio.gz')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'hardware/qspi/build-v2')
    args = parser.parse_args()
    factory = verified_factory(args.factory)
    investigation = inspect_factory(factory)
    payload = read_regular(args.initramfs)
    rescue = make_image(factory, payload)
    manifest = validate(factory, rescue, payload)
    manifest['factory_investigation'] = investigation
    manifest['version'] = 'V2'
    manifest['hardware_results'] = json.loads((ROOT / 'rescue/hardware_results.json').read_text())
    manifest['nc_listener_command'] = (ROOT / 'rescue/rootfs/bin/form3-nc-listen').read_text().splitlines()[-1].removeprefix('exec ')
    metadata_file = args.initramfs.parent / 'manifest.json'
    if metadata_file.is_file():
        userspace = json.loads(read_regular(metadata_file))
        require(userspace['sha256']['form3-rescue.cpio.gz'] == sha256(payload), 'Userspace manifest does not match initramfs')
        manifest['userspace_build'] = userspace
    env0, _ = parse_env(factory)
    env1, _ = parse_env(rescue)
    original_text = ''.join(f'{k}={v}\n' for k, v in env0.items())
    rescue_text = ''.join(f'{k}={v}\n' for k, v in env1.items())
    ranges_text = ''.join(f'0x{a:06x} 0x{b:06x} {b-a}\n' for a, b in diff_ranges(factory, rescue))
    outputs = {IMAGE_NAME: rescue, IMAGE_NAME.replace('.bin', '.sha256'): f'{sha256(rescue)}  {IMAGE_NAME}\n'.encode(),
               'manifest.json': (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(),
               'diff_ranges.txt': ranges_text.encode(), 'environment_original.txt': original_text.encode(),
               'environment_rescue.txt': rescue_text.encode(), 'VALIDATION_REPORT.md': report(manifest, original_text, rescue_text, ranges_text).encode()}
    out = args.output_dir.resolve()
    protected = [ROOT / 'hardware/qspi/original', ROOT / 'hardware/qspi/reads', ROOT / 'hardware/emmc/original', ROOT / 'hardware/qspi/build']
    require(not any(out == p or p in out.parents for p in protected), 'Refusing evidence directory as output')
    out.mkdir(parents=True, exist_ok=True)
    for name in outputs:
        require(not (out / name).exists() and not (out / name).is_symlink(), f'Refusing existing output: {out / name}')
    for name, content in outputs.items():
        with (out / name).open('xb') as file:
            file.write(content)
    print(f'Created {out / IMAGE_NAME}\nSHA256 {sha256(rescue)}\nAll structural validations passed.')


if __name__ == '__main__':
    main()
