/* MEDD Maharashtra 2.0 — main.js : start-up sequence.
 * 1.0 rendered synchronously from embedded data. 2.0: authenticate -> load the bootstrap payload built from
 * PostgreSQL -> load exact aggregates for the active filters -> wire the (unchanged) 1.0 controls -> route
 * -> subscribe to live refresh events. */
let _wired=false;
function wireControls(){
  if(_wired)return; _wired=true;
  // ---- original 1.0 control wiring (unchanged) ----
renderSlicers();
document.getElementById('clearBtn').onclick=resetFilters;
document.getElementById('backBtn').onclick=()=>go('#'+state.page);
document.querySelectorAll('#nav a').forEach(a=>a.onclick=()=>{go('#'+a.dataset.page);document.getElementById('sidebar').classList.remove('open');});
document.getElementById('menuBtn').onclick=()=>document.getElementById('sidebar').classList.toggle('open');
['metricSeg','metricSeg2'].forEach(id=>{const seg=document.getElementById(id);if(!seg)return;
  seg.querySelectorAll('button').forEach(b=>b.onclick=()=>{state.metric=b.dataset.m;
    document.querySelectorAll('#'+id+' button').forEach(x=>x.classList.toggle('on',x===b));
    renderPage(state.page);});});
document.querySelectorAll('#divTable th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortDiv.dir=sortDiv.k===k?-sortDiv.dir:-1;sortDiv.k=k;renderDivTable();});
document.querySelectorAll('#instTable th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortInst.dir=sortInst.k===k?-sortInst.dir:-1;sortInst.k=k;renderInstTable();});


}
async function boot(){
  showBusy(true);
  try{
    if(!API.token){
      const cfg=await API.get('/auth/config');
      if(cfg.auth_enabled){ showBusy(false); showLogin(); return; }
      API.setSession('',await API.get('/auth/me'));   // AUTH_ENABLED=false (development only)
    }
    await loadBootstrap();
    await refreshScope();
    renderUserBadge(); renderSlicers(); wireControls(); renderStatusBar();
    if(!DATA.overview.line_items) showError('The database has no equipment data yet. Place the master Excel workbook in backend/data/incoming (or upload it under Data Management) — the dashboard will refresh automatically.');
    await route();
    startRealtime();
  }catch(e){
    if(e.status!==401) showError('Could not load the dashboard: '+e.message);
  }finally{ showBusy(false); }
}
document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('loginForm').onsubmit=doLogin;
  boot();
});
