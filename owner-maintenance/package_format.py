"""Python 3.5 signed, bounded owner package format. No hardware operations.

RSA/SHA256 verification is delegated to OpenSSL; a separately pinned public key is
mandatory. An archive-provided hash or key is never an authentication authority.
"""
import gzip,hashlib,io,json,os,re,stat,subprocess,tarfile,tempfile

LIMIT=16*1024*1024
PATHS={'panel/lan_ipv4.py','bootstrap/lan_ipv4.py','panel/server.py','panel/panel_data.py','panel/formule_codec.py','panel/static/index.html',
       'panel/static/app.js','panel/static/style.css','bootstrap/bootstrap.py',
       'bootstrap/owner-maintenance.init','bootstrap/socket_launcher.py',
       'bootstrap/ownerctl.py','bootstrap/package_format.py'}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def unique_json(raw):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('Duplicate JSON key')
            out[k]=v
        return out
    def bad(_):raise ValueError('Invalid JSON number')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=bad)

def read_regular(path,limit=LIMIT):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        s=os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_size>limit:raise ValueError('Expected bounded regular file')
        chunks=[];n=0
        while True:
            b=os.read(fd,min(65536,limit+1-n))
            if not b:break
            chunks.append(b);n+=len(b)
            if n>limit:raise ValueError('Input budget exceeded')
        return b''.join(chunks)
    finally:os.close(fd)

def verify(package,public_key,expected_signer,openssl=None):
    key=read_regular(public_key,16384)
    if digest(key)!=expected_signer:raise ValueError('Independent signer fingerprint mismatch')
    if b'PRIVATE KEY' in key or not key.startswith(b'-----BEGIN PUBLIC KEY-----'):
        raise ValueError('Expected public verification key only')
    raw=read_regular(package,8*1024*1024)
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:expanded=f.read(LIMIT+1)
    if len(expanded)>LIMIT:raise ValueError('Expansion budget exceeded')
    blobs={}
    with tarfile.open(fileobj=io.BytesIO(expanded),mode='r:') as tar:
        for member in tar:
            if len(blobs)>=64 or member.name in blobs:raise ValueError('Duplicate or excess members')
            if member.name not in PATHS|{'manifest.json','manifest.sig'}:raise ValueError('Unapproved package path')
            if not member.isfile() or member.issparse() or member.pax_headers or member.size>4*1024*1024:
                raise ValueError('Unsupported archive member')
            if member.mode&0o7000:raise ValueError('Special permission bits forbidden')
            f=tar.extractfile(member);data=f.read(4*1024*1024+1)
            if len(data)!=member.size:raise ValueError('Truncated member')
            blobs[member.name]=data
        if any(expanded[tar.offset:]):raise ValueError('Unexpected trailing archive content')
    if 'manifest.json' not in blobs or 'manifest.sig' not in blobs:raise ValueError('Missing signed manifest')
    if len(blobs['manifest.json'])>32768 or len(blobs['manifest.sig'])>1024:raise ValueError('Signature metadata budget')
    # No archive bytes are executed. OpenSSL receives fixed files in a new temp dir.
    with tempfile.TemporaryDirectory(prefix='owner-signature-') as d:
        for name,data in [('public.pem',key),('manifest.json',blobs['manifest.json']),('signature',blobs['manifest.sig'])]:
            with open(os.path.join(d,name),'wb') as f:f.write(data)
        rsa=subprocess.run((openssl or ['/usr/bin/openssl'])+['rsa','-pubin','-in',os.path.join(d,'public.pem'),'-modulus','-noout'],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        modulus=rsa.stdout.strip().split(b'=',1)
        if rsa.returncode or len(modulus)!=2 or not re.match(b'^[0-9A-Fa-f]{512,1024}$',modulus[1]) or not 2048<=int(modulus[1],16).bit_length()<=4096:
            raise ValueError('Owner package requires RSA 2048..4096 public key')
        cmd=(openssl or ['/usr/bin/openssl'])+['dgst','-sha256','-verify',os.path.join(d,'public.pem'),
             '-signature',os.path.join(d,'signature'),os.path.join(d,'manifest.json')]
        r=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        if r.returncode:raise ValueError('Owner signature verification failed')
    m=unique_json(blobs['manifest.json'])
    if canonical(m)!=blobs['manifest.json']:raise ValueError('Manifest must be canonical JSON')
    if set(m)!={'schema','version','kind','firmware','files'} or m['schema']!=1 or m['kind'] not in ('install','panel','maintenance'):
        raise ValueError('Unsupported package schema')
    if not isinstance(m['version'],str) or not re.match(r'^[0-9]+\.[0-9]+\.[0-9]+-[a-z0-9-]{1,24}$',m['version']):
        raise ValueError('Invalid release version')
    if m['firmware']!=['2.5.6-2773']:raise ValueError('Unsupported firmware compatibility declaration')
    if not isinstance(m['files'],dict) or set(m['files'])!=set(blobs)-{'manifest.json','manifest.sig'}:
        raise ValueError('Manifest/member disagreement')
    if not set(m['files']) or not set(m['files'])<=PATHS:raise ValueError('Invalid file set')
    if m['kind']=='panel' and any(not n.startswith('panel/') for n in m['files']):raise ValueError('Panel update cannot replace bootstrap')
    required={n for n in PATHS if n.startswith('panel/')}
    if not required<=set(m['files']):raise ValueError('Incomplete panel package')
    if m['kind'] in ('install','maintenance') and set(m['files'])!=PATHS:raise ValueError('Incomplete install package')
    for name,meta in m['files'].items():
        if not isinstance(meta,dict) or set(meta)!={'bytes','sha256'} or meta['bytes']!=len(blobs[name]) or meta['sha256']!=digest(blobs[name]):
            raise ValueError('Member content mismatch')
    return {'manifest':m,'manifest_sha256':digest(blobs['manifest.json']),'package_sha256':digest(raw),
            'signer_sha256':expected_signer,'blobs':blobs,'_verified_public_key':key}

def build(source,version,kind,key,public_key,output,openssl=None):
    if os.path.lexists(output):raise ValueError('Never overwrite a package')
    names=sorted(PATHS if kind in ('install','maintenance') else [p for p in PATHS if p.startswith('panel/')])
    blobs={n:read_regular(os.path.join(source,n),4*1024*1024) for n in names}
    m={'schema':1,'version':version,'kind':kind,'firmware':['2.5.6-2773'],
       'files':{n:{'bytes':len(b),'sha256':digest(b)} for n,b in blobs.items()}}
    raw=canonical(m)
    cmd=(openssl or ['/usr/bin/openssl'])+['dgst','-sha256','-sign',key]
    result=subprocess.run(cmd,input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
    if result.returncode:raise ValueError('Owner signing failed; private key contents withheld')
    blobs.update({'manifest.json':raw,'manifest.sig':result.stdout})
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w',format=tarfile.USTAR_FORMAT) as tar:
        for n,b in sorted(blobs.items()):
            info=tarfile.TarInfo(n);info.size=len(b);info.mode=0o644;info.mtime=0
            tar.addfile(info,io.BytesIO(b))
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as dst:
        with gzip.GzipFile(fileobj=dst,filename='',mode='wb',mtime=0) as gz:gz.write(archive.getvalue())
    return verify(output,public_key,digest(read_regular(public_key,16384)),openssl)
