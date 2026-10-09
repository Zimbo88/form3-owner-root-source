#!/usr/bin/env python3
"""Isolated Firefox/Marionette UI test and DEMO screenshot; no external network.

Only authored UI and synthetic credentials are visible. Firefox uses a disposable
profile; no owner browser history, extensions, credentials or printer evidence.
"""
import argparse,json,os,subprocess,tempfile
from pathlib import Path
from evidence_lib import ROOT,safe_output,write_json
CODE=r'''
import sys,os,json,socket,subprocess,time,threading,base64
sys.path.insert(0,'/work/owner-ui')
import server
from panel_data import OwnerStore,HistoricalBundle,consumable_view,field
os.mkdir('/tmp/state',0o700);store=OwnerStore('/tmp/state')
os.mkdir('/tmp/bundle',0o700)
cartridge=consumable_view(b'{"OriginalVolume_mL":1000,"EstimatedVolumeDispensed_ml":800}','cartridge')
for value in cartridge['fields'].values():value['state']='DEMO' if value['value'] is not None else 'UNAVAILABLE'
cartridge['estimated_remaining_ml']['state']='DEMO'
open('/tmp/bundle/panel_snapshot.json','w').write(json.dumps({'schema_version':1,'state':'DEMO','scope':'Synthetic browser fixture',
    'consumables':[cartridge],'jobs':[],'sensors':[{'path':'DEMO thermal fixture','records':90,
    'thermal_history':[{'name':'cpu_thermal','samples':90,'min_celsius':40,'max_celsius':45,
        'gaps_over_300_seconds':1,'backward_clock_steps':0,'state':'DEMO'}]}]}))
open('/tmp/bundle/diagnostics.json','w').write('[]')
open('/tmp/bundle/print_session.json','w').write(json.dumps({'schema_version':1,'state':'HISTORICAL','firmware_scope':'2.5.6-2773',
    'sources':[{'sha256':'a'*64}], 'heater_csv':{'channels':[{'name':'FanHeaterRPM','min':9000,'max':9100,'samples':2,
    'first':1700000000,'last':1700000010,'points':[{'timestamp':1700000000,'value':9000}]}]},'coverage':{'boot_count':1},
    'timeline':[{'timestamp':1700000000,'kind':'log_category','value':'mixer_check_failed'},
    {'timestamp':1700000010,'kind':'task_signal','value':'finished'}]}))
bundle=HistoricalBundle('/tmp/bundle')
store.add_refill({'record_sha256':cartridge['record_sha256'],'quantity_ml':200,'same_material_asserted':True})
class BrowserProvider(server.SampleProvider):
 def snapshot(self):
  r=super().snapshot()
  r['printer']={'printer_state':field('IDLE','DEMO','Synthetic fixture'),
   'tank_level':field(10.25,'DEMO','Synthetic last saved level','mm'),
   'consumables':[dict(cartridge,material=field('White V4.1','DEMO','Synthetic fixture'))],
   'jobs':[],'sensors':[]}
  return r
class ResetFixture:
 def __init__(self):self.state={'state':'AVAILABLE'};self.applies=0
 def request(self,op,plan_id=None,**kwargs):
  if op=='prepare':self.state={'state':'READY','plan_id':'a'*48,'preview':{'material':'FLGPCL02','nominal_ml':1000,'before':{'WriteCount':10,'EstimatedVolumeDispensed_ml':250},'after':{'WriteCount':11,'EstimatedVolumeDispensed_ml':0}}}
  if op=='backup':self.state={'state':'BACKUP_COMPLETE','backup':{'id':'b'*32,'kind':kwargs['kind'],'bytes':128 if kwargs['kind']=='cartridge' else 512,'validation':'SYNTHETIC SNAPSHOT'}}
  if op=='backups':return {'state':'BACKUPS','tank_restore_available':True,'total':2,'backups':[{'id':'b'*32,'kind':'cartridge','material':'FLGPCL04','created':1700000000,'eeprom_sha256':'c'*64},{'id':'d'*32,'kind':'tank','material':'FLGPCL04','created':1700000000,'eeprom_sha256':'e'*64}]}
  if op=='materials':return {'state':'MATERIALS','codes':['FLGPCL04','FLGPWH41'],'tank_write_available':True,'tank_reason':'T/65 tank version 3.3; material only; lifetime preserved.'}
  if op=='prepare_material':self.state={'state':'READY','plan_id':'f'*48,'preview':{'action':'material_assignment','material':'FLGPCL02','nominal_ml':1000,'before':{'material':'FLGPCL02'},'after':{'material':kwargs['material']}}}
  if op=='prepare_restore':self.state={'state':'READY','plan_id':'a'*48,'preview':{'action':'restore_usage','material':'FLGPCL04','nominal_ml':1000,'before':{'WriteCount':11,'EstimatedVolumeDispensed_ml':0},'after':{'WriteCount':12,'EstimatedVolumeDispensed_ml':250}}}
  if op=='prepare_tank_material' or (op=='prepare_restore' and kwargs.get('backup_id')=='d'*32):self.state={'state':'READY','plan_id':'e'*48,'preview':{'kind':'tank','action':'tank_material' if op=='prepare_tank_material' else 'tank_material_restore','material':'FLGPWH41','before':{'material':'FLGPWH41'},'after':{'material':kwargs.get('material','FLGPCL04')},'lifetime_preserved':True}}
  if op=='apply_tank_material':
   if plan_id!='e'*48:raise ValueError('Unexpected tank fixture plan')
   self.applies+=1;self.state={'state':'COMPLETE','stages':{'synthetic_tank_material':'PASS'}}
  if op=='apply_material':
   if plan_id!='f'*48:raise ValueError('Unexpected material fixture plan')
   self.applies+=1;self.state={'state':'COMPLETE','stages':{'synthetic_material':'PASS'}}
  if op=='apply':
   if plan_id!='a'*48:raise ValueError('Unexpected fixture plan')
   self.applies+=1;self.state={'state':'COMPLETE','stages':{'synthetic_transaction':'PASS'},'usage':{'EstimatedVolumeDispensed_ml':0}}
  return self.state
reset_fixture=ResetFixture()
srv=server.make_server(BrowserProvider(),'browser-fixture-only-owner-secret',1328,store,bundle,reset_client=reset_fixture)
t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
os.mkdir('/tmp/profile',0o700)
open('/tmp/profile/user.js','w').write('user_pref("marionette.port",2828);\nuser_pref("browser.shell.checkDefaultBrowser",false);\nuser_pref("datareporting.healthreport.uploadEnabled",false);\nuser_pref("toolkit.telemetry.enabled",false);\nuser_pref("browser.startup.homepage_override.mstone","ignore");\nuser_pref("browser.newtabpage.enabled",false);\n')
log=open('/result/firefox.private.log','wb')
p=subprocess.Popen(['/snap/firefox/current/usr/lib/firefox/firefox','--headless','--no-remote','--profile','/tmp/profile','--marionette','about:blank'],stdout=log,stderr=log)
s=None
try:
 deadline=time.monotonic()+25
 while time.monotonic()<deadline:
  try:s=socket.create_connection(('127.0.0.1',2828),timeout=2);break
  except OSError:time.sleep(.2)
 if s is None:raise RuntimeError('Firefox Marionette unavailable')
 s.settimeout(15)
 def receive():
  size=b''
  while True:
   c=s.recv(1)
   if not c:raise RuntimeError('Marionette closed')
   if c==b':':break
   size+=c
  length=int(size);data=b''
  while len(data)<length:
   chunk=s.recv(length-len(data))
   if not chunk:raise RuntimeError('Short Marionette message')
   data+=chunk
  return json.loads(data)
 receive();seq=0
 def command(name,params):
  global seq
  seq+=1;data=json.dumps([0,seq,name,params]).encode();s.sendall(str(len(data)).encode()+b':'+data)
  r=receive()
  if r[2]:raise RuntimeError('Marionette '+name+' failed: '+r[2].get('error','unknown'))
  return r[3]
 command('WebDriver:NewSession',{'capabilities':{'alwaysMatch':{'acceptInsecureCerts':False}}})
 command('WebDriver:SetWindowRect',{'width':1440,'height':1040})
 command('WebDriver:Navigate',{'url':'http://127.0.0.1:1328/'})
 def js(script):return command('WebDriver:ExecuteScript',{'script':script,'args':[],'newSandbox':False,'sandbox':'default','line':1,'filename':'authored-fixture'})
 shot=command('WebDriver:TakeScreenshot',{'id':None,'full':False,'scroll':False})['value']
 open('/result/login-DEMO.png','wb').write(base64.b64decode(shot))
 js('document.getElementById("token").value="browser-fixture-only-owner-secret";document.getElementById("login-form").requestSubmit();')
 deadline=time.monotonic()+8
 while time.monotonic()<deadline:
  result=js('return {visible:!document.getElementById("dashboard").hidden,error:document.getElementById("error").textContent};')['value']
  if result['visible']:break
  time.sleep(.1)
 if not result['visible']:raise RuntimeError('UI login failed')
 pages=['status','sensors','materials','jobs','diagnostics','network','settings','privacy','maintenance'];results=[]
 for page in pages:
  if page in ('network','privacy','maintenance'):
   js('document.querySelector("nav [data-page=settings]").click();')
   js('document.querySelector("#subnav [data-page='+page+']").click();')
  else:
   selected='status' if page=='sensors' else page
   js('document.querySelector("nav [data-page='+selected+']").click();')
  if page=='sensors':js('document.getElementById("temperature-section").scrollIntoView();')
  time.sleep(.15)
  r=js('return {title:document.getElementById("page-title").textContent,children:document.getElementById("content").children.length,error:document.getElementById("error").textContent};')['value']
  if r['children']==0 or r['error']:raise RuntimeError('Page failed: '+page)
  if page=='diagnostics' and not js('return document.getElementById("content").textContent.includes("RESET_WHILE_PRINTING");')['value']:raise RuntimeError('Code reference missing')
  if page=='materials' and not js('return document.getElementById("content").textContent.includes("10.25 mm") && document.getElementById("content").textContent.includes("White V4.1");')['value']:raise RuntimeError('Material/level fields not rendered')
  if page=='materials' and not js('return Array.from(document.querySelectorAll("#content button")).some(b=>b.disabled && b.textContent==="Pre-dispense pause · unavailable") && document.getElementById("content").textContent.includes("This panel does not prevent automatic filling.");')['value']:raise RuntimeError('Unavailable pre-dispense warning missing')
  if page=='materials' and not js('return document.getElementById("content").textContent.includes("Read-only reconciliation preview");')['value']:
   raise RuntimeError('Refill preview not rendered')
  if page=='sensors' and not js('return document.getElementById("content").textContent.includes("Gaps >300 s");')['value']:
   raise RuntimeError('Historical clock warning not rendered')
  results.append({'page':page,'rendered':True})
  if page=='diagnostics' and not js('return document.getElementById("content").textContent.includes("Heater fan speed") && document.getElementById("content").textContent.includes("not proof of a successful print");')['value']:raise RuntimeError('Capture diagnostics not rendered')
  if page in pages:
   shot=command('WebDriver:TakeScreenshot',{'id':None,'full':True,'scroll':False})['value']
   open('/result/'+page+'-DEMO.png','wb').write(base64.b64decode(shot))
 js('document.querySelector("nav [data-page=status]").click();')
 if js('return document.querySelectorAll("nav button").length;')['value']!=5:raise RuntimeError('Navigation not consolidated')
 if not js('return document.getElementById("content").textContent.includes("GPU activity and live fan RPM: unavailable");')['value']:raise RuntimeError('Unknown GPU activity mislabeled')
 command('WebDriver:SetWindowRect',{'width':390,'height':844});time.sleep(.2)
 small_view=js('return {width:window.innerWidth,height:window.innerHeight};')['value']
 if not js('return document.documentElement.scrollWidth<=window.innerWidth;')['value']:raise RuntimeError('Mobile horizontal overflow')
 shot=command('WebDriver:TakeScreenshot',{'id':None,'full':False,'scroll':False})['value']
 open('/result/overview-mobile-DEMO.png','wb').write(base64.b64decode(shot))
 command('WebDriver:SetWindowRect',{'width':1440,'height':1040})
 js('document.querySelector("nav [data-page=settings]").click();');time.sleep(.2)
 js('document.getElementById("form-alias").value="Draft owner label";');time.sleep(5.5)
 if js('return document.getElementById("form-alias").value;')['value']!='Draft owner label':raise RuntimeError('Background refresh destroyed owner draft')
 js('document.getElementById("form-alias").value="Browser fixture";Array.from(document.querySelectorAll("button")).find(x=>x.textContent==="Save owner preferences").click();');time.sleep(.3)
 if store.settings()['display_alias']!='Browser fixture':raise RuntimeError('Settings UI write failed')
 js('document.querySelector("nav [data-page=materials]").click();');time.sleep(.3)
 js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent==="Manage cartridge & tank").click();');time.sleep(.2)
 js('Array.from(document.querySelectorAll("dialog button")).find(b=>b.textContent==="Prepare a fresh preview").click();')
 js('document.getElementById("form-reset-login").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(1.8)
 if not js('return !!document.getElementById("form-reset-confirmation");')['value']:raise RuntimeError('Reset preview not rendered')
 shot=command('WebDriver:TakeScreenshot',{'id':None,'full':False,'scroll':False})['value']
 open('/result/reset-preview-SYNTHETIC.png','wb').write(base64.b64decode(shot))
 js('document.getElementById("form-reset-confirmation").value="APPLY CARTRIDGE USAGE";document.getElementById("form-reset-secret").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(.3)
 if reset_fixture.applies!=1:raise RuntimeError('Synthetic apply not called exactly once')
 if not js('return document.querySelector("dialog").textContent.includes("COMPLETE") && !document.querySelector("dialog").textContent.includes("browser-fixture-only-owner-secret");')['value']:raise RuntimeError('Reset result or redaction failed')
 shot=command('WebDriver:TakeScreenshot',{'id':None,'full':False,'scroll':False})['value']
 open('/result/reset-SYNTHETIC.png','wb').write(base64.b64decode(shot))
 js('Array.from(document.querySelectorAll("dialog button")).find(b=>b.textContent==="Close").click();')
 for label,filename,expected in [('Back up cartridge','backup-cartridge-SYNTHETIC','BACKUP COMPLETE'),('Back up tank','backup-tank-SYNTHETIC','BACKUP COMPLETE'),('Review saved backups','backups-SYNTHETIC','BACKUPS'),('Review material assignment','material-assignment-SYNTHETIC','MATERIALS')]:
  js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent==="Manage cartridge & tank").click();');time.sleep(.2)
  js('Array.from(document.querySelectorAll("dialog button")).find(b=>b.textContent==='+json.dumps(label)+').click();')
  js('document.getElementById("form-reset-login").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(1.7)
  if not js('return document.querySelector("dialog").textContent.includes('+json.dumps(expected)+');')['value']:raise RuntimeError('Backup/material dialog failed')
  shot=command('WebDriver:TakeScreenshot',{'id':None,'full':False,'scroll':False})['value']
  open('/result/'+filename+'.png','wb').write(base64.b64decode(shot))
  if expected in ('BACKUPS','MATERIALS'):
   label2='Review saved usage restore' if expected=='BACKUPS' else 'Review cartridge material change'
   js('Array.from(document.querySelectorAll("dialog button")).find(b=>b.textContent==='+json.dumps(label2)+').click();')
   js('document.getElementById("form-reset-login").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(1.7)
   if not js('return !!document.getElementById("form-reset-confirmation");')['value']:raise RuntimeError('Restore/material preview missing')
   if not js('return Array.from(document.querySelectorAll("dialog button")).some(b=>b.textContent==="Back up tank");')['value']:raise RuntimeError('Ready preview hides backup navigation')
   suffix='restore' if expected=='BACKUPS' else 'material'
   shot=command('WebDriver:TakeScreenshot',{'id':None,'full':False,'scroll':False})['value']
   open('/result/'+suffix+'-preview-SYNTHETIC.png','wb').write(base64.b64decode(shot))
   phrase='APPLY CARTRIDGE USAGE' if expected=='BACKUPS' else 'CHANGE CARTRIDGE MATERIAL'
   js('document.getElementById("form-reset-confirmation").value='+json.dumps(phrase)+';document.getElementById("form-reset-secret").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(.3)
   if not js('return document.querySelector("dialog").textContent.includes("COMPLETE");')['value']:raise RuntimeError('Restore/material synthetic apply failed')
   shot=command('WebDriver:TakeScreenshot',{'id':None,'full':False,'scroll':False})['value']
   open('/result/'+suffix+'-complete-SYNTHETIC.png','wb').write(base64.b64decode(shot))
  js('Array.from(document.querySelectorAll("dialog button")).find(b=>b.textContent==="Close").click();')
 # New tank material and same-tank material restore: synthetic apply only.
 for entry,label,filename in [('Review material assignment','Review tank material change','tank-material'),('Review saved backups','Review saved tank material','tank-restore')]:
  js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent==="Manage cartridge & tank").click();');time.sleep(.2)
  js('Array.from(document.querySelectorAll("dialog button")).find(b=>b.textContent==='+json.dumps(entry)+').click();');time.sleep(.1)
  js('document.getElementById("form-reset-login").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(.4)
  js('Array.from(document.querySelectorAll("dialog button")).find(b=>b.textContent==='+json.dumps(label)+').click();');time.sleep(.1)
  js('document.getElementById("form-reset-login").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(.4)
  if not js('return !!document.getElementById("tank-empty-clean") && !document.getElementById("tank-empty-clean").checked && document.querySelector("dialog").textContent.includes("lifetime");')['value']:raise RuntimeError('Tank confirmation gate missing')
  shot=command('WebDriver:TakeScreenshot',{'id':None,'full':False,'scroll':False})['value']
  open('/result/'+filename+'-preview-SYNTHETIC.png','wb').write(base64.b64decode(shot))
  before=reset_fixture.applies
  js('document.getElementById("form-reset-confirmation").value="CHANGE CLEAN TANK MATERIAL";document.getElementById("form-reset-secret").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(.3)
  if reset_fixture.applies!=before:raise RuntimeError('Unchecked tank confirmation reached broker')
  js('document.getElementById("tank-empty-clean").checked=true;document.getElementById("form-reset-secret").value="browser-fixture-only-owner-secret";document.querySelector("dialog form").requestSubmit();');time.sleep(.3)
  if reset_fixture.applies!=before+1:raise RuntimeError('Confirmed synthetic tank apply did not run once')
  if not js('return document.querySelector("dialog").textContent.includes("COMPLETE");')['value']:raise RuntimeError('Tank completion not rendered')
  js('Array.from(document.querySelectorAll("dialog button")).find(b=>b.textContent==="Close").click();');time.sleep(.1)
 js('document.getElementById("logout").click();');time.sleep(.2)
 if not js('return document.getElementById("dashboard").hidden;')['value']:raise RuntimeError('Logout failed')
 print(json.dumps({'passed':True,'pages':results,'cartridge_reset_browser_flow':'SYNTHETIC PASS; no hardware writes','settings_saved':True,'unsaved_draft_preserved':True,'logout':True,'data':'DEMO ONLY','network_namespace':'loopback only','main_navigation_entries':5,'small_viewport':small_view,'mobile_no_horizontal_overflow':True,'gpu_utilization_unavailable':True,'firefox_content_sandbox_disabled':False}))
finally:
 if s:s.close()
 p.terminate()
 try:p.wait(timeout=5)
 except subprocess.TimeoutExpired:p.kill();p.wait()
 srv.shutdown();srv.server_close();store.tree.close();bundle.tree.close();log.close()
'''

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-output',required=True);p.add_argument('--report',required=True);a=p.parse_args()
 out=safe_output(a.private_output)
 if not out.resolve().is_relative_to(ROOT/'research-private'):raise ValueError('Private browser profile/log location required')
 out.mkdir(mode=0o700)
 cmd=['bwrap','--unshare-user','--unshare-net','--unshare-pid','--die-with-parent','--clearenv',
      '--ro-bind','/usr','/usr','--ro-bind','/snap','/snap','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
      '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--setenv','HOME','/tmp','--setenv','PATH','/usr/bin',
      '--setenv','MOZ_HEADLESS','1',
      '--ro-bind','/etc/fonts','/etc/fonts',
      '--setenv','FONTCONFIG_PATH','/etc/fonts',
      '--ro-bind',str(ROOT/'owner-ui'),'/work/owner-ui','--ro-bind',str(ROOT/'owner-maintenance'),'/work/owner-maintenance','--bind',str(out),'/result','--chdir','/work',
      '/usr/bin/python3','-B','-c',CODE]
 r=subprocess.run(cmd,capture_output=True,text=True,timeout=100)
 (out/'runner.private.log').write_text(r.stdout+r.stderr)
 try:result=json.loads(r.stdout)
 except ValueError:result={'passed':False,'exit':r.returncode,'reason':'See private browser fixture log'}
 write_json(a.report,result);print(json.dumps(result));raise SystemExit(not result['passed'])
if __name__=='__main__':main()
