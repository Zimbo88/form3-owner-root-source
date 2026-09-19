#!/usr/bin/env python3
"""Compatibility entry for the reviewed public source handoff; explicit selection only.

Delegates to the one canonical packager. Needs a clean committed source tree.
No signing, key generation, vendor execution or hardware contact.
"""
import argparse,json
from package_developer_source import package
from evidence_lib import write_json

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--report',required=True);a=p.parse_args()
    r=package(a.output);write_json(a.report,r);print(json.dumps({k:v for k,v in r.items() if k!='files'},indent=2))
if __name__=='__main__':main()
