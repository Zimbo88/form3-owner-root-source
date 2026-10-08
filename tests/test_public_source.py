"""Public standard-library regression fixtures; no network, sudo or hardware."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import check_public_source as check
import render_public_figures as figures


class Markdown(unittest.TestCase):
    def test_github_heading_punctuation_unicode_and_duplicates(self):
        text='# Hello, `root`!\n\n## Über / SSH :2222\n## Hello root\n## Hello root-1\n## Hello root\n'
        self.assertEqual(check.anchors(text),{'hello-root','über--ssh-2222','hello-root-1','hello-root-1-1','hello-root-2'})

    def test_fenced_heading_ignored_and_setext_html_anchor(self):
        self.assertEqual(check.anchors('```md\n# False\n```\nActual\n===\n<a id="explicit"></a>'),{'actual','explicit'})

    def test_multiple_headings_do_not_consume_next_line(self):
        self.assertEqual(check.anchors('# First\n\n## Next\n'),{'first','next'})

    def test_links_balanced_parentheses_spaces_reference_html(self):
        text='[one](a(b).md#ok) [two](<with space.md#part>)\n[x]: ref.md#end\n<a href="z.md#one">Z</a>'
        self.assertEqual(list(check.links(text)),['a(b).md#ok','with space.md#part','ref.md#end','z.md#one'])

    def test_links_inside_fences_not_executed_or_checked(self):
        self.assertEqual(list(check.links('~~~md\n[x](missing)\n~~~\n[x](real)')),['real'])

    def test_current_version_across_line_wrap(self):
        self.assertEqual(check.version_issues('The current source is\n**0.5.9-review**.','0.5.13-review'),[1])

    def test_historical_versions_preserved(self):
        text='Historical 0.5.9-review passed.\nThe current source is **0.5.13-review**.\n```sh\n# current source 0.1.0-review\n```'
        self.assertEqual(check.version_issues(text,'0.5.13-review'),[])

    def test_stale_title_detected(self):
        self.assertEqual(check.version_issues('# Lifecycle — 0.5.9-review source','0.5.13-review'),[1])

    def test_sequence_message_semicolon_regression(self):
        source = 'sequenceDiagram\n    T->>T: stop writer; file → B → A; readback\n'
        self.assertEqual(check.mermaid_message_issues(source), [2])

    def test_sequence_message_entities_and_breaks(self):
        source = 'sequenceDiagram\n    T->>T: stop writer#59; file → B → A<br/>readback\n    T-->>R: result #amp; receipt\n'
        self.assertEqual(check.mermaid_message_issues(source), [])

    def test_flowchart_semicolons_are_not_sequence_messages(self):
        self.assertEqual(check.mermaid_message_issues('flowchart TD\nA[Merge; keep counter] --> B[Done]\n'), [])

    def test_svg_local_fragment_allowed_external_refused(self):
        self.assertFalse(check.external_svg_url('url( "#gradient" )'))
        self.assertTrue(check.external_svg_url('url(https://example.invalid/x)'))
        self.assertTrue(check.external_svg_url('url(data:image/svg+xml,x)'))


class SourceReview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'VERSION').write_text('0.5.13-review\n')
        (self.root/'README.md').write_text('# Start\n\n[go](guide.md#next)\n')
        (self.root/'guide.md').write_text('# Next\n')

    def review(self):return check.review(self.root,editing=True)

    def test_inline_and_standalone_sequence_delimiters_checked(self):
        source = 'sequenceDiagram\nA->>B: update; readback\n'
        (self.root/'README.md').write_text('# Diagram\n\n```mermaid\n'+source+'```\n')
        (self.root/'flow.mmd').write_text(source)
        errors = self.review()['errors']
        self.assertIn('README.md:5: unescaped Mermaid sequence-message semicolon', errors)
        self.assertIn('flow.mmd:2: unescaped Mermaid sequence-message semicolon', errors)

    def test_fragment_failure_then_success(self):
        self.assertTrue(self.review()['passed'])
        (self.root/'guide.md').write_text('# Changed\n')
        self.assertIn('missing heading',' '.join(self.review()['errors']))

    def test_path_escape_refused(self):
        (self.root/'README.md').write_text('[escape](../)')
        self.assertIn('outside link',' '.join(self.review()['errors']))

    def test_ignored_output_not_a_source_document(self):
        (self.root/'build').mkdir();(self.root/'build/bad.md').write_text('[bad](missing)')
        self.assertTrue(self.review()['passed'])

    def test_shell_is_parsed_never_executed(self):
        sentinel=self.root/'must-not-exist'
        (self.root/'README.md').write_text('```sh\ntouch "'+str(sentinel)+'"\n```\n')
        self.assertTrue(self.review()['passed']);self.assertFalse(sentinel.exists())
        (self.root/'README.md').write_text('```sh\nif then\n```\n')
        self.assertFalse(self.review()['passed'])

    def test_target_new_python_syntax_refused(self):
        d=self.root/'owner-ui';d.mkdir();(d/'probe.py').write_text('x = f"new syntax"\n')
        self.assertIn('grammar mismatch',' '.join(self.review()['errors']))

    def test_active_svg_and_missing_description_refused(self):
        (self.root/'bad.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>invalid</script></svg>')
        errors=' '.join(self.review()['errors'])
        self.assertIn('missing SVG description',errors);self.assertIn('active/external SVG tag',errors)

    def test_missing_metadata_fails_release_mode(self):
        result=check.review(self.root)
        self.assertFalse(result['passed']);self.assertTrue(result['release_check'])
        self.assertFalse(self.review()['release_check'])

    def test_markdown_error_does_not_skip_metadata(self):
        (self.root/'README.md').write_text('[missing](no.md)')
        with patch.object(check,'metadata',return_value=['fixture metadata failure']) as m:
            result=check.review(self.root);m.assert_called_once()
        self.assertIn('fixture metadata failure',result['errors'])

    def test_mermaid_retains_edge_labels_and_dashes(self):
        source='graph [rankdir=TB];\na [label="One"];\nb [label="Two"];\na -> b [label="candidate",style=dashed];\n'
        self.assertIn('a -.-> |"candidate"| b',figures.mermaid(source))
        with self.assertRaises(ValueError):figures.mermaid('rankdir=TB\na -> b;')


class PublicationMetadata(unittest.TestCase):
    def setUp(self):
        import export_public_source as export
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name);repo=base/'input';repo.mkdir()
        (repo/'VERSION').write_text('0.5.13-review\n');(repo/'README.md').write_text('# Synthetic fixture\n')
        (repo/'checksums').mkdir()
        (repo/'checksums/rescue-runtime-files.json').write_text(json.dumps({'files':[{'path':'usr/lib/synthetic','bytes':0,'sha256':'0'*64}]}))
        rows=[]
        for name in ('VERSION','README.md','checksums/rescue-runtime-files.json'):
            rows.append({'source':name,'destination':name,'sha256':export.digest((repo/name).read_bytes()),'category':'synthetic-test','license':'MIT synthetic fixture','provenance':'Authored synthetic test; no device data.'})
        (repo/'publication').mkdir();(repo/'publication/allowlist.json').write_bytes(export.encoded({'schema':1,'entries':rows}))
        for args in (['init','-q'],['add','.'],['-c','user.name=Synthetic Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Synthetic review']):
            subprocess.run(['git','-C',str(repo)]+args,check=True,capture_output=True,timeout=10)
        export.export(base/'output',repo);self.root=base/'output/source'

    def test_official_export_matches_all_metadata(self):
        self.assertEqual(check.metadata(self.root),[])

    def test_changed_selected_bytes_are_rejected(self):
        (self.root/'README.md').write_text('# Changed without export\n')
        self.assertIn('Source checksum mismatch: README.md',check.metadata(self.root))

    def test_unselected_file_is_rejected(self):
        (self.root/'unexpected.txt').write_text('not reviewed')
        self.assertTrue(any('Unselected' in x for x in check.metadata(self.root)))

    def test_duplicate_checksum_entry_is_rejected(self):
        p=self.root/'SOURCE_SHA256SUMS';p.write_text(p.read_text()+p.read_text().splitlines()[0]+'\n')
        with self.assertRaises(ValueError):check.metadata(self.root)

    def test_wrong_publication_version_is_rejected(self):
        p=self.root/'PUBLICATION.json';o=json.loads(p.read_text());o['version']='0.0.0-review';p.write_text(json.dumps(o))
        self.assertIn('Publication review/version mismatch',check.metadata(self.root))

if __name__=='__main__':unittest.main()
