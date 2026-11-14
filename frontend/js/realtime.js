/* MEDD Maharashtra 2.0 — realtime.js : automatic dashboard refresh after ingestion.
 * Server-Sent Events from GET /api/v1/events (driven by PostgreSQL LISTEN/NOTIFY, so a notification is only sent
 * once new data has COMMITTED). Falls back to polling /dashboard/status if the event stream drops. */
let _es=null, _pollTimer=null;
function startRealtime(){
  stopRealtime();
  try{
    const tok=API.token?('?token='+encodeURIComponent(API.token)):'';
    _es=new EventSource((window.MEDD_CONFIG.API_BASE||'/api/v1')+'/events'+tok);
    _es.addEventListener('data_refreshed',e=>{const m=JSON.parse(e.data);onDataRefreshed(m);});
    _es.addEventListener('ingestion_failed',e=>{const m=JSON.parse(e.data);
      toast(`⚠ Upload “${escapeHtml(m.file||'')}” failed validation — production data unchanged. See Data Management.`,'warn');
      if(state.page==='admin')renderAdmin();});
    _es.onerror=()=>{ if(!_pollTimer) _pollTimer=setInterval(pollStatus,60000); };
    _es.onopen=()=>{ if(_pollTimer){clearInterval(_pollTimer);_pollTimer=null;} };
  }catch(e){ _pollTimer=setInterval(pollStatus,60000); }
}
function stopRealtime(){ if(_es){_es.close();_es=null;} if(_pollTimer){clearInterval(_pollTimer);_pollTimer=null;} }
async function pollStatus(){
  try{ const s=await API.get('/dashboard/status');
    if(DATA&&DATA.meta&&s.data_version!==DATA.meta.data_version) onDataRefreshed({data_version:s.data_version,file:(s.last_success||{}).original_name}); }
  catch(e){}
}
let _refreshing=false;
async function onDataRefreshed(m){
  if(_refreshing)return; _refreshing=true;
  try{
    showBusy(true);
    await loadBootstrap();
    // preserve active filters wherever the selected values still exist in the new data
    const keep=(arr,valid)=>arr.filter(x=>valid.has(x));
    state.division=keep(state.division,new Set(DATA.divisions.map(d=>d.name)));
    state.institute=keep(state.institute,new Set(DATA.institutes.map(d=>d.name)));
    state.department=keep(state.department,new Set(DATA.departments.map(d=>d.name)));
    state.equipment=keep(state.equipment,new Set(DATA.equipment_names));
    state.subcat=keep(state.subcat,new Set(DATA.sub_categories));
    state.bedded=keep(state.bedded,new Set((DATA.bedded_capacities||[]).map(String)));
    await refreshScope();
    renderSlicers(); renderStatusBar(); renderFooter();
    if(document.getElementById('page-detail').classList.contains('hide')) renderPage(state.page); else route();
    toast(`✅ Dashboard updated with the latest validated data${m.file?' from “'+escapeHtml(m.file)+'”':''} (data version ${m.data_version}).`,'ok');
  }catch(e){ showError('Automatic refresh failed: '+e.message); }
  finally{ showBusy(false); _refreshing=false; }
}
function renderStatusBar(){
  const el=document.getElementById('dataStatus'); if(!el||!DATA)return;
  const m=DATA.meta||{}, li=m.last_ingestion||{};
  const when=m.last_refresh?new Date(m.last_refresh).toLocaleString('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}):'never';
  const st=li.status?`<span class="pill ${/FAIL/.test(li.status)?'crit':/WARN/.test(li.status)?'med':'low'}" title="${escapeHtml(li.original_name||'')}">${li.status.replace(/_/g,' ').toLowerCase()}</span>`:'';
  el.innerHTML=`<span title="Last successful database refresh">🔄 Data refreshed <b>${when}</b></span> <span class="muted">v${m.data_version||0}</span> ${st}`;
}
function toast(html,kind){
  const t=document.createElement('div'); t.className='toast '+(kind||''); t.innerHTML=html;
  document.body.appendChild(t); setTimeout(()=>t.classList.add('show'),10);
  setTimeout(()=>{t.classList.remove('show');setTimeout(()=>t.remove(),400);},7000);
}
