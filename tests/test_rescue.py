"""Offline-only evidence validation and failure-injection tests. No hardware I/O."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import rescue_common as common
import build_qspi_rescue as builder
from nc_shell_probe import probe as probe_nc_shell

BB = ROOT / 'build/rescue-v2/busybox'
QEMU = shutil.which('qemu-arm')
QSPI = ROOT / 'hardware/qspi/build-v2'


class ImageValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.factory = common.FACTORY.read_bytes()
        cls.rescue = (QSPI / 'form3_qspi_RESCUE_V2.bin').read_bytes()
        cls.payload = (ROOT / 'build/rescue-v2/form3-rescue.cpio.gz').read_bytes()
        cls.raw = gzip.decompress(cls.payload)
        cls.entries = common.parse_newc(cls.raw)
        cls.manifest = json.loads((QSPI / 'manifest.json').read_text())

    def test_A_factory_size(self):
        self.assertEqual(len(self.factory), 4194304)

    def test_B_factory_sha256(self):
        self.assertEqual(hashlib.sha256(self.factory).hexdigest(), '8a09d540d683c96227b875be1462bb0e6f9ab1ee4d0717be787e3cd1dcb4fedf')

    def test_C_factory_crc(self):
        self.assertEqual(struct.unpack_from('<I', self.factory, 0xC0000)[0], zlib.crc32(self.factory[0xC0004:0xC4000]))
        self.assertEqual(zlib.crc32(self.factory[0xC0004:0xC4000]), 0x7DFF027F)

    def test_D_rescue_crc(self):
        self.assertEqual(struct.unpack_from('<I', self.rescue, 0xC0000)[0], zlib.crc32(self.rescue[0xC0004:0xC4000]))

    def test_E_SPL_identical(self):
        self.assertEqual(self.factory[:0x40000], self.rescue[:0x40000])

    def test_F_uboot_identical(self):
        self.assertEqual(self.factory[0x40000:0xC0000], self.rescue[0x40000:0xC0000])

    def test_G_no_change_below_environment(self):
        self.assertEqual(self.factory[:0xC0000], self.rescue[:0xC0000])

    def test_H_changes_confined(self):
        for offset, (a, b) in enumerate(zip(self.factory, self.rescue)):
            if a != b:
                self.assertTrue(0xC0000 <= offset < 0xC4000 or 0x100000 <= offset < 0x100000 + len(self.payload))

    def test_I_FF_tail_and_factory_payload(self):
        self.assertEqual(set(self.factory[0x100000:]), {255})
        self.assertEqual(set(self.rescue[0x100000 + len(self.payload):]), {255})
        self.assertEqual(self.rescue[0x100000:0x100000 + len(self.payload)], self.payload)

    def test_J_rescue_size(self):
        self.assertEqual(len(self.rescue), 4194304)

    def test_K_compressed_initramfs_below_limit(self):
        self.assertLess(len(self.payload), 0x300000)
        self.assertLess(len(self.payload), 0x100000, 'Comfortable headroom: under one third of available space')

    def test_L_static_ARMv7_hard_float(self):
        self.assertEqual(self.entries['bin/busybox']['data'], BB.read_bytes())
        details = subprocess.check_output(['readelf', '-h', '-l', '-A', str(BB)], text=True)
        self.assertIn('ELF32', details)
        self.assertIn('Machine:                           ARM', details)
        self.assertIn('Tag_CPU_arch: v7', details)
        self.assertIn('Tag_ABI_VFP_args: VFP registers', details)
        self.assertNotIn('INTERP', details)
        self.assertNotIn('DYNAMIC', details)
        self.assertIn('statically linked', subprocess.check_output(['file', '-b', str(BB)], text=True))

    def test_M_newc_required_entries_and_devices(self):
        listing = subprocess.check_output(['cpio', '-it', '--quiet'], input=self.raw, stderr=subprocess.PIPE).decode().splitlines()
        for name in ('init', 'bin/busybox', 'bin/form3-backup', 'bin/sh', 'dev/console', 'dev/null'):
            self.assertIn(name, listing)
        self.assertTrue(self.entries['init']['mode'] & 0o111)
        self.assertEqual((self.entries['dev/console']['major'], self.entries['dev/console']['minor']), (5, 1))
        self.assertTrue(stat.S_ISCHR(self.entries['dev/console']['mode']))
        self.assertTrue(all(e['uid'] == e['gid'] == 0 for e in self.entries.values()))

    def test_N_silent_fully_deleted(self):
        self.assertNotIn(b'silent=', self.rescue[0xC0004:0xC4000])
        self.assertNotIn('silent', common.parse_env(self.rescue)[0])

    def test_O_exact_environment_differences(self):
        original = common.parse_env(self.factory)[0]
        rescue = common.parse_env(self.rescue)[0]
        self.assertEqual({k for k in original.keys() | rescue.keys() if original.get(k) != rescue.get(k)}, {'bootcmd', 'silent', 'rescue_boot', 'rescue_size'})
        for name, env in [('original', original), ('rescue', rescue)]:
            self.assertEqual((QSPI / f'environment_{name}.txt').read_text(), ''.join(f'{k}={v}\n' for k, v in env.items()))
        self.assertEqual(rescue['rescue_size'], hex(len(self.payload)))
        self.assertIn('-silent=1', (QSPI / 'VALIDATION_REPORT.md').read_text())

    def test_P_exact_changed_byte_ranges(self):
        # Independently reconstruct full per-byte comparison from the published intervals.
        expected = bytes(a != b for a, b in zip(self.factory, self.rescue))
        reconstructed = bytearray(len(expected))
        last = -1
        for line in (QSPI / 'diff_ranges.txt').read_text().splitlines():
            a, b, size = line.split(); a, b, size = int(a, 16), int(b, 16), int(size)
            self.assertGreater(a, last)
            self.assertEqual(b - a, size)
            reconstructed[a:b] = b'\1' * size
            last = b
        self.assertEqual(expected, bytes(reconstructed))
        report = (QSPI / 'VALIDATION_REPORT.md').read_text()
        self.assertIn((QSPI / 'diff_ranges.txt').read_text(), report)

    def test_Q_every_deliverable_binary_hashed(self):
        files = {'form3_qspi_RESCUE_V2.bin': self.rescue, 'form3-rescue.cpio.gz': self.payload,
                 'form3-rescue.cpio': self.raw, 'busybox': BB.read_bytes()}
        self.assertEqual(self.manifest['binary_sha256'], {name: hashlib.sha256(data).hexdigest() for name, data in files.items()})
        self.assertEqual((QSPI / 'form3_qspi_RESCUE_V2.sha256').read_text(), hashlib.sha256(self.rescue).hexdigest() + '  form3_qspi_RESCUE_V2.bin\n')

    def test_embedded_raw_initrd_and_original_boot_logic(self):
        evidence = builder.inspect_factory(self.factory)
        self.assertEqual(evidence['uboot_header_crc'], '0xd1d93da0')
        env = common.parse_env(self.rescue)[0]
        command = env['rescue_boot']
        self.assertIn('setenv mmcdev 1 && setenv mmcpart ${fl_bootpart} && run load_mmc', command)
        self.assertIn('bootz ${loadaddr} ${rdaddr}:${rescue_size} ${fdtaddr}', command)
        self.assertNotRegex(command, r'saveenv|mmc write|sf (write|erase|update)|fl_check_flip|emmcargs|mmcbootscript|root=/dev')

    def test_in_ram_scripts_match_sources(self):
        for path in (ROOT / 'rescue/rootfs').rglob('*'):
            if path.is_file():
                self.assertEqual(self.entries[path.relative_to(ROOT / 'rescue/rootfs').as_posix()]['data'], path.read_bytes())

    def test_V1_preserved_and_backup_unchanged(self):
        v1 = ROOT / 'hardware/qspi/build/form3_qspi_RESCUE.bin'
        self.assertEqual(hashlib.sha256(v1.read_bytes()).hexdigest(), '337ac8fd1efc5e5d09da4fda9eda3b9c97509ab4c4d98e5299349368e8a8a097')
        old = common.parse_newc(gzip.decompress((ROOT / 'build/rescue/form3-rescue.cpio.gz').read_bytes()))
        self.assertEqual(self.entries['bin/form3-backup']['data'], old['bin/form3-backup']['data'])
        self.assertEqual(self.entries['bin/form3-readonly']['data'], old['bin/form3-readonly']['data'])

    def test_V1_output_directory_refused(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/build_qspi_rescue.py'), '--output-dir', str(ROOT / 'hardware/qspi/build')], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Refusing evidence directory as output', result.stderr)

    def test_repeat_image_build_is_identical(self):
        self.assertEqual(builder.make_image(self.factory, self.payload), self.rescue)

    def test_mutation_guards(self):
        for offset in (0, 0x50000, 0xC5000, 0xFFFFF, 0x3FFFFF):
            with self.subTest(offset=hex(offset)):
                mutated = bytearray(self.rescue); mutated[offset] ^= 1
                with self.assertRaises(ValueError):
                    builder.validate(self.factory, bytes(mutated), self.payload)
        mutated = bytearray(self.factory); mutated[0xC0100] ^= 1
        with self.assertRaisesRegex(ValueError, 'CRC'):
            common.parse_env(mutated)
        for payload in (b'', b'x' * 0x300000):
            with self.assertRaises(ValueError):
                builder.make_image(self.factory, payload)

    def test_bad_factory_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            fake = temp / 'factory.bin'; fake.write_bytes(self.factory[:-1])
            with self.assertRaisesRegex(ValueError, 'size'):
                common.verified_factory(fake)
            fake.write_bytes(bytes([self.factory[0] ^ 1]) + self.factory[1:])
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                common.verified_factory(fake)
            fake.write_bytes(self.factory)
            out = temp / 'out'; out.mkdir()
            target = out / 'form3_qspi_RESCUE_V2.bin'; target.write_bytes(b'KEEP')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/build_qspi_rescue.py'), '--factory', str(fake), '--output-dir', str(out)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), b'KEEP')
            self.assertEqual(fake.read_bytes(), self.factory)


class UserspaceTests(unittest.TestCase):
    def bb(self, *args, **kwargs):
        return subprocess.run(['qemu-arm', str(BB), *args], capture_output=True, timeout=15, **kwargs)

    def test_applet_inventory_and_readonly_fdisk_config(self):
        result = self.bb('--list')
        self.assertEqual(result.returncode, 0)
        applets = set(result.stdout.decode().split())
        self.assertTrue(common.REQUIRED_APPLETS <= applets)
        self.assertFalse(applets & {'fsck', 'mkfs', 'mke2fs', 'sfdisk', 'parted', 'flashcp', 'nandwrite'})
        config = (ROOT / 'build/rescue-v2/busybox.config').read_text()
        self.assertIn('CONFIG_LFS=y', config)
        self.assertIn('CONFIG_FEATURE_DEVPTS=y', config)
        self.assertIn('# CONFIG_FEATURE_FDISK_WRITABLE is not set', config)
        self.assertIn('id', applets)
        for option in ('NC', 'NC_SERVER', 'NC_EXTRA'):
            self.assertIn(f'CONFIG_{option}=y', config)

    def test_nc_help_matches_compiled_binary(self):
        result = self.bb('nc', '--help')
        help_text = (result.stdout + result.stderr).decode()
        self.assertIn('use -ll with -e for persistent server', help_text)
        self.assertIn('-e PROG', help_text)
        self.assertEqual(help_text, (BB.parent / 'busybox-nc-help.txt').read_text())

    def test_persistent_ARM_shell_twice_without_any_PTY(self):
        # Test output must not overwrite the historical V2 validation artifacts.
        with tempfile.TemporaryDirectory(prefix='form3-nc-test-') as temp:
            result = probe_nc_shell(BB, Path(temp), prepared_namespace=os.environ.get('FORM3_NC_PREPARED')=='1')
        self.assertTrue(result['passed'])
        self.assertEqual([c['connection'] for c in result['connections']], [1, 2])
        self.assertTrue(result['persistent_listener_survived_both'])

    def test_nc_status_detects_listen_and_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            pidfile = temp / 'pid'; pidfile.write_text('12345\n')
            tcp = temp / 'tcp'
            script = (ROOT / 'rescue/rootfs/bin/form3-nc-status').read_text()
            script = script.replace('/run/form3-nc.pid', str(pidfile)).replace('/proc/net/tcp', str(tcp))
            test_script = temp / 'status.sh'
            test_script.write_text('kill() { return 0; }\n' + script)
            tcp.write_text('0: 4D00000A:0914 00000000:0000 0A 00000000:00000000\n')
            success = self.bb('ash', str(test_script))
            self.assertEqual(success.returncode, 0)
            self.assertIn(b'FORM3 V2 NC SHELL LISTENING', success.stdout)
            tcp.write_text('0: 4D00000A:0913 00000000:0000 0A 00000000:00000000\n')
            failure = self.bb('ash', str(test_script))
            self.assertEqual(failure.returncode, 1)
            self.assertIn(b'no matching LISTEN socket', failure.stderr)

    def test_sha256_known_vector_and_64bit_arithmetic(self):
        self.assertEqual(self.bb('sha256sum', input=b'abc').stdout.split()[0].decode(), hashlib.sha256(b'abc').hexdigest())
        result = self.bb('ash', '-c', 'echo $((16 * 1024 * 1024 * 1024))')
        self.assertEqual(result.stdout.strip(), b'17179869184')

    def test_large_file_read_beyond_4GiB(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'sparse-fixture'
            offset = 5 * 1024**3
            with path.open('wb') as file:
                file.seek(offset)
                file.write(b'ARM-LARGE-FILE-READ\n')
            result = self.bb('dd', f'if={path}', 'bs=1M', 'skip=5120', 'count=1')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b'ARM-LARGE-FILE-READ\n')

    def test_telnetd_under_qemu_on_localhost(self):
        with tempfile.TemporaryDirectory() as temp:
            login = Path(temp) / 'fixture-login'
            login.write_text('#!/bin/sh\necho FORM3-TELNET-PTY-OK\n')
            login.chmod(0o755)
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0))
                port = reserve.getsockname()[1]
            process = subprocess.Popen([QEMU, str(BB), 'telnetd', '-F', '-b', f'127.0.0.1:{port}', '-l', str(login)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                connection = None
                for _ in range(50):
                    try:
                        connection = socket.create_connection(('127.0.0.1', port), timeout=0.2)
                        break
                    except OSError:
                        if process.poll() is not None:
                            break
                        time.sleep(0.05)
                self.assertIsNotNone(connection, 'Local telnetd did not listen')
                with connection:
                    connection.settimeout(4)
                    received = b''
                    while b'FORM3-TELNET-PTY-OK' not in received:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        received += chunk
                    self.assertIn(b'FORM3-TELNET-PTY-OK', received)
            finally:
                process.terminate()
                process.communicate(timeout=5)

    def test_readonly_ioctl_failure_warns(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.sh'
            harness = '[() { if command [ "$1" = -b ]; then return 0; fi; command [ "$@"; }\nblockdev() { return 1; }\n'
            path.write_text(harness + (ROOT / 'rescue/rootfs/bin/form3-readonly').read_text())
            result = self.bb('ash', str(path))
            self.assertEqual(result.returncode, 1)
            self.assertIn(b'WARNING: CANNOT CONFIRM READ-ONLY FLAG', result.stderr)

    def test_shell_syntax_without_execution(self):
        for path in [ROOT / 'rescue/rootfs/init', *sorted((ROOT / 'rescue/rootfs/bin').iterdir())]:
            self.assertEqual(self.bb('ash', '-n', str(path)).returncode, 0, str(path))
        # Pi/laptop helpers are only parsed. Never executed by offline tests.
        for path in (ROOT / 'scripts').glob('*.sh'):
            subprocess.run(['bash', '-n', str(path)], check=True)

    def test_boot_policy(self):
        script = (ROOT / 'rescue/rootfs/init').read_text()
        mounts = [line.strip() for line in script.splitlines() if re.search(r'\bmount -t ', line)]
        self.assertTrue(mounts)
        for line in mounts:
            self.assertRegex(line, r'mount -t (proc|sysfs|devtmpfs|tmpfs|devpts)\b')
        self.assertIn('telnetd -b 10.0.0.77:2323 -l /bin/sh', script)
        self.assertNotRegex(script, r'\b(fsck|saveenv|switch_root|pivot_root|udhcpc)\b')
        self.assertNotRegex(script, r'route add default|\b(reboot|poweroff)\s*$')
        self.assertLess(script.index('form3-readonly'), script.index('telnetd -b'))
        self.assertLess(script.index('form3-readonly'), script.index('form3-nc-listen'))
        self.assertLess(script.index('form3-nc-listen'), script.index('telnetd -b'))
        self.assertIn('form3-nc-status', script)
        launcher = (ROOT / 'rescue/rootfs/bin/form3-nc-listen').read_text()
        self.assertNotRegex(launcher, r'/dev/pts|/dev/ptmx|cttyhack|setsid')

    def test_helpers_bound_listener_and_preserve_files(self):
        receiver = (ROOT / 'scripts/receive_emmc_via_pi.sh').read_text()
        self.assertIn('nc -4 -l 10.0.0.1 9000', receiver)
        self.assertIn('nc -l -s 10.0.0.1 -p 9000', receiver)
        self.assertNotIn('nc -4 -l -N', receiver)
        self.assertIn('set -o noclobber', receiver)
        self.assertIn('set -euo pipefail', receiver)
        self.assertIn('StrictHostKeyChecking=yes', receiver)
        self.assertIn('sha256sum', receiver)

    def test_backup_rejects_rpmb_partitions_and_injection(self):
        script = str(ROOT / 'rescue/rootfs/bin/form3-backup')
        for args in [[], ['/dev/mmcblk0rpmb'], ['/dev/mmcblk0p1'], ['/dev/sda'], ['/dev/mmcblk0', '-e'],
                     ['/dev/mmcblk0', '999.1.1.1'], ['/dev/mmcblk0', '127.0.0.1', '0'],
                     ['/dev/mmcblk0', '127.0.0.1', '65536']]:
            result = self.bb('ash', script, *args)
            self.assertEqual(result.returncode, 2, (args, result.stderr))

    def stream_test(self, failure=None):
        """Actual ARM ash/dd/tee/hash/nc on loopback; fake device is a regular file.

        Only test harness overrides -b and blockdev and redirects dd's allowlisted
        source to the fixture. The delivered backup command has no test override.
        """
        with tempfile.TemporaryDirectory(prefix='form3-stream-test-') as temp:
            temp = Path(temp)
            data = bytes(range(256)) * 8193
            fixture = temp / 'fixture'; fixture.write_bytes(data)
            mounts = temp / 'mounts'; mounts.write_text('')
            bindir = temp / 'bin'; bindir.mkdir()
            # Registered qemu-arm binfmt handles ARM applet subprocesses.
            for applet in subprocess.check_output(['qemu-arm', str(BB), '--list'], text=True).split():
                (bindir / applet).symlink_to(BB)
            listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(1)
            listener.settimeout(12)
            port = listener.getsockname()[1]
            received = bytearray()
            errors = []
            def receive():
                try:
                    with listener:
                        conn, _ = listener.accept()
                        with conn:
                            conn.settimeout(12)
                            while True:
                                part = conn.recv(65536)
                                if not part:
                                    break
                                received.extend(part)
                                if failure == 'disconnect':
                                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
                                    break
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=receive, daemon=True); thread.start()
            dd_body = 'command dd if="$FIXTURE" bs=1M'
            if failure == 'read':
                dd_body = 'command dd if="$FIXTURE" bs=1024 count=3; return 1'
            if failure == 'short':
                dd_body = 'command dd if="$FIXTURE" bs=1024 count=3'
            harness = '''
[() { if command [ "$1" = -b ]; then return 0; fi; command [ "$@"; }
blockdev() { case "$1" in --getro) echo 1 ;; --getsize64) echo "$FIXTURE_SIZE" ;; *) return 99 ;; esac; }
dd() {
    command [ "$1" = if=/dev/mmcblk0 ] && command [ "$2" = bs=1M ] || return 98
    ''' + dd_body + '''
}
'''
            script = (ROOT / 'rescue/rootfs/bin/form3-backup').read_text()
            script = script.replace('/proc/mounts', str(mounts)).replace('/run/form3-backup.XXXXXX', str(temp / 'work.XXXXXX'))
            runfile = temp / 'run.sh'; runfile.write_text(harness + script)
            env = dict(os.environ, PATH=str(bindir), FIXTURE=str(fixture), FIXTURE_SIZE=str(len(data)))
            result = subprocess.run([QEMU, str(BB), 'ash', str(runfile), '/dev/mmcblk0', '127.0.0.1', str(port)], env=env, capture_output=True, timeout=20)
            thread.join(13)
            self.assertFalse(thread.is_alive(), 'Listener did not exit')
            self.assertFalse(errors, errors)
            self.assertEqual(fixture.read_bytes(), data, 'Source fixture was modified')
            self.assertFalse(list(temp.glob('work.*')), 'RAM working directory not cleaned')
            if failure is None:
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(bytes(received), data)
                self.assertIn(hashlib.sha256(data).hexdigest().encode(), result.stdout)
                self.assertIn(f'source stream bytes: {len(data)}'.encode(), result.stdout)
            else:
                self.assertNotEqual(result.returncode, 0, result.stdout.decode())
                self.assertNotIn(b'Source stream complete.', result.stdout)

    def test_actual_ARM_stream_and_hash(self):
        self.stream_test()

    def test_read_error_does_not_report_success(self):
        self.stream_test('read')

    def test_short_read_does_not_report_success(self):
        self.stream_test('short')

    def test_network_disconnect_does_not_report_success(self):
        self.stream_test('disconnect')


if __name__ == '__main__':
    unittest.main(verbosity=2)
