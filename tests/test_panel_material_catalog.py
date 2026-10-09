"""Synthetic catalog eligibility is separate from resin compatibility."""
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'owner-maintenance'))
from material_catalog import allowed_materials

class CatalogTests(unittest.TestCase):
    def catalog(self):
        return {'schemaVersion':1,'materials':[{'code':'FLGPCL','machines':[],
          'versions':[{'version':4,'isPublic':True,'machines':{'include':[{'MachineTypeId':'DGJR-1-0'}]}}]}]}
    def run_catalog(self,value):return allowed_materials(json.dumps(value).encode())
    def test_explicit_public_form3_entry(self):self.assertEqual(self.run_catalog(self.catalog()),['FLGPCL04'])
    def test_private_and_other_family_excluded(self):
        for field,value in [('isPublic',False),('machines',{'include':[{'MachineTypeId':'OTHER'}]})]:
            obj=self.catalog();obj['materials'][0]['versions'][0][field]=value
            self.assertEqual(self.run_catalog(obj),[])
    def test_ambiguous_or_excessive_input_rejected(self):
        obj=self.catalog();obj['materials']*=2
        with self.assertRaises(ValueError):self.run_catalog(obj)
        with self.assertRaises(ValueError):allowed_materials(b' '*(2**21+1))
        with self.assertRaises(ValueError):allowed_materials(b'{"schemaVersion":1,"schemaVersion":1}')
    def test_unknown_rule_not_permission(self):
        obj=self.catalog();obj['materials'][0]['versions'][0]['machines']['exclude']=[]
        self.assertEqual(self.run_catalog(obj),[])
    def test_unknown_schema_rejected(self):
        obj=self.catalog();obj['schemaVersion']=2
        with self.assertRaises(ValueError):self.run_catalog(obj)
