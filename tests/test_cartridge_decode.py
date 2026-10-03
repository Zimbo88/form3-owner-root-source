"""Synthetic inputs only: no vendor keys, cartridge identities or EEPROM data."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import decode_cartridge_memory as decoder

SECRET = 'SYNTHETIC-NOT-A-VENDOR-KEY'
NAME = '2d-0123456789ab'
# Authored fixture, not a captured consumable. Algorithm primitives independently
# compared with isolated ARM functions; see CARTRIDGE_DECODING.md.
IMAGE = bytes.fromhex(
    '430001020304100260171f6ddf393f44fdd0b2d286fe8e1a10a9649c624d629e9c7c'
    'e880c6d118a8795c73ffffffffffffffffffffffffffffffffffffffffff013dc2b0'
    '0668fe58348de70d7e014405ffffffffffffffffffffffffffffffff013dc2b00668fe'
    '58348de70d7e014405ffffffffffffffffffffffffffffffff')


def record():
    return dict(SecretKey=SECRET, DispenseCount=284, WriteCount=538,
                EstimatedVolumeDispensed_ml=1033.6, CumulativeDispenseTime_s=4779)


class CartridgeDecodeTests(unittest.TestCase):
    def test_known_key_derivation(self):
        self.assertEqual(decoder.derive_key(SECRET, NAME), b'd67b9663ceb9f26f')

    def test_known_native_block_vector(self):
        self.assertEqual(decoder._block(bytes(range(16)), bytes(range(8))).hex(),
                         '256004e1f55bc0c7')

    def test_checksum_overflow_is_modulo_65536(self):
        self.assertEqual(decoder.checksum(bytes([255]) * 33), 0x2ecf20df)
        self.assertEqual(decoder.checksum(b''), 0)
        self.assertEqual(decoder.checksum(bytes(range(1, 12))), 0x011e0042)
        with self.assertRaises(ValueError):
            decoder.checksum(bytes(34))

    def test_valid_synthetic_copies(self):
        result = decoder.decode(IMAGE, record(), NAME)
        self.assertTrue(result['ro_checksum_valid'])
        self.assertTrue(result['rw_usage_equal'])
        self.assertFalse(result['native_write_supported'])
        self.assertFalse(result['checksum_is_signature_or_mac'])
        for copy in result['rw_copies']:
            self.assertTrue(all(copy['record_matches'].values()))
            self.assertEqual(copy['usage']['DispenseCount'], 284)

    def test_unknown_physical_remaining_volume(self):
        self.assertEqual(decoder.decode(IMAGE, record(), NAME)['physical_remaining_volume'], 'UNKNOWN')

    def test_wrong_key_and_identity_fail_closed(self):
        altered = record()
        altered['SecretKey'] += '-wrong'
        for r, n in [(altered, NAME), (record(), '2d-aaaaaaaaaaaa')]:
            with self.assertRaises(ValueError):
                decoder.decode(IMAGE, r, n)

    def test_all_record_byte_corruptions_rejected(self):
        for i in list(range(43)) + list(range(64, 80)) + list(range(96, 112)):
            damaged = bytearray(IMAGE)
            damaged[i] ^= 1
            with self.subTest(offset=i), self.assertRaises(ValueError):
                decoder.decode(bytes(damaged), record(), NAME)

    def test_unchecked_padding_not_misrepresented_as_authenticated(self):
        changed = bytearray(IMAGE)
        changed[120] ^= 1
        result = decoder.decode(bytes(changed), record(), NAME)
        self.assertTrue(result['ro_checksum_valid'])
        self.assertFalse(result['checksum_is_signature_or_mac'])

    def test_record_comparison_does_not_forge_agreement(self):
        changed = record()
        changed['WriteCount'] = 1
        result = decoder.decode(IMAGE, changed, NAME)
        self.assertFalse(result['rw_copies'][0]['record_matches']['WriteCount'])

    def test_malformed_dimensions_and_versions(self):
        for value in (b'', IMAGE[:127], IMAGE + b'x'):
            with self.assertRaises(ValueError):
                decoder.decode(value, record(), NAME)
        for offset in (1, 64, 96):
            changed = bytearray(IMAGE)
            changed[offset] = 7
            with self.assertRaises(ValueError):
                decoder.decode(bytes(changed), record(), NAME)

    def test_private_and_unknown_keys_not_exported(self):
        r = record()
        r['PRIVATE-UNKNOWN-KEY-AS-DICTIONARY-NAME'] = 'hidden'
        r['Manufacturer'] = 'private identity'
        text = json.dumps(decoder.decode(IMAGE, r, NAME))
        for value in (SECRET, NAME, 'PRIVATE-UNKNOWN', 'private identity', 'hidden'):
            self.assertNotIn(value, text)

    def test_record_parser(self):
        good = json.dumps(record()).encode()
        self.assertEqual(decoder.parse_record(good)['WriteCount'], 538)
        for value in (b'[]', b'{', b'{"x":1,"x":2}', b'x' * 65537,
                      good.replace(b'538', b'NaN'), good.replace(b'538', b'true')):
            with self.assertRaises(ValueError):
                decoder.parse_record(value)

    def test_bad_secret_not_in_error_message(self):
        for secret in (None, '', '\u2603', 'x' * 1025):
            with self.assertRaises(ValueError) as error:
                decoder.derive_key(secret, NAME)
            self.assertNotIn('\u2603', str(error.exception))

    def test_invalid_device_names(self):
        for value in ('', '/dev/w1', '2d-ABCDEF012345', '2d-0123456789ab\n', '4c-0123456789ab'):
            with self.assertRaises(ValueError):
                decoder.derive_key(SECRET, value)

    def test_input_pins_bounds_symlinks_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'image'
            p.write_bytes(IMAGE)
            pin = hashlib.sha256(IMAGE).hexdigest()
            self.assertEqual(decoder.read_pinned(p, pin, 128), IMAGE)
            link = p.parent / 'link'
            link.symlink_to(p)
            for path, sha, size in ((p, '0' * 64, 128), (p, pin, 127),
                                     (link, pin, 128), ('/dev/null', pin, 128)):
                with self.assertRaises((ValueError, OSError)):
                    decoder.read_pinned(path, sha, size)

    def test_output_is_private_and_non_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'report.json'
            decoder.write_report(p, {'safe': True})
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                decoder.write_report(p, {})
            symlink = p.parent / 'link'
            symlink.symlink_to(p)
            with self.assertRaises(ValueError):
                decoder.write_report(symlink, {})

    def test_cli_failure_redacts_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'input'
            p.write_bytes(IMAGE)
            r = subprocess.run([sys.executable, decoder.__file__, str(p),
                                '--sha256', '0' * 64, '--record-file', SECRET,
                                '--record-sha256', '0' * 64, '--device-name-file', NAME,
                                '--device-name-sha256', '0' * 64,
                                '--output', str(p.parent / 'out')],
                               capture_output=True, timeout=10)
            self.assertEqual(r.returncode, 2)
            self.assertNotIn(SECRET, r.stderr.decode())
            self.assertNotIn(NAME, r.stderr.decode())


if __name__ == '__main__':
    unittest.main()
