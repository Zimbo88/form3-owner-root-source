"""Synthetic existing-file checks, never programmer or physical reads."""
import hashlib,os,struct,sys,tempfile,unittest,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from inspect_qspi_reads import inspect

class QSPIReadChecks(unittest.TestCase):
    def fixture(self,d):
        raw=bytearray(b'\xff'*4194304)
        raw[20:30]=b'CHSETTINGS';struct.pack_into('<II',raw,0x200,128,0x40300000)
        payload=b'U-Boot SYNTHETIC';header=struct.pack('>7I4B32s',0x27051956,0,0,len(payload),0x80800000,0x80800000,zlib.crc32(payload),17,2,5,0,b'SYNTHETIC')
        header=header[:4]+struct.pack('>I',zlib.crc32(header))+header[8:]
        raw[0x40000:0x40040]=header;raw[0x40040:0x40040+len(payload)]=payload
        body=b'fl_bootpart=6\0\0';body+=b'\xff'*(16380-len(body))
        raw[0xc0000:0xc4000]=struct.pack('<I',zlib.crc32(body))+body
        paths=[Path(d)/('read%d.bin'%n) for n in range(3)]
        for p in paths:p.write_bytes(raw)
        return paths,bytes(raw)
    def test_three_equal_meaningful_files(self):
        with tempfile.TemporaryDirectory() as d:
            paths,raw=self.fixture(d);r=inspect(paths,hashlib.sha256(raw).hexdigest())
            self.assertTrue(r['three_byte_identical']);self.assertFalse(r['electrical_safety_proven'])
    def test_different_or_short_or_crc_corrupt_refused(self):
        for offset in (0,0xc0010,0x40004,0x40045,0x200,None):
            with tempfile.TemporaryDirectory() as d:
                paths,raw=self.fixture(d);b=bytearray(raw)
                if offset is None:b=b[:-1]
                else:b[offset]^=1
                paths[2].write_bytes(b)
                with self.assertRaises(ValueError):inspect(paths)
    def test_same_inode_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            paths,raw=self.fixture(d)
            with self.assertRaises(ValueError):inspect([paths[0]]*3)
            link=Path(d)/'alias';link.symlink_to(paths[0])
            with self.assertRaises(OSError):inspect([paths[0],paths[1],link])
    def test_blank_wrong_hash_and_missing_read_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            paths,raw=self.fixture(d)
            with self.assertRaises(ValueError):inspect(paths,'0'*64)
            with self.assertRaises(ValueError):inspect(paths[:2])
            paths[0].write_bytes(b'\xff'*len(raw))
            with self.assertRaises(ValueError):inspect(paths)
