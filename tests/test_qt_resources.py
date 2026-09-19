import hashlib,struct,sys,tempfile,unittest,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from inspect_qt_resources import Resource,extract_selected,replace_members,MAX_MEMBER,private_destination
from inspect_palantir_resources import inspect as inspect_embedded
from build_native_clock_review import patch_qml,ORIGINAL,REPLACEMENT
from inspect_psplash_image import decode_rle,encode_rle,inspect as inspect_splash

def fixture(entries=None):
    entries=entries or [('screen.qml',b'import QtQuick 2.9\nItem {}',False,0,1)]
    payload=bytearray();names=bytearray();nodes=[]
    for name,data,compressed,country,language in entries:
        no=len(names);encoded=name.encode('utf-16-be')
        names.extend(struct.pack('>HI',len(encoded)//2,0)+encoded)
        offset=len(payload);stored=struct.pack('>I',len(data))+zlib.compress(data) if compressed else data
        payload.extend(struct.pack('>I',len(stored))+stored)
        nodes.append(struct.pack('>IHHHIQ',no,int(compressed),country,language,offset,0))
    tree=struct.pack('>IHIIQ',0,2,len(nodes),1,0)+b''.join(nodes)
    return b'qres'+struct.pack('>4I',2,20+len(payload)+len(names),20,20+len(payload))+payload+names+tree

class QtResourceTests(unittest.TestCase):
    def test_plain_and_compressed(self):
        r=Resource(fixture([('one.qml',b'Item {}',False,0,1),('two.qml',b'x'*100,True,0,1)]))
        self.assertEqual(r.inventory()['total_member_bytes'],107)
    def test_header_truncation(self):
        for size in range(42):
            with self.assertRaises(ValueError):Resource(fixture()[:size])
    def test_wrong_format_version(self):
        d=bytearray(fixture());struct.pack_into('>I',d,4,3)
        with self.assertRaises(ValueError):Resource(bytes(d))
    def test_node_tail_truncation(self):
        with self.assertRaises(ValueError):Resource(fixture()[:-1])
    def test_name_escape(self):
        for name in ['..','../x','a/b','a\\b','\x00','x\n']:
            with self.assertRaises(ValueError):Resource(fixture([(name,b'',False,0,1)]))
    def test_duplicate_member(self):
        row=('same.qml',b'x',False,0,1)
        with self.assertRaises(ValueError):Resource(fixture([row,row]))
    def test_tree_cycle(self):
        d=bytearray(fixture());tree=struct.unpack_from('>I',d,8)[0];struct.pack_into('>I',d,tree+10,0)
        with self.assertRaises(ValueError):Resource(bytes(d))
    def test_unreachable_node(self):
        d=bytearray(fixture());tree=struct.unpack_from('>I',d,8)[0];struct.pack_into('>I',d,tree+6,0)
        with self.assertRaises(ValueError):Resource(bytes(d))
    def test_payload_outside_section(self):
        d=bytearray(fixture());tree=struct.unpack_from('>I',d,8)[0];struct.pack_into('>I',d,tree+22+10,0x100000)
        with self.assertRaises(ValueError):Resource(bytes(d))
    def test_expansion_bomb(self):
        d=bytearray(fixture([('x',b'x',True,0,1)]));struct.pack_into('>I',d,24,MAX_MEMBER+1)
        with self.assertRaises(ValueError):Resource(bytes(d)).inventory()
    def test_bad_compressed_stream(self):
        d=bytearray(fixture([('x',b'x',True,0,1)]));d[30]^=0xff
        with self.assertRaises(ValueError):Resource(bytes(d)).inventory()
    def test_false_expanded_length(self):
        d=bytearray(fixture([('x',b'123',True,0,1)]));struct.pack_into('>I',d,24,2)
        with self.assertRaises(ValueError):Resource(bytes(d)).inventory()
    def test_extract_new_private_only(self):
        with tempfile.TemporaryDirectory() as t:
            dest=Path(t)/'research-private'/'selected'
            self.assertEqual(extract_selected(Resource(fixture()),['screen.qml'],dest),1)
            self.assertEqual((dest/'screen.qml').read_bytes(),b'import QtQuick 2.9\nItem {}')
            with self.assertRaises(FileExistsError):extract_selected(Resource(fixture()),['screen.qml'],dest)
    def test_public_output_refused(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):extract_selected(Resource(fixture()),['screen.qml'],Path(t)/'public')
    def test_original_evidence_parent_refused(self):
        with tempfile.TemporaryDirectory() as t:
            for area in ('emmc','qspi'):
                dest=Path(t)/'hardware'/area/'original/research-private/output'
                with self.assertRaises(ValueError):private_destination(dest)
                self.assertFalse(dest.exists())
    def test_symlink_parent_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'research-private').mkdir();(p/'real').mkdir();(p/'research-private/link').symlink_to(p/'real',target_is_directory=True)
            with self.assertRaises(ValueError):private_destination(p/'research-private/link/out')
            self.assertFalse((p/'real/out').exists())
    def test_ambiguous_locale_refused(self):
        r=Resource(fixture([('x',b'1',False,0,1),('x',b'2',False,0,2)]))
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):extract_selected(r,['x'],Path(t)/'research-private/out')
    def test_selected_missing(self):
        with self.assertRaises(ValueError):extract_selected(Resource(fixture()),['missing'],'research-private/unused')
    def test_replace_preserves_all_other_content(self):
        r=Resource(fixture([('x',b'old',True,0,1),('other',b'unchanged',True,0,1)]))
        n=replace_members(r,{'x':b'new'})
        self.assertEqual({a['path']:n.contents(a) for a in n.rows},{'x':b'new','other':b'unchanged'})
        self.assertEqual(n.data[n.names:n.tree],r.data[r.names:r.tree])
    def test_replace_missing_or_oversized(self):
        for value in ({},{'missing':b'x'},{'screen.qml':b'x'*(MAX_MEMBER+1)}):
            with self.assertRaises(ValueError):replace_members(Resource(fixture()),value)
    def test_arbitrary_binary_pins_rejected(self):
        with self.assertRaises(ValueError):inspect_embedded(b'ELF')
        with self.assertRaises(ValueError):inspect_splash(b'ELF')
    def test_clock_insertion_preserves_custom_subtitle(self):
        src=('import QtQuick 2.9 as QtQuick\nQtQuick.Item {\nvalue: '+ORIGINAL+'\n}').encode()
        frag=(Path(__file__).resolve().parents[1]/'owner-ui/native/idle-clock.qmlinc').read_bytes()
        changed=patch_qml(src,frag).decode()
        self.assertIn(REPLACEMENT,changed)
        self.assertIn('model.text_headerSubtitle !== "" ? model.text_headerSubtitle :',changed)
        self.assertNotIn('ProcessLaunchHelper',changed)
        with self.assertRaises(ValueError):patch_qml(changed.encode(),frag)
    def test_clock_source_drift_refused(self):
        with self.assertRaises(ValueError):patch_qml(b'Item {}',b'property double a: 0')

