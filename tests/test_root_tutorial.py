"""Check authored tutorial syntax and local SSH profile creation without networking."""
import os
import ast
import base64
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import struct
import unittest

DOCS = Path(__file__).resolve().parents[1] / 'docs/public'
ROOT = DOCS.parents[1]
HOST_BLOB = b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(range(32))
PUBLIC = base64.b64encode(HOST_BLOB).decode()
FINGERPRINT = 'SHA256:' + base64.b64encode(hashlib.sha256(HOST_BLOB).digest()).decode().rstrip('=')


class RootTutorial(unittest.TestCase):
    def test_shell_blocks_parse_without_running_them(self):
        count = 0
        for name in ('COMMAND_WALKTHROUGH.md', 'PI5_CLIP_GUIDE.md', 'ROOT_GUIDE.md', 'OWNER_INSTALL.md', 'SECURE_SSH.md', 'LOG_REVIEW.md'):
            text = (DOCS/name).read_text()
            for block in re.findall(r'```sh\n(.*?)\n```', text, re.S):
                result = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, name + ': shell syntax')
                self.assertRegex(block.splitlines()[0], r'^# (LAPTOP|PI|RESCUE|NORMAL PRINTER)')
                count += 1
        self.assertGreaterEqual(count, 55)

    def run_profile(self, directory, candidate=None, host='192.168.50.20', pin=FINGERPRINT, jump=None):
        base = Path(directory)
        key = base/'owner-client-ed25519'; key.write_text('AUTHORED DUMMY FILE; no key material');key.chmod(0o600)
        scan = base/'candidate'; scan.write_text(candidate if candidate is not None else '[192.168.50.20]:2222 ssh-ed25519 '+PUBLIC+'\n')
        cmd=[sys.executable,'-B',str(ROOT/'tools/create_owner_ssh_profile.py'),
             '--directory',str(base),'--host',host,'--key',str(key),'--candidate',str(scan),
             '--expected-host-fingerprint',pin]
        if jump is not None:cmd+=['--jump-alias',jump]
        return subprocess.run(cmd,capture_output=True,text=True,timeout=5)

    def test_profile_with_spaces_pins_alias_and_only_owner_key(self):
        with tempfile.TemporaryDirectory(prefix='owner tutorial ') as d:
            result = self.run_profile(d); self.assertEqual(result.returncode, 0)
            p=Path(d)
            config=subprocess.check_output(['ssh','-G','-F',str(p/'owner-ssh.conf'),'form3-owner'],
                                           stderr=subprocess.DEVNULL,text=True,timeout=5)
            for line in ('user root', 'port 2222', 'hostkeyalias form3-owner',
                         'stricthostkeychecking true', 'identitiesonly yes',
                         'passwordauthentication no', 'kbdinteractiveauthentication no', 'forwardagent no'):
                self.assertIn(line, config)
            identities=[x for x in config.splitlines() if x.startswith('identityfile ')]
            self.assertEqual(len(identities), 1)
            self.assertIn(str(p/'owner-client-ed25519'), identities[0])
            self.assertEqual((p/'owner-known-hosts').read_text(),'form3-owner ssh-ed25519 '+PUBLIC+'\n')
            for name in ('owner-known-hosts','owner-ssh.conf'):
                self.assertEqual((p/name).stat().st_mode & 0o777, 0o600)

    def test_existing_pin_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'owner-known-hosts';p.write_text('preserve existing reviewed pin')
            result=self.run_profile(d)
            self.assertNotEqual(result.returncode,0);self.assertEqual(p.read_text(),'preserve existing reviewed pin')
            self.assertFalse((Path(d)/'owner-ssh.conf').exists())

    def test_bad_candidate_or_public_address_refused(self):
        for candidate, host in [('', '192.168.50.20'), ('x ssh-rsa placeholder\n','192.168.50.20'),
                                ('x ssh-ed25519 placeholder\ny ssh-ed25519 placeholder\n','192.168.50.20'),
                                (None,'8.8.8.8'), (None,'127.0.0.1')]:
            with tempfile.TemporaryDirectory() as d:
                self.assertNotEqual(self.run_profile(d,candidate,host).returncode,0)
                self.assertFalse((Path(d)/'owner-ssh.conf').exists())

    def test_wrong_fingerprint_rejected_without_key_material_output(self):
        with tempfile.TemporaryDirectory() as d:
            result=self.run_profile(d,pin='SHA256:WRONG')
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn(PUBLIC,result.stdout+result.stderr)
            self.assertFalse((Path(d)/'owner-known-hosts').exists())

    def test_optional_jump_preserves_strict_both_hops(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_profile(d,jump='fixture-pi').returncode,0)
            config=subprocess.check_output(['ssh','-G','-F',str(Path(d)/'owner-ssh.conf'),'form3-owner'],
                                           stderr=subprocess.DEVNULL,text=True,timeout=5)
            self.assertIn('proxycommand /usr/bin/ssh -o BatchMode=yes -o StrictHostKeyChecking=yes',config)
            self.assertIn('-o ForwardAgent=no -W %h:%p fixture-pi',config)
            self.assertIn('hostkeyalias form3-owner',config)

    def test_jump_shell_injection_refused(self):
        for jump in ('x;id','-bad','space alias','$(id)'):
            with tempfile.TemporaryDirectory() as d:
                self.assertNotEqual(self.run_profile(d,jump=jump).returncode,0)
                self.assertFalse((Path(d)/'owner-ssh.conf').exists())

    def test_world_accessible_directory_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);p.chmod(0o755)
            self.assertNotEqual(self.run_profile(d).returncode,0)
            p.chmod(0o700)
            (p/'owner-known-hosts').symlink_to(p/'not-created')
            self.assertNotEqual(self.run_profile(d).returncode,0)
            self.assertFalse((p/'not-created').exists())

    def test_walkthrough_python_snippets_compile_only(self):
        text=(DOCS/'COMMAND_WALKTHROUGH.md').read_text()
        blocks=re.findall(r"(?:owner_python|python3) - <<'PY'\n(.*?)\nPY",text,re.S)
        self.assertGreaterEqual(len(blocks),4)
        for body in blocks:compile(body,'tutorial','exec')

    def test_ext4_flag_decoder_on_synthetic_headers(self):
        text=(DOCS/'COMMAND_WALKTHROUGH.md').read_text()
        body=next(b for b in re.findall(r"owner_python - <<'PY'\n(.*?)\nPY",text,re.S) if 'def ext_state' in b)
        tree=ast.parse(body)
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='ext_state')
        namespace={'struct':struct}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'synthetic-header','exec'),namespace)
        decode=namespace['ext_state'];raw=bytearray(1024)
        with self.assertRaises(ValueError):decode(raw)
        struct.pack_into('<H',raw,0x38,0xef53);struct.pack_into('<H',raw,0x3a,1)
        self.assertTrue(decode(raw)['clean_flag']);self.assertFalse(decode(raw)['needs_journal_recovery'])
        struct.pack_into('<I',raw,0x60,4)
        self.assertTrue(decode(raw)['needs_journal_recovery'])
        struct.pack_into('<H',raw,0x3a,6)
        self.assertTrue(decode(raw)['errors_flag']);self.assertTrue(decode(raw)['orphan_recovery_flag'])
        self.assertFalse(decode(raw)['healthy_filesystem_proven'])
        with self.assertRaises(ValueError):decode(raw[:-1])

    def test_dhcp_example_syntax_only(self):
        text=(DOCS/'COMMAND_WALKTHROUGH.md').read_text()
        conf=re.search(r'owner-dhcp.conf" <<EOF\n(.*?)\nEOF',text,re.S).group(1)
        conf=conf.replace('$PRINTER_ETH0_MAC','02:00:00:00:00:01')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dhcp.conf';p.write_text(conf)
            result=subprocess.run(['/usr/sbin/dnsmasq','--test','--conf-file='+str(p)],
                                  capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0)
        for token in ('port=0','interface=eth0','except-interface=lo','bind-interfaces',
                      'dhcp-ignore=tag:!owner','dhcp-option=option:router','dhcp-option=option:dns-server'):
            self.assertIn(token,conf)


if __name__ == '__main__':
    unittest.main()
