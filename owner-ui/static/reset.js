"use strict";
// Independent dialog: periodic status refresh never destroys confirmation input.
let resetDialog=null,resetPoll=null;
function closeResetDialog(){clearTimeout(resetPoll);if(resetDialog){resetDialog.remove();resetDialog=null;}}
function cartridgeResetCard(){
 const p=panel('Cartridge & tank maintenance','Supported format: verified legacy C/0, RW/1, 1000 mL. Other formats stay unavailable. Resets electronic usage only; it does not measure or add resin. Usage adjustments preserve material and chip identity. Material assignment is a separate reviewed action. Tank material changes preserve lifetime usage.');
 p.append(el('p','Keep the printer idle. Do not start a job, remove the cartridge or switch power during the transaction. Other cartridge formats are refused.','tagline'));
 p.append(button('Manage cartridge & tank',openResetDialog));return p;
}
function openResetDialog(){
 closeResetDialog();const epoch=sessionEpoch,d=el('dialog',undefined,'reset-dialog');resetDialog=d;
 const title=el('h2','Cartridge & tank maintenance'),body=el('div'),message=el('p','', 'tagline');message.setAttribute('role','status');
 d.append(title,body,message,button('Close',()=>{d.close();closeResetDialog();},true));document.body.append(d);
 d.addEventListener('cancel',closeResetDialog);d.showModal();
 const active=()=>resetDialog===d&&epoch===sessionEpoch;
 const fail=e=>{if(active())message.textContent=e.message||String(e);};
 async function observe(){if(!active())return;try{const state=await(await api('/api/cartridge-reset')).json();if(!active())return;show(state);if(state.busy||['PREPARING','APPLYING','BACKING_UP'].includes(state.state))resetPoll=setTimeout(observe,1500);}catch(e){fail(e);if(active())message.textContent+=' Close and reopen to inspect the saved result. A lost browser connection does not cancel a started write.';}}
 function show(s){
  body.replaceChildren();message.textContent=s.error||'';body.append(el('h3',s.state.replaceAll('_',' ')));
  if(s.preview){const p=s.preview;body.append(row('Operation',p.kind==='tank'?'Change tank material; preserve lifetime':p.action==='material_assignment'?'Change reported material; preserve usage':(p.action==='restore_usage'?'Restore saved usage; preserve identity and advance write count':'Reset electronic usage')),row('Material',p.material),row(p.kind==='tank'?'Scope':'Nominal capacity',p.kind==='tank'?'T/65 tank 3.3; lifetime unchanged':p.nominal_ml+' mL'),row('Physical resin level','Not measured'));
   body.append(table(['Electronic field','Before','Planned after'],Object.keys(p.before).map(k=>[k,p.before[k],p.after[k]])));
  }
  if(s.state==='ALREADY_FRESH')body.append(el('p','The requested state already matches. No EEPROM write or service restart is needed.'));
  if(s.state==='READY'){
   body.append(el('p','Preview expires after five minutes. A fresh target and idle check runs again before any write. This action backs up the original state and briefly restarts the cartridge service.'));
   const isTank=s.preview&&s.preview.kind==='tank';const isMaterial=s.preview&&s.preview.action==='material_assignment';const form=el('form'),phrase=input(form,isTank?'Type CHANGE CLEAN TANK MATERIAL':isMaterial?'Type CHANGE CARTRIDGE MATERIAL':'Type APPLY CARTRIDGE USAGE','reset-confirmation',''),secret=input(form,'Re-enter owner access secret','reset-secret','','password');secret.autocomplete='off';
   let clean=null;if(isTank){const label=el('label');clean=document.createElement('input');clean.type='checkbox';clean.id='tank-empty-clean';label.append(clean,document.createTextNode(' I confirm this tank is empty, cleaned and ready for the selected material.'));form.append(label,el('p','Lifetime, print history, film identity and safety checks stay unchanged. A material label does not establish chemical compatibility.'));}
   const apply=el('button',isTank?'Change reported tank material':isMaterial?'Change reported cartridge material':'Apply electronic usage');apply.type='submit';apply.disabled=!!s.preview&&s.preview.apply_ready===false;if(apply.disabled)form.append(el('p',s.preview.apply_blocker,'source-note'));form.append(apply);
   form.addEventListener('submit',async e=>{e.preventDefault();if(!active()||apply.disabled)return;apply.disabled=true;const value=secret.value;secret.value='';try{const payload={plan_id:s.plan_id,confirmation:phrase.value,secret:value};if(isTank)payload.tank_empty_clean=clean.checked;const s2=await(await api(isTank?'/api/cartridge-reset/tank-material-apply':isMaterial?'/api/cartridge-reset/material-apply':'/api/cartridge-reset/apply',payload)).json();if(active()){show(s2);resetPoll=setTimeout(observe,1000);}}catch(e){fail(e);apply.disabled=false;}});body.append(form);
  }
  if(s.state==='PREPARING')body.append(el('p','Reading the connected consumable and verifying pinned firmware. This can take about a minute on the printer; no memory write occurs during preview.'));
  if(s.state==='APPLYING')body.append(el('p','Private backup → reviewed file/memory transaction → full readbacks → service reload. Keep power connected. Closing this dialog does not cancel the transaction.'));
  if(s.stages)body.append(table(['Verification','Result'],Object.entries(s.stages)));
  if(s.usage)body.append(table(['Verified electronic field','Value'],Object.entries(s.usage)));
  if(s.state==='MATERIALS'){body.append(el('p','Catalog membership is not physical resin compatibility. Choose cartridge or tank explicitly. Each operation preserves physical identity. Tank assignment preserves its current lifetime and dates; confirm an empty, cleaned tank before applying.'));const select=el('select');select.id='material-target';select.setAttribute('aria-label','Target cartridge material');s.codes.forEach(code=>{const o=el('option',code);o.value=code;select.append(o);});body.append(select,button('Review cartridge material change',()=>authenticate('/api/cartridge-reset/material-preview',{material:select.value})));const tank=button('Review tank material change',()=>authenticate('/api/cartridge-reset/tank-material-preview',{material:select.value}));tank.disabled=!s.tank_write_available;body.append(tank,el('p',s.tank_reason,'source-note'));}
  if(s.state==='BACKUP_COMPLETE')body.append(el('p','Private backup saved and verified. No EEPROM write or service restart.'),row('Backup ID',s.backup.id),row('Kind',s.backup.kind),row('Memory bytes',s.backup.bytes),row('Validation',s.backup.validation));
  if(s.state==='BACKUPS'){body.append(el('p','Showing the latest '+s.backups.length+' of '+s.total+' retained backups. Older backups remain in the private store.'));body.append(el('p','Raw backups contain device-private data and remain root-only. Cartridge restore recovers usage for the same chip and material. Tank restore recovers the saved material label for the same tank and keeps current lifetime values; it is not a full-memory or lifetime reset.'));for(const b of s.backups){const box=el('section');box.append(row('Saved',new Date(b.created*1000).toISOString()),row('Kind / material',b.kind+' / '+b.material),row('Memory SHA256',b.eeprom_sha256));const restore=button(b.kind==='tank'?'Review saved tank material':'Review saved usage restore',()=>authenticate('/api/cartridge-reset/restore-preview',{backup_id:b.id}));restore.disabled=b.kind==='tank'&&!s.tank_restore_available;box.append(restore);body.append(box);}}
  if(s.state==='COMPLETE')body.append(el('p','The requested electronic change was verified after service reload. Private backups are retained on the printer. Physical resin quantity remains unknown.'));
  if(s.state==='RECOVERY_REQUIRED')body.append(el('p','Further resets are locked. Preserve the printer and private receipts for review; do not retry blindly.'));
  if(['AVAILABLE','READY','UNAVAILABLE','EXPIRED','COMPLETE','ALREADY_FRESH','BACKUP_COMPLETE','BACKUPS','MATERIALS'].includes(s.state)){body.append(button('Prepare a fresh preview',()=>authenticate(),true),button('Back up cartridge',()=>authenticate('/api/cartridge-reset/backup',{kind:'cartridge'}),true),button('Back up tank',()=>authenticate('/api/cartridge-reset/backup',{kind:'tank'}),true),button('Review saved backups',()=>authenticate('/api/cartridge-reset/backups',{}),true),button('Review material assignment',()=>authenticate('/api/cartridge-reset/materials',{}),true));}
 }
 function authenticate(endpoint='/api/cartridge-reset/prepare',payload={}){body.replaceChildren();message.textContent='';body.append(el('p','Owner authentication is required even when ordinary WLAN viewing does not require login. HTTP sends credentials unencrypted; use the isolated HTTPS path when needed.'));
  const form=el('form'),secret=input(form,'Owner access secret','reset-login','','password');secret.autocomplete='off';const go=el('button','Authenticate & preview');go.type='submit';form.append(go);
  form.addEventListener('submit',async e=>{e.preventDefault();if(!active()||go.disabled)return;go.disabled=true;const value=secret.value;secret.value='';try{const login=await(await api('/api/login',{secret:value})).json();if(!active())return;csrf=login.csrf;const s=await(await api(endpoint,payload)).json();if(active()){show(s);if(s.busy||['PREPARING','APPLYING','BACKING_UP'].includes(s.state))resetPoll=setTimeout(observe,1000);}}catch(e){fail(e);go.disabled=false;}});body.append(form);
 }
 observe();
}
