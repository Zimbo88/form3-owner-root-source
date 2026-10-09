"""Typed client for the root-owned local cartridge broker; no shell or paths."""
import json
import os
import socket
import stat
import struct

SOCKET='/run/form3-cartridge-reset/broker.sock'


class ResetClient(object):
    def request(self,operation,plan_id=None,kind=None,backup_id=None,material=None):
        if operation not in ('status','prepare','apply','backup','backups','prepare_restore','materials','prepare_material','apply_material'):
            raise ValueError('Unknown reset operation')
        data={'operation':operation}
        if operation in ('apply','apply_material'):data['plan_id']=plan_id
        if operation=='prepare_material':
            if not isinstance(material,str) or not __import__('re').fullmatch(r'FL[A-Z0-9]{6}',material):raise ValueError('Invalid material code')
            data['material']=material
        if operation=='backup':
            if kind not in ('cartridge','tank'):raise ValueError('Invalid backup kind')
            data['kind']=kind
        if operation=='prepare_restore':
            if not isinstance(backup_id,str) or not __import__('re').fullmatch(r'[a-f0-9]{32}',backup_id):raise ValueError('Invalid backup identifier')
            data['backup_id']=backup_id
        info=os.lstat(SOCKET)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o007:
            raise ValueError('Untrusted local reset broker')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(SOCKET)
            credentials=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if credentials[1]!=0:raise ValueError('Reset broker is not root-owned')
            client.sendall((json.dumps(data)+'\n').encode())
            raw=b''
            while b'\n' not in raw and len(raw)<=8192:
                part=client.recv(8193-len(raw))
                if not part:break
                raw+=part
        if not raw.endswith(b'\n') or len(raw)>8192:raise ValueError('Invalid broker reply')
        result=json.loads(raw.decode())
        if not isinstance(result,dict):raise ValueError('Invalid broker response')
        return result
