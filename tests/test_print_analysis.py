"""Synthetic offline-capture parser and panel tests; no hardware/real secrets."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'owner-ui'))
import analyze_print_session as parser
from panel_data import HistoricalBundle, print_session_view

BOOT = '00000000-0000-0000-0000-000000000001'


def event(kind, payload, stamp=1780000000):
    return {'event': {'kind': kind, 'device_epoch': stamp, 'device_monotonic': stamp-1700000000,
                      'boot_id': BOOT, 'payload': payload}}


def binary(raw, **fields):
    return dict(fields, data_b64=base64.b64encode(raw).decode(), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def file_event(raw, offset=0, inode=1, initial=0, path='/data/logs/sauron.log'):
    return event('file', binary(raw, offset=offset, inode=inode, device=1, generation=0,
                               path=path, initial_size=initial))


def report():
    return {'schema_version': 1, 'state': 'HISTORICAL', 'firmware_scope': '2.5.6-2773',
        'sources': [{'sha256': 'a'*64}], 'heater_csv': {'channels': [
            {'name': 'FanHeaterRPM', 'min': 9000, 'max': 9100, 'samples': 2, 'first': 10, 'last': 20,
             'points': [{'timestamp': 10, 'value': 9000}, {'timestamp': 20, 'value': 9100}]}]},
        'timeline': [{'timestamp': 12.1, 'kind': 'log_category', 'value': 'mixer_check_failed'},
                     {'timestamp': 12.2, 'kind': 'log_category', 'value': 'mixer_check_failed'},
                     {'timestamp': 20, 'kind': 'task_signal', 'value': 'finished'}],
        'coverage': {'boot_count': 1}}


class OfflinePrintAnalysis(unittest.TestCase):
    def run_events(self, rows):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'capture.jsonl'
            identity = event('identity', {'firmware':'2.5.6-2773','kernel':'4.9.65+','selected_slot':6})
            data = b''.join(json.dumps(row).encode()+b'\n' for row in [identity]+rows); p.write_bytes(data)
            with patch('socket.socket', side_effect=AssertionError('No network permitted')):
                result = parser.analyze([p])
            self.assertEqual(p.read_bytes(), data)
            return result

    def test_overlap_removed_without_text_based_fault_dedup(self):
        text = b'2026-05-29T00:00:01Z mixer check failed\n'
        result = self.run_events([file_event(text), file_event(text), file_event(text, offset=len(text))])
        self.assertEqual(result['log_categories'][0]['matching_lines'], 2)
        self.assertEqual(len(result['timeline']), 2)
        self.assertFalse(result['print_success_proven'])

    def test_overlap_mismatch_refused(self):
        with self.assertRaises(ValueError):
            self.run_events([file_event(b'abc'), file_event(b'axx')])

    def test_holes_and_partial_lines_never_joined(self):
        result = self.run_events([file_event(b'mixer check'), file_event(b' failed\n', offset=20)])
        self.assertEqual(result['coverage']['file_byte_gaps'], 1)
        self.assertEqual(result['log_categories'], [])

    def test_initial_history_boundary_preserved(self):
        text = b'2026-05-29T00:00:01Z mixer check failed\n'
        result = self.run_events([file_event(text+text, initial=len(text))])
        self.assertEqual([x['source']['baseline_at_first_capture'] for x in result['timeline']], [True, False])

    def test_unknown_paths_and_embedded_secrets_dropped(self):
        text = b'2026-05-29T00:00:01Z mixer check failed credential=SYNTHETIC_SECRET\n'
        result = self.run_events([file_event(text), file_event(text, inode=2, path='/data/logs/../../private.log')])
        encoded = json.dumps(result)
        self.assertNotIn('SYNTHETIC_SECRET', encoded); self.assertNotIn('private.log', encoded)
        self.assertEqual(len(result['files']), 1)

    def test_hash_and_size_rejection(self):
        for field, value in [('sha256', '0'*64), ('bytes', 999), ('data_b64', '!')]:
            row = file_event(b'abc'); row['event']['payload'][field] = value
            with self.assertRaises(ValueError): self.run_events([row])

    def test_coordinate_and_clock_rejection(self):
        for field, value in [('offset', -1), ('inode', True), ('generation', '0')]:
            row = file_event(b'abc'); row['event']['payload'][field] = value
            with self.assertRaises(ValueError): self.run_events([row])
        row = file_event(b'abc'); row['event']['device_epoch'] = float('nan')
        with self.assertRaises(ValueError): self.run_events([row])

    def test_truncated_duplicate_and_oversized_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'input'
            for raw in [b'{', b'{"event":{},"event":{}}\n', b'x'*(parser.MAX_LINE+1)]:
                p.write_bytes(raw)
                with self.assertRaises(ValueError): parser.analyze([p])

    def test_symlink_fifo_and_ancestor_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p/'source').write_text('{}\n'); (p/'link').symlink_to(p/'source'); os.mkfifo(p/'fifo')
            with self.assertRaises(OSError): parser.analyze([p/'link'])
            with self.assertRaises(ValueError): parser.analyze([p/'fifo'])
            (p/'dirlink').symlink_to(p, target_is_directory=True)
            with self.assertRaises(OSError): parser.analyze([p/'dirlink'/'source'])

    def test_stream_and_file_budgets(self):
        with patch.object(parser, 'MAX_FILE_BYTES', 2):
            with self.assertRaises(ValueError): self.run_events([file_event(b'abc')])
        with patch.object(parser, 'MAX_EVENTS', 0):
            with self.assertRaises(ValueError): self.run_events([file_event(b'abc')])

    def test_unknown_firmware_empty_and_missing_identity_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input'
            for rows in [[], [file_event(b'abc')],
                         [event('identity', {'firmware':'other','kernel':'4.9.65+','selected_slot':6})]]:
                p.write_bytes(b''.join(json.dumps(row).encode()+b'\n' for row in rows))
                with self.assertRaises(ValueError): parser.analyze([p])

    def test_fragmented_signal_and_partial_final_frame(self):
        block = (b'signal time=1780000000.000001 sender=:1.3 -> destination=(null destination) serial=10 '
                 b'path=/com/formlabs/Sauron; interface=com.formlabs.Sauron; member=finished\n')
        tail = block.replace(b'finished', b'aborted')
        raw = block + tail
        rows = [event('dbus', binary(raw[:31], channel='stdout')), event('dbus', binary(raw[31:], channel='stdout'))]
        result = self.run_events(rows)
        self.assertEqual([x['value'] for x in result['timeline']], ['finished'])
        self.assertEqual(result['coverage']['partial_final_signals_omitted'], 1)
        self.assertFalse(result['print_success_proven'])

    def test_temperature_error_flag_not_inverted(self):
        header = (b'signal time=1780000000.000001 sender=:1.3 -> destination=(null destination) serial=10 '
                  b'path=/com/formlabs/momo/temperatures/Tower; interface=com.formlabs.Temperature; member=temperature\n')
        one = header + b'   struct {\n      boolean false\n      double 30.5\n   }\n'
        two = header.replace(b'serial=10', b'serial=11') + b'   struct {\n      boolean true\n      double 999\n   }\n'
        result = self.run_events([event('dbus', binary(one+two+header, channel='stdout'))])
        row = result['bus_temperatures'][0]
        self.assertEqual(row['samples'], 1); self.assertEqual(row['max'], 30.5); self.assertEqual(row['error_flag_count'], 1)

    def test_csv_schema_exact_and_nonfinite_refused(self):
        header = '\t'.join(parser.CSV_COLUMNS)+'\n'; values = ['2026-05-29T00:00:01Z']+['0']*14
        raw = (header+'\t'.join(values)+'\n').encode()
        result = self.run_events([file_event(raw, path='/data/logs/daguerreHeater_v1.csv')])
        self.assertEqual(result['heater_csv']['rows'], 1)
        values[2] = 'nan'; raw = (header+'\t'.join(values)+'\n').encode()
        result = self.run_events([file_event(raw, path='/data/logs/daguerreHeater_v1.csv')])
        self.assertEqual(result['heater_csv']['rows'], 0)
        self.assertEqual(result['heater_csv']['invalid_rows'], 1)


class PanelPrintHistory(unittest.TestCase):
    def test_history_has_no_live_state_or_success_clearance(self):
        result = print_session_view(json.dumps(report()))
        self.assertEqual(result['state'], 'HISTORICAL')
        self.assertEqual(len(result['events']), 2)
        self.assertFalse(result['safe_idle_proven']); self.assertFalse(result['print_success_proven'])
        self.assertIn('not proof', result['events'][-1]['description'])

    def test_unknown_keys_and_values_never_leave_view(self):
        value = report(); value['SYNTHETIC_KEY_IN_NAME'] = 'SYNTHETIC_SECRET'
        value['timeline'].append({'timestamp': 10, 'kind': 'task_signal', 'value': 'SYNTHETIC_SECRET'})
        value['heater_csv']['channels'][0]['extra'] = 'SYNTHETIC_SECRET'
        result = json.dumps(print_session_view(json.dumps(value)))
        self.assertNotIn('SYNTHETIC', result)

    def test_bad_schema_bounds_and_duplicate_channel(self):
        for mutate in [lambda v: v.update(state='LIVE'), lambda v: v.update(firmware_scope='unknown'),
                       lambda v: v['sources'][0].update(sha256='x'),
                       lambda v: v['heater_csv']['channels'][0].update(samples=True),
                       lambda v: v['heater_csv']['channels'][0].update(min=9200),
                       lambda v: v['heater_csv']['channels'][0].update(points=[{}]*61),
                       lambda v: v['heater_csv']['channels'].append(v['heater_csv']['channels'][0])]:
            value = report(); mutate(value)
            with self.assertRaises(ValueError): print_session_view(json.dumps(value))

    def test_missing_invalid_and_valid_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p/'panel_snapshot.json').write_text('{"schema_version":1}')
            bundle = HistoricalBundle(d)
            try:
                self.assertEqual(bundle.summary()['print_session']['state'], 'UNAVAILABLE')
                (p/'print_session.json').write_text('{')
                self.assertEqual(bundle.summary()['print_session']['reason'], 'INVALID_CAPTURE_REPORT')
                (p/'print_session.json').write_text(json.dumps(report()))
                self.assertEqual(bundle.summary()['print_session']['channels'][0]['unit'], 'RPM')
            finally: bundle.tree.close()


if __name__ == '__main__':
    unittest.main()
