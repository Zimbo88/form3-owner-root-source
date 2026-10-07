#!/usr/bin/env python3
"""Offline public-source review. No hardware, network, sudo or vendor input.

Checks the Markdown subset used here: ATX/setext headings, inline/reference links,
explicit HTML anchors, fenced shell blocks. It is not a general GitHub renderer.
Generated publication metadata is required by default; --editing reports its
intentional omission and is never a release/CI success receipt.
"""
from python35_grammar import parse as parse_target
import argparse
import ast
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', 'build', 'research-private', '.venv', '__pycache__', '.cache'}
RESERVED = {'PUBLICATION.json', 'SOURCE_SHA256SUMS', 'publication/allowlist.json',
            'RESCUE_RUNTIME_SHA256SUMS'}


def files(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and
                  not any(x in EXCLUDED for x in p.relative_to(root).parts))


def prose(text):
    """Remove complete fenced blocks without exposing their examples as links."""
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if match:
            mark = match[1]
            if fence is None:
                fence = (mark[0], len(mark))
            elif mark[0] == fence[0] and len(mark) >= fence[1] and not match[2].strip():
                fence = None
            lines.append('')
        else:
            lines.append(line if fence is None else '')
    return '\n'.join(lines)


def slug(text):
    # Heading markup contributes rendered text, not formatting delimiters/URLs.
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]*>', '', text)
    text = html.unescape(text).lower().replace('`', '')
    return ''.join(c for c in text if c in '-_' or
                   unicodedata.category(c)[0] not in 'PS').replace(' ', '-')


def anchors(text):
    text = prose(text)
    used = set()
    for match in re.finditer(r'^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$|^([^\n]+)\n {0,3}(?:=+|-+)[ \t]*$', text, re.M):
        stem = slug(match[1] or match[2]); candidate = stem; number = 0
        while candidate in used:
            number += 1; candidate = stem + '-' + str(number)
        used.add(candidate)
    used.update(html.unescape(m[1]) for m in re.finditer(r'<(?:a|h[1-6])\b[^>]*(?:id|name)=["\']([^"\']+)', text, re.I))
    return used


def links(text):
    text = prose(text)
    # Angle destinations and balanced parentheses are supported; titles omitted.
    for m in re.finditer(r'!?\[[^\]\n]*\]\(', text):
        pos = m.end()
        if text[pos:pos+1] == '<':
            end = text.find('>', pos)
            if end != -1:
                yield text[pos+1:end]
            continue
        depth = 0; result = []
        while pos < len(text):
            c = text[pos]
            if c == ')' and depth == 0 or c.isspace():
                break
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            result.append(c); pos += 1
        if result:
            yield ''.join(result)
    # Reference definitions are checked even if currently unused.
    for m in re.finditer(r'^ {0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)', text, re.M):
        yield m[1].strip('<>')
    for m in re.finditer(r'<(?:a|img)\b[^>]*(?:href|src)=["\']([^"\']+)', text, re.I):
        yield html.unescape(m[1])


def version_issues(text, version):
    result = []
    clean = prose(text)
    pattern = r"current (?:repository version|source(?: version)?|release|version)(?: is|:| =)?[ \t\n*`]+(\d+\.\d+\.\d+-review)"
    for m in re.finditer(pattern, clean, re.I):
        if m[1] != version:
            result.append(clean.count('\n', 0, m.start())+1)
    for n,line in enumerate(clean.splitlines(),1):
        if re.match(r'^# .*— .*source',line):
            if any(v != version for v in re.findall(r'\b\d+\.\d+\.\d+-review\b',line)):
                result.append(n)
    return sorted(set(result))


def external_svg_url(value):
    return any(not m[1].strip(' \"\'').startswith('#')
               for m in re.finditer(r'url\(([^)]*)\)', value, re.I))


