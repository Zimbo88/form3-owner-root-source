#!/usr/bin/env python3
"""Redact sensitive path components or audit staged Git content before a commit.

This conservative audit is a guard, not a guarantee. Inspect git diff --cached too.
"""
import argparse
import hashlib
import json
from pathlib import PurePosixPath
import re
import subprocess
from evidence_lib import safe_output

def private_path(path):
    parts=PurePosixPath(path).parts
    if len(parts)<=2:return path
    if parts[1] in ['jobs','prints','Cartridges','Tanks','JarvikTags','Pumps','printernet_client','upload-logs']:
        return '/'+parts[1]+'/'+'/'.join('item-'+hashlib.sha256(p.encode()).hexdigest()[:16] for p in parts[2:])
    return re.sub(r'(?i)(?:ethernet|wifi)_[0-9a-f_]+',lambda m:'interface-'+hashlib.sha256(m.group().encode()).hexdigest()[:16],path)

def audit_bytes(name,data):
    reasons=[]
    if len(data)>25<<20:reasons.append('oversized file')
    if re.search(r'(^|/)(research-private|vendor|analysis-work|\.cache|build)/',name):reasons.append('private/binary workspace path')
    if re.search(r'\.(?:img|bin|gpg|kbx|p12|pfx|formware2?|formlogs|pem|key|gz|xz|zip|tar|rcc|dtb|dtbo|cpio|itb|raw|rgba|rle|db|sqlite3?|so|o|a)$',name,re.I):reasons.append('binary/key/archive extension requires exclusion')
    if data.startswith((b'\x7fELF',b'MZ',b'\x1f\x8b',b'qres',b'\xd0\x0d\xfe\xed',b'PK\x03\x04',b'\xfd7zXZ\x00',b'!<arch>\n')):reasons.append('executable/compressed/resource binary')
    if re.search(rb'(?m)^GIT binary patch\r?$',data) or data.startswith((b'BSDIFF40',b'\xd6\xc3\xc4')):
        reasons.append('binary delta may redistribute vendor bytes; use authored source transformations')
    if re.search(rb'-----BEGIN (?:[A-Z ]*PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----\s+[A-Za-z0-9+/=\r\n]{40,}',data):reasons.append('private key material')
    if re.search(rb'(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])',data):reasons.append('AWS access key ID')
    if re.search(rb'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}',data):reasons.append('JWT token')
    if re.search(rb'\$(?:1|5|6|y)\$[A-Za-z0-9./]{1,32}\$[A-Za-z0-9./]{16,}',data):reasons.append('password hash')
    return reasons

def audit_known_values(data,values):
    """Match a caller-supplied private dictionary; return fingerprints only.

    Values must stay local and must not be supplied on a shell command line.
    This complements format patterns for opaque device/service credentials.
    """
    found=[]
    for value in values:
        value=value.encode() if isinstance(value,str) else value
        if len(value)>=8 and value in data:
            found.append(hashlib.sha256(value).hexdigest())
    return sorted(set(found))

def staged_audit(repo):
    names=subprocess.check_output(['git','-C',repo,'diff','--cached','--name-only','--diff-filter=ACMR','-z']).decode().split('\0')
    violations=[]
    for name in filter(None,names):
        data=subprocess.check_output(['git','-C',repo,'show',':'+name])
        reasons=audit_bytes(name,data)
        if reasons:violations.append(dict(path=name,reasons=reasons))
    return dict(checked_files=len([n for n in names if n]),violations=violations,passed=not violations)

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('staged');a.add_argument('--repo',default='.')
    b=sub.add_parser('inventory');b.add_argument('source');b.add_argument('--output',required=True);b.add_argument('--private-paths',action='store_true')
    args=p.parse_args()
    if args.command=='staged':
        result=staged_audit(args.repo);print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
    with open(args.source) as src,safe_output(args.output).open('x') as out:
        for line in src:
            row=json.loads(line)
            if args.private_paths:
                row['path']=private_path(row['path'])
                if 'target' in row:row['target']=private_path(row['target'])
            out.write(json.dumps(row,sort_keys=True)+'\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
