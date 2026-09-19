"""Authored wording fixtures; no personal observation is inferred by this check."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from developer_check import narrative_issues

class DocumentationVoice(unittest.TestCase):
    def test_first_person_and_impersonal_evidence(self):
        self.assertEqual(narrative_issues('I started this project to repair my printer.\nThe automated fixture passed.\nThe owner service remains unprivileged.'), [])
    def test_third_person_self_narrative_is_flagged(self):
        self.assertEqual(narrative_issues('Mathias started this work.\nThe owner reported a display observation.\nIn his account, repair was unavailable.'), [1,2,3])
    def test_copyright_and_third_party_credit_remain(self):
        self.assertEqual(narrative_issues('Copyright 2026 Mathias Zimmermann\nI thank Łukasz Jakóbiec for the articles.\nThe author describes a different Form 3+ fault.'), [])