def metadata(root):
    from export_public_source import policy_entries
    from package_developer_source import runtime_checksums
    from sanitize_report import audit_bytes
    errors = []
    rows = policy_entries((root/'publication/allowlist.json').read_bytes())
    declared = {}
    for line in (root/'SOURCE_SHA256SUMS').read_text().splitlines():
        m = re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.+/-]+)', line)
        if not m or m[2] in declared or '..' in Path(m[2]).parts or Path(m[2]).is_absolute():
            raise ValueError('Malformed/duplicate source checksum entry')
        declared[m[2]] = m[1]
    expected = {r['destination'] for r in rows} | RESERVED
    expected.remove('SOURCE_SHA256SUMS')
    if set(declared) != expected:
        errors.append('SOURCE_SHA256SUMS member set mismatch')
    for name, pin in declared.items():
        p = root/name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != pin:
            errors.append('Source checksum mismatch: '+name)
    for row in rows:
        p = root/row['destination']
        if p.is_symlink() or not p.is_file():
            errors.append('Missing/linked selected file: '+row['destination']); continue
        data = p.read_bytes()
        if row['source'] != row['destination'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            errors.append('Normalized allowlist mismatch: '+row['destination'])
        if audit_bytes(row['destination'], data):
            errors.append('Publication material guard rejected: '+row['destination'])
    pub = json.loads((root/'PUBLICATION.json').read_text())
    normalized = [dict(row, source=row['destination']) for row in pub['reviewed_files']]
    if normalized != rows or pub['version'] != (root/'VERSION').read_text().strip():
        errors.append('Publication review/version mismatch')
    if not re.fullmatch(r'[a-f0-9]{40}', pub['producer_commit']) or pub['legal_clearance'] is not False:
        errors.append('Invalid publication provenance/clearance')
    if (root/'RESCUE_RUNTIME_SHA256SUMS').read_bytes() != runtime_checksums((root/'checksums/rescue-runtime-files.json').read_bytes()):
        errors.append('Generated runtime checksums mismatch')
    actual = {str(p.relative_to(root)) for p in files(root)}
    if actual != expected | {'SOURCE_SHA256SUMS'}:
        errors.append('Unselected/missing tree members: '+', '.join(sorted(actual ^ (expected | {'SOURCE_SHA256SUMS'}))))
    return errors


def review(root, editing=False):
    root = root.resolve(); errors = []; all_files = files(root)
    docs = {p: p.read_text() for p in all_files if p.suffix == '.md'}
    headings = {p: anchors(s) for p, s in docs.items()}
    local = fragments = shell = svg_count = target_count = 0
    embedded = set()
    for p, text in docs.items():
        for target in links(text):
            u = urlsplit(target)
            if u.scheme or target.startswith('//'):
                continue
            dest = (p.parent/unquote(u.path)).resolve() if u.path else p
            local += 1
            if not dest.is_relative_to(root) or not dest.exists():
                errors.append(str(p.relative_to(root))+': missing/outside link '+target)
            elif u.fragment and dest.suffix == '.md':
                fragments += 1
                if unquote(u.fragment) not in headings.get(dest, set()):
                    errors.append(str(p.relative_to(root))+': missing heading '+target)
            if dest.suffix == '.svg':
                embedded.add(dest)
        for n in version_issues(text, (root/'VERSION').read_text().strip()):
            errors.append(str(p.relative_to(root))+':'+str(n)+': current-version drift')
        for block in re.findall(r'```(?:sh|bash|shell)\n(.*?)\n```', text, re.S):
            result = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True, timeout=5)
            shell += 1
            if result.returncode:
                errors.append(str(p.relative_to(root))+': invalid shell block (syntax only)')
        for body in re.findall(r"(?:owner_python|python3) - <<'PY'\n(.*?)\nPY", text, re.S):
            try: ast.parse(body)
            except SyntaxError: errors.append(str(p.relative_to(root))+': invalid Python here-document')
    for p in all_files:
        if p.suffix == '.svg':
            svg_count += 1; data = p.read_bytes()
            if b'<!ENTITY' in data:
                errors.append(str(p.relative_to(root))+': SVG entity forbidden'); continue
            tree = ET.fromstring(data)
            tags = [n.tag.split('}')[-1] for n in tree.iter()]
            if 'desc' not in tags or not any(n.text and n.text.strip() for n in tree.iter() if n.tag.endswith('desc')):
                errors.append(str(p.relative_to(root))+': missing SVG description')
            for n in tree.iter():
                if n.tag.split('}')[-1] in ('script', 'foreignObject', 'image', 'iframe', 'style', 'animate', 'set'):
                    errors.append(str(p.relative_to(root))+': active/external SVG tag')
                for k,v in n.attrib.items():
                    if k.lower().startswith('on') or (k.split('}')[-1]=='href' and not v.startswith('#')) or external_svg_url(v):
                        errors.append(str(p.relative_to(root))+': active/external SVG attribute')
            if p.parent == root/'docs/figures' and p not in embedded:
                errors.append(str(p.relative_to(root))+': unused numbered diagram')
            if p.parent == root/'docs/figures' and float(tree.attrib.get('width','0pt').rstrip('pt')) > 950:
                errors.append(str(p.relative_to(root))+': diagram too wide; wrap labels or stack nodes')
        if p.suffix == '.py' and p.parent.name in ('owner-maintenance','owner-ui'):
            target_count += 1
            try: parse_target(p.read_text())
            except SyntaxError: errors.append(str(p.relative_to(root))+': target grammar mismatch')
        if p.suffix == '.sh' or str(p.relative_to(root)).startswith('rescue/rootfs/') and p.read_bytes().startswith(b'#!/bin/sh') or p.name.endswith('.init'):
            shell += 1
            if subprocess.run(['bash','-n',str(p)],capture_output=True,timeout=5).returncode:
                errors.append(str(p.relative_to(root))+': shell file syntax')
    if not editing:
        try: errors.extend(metadata(root))
        except (ValueError, KeyError, OSError) as exc: errors.append('Metadata check failed: '+str(exc))
    return {'passed':not errors,'release_check':not editing,'errors':errors,'local_links':local,
            'heading_fragments':fragments,'shell_syntax_checks':shell,'svg_files':svg_count,
            'target_python35_grammar_files':target_count,'hardware_contact':False,
            'external_links':'NOT FETCHED; separate non-blocking review',
            'metadata':'NOT RUN (--editing)' if editing else 'checked',
            'runtime_compatibility_proven':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--editing',action='store_true');p.add_argument('--output');a=p.parse_args()
    result=review(ROOT,a.editing)
    if a.output:
        from evidence_lib import safe_output,write_json
        write_json(safe_output(a.output),result)
    print(json.dumps(result,indent=2));raise SystemExit(not result['passed'])


if __name__=='__main__': main()