class SplashTests(unittest.TestCase):
    def test_repeat_and_literal(self):
        raw=bytes([130])+b'abcd'+bytes([2])+b'12345678'+b'\0'
        pixels,used=decode_rle(raw,4,1)
        self.assertEqual(pixels,b'abcdabcd12345678');self.assertEqual(used,len(raw))
    def test_roundtrip_runs(self):
        pixels=b'rgba'*300+b'abcd'+b'1234'*20
        encoded=encode_rle(pixels);self.assertEqual(decode_rle(encoded,321,1)[0],pixels)
    def test_truncated_literal(self):
        with self.assertRaises(ValueError):decode_rle(b'\x02abc',2,1)
    def test_truncated_repeat(self):
        with self.assertRaises(ValueError):decode_rle(b'\x82abc',2,1)
    def test_early_terminators(self):
        for data in [b'\x00',b'\x80']:
            with self.assertRaises(ValueError):decode_rle(data,1,1)
    def test_expansion_overflow(self):
        with self.assertRaises(ValueError):decode_rle(b'\x82abcd\0',1,1)
    def test_missing_terminator(self):
        with self.assertRaises(ValueError):decode_rle(b'\x81abcd',1,1)
    def test_invalid_dimensions_and_channels(self):
        for args in [(0,1,4),(2049,1,4),(1,1,5),(True,1,4)]:
            with self.assertRaises(ValueError):decode_rle(b'\0',*args)


