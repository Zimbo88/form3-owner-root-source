import sys,unittest,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_signature_brand import elements,native,panel,NS
from native_display_transaction import PROFILES,SPLASH,RCC,SIGNATURE_SHA,OWNER_ROOT_SHA,Transaction

class SignatureBrand(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.data=(self.root/'owner-ui/native/signature-mark.svg').read_bytes()
    def test_shared_geometry_and_native_scale_are_exact(self):
        data=native(self.data);r=ET.fromstring(data)
        self.assertEqual(r.get('viewBox'),'0 0 1280 720')
        self.assertEqual(r.find('{'+NS+'}g').get('transform'),'translate(289 269) scale(1.3)')
        self.assertEqual((self.root/'owner-ui/native/root-mark.svg').read_text(),data)
        self.assertIn(panel(self.data),(self.root/'owner-ui/static/index.html').read_text())
    def test_active_external_and_malformed_artwork_rejected(self):
        for fragment in (b'<script/>',b'<image href="https://invalid.example/image"/>',b'<path d="M0 0" onclick="bad()"/>'):
            with self.assertRaises(ValueError):elements(self.data.replace(b'</svg>',fragment+b'</svg>'))
        with self.assertRaises(ValueError):elements(b'<!DOCTYPE svg>'+self.data)
        with self.assertRaises(ValueError):elements(self.data.replace(b'0 0 540 140',b'0 0 9999 9999'))
    def test_colour_and_components_are_reviewed(self):
        with self.assertRaises(ValueError):elements(self.data.replace(b'#e58b38',b'#ffffff'))
        self.assertEqual(len(elements(self.data)),4)
        self.assertFalse(any(x.tag.endswith('text') for x in ET.fromstring(self.data).iter()))
    def test_owner_logo_profiles_preserve_clock_and_require_known_original(self):
        for name,before in [('owner-root-splash',SIGNATURE_SHA),('owner-root-splash-factory',PROFILES['initial-utc'][SPLASH][0])]:
            p=PROFILES[name];self.assertEqual(set(p),{SPLASH})
            self.assertEqual(p[SPLASH][:2],(before,OWNER_ROOT_SHA))
        self.assertNotIn(b'M1 15 L1 28 L43 90',self.data)
        self.assertIn(b'Original open-terminal',self.data)

    def test_splash_update_cannot_touch_native_clock(self):
        p=PROFILES['signature-splash'];self.assertEqual(set(p),{SPLASH});self.assertNotIn(RCC,p)
        self.assertEqual(p[SPLASH][1],SIGNATURE_SHA)
        t=object.__new__(Transaction);t.pins=p
        self.assertEqual(t.operation(),'native-display-splash')

if __name__=='__main__':unittest.main()
