"""Bounded explicit Form 3 catalog entries, not resin compatibility approval."""
import re
from package_format import unique_json


def allowed_materials(raw):
    if len(raw)>2<<20:raise ValueError('Material catalog exceeds bound')
    root=unique_json(raw)
    if not isinstance(root,dict) or type(root.get('schemaVersion')) is not int or root['schemaVersion']!=1:
        raise ValueError('Unknown material catalog schema')
    entries=root.get('materials')
    if not isinstance(entries,list) or len(entries)>512:raise ValueError('Invalid material catalog')
    found=set();result=[]
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('Invalid material entry')
        code=entry.get('code');versions=entry.get('versions')
        if not isinstance(code,str) or not re.fullmatch(r'FL[A-Z0-9]{4}',code):continue
        if entry.get('machines')!=[]:continue
        if not isinstance(versions,list) or len(versions)>100:raise ValueError('Invalid material version list')
        for version in versions:
            if not isinstance(version,dict):raise ValueError('Invalid material version')
            number=version.get('version')
            if type(number) is not int or not 0<=number<=99:continue
            label=code+'{0:02d}'.format(number)
            if label in found:raise ValueError('Ambiguous material code')
            found.add(label)
            machines=version.get('machines')
            if not isinstance(machines,dict) or set(machines)!={'include'}:continue
            included=machines['include']
            if not isinstance(included,list) or len(included)>64:raise ValueError('Invalid machine include list')
            if version.get('isPublic') is True and any(isinstance(x,dict) and x.get('MachineTypeId')=='DGJR-1-0' for x in included):result.append(label)
    if len(result)>256:raise ValueError('Catalog result exceeds bounded reply')
    return sorted(result)
