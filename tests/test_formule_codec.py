"""Synthetic offline fixtures, not captured traffic or hardware observations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'owner-ui'))
from formule_codec import FrameDecoder, ProtocolError, metadata_object, status_projection
from form3ctl import decode_file, main

def wire(obj=None, attachment=b'', raw=None):
    if raw is None:
        obj = obj if obj is not None else {'Id': 'fixture', 'Method':'PROTOCOL_METHOD_GET_STATUS', 'Version':1, 'Parameters':{}}
        raw = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    return struct.pack('<I', len(raw)) + raw + struct.pack('<q', len(attachment)) + attachment

class FormuleTests(unittest.TestCase):
    def test_known_prefix_fixture(self):
        frame = wire(raw=b'{}')
        self.assertEqual(frame, b'\x02\x00\x00\x00{}' + b'\x00'*8)

    def test_one_complete_frame(self):
        d = FrameDecoder(); out=d.feed(wire()); self.assertEqual(d.finish(),1)
        self.assertEqual(out[0]['method'],'PROTOCOL_METHOD_GET_STATUS')
        self.assertEqual(out[0]['authorization'],'NOT ESTABLISHED BY FRAME PARSING')

    def test_every_single_split(self):
        frame=wire(attachment=b'\x00\xffprivate-fixture')
        for i in range(len(frame)+1):
            d=FrameDecoder();out=d.feed(frame[:i])+d.feed(frame[i:]);d.finish()
            self.assertEqual(len(out),1)
            self.assertEqual(out[0]['attachment_sha256'],hashlib.sha256(b'\x00\xffprivate-fixture').hexdigest())

    def test_byte_at_a_time(self):
        d=FrameDecoder();out=[]
        for b in wire():out.extend(d.feed(bytes([b])))
        self.assertEqual(d.finish(),1);self.assertEqual(len(out),1)

    def test_two_frames_and_new_session(self):
        d=FrameDecoder();self.assertEqual(len(d.feed(wire()+wire())),2);d.finish()
        d.reset();self.assertEqual(len(d.feed(wire())),1);self.assertEqual(d.finish(),1)

    def test_attachment_streaming_bounded(self):
        data=b'Z'*200000;frame=wire(attachment=data);d=FrameDecoder();out=[]
        for off in range(0,len(frame),1000):
            out.extend(d.feed(frame[off:off+1000]));self.assertLessEqual(len(d.buffer),1000)
        d.finish();self.assertEqual(out[0]['attachment_bytes'],len(data))
        self.assertNotIn('ZZZZ',json.dumps(out))

    def test_partial_header(self):
        d=FrameDecoder();d.feed(b'\x01');self.assertRaises(ProtocolError,d.finish)

    def test_partial_attachment(self):
        d=FrameDecoder();d.feed(wire(attachment=b'123')[:-1]);self.assertRaises(ProtocolError,d.finish)

    def test_rejected_stream_requires_reset(self):
        d=FrameDecoder();self.assertRaises(ProtocolError,d.feed,b'\x00'*4)
        self.assertRaises(ProtocolError,d.feed,wire());d.reset();self.assertEqual(len(d.feed(wire())),1)

    def test_invalid_lengths(self):
        for n in [0,65537,0xffffffff,0xfffffffe]:
            self.assertRaises(ProtocolError,FrameDecoder().feed,struct.pack('<I',n))
        for n in [-1,4*1024*1024+1,2**63-1]:
            self.assertRaises(ProtocolError,FrameDecoder().feed,struct.pack('<I',2)+b'{}'+struct.pack('<q',n))

    def test_bad_endian(self):
        self.assertRaises(ProtocolError,FrameDecoder().feed,struct.pack('>I',2)+b'{}'+b'\0'*8)

    def test_duplicate_secret_key_rejected_without_echo(self):
        with self.assertRaises(ProtocolError) as c:metadata_object(b'{"SECRET_VALUE":1,"SECRET_VALUE":2}')
        self.assertNotIn('SECRET_VALUE',str(c.exception))

    def test_invalid_json(self):
        for raw in [b'[]',b'{',b'null',b'{"x":NaN}',b'{"x":1e999}',b'\xff']:
            self.assertRaises(ProtocolError,FrameDecoder().feed,wire(raw=raw))

    def test_deep_and_wide_json(self):
        for raw in [b'{"x":'+b'['*40+b'0'+b']'*40+b'}',json.dumps({'x':[0]*5000}).encode()]:
            self.assertRaises(ProtocolError,metadata_object,raw)

    def test_unknown_opcode_withheld(self):
        out=FrameDecoder().feed(wire({'Method':'SECRET_OPCODE','Parameters':{'SECRET_KEY':'SECRET_VALUE'}}))[0]
        self.assertEqual(out['method'],'UNKNOWN');self.assertNotIn('SECRET',json.dumps(out))

    def test_identity_and_error_redaction(self):
        out=FrameDecoder().feed(wire({'Id':'SECRET_ID','ReplyToMethod':'PROTOCOL_METHOD_GET_STATUS','Version':1,'Success':True,'Error':'SECRET_ERROR','Parameters':{'tankId':'SECRET_TANK','SecretKey':'SECRET_KEY','SECRET_MAP_KEY':'value','isPrinting':False}}))[0]
        self.assertNotIn('SECRET',json.dumps(out));self.assertTrue(out['error_present'])
        self.assertEqual(out['status']['isPrinting']['availability'],'HISTORICAL')
        self.assertNotIn('safe_idle',json.dumps(out))

    def test_types_and_freshness(self):
        out=status_projection({'isPrinting':0,'estimatedTotalPrintTime_ms':True,'isPrimed':True})
        self.assertEqual(out['isPrinting']['availability'],'UNAVAILABLE')
        self.assertEqual(out['estimatedTotalPrintTime_ms']['availability'],'UNAVAILABLE')
        self.assertRaises(ProtocolError,status_projection,{},'LIVE')
        self.assertRaises(ProtocolError,FrameDecoder,provenance='LIVE')

    def test_time_units_and_bounds(self):
        out=status_projection({'estimatedTotalPrintTime_ms':5000,'estimatedPrintTimeRemaining_ms':-1},'DEMO')
        self.assertEqual(out['estimatedTotalPrintTime_ms']['unit'],'ms')
        self.assertEqual(out['estimatedTotalPrintTime_ms']['availability'],'DEMO')
        self.assertEqual(out['estimatedPrintTimeRemaining_ms']['availability'],'UNAVAILABLE')

    def test_frame_count_bound(self):
        self.assertRaises(ProtocolError,FrameDecoder(max_frames=1).feed,wire()+wire())

    def test_chunk_bound(self):
        self.assertRaises(ProtocolError,FrameDecoder().feed,b'A'*65537)
        self.assertRaises(ProtocolError,FrameDecoder().feed,'not bytes')

    def test_cli_no_network_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            inp=Path(t)/'capture.bin';out=Path(t)/'report.json';inp.write_bytes(wire())
            with mock.patch.object(socket,'socket',side_effect=AssertionError('network forbidden')):
                self.assertEqual(main(['decode','--input',str(inp),'--output',str(out),'--demo']),0)
                before=out.read_bytes();self.assertEqual(main(['decode','--input',str(inp),'--output',str(out)]),1)
                self.assertEqual(before,out.read_bytes())
            self.assertEqual(os.stat(str(out)).st_mode&0o777,0o600)

    def test_symlink_and_device_input_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a';p.write_bytes(wire());link=Path(t)/'link';link.symlink_to(p)
            self.assertRaises(OSError,decode_file,str(link))
            self.assertRaises(ProtocolError,decode_file,'/dev/null')

    def test_output_symlink_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'in';p.write_bytes(wire());target=Path(t)/'target';target.write_text('keep')
            link=Path(t)/'out';link.symlink_to(target)
            self.assertEqual(main(['decode','--input',str(p),'--output',str(link)]),1)
            self.assertEqual(target.read_text(),'keep')

    def test_raw_attachment_not_retained(self):
        d=FrameDecoder();out=d.feed(wire(attachment=b'PRIVATE_PAYLOAD'));d.finish()
        self.assertNotIn('PRIVATE_PAYLOAD',json.dumps(out));self.assertIsNone(d.pending)
        self.assertEqual(d.buffer,bytearray())

if __name__=='__main__':unittest.main()
