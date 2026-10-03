#!/usr/bin/env python3
"""Explicit read-only LAN panel asset check; no discovery, login or settings changes.

Compare complete served bytes against a selected local source tree. This detects
truncated transfers but is not browser or authenticated API acceptance. Redirects,
public targets, credentials in URLs, proxies and unverified HTTPS are not used.
"""
import argparse
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import ssl
from urllib.parse import urlsplit
from evidence_lib import write_json

PRIVATE=tuple(ipaddress.ip_network(s) for s in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
FILES={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}


def target(url):
    parsed=urlsplit(url)
    if (parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in ('','/') or parsed.port!=1328):
        raise ValueError('Explicit credential-free LAN root URL on port 1328 required')
    address=ipaddress.ip_address(parsed.hostname or '')
    if address.version!=4 or not any(address in n for n in PRIVATE):raise ValueError('RFC1918 IPv4 target required')
    return parsed.scheme,str(address)


def response_bytes(response,expected):
    if response.status!=200:raise ValueError('Asset failed or redirected')
    lengths=response.headers.get_all('Content-Length',[])
    if lengths!=[str(len(expected))] or response.headers.get('Transfer-Encoding'):
        raise ValueError('Unexpected asset framing/length')
    raw=response.read(len(expected)+1)
    if raw!=expected:raise ValueError('Incomplete or changed asset content')
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'complete':True}


def check(url,source,ca=None):
    scheme,host=target(url);root=Path(source)
    expected={path:(root/name).read_bytes() for path,name in FILES.items()}
    if any(len(raw)>512<<10 for raw in expected.values()):raise ValueError('Local asset bound')
    context=ssl.create_default_context(cafile=ca) if scheme=='https' else None
    result=[]
    for path,raw in expected.items():
        con=(http.client.HTTPSConnection(host,1328,timeout=8,context=context) if context
             else http.client.HTTPConnection(host,1328,timeout=8))
        try:
            con.request('GET',path,headers={'Host':host+':1328','Cache-Control':'no-cache'})
            result.append(dict(response_bytes(con.getresponse(),raw),path=path))
        finally:con.close()
    return {'schema_version':1,'transport':scheme,'asset_checks':result,
            'source':str(root.resolve()),'browser_acceptance':False,'settings_changed':False,'passed':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True)
    p.add_argument('--source',default=str(Path(__file__).resolve().parents[1]/'owner-ui/static'))
    p.add_argument('--ca',help='Reviewed owner CA file for HTTPS; verification is mandatory')
    p.add_argument('--output',required=True);a=p.parse_args()
    report=check(a.url,a.source,a.ca);write_json(a.output,report)
    print(json.dumps({'passed':True,'assets':len(report['asset_checks']),'browser_acceptance':False,'transport':report['transport']}))


if __name__=='__main__':main()
