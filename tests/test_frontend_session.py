"""Execute actual frontend async flows with deferred synthetic HTTP responses."""
import subprocess,unittest
from pathlib import Path

class FrontendSession(unittest.TestCase):
    def test_panel_release_version_matches_source_version(self):
        root=Path(__file__).resolve().parents[1]
        import ast
        assignments=ast.parse((root/'owner-ui/panel_data.py').read_text()).body
        value=next(ast.literal_eval(x.value) for x in assignments if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in x.targets))
        self.assertEqual(value,(root/'VERSION').read_text().strip())
    def test_logout_discards_delayed_status_and_errors(self):
        source=Path(__file__).resolve().parents[1]/'owner-ui/static/app.js'
        js=r'''
const vm=require('vm'),fs=require('fs'),assert=require('assert');
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{hidden:false,textContent:'',dataset:{},listeners:{},append(){},replaceChildren(){},addEventListener(n,f){this.listeners[n]=f;}});return nodes.get(id);}
const pending=[];const sandbox={console,Map,URL,Error,JSON,Promise,Number,String,Object,Array,Date,clearTimeout(){},setTimeout(){return 1;},window:{scrollTo(){}},document:{getElementById:node,createElement:t=>({dataset:{},append(){},addEventListener(){}}),querySelectorAll(){return [];}},fetch(path){return new Promise((resolve,reject)=>pending.push({path,resolve,reject}));}};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),'reset.js'),'utf8'),sandbox);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),sandbox);
function response(value){return {ok:true,json:async()=>value};}
(async()=>{
  // Prevent startup login; this fixture tests explicit refresh and logout races.
  pending.shift().resolve(response({authentication_required:true}));await new Promise(setImmediate);
  for(const failure of [false,true]){
    vm.runInContext("csrf='synthetic';snapshot={};document.getElementById('dashboard').hidden=false",sandbox);
    const refresh=vm.runInContext('refresh()',sandbox);assert.equal(pending.length,4);
    const status=pending.splice(0);
    const logout=node('logout').listeners.click();assert.equal(pending.length,1);
    assert.equal(node('dashboard').hidden,true,'logout must hide immediately');
    const logoutRequest=pending.shift();logoutRequest.resolve(response({}));await logout;
    for(const x of status){if(failure)x.reject(new Error('old session failure'));else x.resolve(response({}));}
    await refresh;
    assert.equal(node('dashboard').hidden,true,'old refresh reopened dashboard');
    assert.equal(vm.runInContext('snapshot',sandbox),null);
    assert.equal(vm.runInContext('csrf',sandbox),'');
  }
  // Authentication failure invalidates another in-flight refresh too.
  const r=vm.runInContext('refresh()',sandbox);const queued=pending.splice(0);
  vm.runInContext("error({status:401,message:'expired'})",sandbox);
  queued.forEach(x=>x.resolve(response({})));await r;
  assert.equal(node('dashboard').hidden,true);assert.equal(vm.runInContext('snapshot',sandbox),null);
  console.log('3 deferred-response cases passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run(['node','-e',js,str(source)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertIn(b'3 deferred-response cases passed',result.stdout)

if __name__=='__main__':unittest.main()
