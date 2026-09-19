#!/usr/bin/env python3
"""Build/verify an owner-signed source package; never generate signing keys.

Use a separately managed owner RSA signing key. Disposable fixture keys are only
for tests and must never become production authority. No hardware operations.
"""
import argparse,json,os,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'owner-maintenance'))
from package_format import PATHS,build,verify

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['build','verify'])
    p.add_argument('--package',required=True);p.add_argument('--public-key',required=True)
    p.add_argument('--signer-sha256',required=True,help='Independent SHA256 of public PEM, never obtained from package')
    p.add_argument('--signing-key');p.add_argument('--version');p.add_argument('--kind',choices=['install','panel','maintenance'],default='install')
    a=p.parse_args()
    if a.command=='build':
        if not a.signing_key or not a.version:p.error('Build requires explicit signing key and version')
        import hashlib
        if hashlib.sha256(Path(a.public_key).read_bytes()).hexdigest()!=a.signer_sha256:p.error('Public signer pin mismatch')
        with tempfile.TemporaryDirectory(prefix='owner-authored-package-') as source:
            for name in PATHS:
                top,tail=name.split('/',1);src=ROOT/('owner-ui' if top=='panel' and tail!='lan_ipv4.py' else 'owner-maintenance')/tail
                dst=Path(source)/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
            r=build(source,a.version,a.kind,a.signing_key,a.public_key,a.package)
    else:r=verify(a.package,a.public_key,a.signer_sha256)
    if r['signer_sha256']!=a.signer_sha256:raise ValueError('Signer changed during package build')
    print(json.dumps({k:v for k,v in r.items() if k not in ('blobs','_verified_public_key')},sort_keys=True,indent=2))
if __name__=='__main__':main()
