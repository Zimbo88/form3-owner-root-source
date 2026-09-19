#!/usr/bin/env python3
"""Build pinned static ARMv7 BusyBox and reproducible RAM-only newc/gzip."""
import argparse
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile

from rescue_common import ROOT, REQUIRED_APPLETS, newc, sha256, require, validate_elf, verified_factory, FACTORY


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def fetch(package, offline):
    path = ROOT / '.cache/downloads' / package['archive']
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        require(not offline, f'Offline cache missing: {path}')
        partial = path.with_suffix(path.suffix + '.download')
        for url in package['urls']:
            result = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--connect-timeout', '15', '--max-time', '600', '-o', str(partial), url])
            if result.returncode == 0:
                require(sha256(partial.read_bytes()) == package['sha256'], f'Download hash mismatch: {url}')
                partial.rename(path)
                break
        require(path.exists(), f'Cannot download {package["archive"]}')
    require(sha256(path.read_bytes()) == package['sha256'], f'Cached archive hash mismatch: {path}')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory', type=Path, default=FACTORY, help='Read-only authenticated reference factory input; exact hash remains mandatory')
    parser.add_argument('--offline', action='store_true', help='Use verified download cache only')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/rescue-v2')
    args = parser.parse_args()
    verified_factory(args.factory)  # Always authenticate evidence before any build/download.
    lock = json.loads((ROOT / 'rescue/sources.lock.json').read_text())
    archives = {name: fetch(lock[name], args.offline) for name in ('busybox', 'toolchain')}
    out = args.output_dir.resolve()
    require(out != ROOT and ROOT / 'hardware' not in out.parents, 'Userspace output must be outside hardware evidence')
    out.mkdir(parents=True, exist_ok=True)
    require(not any(out.iterdir()), 'Output directory must be empty; choose a new directory for rebuilds')
    # GNU make/BusyBox cannot handle the spaces in this project path.
    with tempfile.TemporaryDirectory(prefix='form3-rescue-build-') as temp:
        work = Path(temp)
        for archive in archives.values():
            with tarfile.open(archive) as tar:
                tar.extractall(work, filter='data')
        source = work / ('busybox-' + lock['busybox']['version'])
        patches = sorted((ROOT / 'rescue/patches').glob('*.patch'))
        for patch in patches:
            run(['patch', '--batch', '--forward', '-p1', '-i', patch], cwd=source, capture_output=True)
        tc = work / lock['toolchain']['version']
        prefix = str(tc / 'bin/arm-buildroot-linux-musleabihf-')
        env = dict(os.environ, LC_ALL='C', TZ='UTC', SOURCE_DATE_EPOCH=str(lock['source_date_epoch']), KCONFIG_NOTIMESTAMP='1')
        shutil.copyfile(ROOT / 'rescue/busybox.config', source / '.config')
        make = ['make', 'ARCH=arm', 'CROSS_COMPILE=' + prefix, 'HOSTCFLAGS=-O2 -std=gnu11']
        with (out / 'build.log').open('w') as log:
            run(make + ['oldconfig'], cwd=source, env=env, input='\n' * 2000, text=True, stdout=log, stderr=subprocess.STDOUT)
            run(make + ['-j' + str(min(os.cpu_count() or 2, 8))], cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
            run(make + ['busybox.links'], cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
        binary = (source / 'busybox').read_bytes()
        validate_elf(binary)
        shutil.copyfile(source / 'busybox', out / 'busybox')
        (out / 'busybox').chmod(0o755)
        shutil.copyfile(source / '.config', out / 'busybox.config')
        shutil.copyfile(source / 'LICENSE', out / 'BusyBox.LICENSE')
        applets = set((source / 'busybox.links').read_text().split())
        names = {Path(p).name for p in applets}
        require(REQUIRED_APPLETS <= names, 'Missing applets: ' + str(REQUIRED_APPLETS - names))
        require('id' in names, 'V2 requires the id applet')
        config = (source / '.config').read_text()
        for option in ('NC', 'NC_SERVER', 'NC_EXTRA'):
            require(f'CONFIG_{option}=y\n' in config, f'V2 requires CONFIG_{option}=y')
        require('# CONFIG_NC_110_COMPAT is not set' in config, 'V2 uses BusyBox nc semantics, not nc-1.10 compatibility')
        (out / 'applets.txt').write_text('\n'.join(sorted(names)) + '\n')
        file_text = run(['file', '-b', out / 'busybox'], capture_output=True, text=True).stdout
        elf_text = run(['readelf', '-h', '-l', '-A', out / 'busybox'], capture_output=True, text=True).stdout
        require('Tag_CPU_arch: v7' in elf_text and 'statically linked' in file_text, 'ARMv7/static verification failed')
        (out / 'busybox.file.txt').write_text(file_text)
        (out / 'busybox.readelf.txt').write_text(elf_text)
        help_result = subprocess.run(['qemu-arm', str(out / 'busybox'), 'nc', '--help'], capture_output=True, text=True)
        nc_help = help_result.stdout + help_result.stderr
        require('use -ll with -e for persistent server' in nc_help, 'Built nc does not advertise the required persistent server')
        (out / 'busybox-nc-help.txt').write_text(nc_help)
        entries = []
        dirs = 'bin sbin usr usr/bin usr/sbin proc sys dev dev/pts dev/shm etc run tmp root'.split()
        for d in dirs:
            entries.append((d, stat.S_IFDIR | (0o1777 if d == 'tmp' else 0o755), b'', 0, 0))
        for name, major, minor in [('console', 5, 1), ('null', 1, 3)]:
            entries.append(('dev/' + name, stat.S_IFCHR | 0o600, b'', major, minor))
        entries.append(('bin/busybox', stat.S_IFREG | 0o755, binary, 0, 0))
        for applet in sorted(names):
            entries.append(('bin/' + applet, stat.S_IFLNK | 0o777, b'busybox', 0, 0))
        rootfs = ROOT / 'rescue/rootfs'
        for path in sorted(rootfs.rglob('*')):
            if path.is_file():
                name = path.relative_to(rootfs).as_posix()
                mode = 0o755 if name == 'init' or name.startswith('bin/') else (0o600 if name == 'etc/shadow' else 0o644)
                entries.append((name, stat.S_IFREG | mode, path.read_bytes(), 0, 0))
        raw = newc(entries, lock['source_date_epoch'])
        buffer = io.BytesIO()
        with gzip.GzipFile(filename='', mode='wb', fileobj=buffer, mtime=0, compresslevel=9) as gz:
            gz.write(raw)
        compressed = buffer.getvalue()
        require(len(compressed) < 0x300000, 'Initramfs exceeds QSPI capacity')
        (out / 'form3-rescue.cpio').write_bytes(raw)
        (out / 'form3-rescue.cpio.gz').write_bytes(compressed)
        metadata = {'sources': lock, 'compiler': run([prefix + 'gcc', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
                    'linker': run([prefix + 'ld', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
                    'host_gcc': run(['gcc', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
                    'make': run(['make', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
                    'python': run(['python3', '--version'], capture_output=True, text=True).stdout.strip(),
                    'gzip': 'Python gzip.GzipFile, zlib ' + __import__('zlib').ZLIB_RUNTIME_VERSION,
                    'file': file_text.strip(), 'uncompressed_bytes': len(raw), 'compressed_bytes': len(compressed),
                    'busybox_bytes': len(binary), 'sha256': {p.name: sha256(p.read_bytes()) for p in [out / 'busybox', out / 'form3-rescue.cpio', out / 'form3-rescue.cpio.gz']},
                    'nc_help': nc_help,
                    'patches_sha256': {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in patches},
                    'inputs_sha256': {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in [ROOT / 'rescue/busybox.config', ROOT / 'tools/build_rescue.py', ROOT / 'tools/rescue_common.py', *patches, *sorted(rootfs.rglob('*'))] if p.is_file()}}
        (out / 'manifest.json').write_text(json.dumps(metadata, indent=2, sort_keys=True) + '\n')
        (out / 'SHA256SUMS').write_text(''.join(f'{value}  {name}\n' for name, value in sorted(metadata['sha256'].items())))
        print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
