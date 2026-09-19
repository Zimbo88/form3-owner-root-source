"""Authored synthetic fixtures. No device, D-Bus or vendor program execution."""
import json
import math
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'owner-ui')]
from inspect_qt_metadata import Elf32, MetadataError, inspect
from panel_data import field, number, refill_preview
from server import LinuxProvider, decorate_snapshot
from build_diagnostic_bundle import thermal_history, decode_metrics
import msgpack


def qt_fixture():
    b = bytearray(4096)
    b[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HH', b, 16, 2, 40)
    struct.pack_into('<I', b, 28, 52)
    struct.pack_into('<HH', b, 42, 32, 1)
    struct.pack_into('<8I', b, 52, 1, 0, 0x10000, 0, len(b), len(b), 5, 4096)
    struct.pack_into('<6I', b, 0x100, 0, 0x10400, 0x10200, 0x10800, 0, 0)
    struct.pack_into('<14I', b, 0x200, 7, 0, 0, 0, 2, 14, 0, 0, 0, 0, 0, 0, 0, 1)
    struct.pack_into('<5I', b, 0x238, 1, 1, 24, 0, 0x46)
    struct.pack_into('<5I', b, 0x24c, 2, 0, 26, 0, 0x4a)
    struct.pack_into('<3I', b, 0x260, 43, 0x80000003, 11)
    for i, value in enumerate(['Fixture::Status', 'changed', 'GetStates', 'FixtureState']):
        raw = value.encode()
        entry = 0x400 + i * 16
        pos = 0x500 + i * 64
        struct.pack_into('<iiIi', b, entry, -1, len(raw), 0, pos-entry)
        b[pos:pos+len(raw)+1] = raw + b'\0'
    b[0xe00:0xe00+24] = b'private-fixture-excluded!'
    return b


class QtMetadata(unittest.TestCase):
    def test_structural_metadata_not_safety_authorization(self):
        x = Elf32(qt_fixture()).meta(0x10100)
        self.assertEqual(x['class'], 'Fixture::Status')
        self.assertEqual(x['methods'][0]['argument_types'], [{'name':'FixtureState'}])
        self.assertEqual(x['methods'][1]['name'], 'GetStates')
        self.assertEqual(x['methods'][1]['kind'], 'slot')
        self.assertIn('UNKNOWN', x['methods'][1]['side_effects'])
        self.assertFalse(x['live_interface_proven'])
        self.assertNotIn('private-fixture', json.dumps(x))

    def test_truncated_and_wrong_platform(self):
        raw = qt_fixture()
        for n in (0, 40, 51, 70, 1024):
            with self.assertRaises(MetadataError): Elf32(raw[:n])
        for pos, value in ((4, 2), (5, 2), (16, 3), (18, 62)):
            b = raw[:]; b[pos] = value
            with self.assertRaises(MetadataError): Elf32(b)

    def test_bounds_revision_arguments_strings(self):
        for offset, value in ((0x200, 8), (0x210, 257), (0x23c, 17),
                              (0x238, 4097), (0x404, 257), (0x40c, 0xffffff00)):
            b = qt_fixture(); struct.pack_into('<I', b, offset, value)
            with self.assertRaises(MetadataError): Elf32(b).meta(0x10100)
        b = qt_fixture(); b[0x500] = ord('/')
        with self.assertRaises(MetadataError): Elf32(b).meta(0x10100)

    def test_unmapped_ambiguous_and_device_inputs(self):
        b = qt_fixture(); elf = Elf32(b)
        with self.assertRaises(MetadataError): elf.read(0x13000, 4)
        elf.segments.append(elf.segments[0])
        with self.assertRaises(MetadataError): elf.meta(0x10100)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'blob'; p.write_bytes(b)
            (Path(d)/'link').symlink_to(p)
            with self.assertRaises(OSError): inspect(Path(d)/'link', [0x10100])
            with self.assertRaises(MetadataError): inspect(p, [])
            self.assertFalse(inspect(p, [0x10100])['vendor_execution'])


class DataQuality(unittest.TestCase):
    def test_enrich_existing_bundle_match_and_escape_guards(self):
        import enrich_diagnostic_history as tool
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle=root/'bundle';(bundle/'raw').mkdir(parents=True)
            (root/'research-private').mkdir()
            thermal=root/'thermal';raw=msgpack.packb([1000,{'type':'cpu_thermal','temp':42}],use_bin_type=True)
            thermal.write_bytes(raw)
            snapshot={'schema_version':1,'state':'HISTORICAL','scope':'unreplayed fixture','logs':[
                {'file_id':'log-000','decoded_size':7}], 'sensors':[{'path':'logs/fluentbit_system_thermal.msgpack',
                'source_sha256':hashlib.sha256(raw).hexdigest()}]}
            (bundle/'raw/log-000.log').write_bytes(b'fixture')
            (bundle/'panel_snapshot.json').write_text(json.dumps(snapshot));(bundle/'diagnostics.json').write_text('[]')
            (bundle/'private-jobs-catalog.json').write_text('DO NOT COPY FIXTURE')
            before=(bundle/'panel_snapshot.json').read_bytes()
            with patch.object(tool,'ROOT',root):
                out=root/'research-private/valid';result=tool.enrich(bundle,thermal,out)
                self.assertEqual(result['copied_logs'],1);self.assertFalse(result['recovery_coverage_expanded'])
                self.assertEqual((bundle/'panel_snapshot.json').read_bytes(),before)
                self.assertFalse((out/'private-jobs-catalog.json').exists())
                self.assertEqual(json.loads((out/'panel_snapshot.json').read_text())['sensors'][0]['thermal_history'][0]['samples'],1)
                with self.assertRaises(FileExistsError):tool.enrich(bundle,thermal,out)
                thermal.write_bytes(msgpack.packb([1001,{}]))
                with self.assertRaises(ValueError):tool.enrich(bundle,thermal,root/'research-private/mismatch')
                thermal.write_bytes(raw);snapshot['logs'][0]['file_id']='../private'
                (bundle/'panel_snapshot.json').write_text(json.dumps(snapshot))
                with self.assertRaises(ValueError):tool.enrich(bundle,thermal,root/'research-private/escape')

    def test_thermal_clock_gaps_and_point_limit(self):
        rows=[{'timestamp':1000+i*10,'values':{'type':'cpu_thermal','temp':40+i/100.0,
               'synthetic-private-field':'never emit'}} for i in range(90)]
        for row in rows[40:]:row['timestamp']+=20000000
        result=thermal_history(rows)[0]
        self.assertEqual(result['samples'],90);self.assertEqual(len(result['points']),60)
        self.assertEqual(result['gaps_over_300_seconds'],1)
        self.assertEqual(sum(not x['continuous_from_previous'] for x in result['points']),2)
        self.assertEqual(result['state'],'HISTORICAL');self.assertEqual(result['safety_assessment'],'UNKNOWN')
        self.assertNotIn('synthetic-private',json.dumps(result))

    def test_thermal_bad_numbers_and_messagepack_event_time(self):
        rows=[{'timestamp':10,'values':{'type':'cpu_thermal','temp':float('inf')}},
              {'timestamp':11,'values':{'type':'unknown','temp':20}}]
        self.assertEqual(thermal_history(rows),[])
        raw=msgpack.packb([msgpack.ExtType(0,struct.pack('>II',10,1000000000)),{'temp':20}],use_bin_type=True)
        with self.assertRaises(ValueError):decode_metrics(raw)
        with self.assertRaises(ValueError):thermal_history([None])

    def test_future_missing_and_expired_observations(self):
        with patch('panel_data.time.time', return_value=1000):
            for stamp in (None, True, float('nan'), float('inf'), 1001, 900):
                result = field(2, 'LIVE', 'fixture', timestamp=stamp, max_age=30)
                self.assertFalse(result['fresh']); self.assertEqual(result['state'], 'CACHED')
            self.assertTrue(field(2, 'LIVE', timestamp=999, max_age=30)['fresh'])
            self.assertEqual(field(None, 'LIVE', timestamp=999, max_age=30)['state'], 'UNAVAILABLE')
            self.assertEqual(field(2, 'HISTORICAL', timestamp=900, max_age=30)['state'], 'HISTORICAL')
        self.assertIsNone(number(10**1000))

    def test_kernel_numeric_rejection_and_temperature_source(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p/'proc').mkdir(); (p/'sys/class/thermal/thermal_zone0').mkdir(parents=True)
            temp = p/'sys/class/thermal/thermal_zone0/temp'
            temp.write_text('43210'); (temp.parent/'type').write_text('cpu_thermal')
            (p/'proc/uptime').write_text('NaN 0'); (p/'proc/loadavg').write_text('1 inf 3 1/2 1')
            provider = LinuxProvider(p)
            try:
                snapshot = decorate_snapshot(provider.snapshot())
                self.assertIsNone(snapshot['system']['uptime_seconds'])
                self.assertIsNone(snapshot['system']['load_1_5_15'])
                self.assertEqual(snapshot['sensors'][0]['celsius'], 43.21)
                self.assertTrue(snapshot['sensors'][0]['observation']['source'].endswith('/temp'))
                for value in ('not-a-number', '999999999', '-273151'):
                    temp.write_text(value)
                    s = decorate_snapshot(provider.snapshot())
                    self.assertEqual(s['sensors'][0]['observation']['state'], 'UNAVAILABLE')
                    self.assertFalse(s['sensors'][0]['safety_limit'])
                    json.dumps(s, allow_nan=False)
            finally: provider.tree.close()

    def test_refill_snapshot_match_is_not_native_reconciliation(self):
        record = {'kind':'cartridge', 'record_sha256':'a'*64}
        entries = [{'record_sha256':'a'*64,'quantity_ml':200,'same_material_asserted':True},
                   {'record_sha256':'b'*64,'quantity_ml':100,'same_material_asserted':False}]
        before = json.dumps(entries)
        result = refill_preview([record], entries)
        self.assertEqual(result['records'][0]['owner_declared_added_ml'], 200)
        self.assertEqual(result['unmatched_declarations'], 1)
        self.assertIsNone(result['records'][0]['physical_remaining_ml']['value'])
        self.assertFalse(result['records'][0]['dispense_permission'])
        self.assertFalse(result['native_reset_enabled'])
        self.assertEqual(json.dumps(entries), before)
        entries[0]['quantity_ml'] = float('inf')
        with self.assertRaises(ValueError): refill_preview([record], entries)

    def test_refill_unknown_and_corrupt_records(self):
        self.assertEqual(refill_preview([], [])['records'], [])
        for value in (None, [{}]*129):
            with self.assertRaises(ValueError): refill_preview(value, [])
        with self.assertRaises(ValueError): refill_preview([], [{}]*257)
        with self.assertRaises(ValueError): refill_preview([{'kind':'cartridge','record_sha256':'../private'}], [])


if __name__ == '__main__':
    unittest.main()
