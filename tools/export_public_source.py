#!/usr/bin/env python3
"""Export only individually reviewed, hash-pinned Git files to a NEW source review.

No network, signing, Git history copying, firmware input, hardware or publication.
The allowlist is a maintainer review record, not legal clearance or authorization.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile

from evidence_lib import ROOT
from package_developer_source import validate_member, runtime_checksums

POLICY = 'publication/allowlist.json'
MAX_POLICY = 2 << 20
MAX_FILES = 600
MAX_FILE = 25 << 20
MAX_TOTAL = 64 << 20
CATEGORIES = {'authored-code', 'synthetic-test', 'guide', 'original-artwork',
              'compatibility-checksums', 'dependency-recipe', 'notice'}
RESERVED = {POLICY, 'PUBLICATION.json', 'SOURCE_SHA256SUMS'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(obj):
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def path_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.+/-]+', value):
        raise ValueError('Invalid publication path')
    parts = value.split('/')
    if len(value) > 200 or any(p in ('', '.', '..', '.git', 'research-private', 'build', 'original') for p in parts):
        raise ValueError('Forbidden publication path')
    return value


def policy_entries(raw):
    if len(raw) > MAX_POLICY:
        raise ValueError('Publication policy too large')
    obj = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(obj, dict) or set(obj) != {'schema', 'entries'} or type(obj['schema']) is not int or obj['schema'] != 1:
        raise ValueError('Unknown publication schema')
    rows = obj['entries']
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
        raise ValueError('Publication entry bound')
    sources, targets = set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'source', 'destination', 'sha256', 'category', 'license', 'provenance'}:
            raise ValueError('Malformed publication entry')
        source, target = path_name(row['source']), path_name(row['destination'])
        if source in sources or target.casefold() in targets or target.casefold() in {p.casefold() for p in RESERVED}:
            raise ValueError('Duplicate/reserved publication path')
        if not isinstance(row['category'], str) or row['category'] not in CATEGORIES or not isinstance(row['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', row['sha256']):
            raise ValueError('Invalid category/hash')
        for key in ('license', 'provenance'):
            if not isinstance(row[key], str) or not 4 <= len(row[key]) <= 600 or any(ord(c) < 32 for c in row[key]):
                raise ValueError('Missing/bad rights or provenance review')
        sources.add(source)
        targets.add(target.casefold())
    # Reject parent/file collisions before creating anything, including on Windows/macOS.
    for target in targets | {p.casefold() for p in RESERVED}:
        if any(str(parent) in targets for parent in PurePosixPath(target).parents if str(parent) != '.'):
            raise ValueError('Publication directory/file collision')
    return sorted(rows, key=lambda r: r['destination'])


def new_directory(path):
    p = Path(os.path.abspath(path))
    if any(part in ('original', '.git') for part in p.parts) or str(p).startswith(('/dev/', '/proc/', '/sys/')):
        raise ValueError('Evidence/system output forbidden')
    for item in (p,) + tuple(p.parents):
        if item.is_symlink():
            raise ValueError('Output symlink forbidden')
    if p.exists():
        raise FileExistsError('Publication output must be new')
    return p


def export(output, repo=ROOT):
    repo = Path(repo).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo)] + list(args), stderr=subprocess.PIPE, timeout=30)
    def unchanged(commit=None):
        if git('status', '--porcelain', '--untracked-files=normal').strip():
            raise ValueError('Commit reviewed changes first; source tree must be clean')
        if commit and git('rev-parse', 'HEAD').decode().strip() != commit:
            raise ValueError('Source commit changed during export; output is not approved')
    unchanged()
    commit = git('rev-parse', 'HEAD').decode().strip()
    tree = {}
    for line in git('ls-tree', '-rz', commit).split(b'\0'):
        if not line:
            continue
        meta, name = line.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        tree[name.decode()] = (mode, kind, blob)
    def read(name, limit=MAX_FILE):
        if name not in tree:
            raise ValueError('Allowlisted source missing: ' + name)
        mode, kind, blob = tree[name]
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('Only regular committed files: ' + name)
        if int(git('cat-file', '-s', blob)) > limit:
            raise ValueError('Source file exceeds bound')
        return mode, git('cat-file', 'blob', blob)
    _, policy = read(POLICY, MAX_POLICY)
    validate_member(POLICY, '100644', policy)
    rows = policy_entries(policy)
    members, total = {}, 0
    for row in rows:
        mode, data = read(row['source'])
        if validate_member(row['source'], mode, data) != row['sha256']:
            raise ValueError('Review hash mismatch: ' + row['source'])
        validate_member(row['destination'], mode, data)
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError('Total source bound exceeded')
        members[row['destination']] = (mode, data)
    if 'VERSION' not in members:
        raise ValueError('VERSION must be explicitly selected')
    version = members['VERSION'][1].decode().strip()
    if not re.fullmatch(r'[0-9a-z.-]+', version):
        raise ValueError('Invalid version')
    # The exported tree can be reviewed/committed and exported again without private paths.
    normalized = [dict(row, source=row['destination']) for row in rows]
    members[POLICY] = ('100644', encoded({'schema': 1, 'entries': normalized}))
    runtime = 'checksums/rescue-runtime-files.json'
    if runtime in members:
        if 'RESCUE_RUNTIME_SHA256SUMS' in members:
            raise ValueError('Generated checksum path collision')
        members['RESCUE_RUNTIME_SHA256SUMS'] = ('100644', runtime_checksums(members[runtime][1]))
    provenance = {'schema': 1, 'kind': 'UNSIGNED SOURCE REVIEW; not an installation package',
                  'version': version, 'producer_commit': commit, 'producer_allowlist_sha256': digest(policy),
                  'reviewed_files': rows, 'excluded_tracked_file_count': len(tree) - len(rows) - 1,
                  'history_included': False, 'legal_clearance': False, 'hardware_contact': False}
    members['PUBLICATION.json'] = ('100644', encoded(provenance))
    sums = ''.join(digest(data) + '  ' + name + '\n' for name, (_, data) in sorted(members.items())).encode()
    members['SOURCE_SHA256SUMS'] = ('100644', sums)
    if sum(len(data) for _, data in members.values()) > MAX_TOTAL:
        raise ValueError('Source plus metadata bound exceeded')
    unchanged(commit)
    out = new_directory(output)
    out.mkdir(parents=True, mode=0o700)
    source = out / 'source'
    source.mkdir(mode=0o700)
    archive = out / ('form3-owner-source-' + version + '.tar.gz')
    with archive.open('xb') as stream, gzip.GzipFile(fileobj=stream, filename='', mode='wb', mtime=0) as zipped, tarfile.open(fileobj=zipped, mode='w|', format=tarfile.PAX_FORMAT) as tar:
        for name, (mode, data) in sorted(members.items()):
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with dest.open('xb') as f:
                f.write(data)
            dest.chmod(int(mode[-3:], 8))
            info = tarfile.TarInfo('source/' + name)
            info.size, info.mode, info.mtime = len(data), int(mode[-3:], 8), 0
            tar.addfile(info, io.BytesIO(data))
    report = {key: value for key, value in provenance.items() if key != 'reviewed_files'}
    report.update(git_commit=commit, archive=archive.name, bytes=archive.stat().st_size,
                  sha256=digest(archive.read_bytes()), files=[{'path': n, 'bytes': len(d), 'sha256': digest(d), 'mode': m} for n, (m, d) in sorted(members.items())])
    (out / 'manifest.json').write_bytes(encoded(report))
    (out / 'SHA256SUMS').write_text(report['sha256'] + '  ' + archive.name + '\n' + digest((out/'manifest.json').read_bytes()) + '  manifest.json\n')
    unchanged(commit)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, help='New local review directory; never published automatically')
    args = p.parse_args()
    os.umask(0o077)
    result = export(args.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
