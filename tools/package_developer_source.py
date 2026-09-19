#!/usr/bin/env python3
"""Package the hash-pinned publication allowlist from one clean Git commit.

Reads committed blobs, refuses uncommitted tracked/staged source and forbidden material.
Never follows worktree symlinks or copies ignored/private output. Output must be new.
"""
import argparse,hashlib,json,re
from pathlib import Path,PurePosixPath
from evidence_lib import ROOT
from sanitize_report import audit_bytes

MAX_FILE=25<<20
MAX_TOTAL=128<<20

def validate_member(name,mode,data):
    parts=PurePosixPath(name).parts
    if not parts or name.startswith('/') or any(p in ('..','.git','research-private','build') for p in parts):
        raise ValueError('Forbidden source path')
    if mode not in ('100644','100755'):raise ValueError('Only committed regular source files are allowed')
    reasons=audit_bytes(name,data)
    if reasons:raise ValueError('Source material audit refused '+name+': '+', '.join(reasons))
    return hashlib.sha256(data).hexdigest()

def runtime_checksums(raw):
    if len(raw)>2<<20:raise ValueError('Runtime inventory too large')
    obj=json.loads(raw);rows=obj.get('files')
    if not isinstance(rows,list) or not 1<=len(rows)<=5000:raise ValueError('Runtime inventory count')
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Malformed runtime entry')
        name=row.get('path');sha=row.get('sha256');size=row.get('bytes')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_./+@-]+',name):raise ValueError('Unsafe runtime path')
        parts=PurePosixPath(name).parts
        if name.startswith('/') or '..' in parts or name in seen or not name.startswith(('lib/','usr/lib/','usr/bin/')):
            raise ValueError('Unexpected/duplicate runtime path')
        if not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{64}',sha) or type(size) is not int or size<0:
            raise ValueError('Invalid runtime hash/size')
        seen.add(name);result.append((name,sha))
    return ''.join(sha+'  '+name+'\n' for name,sha in sorted(result)).encode('ascii')

def package(output,repo=ROOT):
    """Compatibility entry; only the explicit public review allowlist is exported."""
    from export_public_source import export
    return export(output, repo)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    r=package(a.output);print(json.dumps({k:v for k,v in r.items() if k!='files'},indent=2))
if __name__=='__main__':main()
