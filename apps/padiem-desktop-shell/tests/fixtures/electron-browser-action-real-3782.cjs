/** #3782 opt-in real Windows Electron test, never a real owner P01. */
const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict');
const http=require('node:http');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
let win,server;
async function run(){
  await app.whenReady();
  server=http.createServer((_req,res)=>{
    res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
    res.end('<html><head><title>BEFORE</title></head><body style="margin:0">'+
      '<button style="position:absolute;left:55px;top:50px;width:130px;height:55px" '+
      'onclick="document.title=\'AFTER\'">Local only tab</button></body></html>');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  win=new BrowserWindow({show:true,width:500,height:350,
    webPreferences:{sandbox:true,nodeIntegration:false,contextIsolation:true}});
  await win.loadURL(origin+'/');
  win.focus();win.webContents.focus();
  const root=path.resolve(__dirname,'..','..','dist','src','browser');
  const {createElectronBrowserActionBinding}=await import(pathToFileURL(path.join(root,'browser-action-electron-binding.js')).href);
  const {createElectronBrowserObservationSource}=await import(pathToFileURL(path.join(root,'browser-observation-electron-source.js')).href);
  const observer=createElectronBrowserObservationSource(win.webContents);
  const before=await observer.snapshot();
  const button=before.elements.find(x=>x.role==='button'&&x.name==='Local only tab');
  assert.ok(button,'real AX node must obtain a box before Input');
  assert.deepEqual(button.bounds,{x:55,y:50,width:130,height:55});
  assert.equal(before.origin,origin);
  assert.equal(win.webContents.getTitle(),'BEFORE');
  const actor=createElectronBrowserActionBinding(win.webContents);
  await actor.dispatch([{kind:'click',x:button.bounds.x+button.bounds.width/2,
    y:button.bounds.y+button.bounds.height/2}]);
  await new Promise(resolve=>setTimeout(resolve,180));
  assert.equal(win.webContents.getTitle(),'AFTER','actual Chromium mouse input executes');
  await actor.close();await observer.close();
  console.log('PADIEM_REAL_ELECTRON_BROWSER_TEST=PASS');
}
run().catch(e=>{console.error('PADIEM_REAL_ELECTRON_BROWSER_TEST=FAIL',e?.message);process.exitCode=1})
  .finally(()=>{try{win?.destroy()}catch{}try{server?.close()}catch{}app.quit()});
