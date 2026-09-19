"""Synthetic certificate metadata; no clock changes, secrets or target connection."""
import copy,importlib.util,pathlib,ssl,stat,sys,unittest
from unittest import mock
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'owner-maintenance'))
import socket_launcher as launcher

class LauncherClockTests(unittest.TestCase):
 def setUp(self):
  self.ip='192.168.50.20'
  self.cert={'subjectAltName':(('IP Address',self.ip),),'notBefore':'Jan  1 00:00:00 2024 GMT','notAfter':'Jan  2 00:00:00 2024 GMT'}
  self.start=ssl.cert_time_to_seconds(self.cert['notBefore'])
 def reject(self,cert,ip,now,code):
  with self.assertRaises(launcher.CertificateStateError) as c:launcher.validate_primary_certificate(cert,ip,now)
  self.assertEqual(c.exception.exit_code,code)
  self.assertEqual(str(c.exception),'Primary TLS readiness check failed')
 def test_exact_window_boundaries(self):
  launcher.validate_primary_certificate(self.cert,self.ip,self.start)
  launcher.validate_primary_certificate(self.cert,self.ip,self.start+86399)
  self.reject(self.cert,self.ip,self.start-1,20);self.reject(self.cert,self.ip,self.start+86400,21)
 def test_ip_san_exact_no_dns_or_wildcard(self):
  for names in [(('DNS',self.ip),),(('IP Address','192.168.50.21'),),(('DNS','*'),)]:
   c=dict(self.cert,subjectAltName=names);self.reject(c,self.ip,self.start,22)
 def test_invalid_clock_values(self):
  for now in [float('nan'),float('inf'),-float('inf'),True,'123',None]:self.reject(self.cert,self.ip,now,24)
 def test_malformed_or_inverted_certificate(self):
  for c in [{},dict(self.cert,notAfter='invalid'),dict(self.cert,notAfter=self.cert['notBefore']),
            dict(self.cert,subjectAltName=None),dict(self.cert,notBefore=self.cert['notAfter'])]:
   self.reject(c,self.ip,self.start,25)
 def context(self,ip,now):
  config={'panel_enabled':True,'interface':'eth0','uid':65000,'gid':65000,'client_network':'192.168.50.0/24'}
  def info(path):
   directory=path.endswith(('/panel-identity','/state'))
   return type('Stat',(),{'st_uid':65000,'st_gid':65000,'st_mode':(stat.S_IFDIR|0o700) if directory else (stat.S_IFREG|0o600)})()
  return (mock.patch.multiple(launcher,normal_context=mock.Mock(),configuration=mock.Mock(return_value=config),
    address=mock.Mock(return_value=ip),lan_configuration=mock.Mock(return_value={'interface':'wlan0','http_enabled':True}),
    release=mock.Mock(return_value=('/fixture','0.5.4-review'))),mock.patch.object(launcher.os,'lstat',side_effect=info),
    mock.patch.object(launcher.ssl._ssl,'_test_decode_cert',return_value=self.cert),mock.patch('time.time',return_value=now))
 def test_invalid_primary_clock_never_falls_back_to_wlan_http(self):
  for now,code in [(self.start-1,20),(self.start+86400,21)]:
   a,b,c,d=self.context(self.ip,now)
   with a,b,c,d,mock.patch.object(launcher,'bind_and_drop') as bind,mock.patch.object(launcher,'drop_identity') as drop,mock.patch.object(launcher.os,'execve') as execute:
    with self.assertRaises(launcher.CertificateStateError) as error:launcher.launch()
    self.assertEqual(error.exception.exit_code,code)
    bind.assert_not_called();drop.assert_not_called();execute.assert_not_called()
 def test_absent_primary_keeps_explicit_wlan_only_behavior(self):
  a,b,c,d=self.context(None,self.start-1)
  with a,b,c,d,mock.patch.object(launcher,'bind_and_drop') as bind,mock.patch.object(launcher,'drop_identity') as drop,mock.patch.object(launcher.os,'execve') as execute:
   launcher.launch();bind.assert_not_called();drop.assert_called_once_with(65000,65000)
   self.assertIn('--owner-lan-only',execute.call_args[0][1])
   self.assertNotIn('--tls-cert',execute.call_args[0][1])
