"use strict";
// Independent dialog: periodic status refresh never destroys confirmation input.
let resetDialog=null,resetPoll=null;
function closeResetDialog(){clearTimeout(resetPoll);if(resetDialog){resetDialog.remove();resetDialog=null;}}
function cartridgeResetCard(){
 const p=panel('Clear cartridge usage reset','Reviewed scope: legacy Clear FLGPCL02, 1000 mL. Resets electronic usage only; it does not measure or add resin. Material and chip identity stay unchanged.');
 p.append(el('p','Keep the printer idle. Do not start a job, remove the cartridge or switch power during the transaction. Other cartridge formats are refused.','tagline'));
 p.append(button('Review cartridge reset',openResetDialog));return p;
}
function openResetDialog(){
 closeResetDialog();const epoch=sessionEpoch,d=el('dialog',undefined,'reset-dialog');resetDialog=d;
 const title=el('h2','Clear usage reset'),body=el('div'),message=el('p','', 'tagline');message.setAttribute('role','status');
 d.append(title,body,message,button('Close',()=>{d.close();closeResetDialog();},true));document.body.append(d);
 d.addEventListener('cancel',closeResetDialog);d.showModal();
 const active=()=>resetDialog===d&&epoch===sessionEpoch;
 const fail=e=>{if(active())message.textContent=e.message||String(e);};
 async function observe(){if(!active())return;try{const state=await(await api('/api/cartridge-reset')).json();if(!active())return;show(state);if(state.busy||['PREPARING','APPLYING'].includes(state.state))resetPoll=setTimeout(observe,1500);}catch(e){fail(e);if(active())message.textContent+=' Close and reopen to inspect the saved result. A lost browser connection does not cancel a started write.';}}
 function show(s){
  body.replaceChildren();message.textContent=s.error||'';body.append(el('h3',s.state.replaceAll('_',' ')));
  if(s.preview){const p=s.preview;body.append(row('Material',p.material),row('Nominal capacity',p.nominal_ml+' mL'),row('Physical resin level','Not measured'));
   body.append(table(['Electronic field','Before','Planned after'],Object.keys(p.before).map(k=>[k,p.before[k],p.after[k]])));
  }
  if(s.state==='ALREADY_FRESH')body.append(el('p','Usage is already zero. No EEPROM write or service restart is needed.'));
  if(s.state==='READY'){
   body.append(el('p','Preview expires after five minutes. A fresh target and idle check runs again before any write. This action backs up the original state and briefly restarts the cartridge service.'));
   const form=el('form'),phrase=input(form,'Type RESET CLEAR USAGE','reset-confirmation',''),secret=input(form,'Re-enter owner access secret','reset-secret','','password');secret.autocomplete='off';
   const apply=el('button','Reset electronic usage');apply.type='submit';form.append(apply);
   form.addEventListener('submit',async e=>{e.preventDefault();if(!active()||apply.disabled)return;apply.disabled=true;const value=secret.value;secret.value='';try{const s2=await(await api('/api/cartridge-reset/apply',{plan_id:s.plan_id,confirmation:phrase.value,secret:value})).json();if(active()){show(s2);resetPoll=setTimeout(observe,1000);}}catch(e){fail(e);apply.disabled=false;}});body.append(form);
  }
  if(s.state==='APPLYING')body.append(el('p','Backup → persistent record → copy B → copy A → readback → service reload. Keep power connected. Closing this dialog does not cancel the transaction.'));
  if(s.stages)body.append(table(['Verification','Result'],Object.entries(s.stages)));
  if(s.usage)body.append(table(['Verified electronic field','Value'],Object.entries(s.usage)));
  if(s.state==='COMPLETE')body.append(el('p','Usage reset verified after service reload. Private backups are retained on the printer. Physical resin quantity remains unknown.'));
  if(s.state==='RECOVERY_REQUIRED')body.append(el('p','Further resets are locked. Preserve the printer and private receipts for review; do not retry blindly.'));
  if(['AVAILABLE','UNAVAILABLE','EXPIRED','COMPLETE','ALREADY_FRESH'].includes(s.state))body.append(button('Prepare a fresh preview',()=>authenticate(),true));
 }
 function authenticate(){body.replaceChildren();message.textContent='';body.append(el('p','Owner authentication is required even when ordinary WLAN viewing does not require login. HTTP sends credentials unencrypted; use the isolated HTTPS path when needed.'));
  const form=el('form'),secret=input(form,'Owner access secret','reset-login','','password');secret.autocomplete='off';const go=el('button','Authenticate & preview');go.type='submit';form.append(go);
  form.addEventListener('submit',async e=>{e.preventDefault();if(!active()||go.disabled)return;go.disabled=true;const value=secret.value;secret.value='';try{const login=await(await api('/api/login',{secret:value})).json();if(!active())return;csrf=login.csrf;const s=await(await api('/api/cartridge-reset/prepare',{})).json();if(active()){show(s);resetPoll=setTimeout(observe,1000);}}catch(e){fail(e);go.disabled=false;}});body.append(form);
 }
 observe();
}