class SplashBuilderTests(unittest.TestCase):
    def test_builder_rejects_unknown_executable(self):
        from build_psplash_review import build
        with self.assertRaises(ValueError):build(b'not pinned',b'', 'research-private/unused')
    def test_literal_span_roundtrip(self):
        pixels=b''.join(bytes([x,x^13,x^73,255]) for x in range(200))
        encoded=encode_rle(pixels)
        self.assertEqual(decode_rle(encoded,200,1)[0],pixels)
        self.assertLess(len(encoded),len(pixels)+4)
    def test_slice_only_builder_and_no_overwrite(self):
        from unittest.mock import patch
        import build_psplash_review as b
        pixels=b'\0\0\0\xff'*(1280*720);capacity=40000;binary=b'PREFIX0123456789'+b'X'*capacity+b'SUFFIX'
        class E:
            segments=[(0x10000,0,len(binary))]
        source={'rle_pointer':'0x10010','rle_bytes_including_terminator':capacity}
        with tempfile.TemporaryDirectory() as t,patch.object(b,'inspect',return_value=(None,source)),patch.object(b,'Elf32',return_value=E()):
            dest=Path(t)/'research-private/review';result=b.build(binary,pixels,dest)
            output=(dest/'psplash-default-root-review').read_bytes()
            self.assertEqual(output[:16],binary[:16]);self.assertEqual(output[-6:],b'SUFFIX');self.assertEqual(len(output),len(binary))
            self.assertTrue(result['all_pixels_roundtrip_verified'])
            with self.assertRaises(FileExistsError):b.build(binary,pixels,dest)
    def test_capacity_failure_creates_no_candidate(self):
        from unittest.mock import patch
        import build_psplash_review as b
        pixels=b'\0\0\0\xff'*(1280*720)
        with tempfile.TemporaryDirectory() as t,patch.object(b,'inspect',return_value=(None,{'rle_bytes_including_terminator':3})):
            dest=Path(t)/'research-private/review'
            with self.assertRaises(ValueError):b.build(b'synthetic',pixels,dest)
            self.assertFalse(dest.exists())

class SvgReviewTests(unittest.TestCase):
    def source(self):return (Path(__file__).resolve().parents[1]/'owner-ui/native/root-mark.svg').read_bytes()
    def test_authored_svg(self):
        from build_native_display_review import validate_svg
        self.assertTrue(validate_svg(self.source()))
    def test_external_reference_with_spacing(self):
        from build_native_display_review import validate_svg
        for fragment in [b'<image href = "file:///private/secret"/>',b'<use href="https://invalid.example/a"/>',b'<g onclick="x()"/>',b'<path fill="url(file:///private/a)"/>']:
            with self.assertRaises(ValueError):validate_svg(self.source().replace(b'</svg>',fragment+b'</svg>'))
    def test_entity_and_wrong_canvas(self):
        from build_native_display_review import validate_svg
        for data in [b'<!DOCTYPE svg>'+self.source(),self.source().replace(b'width="1280"',b'width="4096"',1)]:
            with self.assertRaises(ValueError):validate_svg(data)

if __name__=='__main__':unittest.main()
