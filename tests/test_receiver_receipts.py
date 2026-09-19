"""Receiver failures use a local fake SSH executable; no Pi or network is contacted."""
import hashlib,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class ReceiverReceipts(unittest.TestCase):
    def run_case(self,exit_code,expected=4):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        scripts=root/'scripts';scripts.mkdir();binpath=root/'bin';binpath.mkdir()
        shutil.copyfile(ROOT/'scripts/receive_emmc_via_pi.sh',scripts/'receive.sh')
        # /etc/alternatives is intentionally absent from the isolated fixture.
        awk=next((p for p in ('/usr/bin/mawk','/usr/bin/gawk') if os.path.isfile(p)),None)
        self.assertIsNotNone(awk,'Install a host awk implementation for receiver fixtures')
        (binpath/'awk').symlink_to(awk)
        ssh=binpath/'ssh';ssh.write_text('#!/bin/sh\nprintf TEST\nexit '+str(exit_code)+'\n');ssh.chmod(0o700)
        # Fixture-only PATH intercepts SSH. The suite's network namespace is disconnected.
        env=dict(os.environ,PATH=str(binpath)+':/usr/bin:/bin',FORM3_PI_SSH='fixture-pi')
        r=subprocess.run(['/bin/bash',str(scripts/'receive.sh'),'fixture.img',str(expected)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        out=root/'hardware/emmc/original/fixture.img'
        self.assertTrue(out.exists(),r.stderr.decode(errors='replace'))
        self.assertEqual(out.read_bytes(),b'TEST')
        self.assertIn(hashlib.sha256(b'TEST').hexdigest(),Path(str(out)+'.sha256').read_text())
        self.assertIn('Received bytes: 4',Path(str(out)+'.receipt.txt').read_text())
        return r,out
    def test_failed_pipeline_keeps_hash_receipt_and_incomplete_even_at_expected_length(self):
        r,out=self.run_case(1)
        self.assertNotEqual(r.returncode,0);self.assertTrue(Path(str(out)+'.incomplete').exists())
        self.assertIn('Pipeline completed: 0',Path(str(out)+'.receipt.txt').read_text())
    def test_clean_short_transfer_keeps_receipt_and_marker(self):
        r,out=self.run_case(0,8)
        self.assertNotEqual(r.returncode,0);self.assertTrue(Path(str(out)+'.incomplete').exists())
    def test_complete_fixture_clears_only_its_marker(self):
        r,out=self.run_case(0)
        self.assertEqual(r.returncode,0);self.assertFalse(Path(str(out)+'.incomplete').exists())

    def test_missing_or_option_like_pi_target_stops_before_ssh_or_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);scripts=root/'scripts';scripts.mkdir();binpath=root/'bin';binpath.mkdir()
            shutil.copyfile(ROOT/'scripts/receive_emmc_via_pi.sh',scripts/'receive.sh')
            marker=root/'ssh-called';ssh=binpath/'ssh'
            ssh.write_text('#!/bin/sh\ntouch "'+str(marker)+'"\nexit 99\n');ssh.chmod(0o700)
            for target in (None,'-oProxyCommand=bad','alias with spaces'):
                env=dict(os.environ,PATH=str(binpath)+':/usr/bin:/bin');env.pop('FORM3_PI_SSH',None)
                if target is not None:env['FORM3_PI_SSH']=target
                r=subprocess.run(['/bin/bash',str(scripts/'receive.sh'),'fixture.img','4'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3)
                self.assertNotEqual(r.returncode,0)
                self.assertFalse(marker.exists());self.assertFalse((root/'hardware').exists())
