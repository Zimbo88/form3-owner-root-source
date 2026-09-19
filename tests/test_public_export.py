"""Synthetic temporary Git repositories only; no credentials/network/evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import export_public_source as public


class PublicExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'VERSION').write_text('0.0.0-review\n')
        (self.repo / 'guide.txt').write_text('Authored synthetic guide.\n')
        (self.repo / 'unreviewed.txt').write_text('Must never appear in export.\n')
        self.rows = [self.row('VERSION'), self.row('guide.txt', 'README.md')]
        self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo)] + list(args), stderr=subprocess.PIPE, timeout=20)

    def row(self, name, dest=None):
        return {'source': name, 'destination': dest or name, 'sha256': hashlib.sha256((self.repo/name).read_bytes()).hexdigest(),
                'category': 'guide', 'license': 'MIT (synthetic)', 'provenance': 'Authored synthetic fixture; no recovered content.'}

    def commit(self):
        path = self.repo / public.POLICY
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'schema': 1, 'entries': self.rows}))
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic review', '--allow-empty')

    def output(self, name='out'):
        return self.base / name

    def test_only_explicit_files_and_generated_metadata(self):
        r = public.export(self.output(), self.repo)
        names = {x['path'] for x in r['files']}
        self.assertEqual(names, {'VERSION', 'README.md', public.POLICY, 'PUBLICATION.json', 'SOURCE_SHA256SUMS'})
        self.assertEqual(r['excluded_tracked_file_count'], 1)
        self.assertFalse(r['history_included'])
        self.assertFalse(r['legal_clearance'])
        self.assertNotIn('unreviewed.txt', (self.output()/'manifest.json').read_text())

    def test_exact_input_pin_required_even_after_commit(self):
        (self.repo/'guide.txt').write_text('Changed without approval.\n')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            public.export(self.output(), self.repo)
        self.assertFalse(self.output().exists())

    def test_uncommitted_or_untracked_work_refused(self):
        (self.repo/'new.txt').write_text('local work')
        with self.assertRaises(ValueError): public.export(self.output(), self.repo)
        self.assertFalse(self.output().exists())

    def test_output_is_non_overwriting_and_deterministic(self):
        first = public.export(self.output(), self.repo)
        second = public.export(self.output('second'), self.repo)
        self.assertEqual(first['sha256'], second['sha256'])
        with self.assertRaises(FileExistsError): public.export(self.output(), self.repo)

    def test_exported_selection_is_self_contained_for_next_review(self):
        public.export(self.output(), self.repo)
        source = self.output()/'source'
        args = ['git', '-C', str(source)]
        for command in (['init','-q'], ['add','.'], ['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Clean exported source']):
            subprocess.run(args+command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        result = public.export(self.output('again'), source)
        self.assertEqual((self.output('again')/'source/README.md').read_text(), 'Authored synthetic guide.\n')
        self.assertEqual(result['version'], '0.0.0-review')

    def test_path_escape_glob_duplicates_parent_collision(self):
        for value in ('../escape', '/absolute', 'a//b', 'tools/*.py', 'a/./b', 'research-private/no', '.git/config', 'original/evidence'):
            with self.subTest(value=value):
                row = dict(self.rows[0], destination=value)
                with self.assertRaises(ValueError): public.policy_entries(public.encoded({'schema':1,'entries':[row]}))
        cases = [self.rows+[self.rows[0]], [dict(self.rows[0], destination='file'), dict(self.rows[1], destination='file/child')],
                 [dict(self.rows[0], destination='NAME'), dict(self.rows[1], destination='name')]]
        for rows in cases:
            with self.assertRaises(ValueError): public.policy_entries(public.encoded({'schema':1,'entries':rows}))

    def test_truncated_unknown_duplicate_and_missing_review_fields(self):
        for raw in (b'{', b'[]', b'{"schema":1,"schema":1,"entries":[]}', b'{"schema":2,"entries":[]}', public.encoded({'schema':1,'entries':[]})):
            with self.assertRaises(ValueError): public.policy_entries(raw)
        for field in ('provenance', 'license', 'sha256', 'category'):
            row = dict(self.rows[0]); row[field] = ''
            with self.assertRaises(ValueError): public.policy_entries(public.encoded({'schema':1,'entries':[row]}))

    def test_symlink_input_and_output_refused(self):
        (self.repo/'guide.txt').unlink()
        (self.repo/'guide.txt').symlink_to('VERSION')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'regular'): public.export(self.output(), self.repo)
        (self.base/'linked').symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(ValueError): public.new_directory(self.base/'linked/output')

    def test_magic_or_secret_rejected_despite_review_pin(self):
        for data in (b'\x7fELFsynthetic', b'-----BEGIN PRIVATE KEY-----\n'+b'A'*80+b'\n'):
            (self.repo/'guide.txt').write_bytes(data)
            self.rows[1] = self.row('guide.txt', 'README.md')
            self.commit()
            with self.assertRaises(ValueError): public.export(self.output(), self.repo)
        self.assertFalse(self.output().exists())

    def test_expansion_bound_before_output(self):
        with mock.patch.object(public, 'MAX_TOTAL', 1):
            with self.assertRaises(ValueError): public.export(self.output(), self.repo)
        self.assertFalse(self.output().exists())

    def test_missing_selected_file_does_not_fall_back_to_directory(self):
        (self.repo/'guide.txt').unlink()
        self.commit()
        with self.assertRaisesRegex(ValueError, 'missing'): public.export(self.output(), self.repo)

    def test_archived_modes_no_links_and_fixed_timestamps(self):
        import tarfile
        report = public.export(self.output(), self.repo)
        with tarfile.open(self.output()/report['archive']) as archive:
            for member in archive:
                self.assertTrue(member.isfile())
                self.assertEqual(member.mtime, 0)
                self.assertIn(member.mode, (0o644, 0o755))
                self.assertTrue(member.name.startswith('source/'))
        self.assertFalse(any(p.name == '.git' for p in (self.output()/'source').rglob('*')))
