"""Authored synthetic bytes only. No native key, EEPROM fixture or hardware access."""
import hashlib,json,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import inspect_cartridge_memory as memory
import inspect_cartridge_layout as layout

class CartridgeMemory(unittest.TestCase):
    def image(self):
        data=bytearray(b'\xff'*128);data[:2]=b'C\0'
        a=b'\1'+b'synthetic!!'+b'\0'*4
        self.assertEqual(len(a),16)
        data[64:80]=a;data[96:112]=a
        return bytes(data)
    def inspect(self,data):return memory.inspect_image(data,hashlib.sha256(data).hexdigest())
    def test_identical_copies_never_claim_authentication_or_fullness(self):
        result=self.inspect(self.image());self.assertTrue(result['rw_copies_equal'])
        self.assertFalse(result['write_supported']);self.assertFalse(result['restore_tested'])
        self.assertFalse(result['physically_full_proven'])
        self.assertTrue(all(c['reviewed_version'] and not c['checksum_verified'] for c in result['rw_copies']))
        self.assertNotIn('synthetic!!',json.dumps(result))
    def test_partial_copy_change_is_visible_without_faking_a_repair(self):
        raw=bytearray(self.image());raw[70]^=1;r=self.inspect(bytes(raw))
        self.assertFalse(r['rw_copies_equal']);self.assertFalse(r['write_supported'])
    def test_pin_truncation_size_and_type_fail_closed(self):
        raw=self.image()
        for data in (raw[:-1],raw+b'x',b'T'+raw[1:],raw[:1]+b'\1'+raw[2:]):
            with self.assertRaises(ValueError):self.inspect(data)
        for pin in ('','0'*64,'a'*63):
            with self.assertRaises(ValueError):memory.inspect_image(raw,pin)
    def test_unknown_rw_version_is_not_reported_valid(self):
        raw=bytearray(self.image());raw[64]=7;r=self.inspect(bytes(raw))
        self.assertFalse(r['rw_copies'][0]['reviewed_version'])
        self.assertFalse(r['rw_copies'][0]['checksum_verified'])
    def test_plaintext_layout_has_no_ciphertext_or_authentication_claim(self):
        raw=b'\x03\x02\x01'+struct.pack('<IHH',42,6543,321)
        r=memory.decode_decrypted_rw(raw)
        self.assertEqual(r['packed_dispense_counter_bytes'],[3,2,1])
        self.assertEqual(r['WriteCount'],42);self.assertEqual(r['EstimatedVolumeDispensed_ml'],654.3)
        self.assertEqual(r['CumulativeDispenseTime_s'],321);self.assertFalse(r['provenance_verified'])
        for bad in (b'',raw[:-1],raw+b'x','x'*11):
            with self.assertRaises(ValueError):memory.decode_decrypted_rw(bad)
    def test_lowering_a_single_mirror_does_not_lower_the_usage_maximum(self):
        old={k:120 for k in memory.USAGE_FIELDS};lower={k:0 for k in memory.USAGE_FIELDS}
        lower['SecretKey']='synthetic-private-marker'
        for a,b in ((old,lower),(lower,old)):
            r=memory.monotonic_usage_model(a,b);self.assertEqual(r['projected_usage'],old)
            self.assertFalse(r['native_write_authorized']);self.assertNotIn('synthetic-private-marker',json.dumps(r))
    def test_missing_invalid_unknown_and_negative_usage_not_accepted(self):
        valid={k:1 for k in memory.USAGE_FIELDS}
        for v in (None,True,-1,float('nan'),float('inf'),'1'):
            bad=dict(valid,EstimatedVolumeDispensed_ml=v)
            with self.assertRaises(ValueError):memory.monotonic_usage_model(valid,bad)
        with self.assertRaises(ValueError):memory.monotonic_usage_model(valid,{})

class LayoutPin(unittest.TestCase):
    def test_unreviewed_binary_never_reaches_metadata_parser(self):
        for raw in (b'',b'\x7fELF\1\1'+b'\0'*200,b'proprietary-looking but synthetic'):
            with self.assertRaises(ValueError):layout.inspect(raw)
