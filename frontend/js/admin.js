/* MEDD Maharashtra 2.0 — admin.js : "Data Management" page (new in 2.0; no 1.0 module was changed for it).
 * Shows ingestion status + history, validation reports, upload (data managers), rollback of the latest load,
 * KPI reconciliation against the MEDD 1.0 dashboard figures, and the audit trail. */
const ST_CLS={SUCCESS:'low',SUCCESS_WITH_WARNINGS:'med',FAILED:'crit',DUPLICATE:'',PROCESSING:'med',RECEIVED:'',ROLLED_BACK:'high'};
async function renderAdmin(){
  setCrumbScope();
  const el=document.getElementById('page-admin');
  const canW=API.can('ingestion:write'), canR=API.can('ingestion:read');
  if(!canR){el.innerHTML='<h2 class="secTitle">Data Management</h2><div class="card">Your role does not have access to data management.</div>';return;}
  el.innerHTML=`<h2 class="secTitle">Data Management</h2>
    <p class="muted" style="margin-bottom:14px">Excel / CSV / JSON files placed in <code>backend/data/incoming/</code> (or uploaded below) are detected automatically, validated, staged and applied to PostgreSQL in a single transaction. A failed file never changes production data. The dashboard refreshes itself when new data commits.</p>
    <div class="statbar" id="admStats"></div>
    <div class="grid2">
      <div class="card"><h3>Upload a workbook</h3>
        ${canW?`<div class="desc">Accepted: .xlsx, .xlsm, .xls, .csv, .json. The file goes to the incoming folder and is processed by the watcher.</div>
        <form id="upForm" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><input type="file" id="upFile" accept=".xlsx,.xlsm,.xls,.csv,.json" required>
        <button class="btn" type="submit" style="background:var(--primary);color:#fff">Upload &amp; process</button></form><div id="upMsg" class="muted" style="margin-top:8px"></div>`
        :'<div class="muted">Your role can view ingestion history but not upload files.</div>'}
        <div id="watchInfo" class="muted" style="margin-top:12px"></div></div>
      <div class="card"><h3>KPI reconciliation vs MEDD 1.0 <span class="seg" id="recSeg"><button data-l="overview" class="on">State</button><button data-l="division">Division</button><button data-l="institute">Institute</button><button data-l="department">Department</button></span></h3>
        <div class="desc">Live PostgreSQL figures compared with the numbers embedded in the original dashboard. Differences mean the source workbook versions differ — see the ingestion report.</div>
        <div class="scroll" style="max-height:330px"><table id="recTable"></table></div></div>
    </div>
    <div class="card" style="margin-top:16px"><h3>Ingestion history</h3><div class="scroll tall"><table id="ingTable"></table></div></div>
    <div class="card hide" id="ingDetail" style="margin-top:16px"></div>
    ${API.can('audit:read')?'<div class="card" style="margin-top:16px"><h3>Audit trail (latest 100)</h3><div class="scroll" style="max-height:360px"><table id="audTable"></table></div></div>':''}`;
  if(canW){document.getElementById('upForm').onsubmit=async ev=>{ev.preventDefault();
    const f=document.getElementById('upFile').files[0]; if(!f)return; const msg=document.getElementById('upMsg');
    msg.textContent='Uploading '+f.name+'…'; const fd=new FormData(); fd.append('file',f);
    try{const r=await API.post('/ingestion/upload',fd); msg.innerHTML='✅ '+escapeHtml(r.message)+' Watch the history below — it updates automatically.';
      setTimeout(loadIngestion,4000);}catch(e){msg.textContent='❌ '+e.message;}};}
  document.querySelectorAll('#recSeg button').forEach(b=>b.onclick=()=>{document.querySelectorAll('#recSeg button').forEach(x=>x.classList.toggle('on',x===b));loadRecon(b.dataset.l);});
  loadIngestion(); loadRecon('overview'); if(API.can('audit:read'))loadAudit();
}
async function loadIngestion(){
  if(state.page!=='admin')return;
  let files=[],w={};
  try{[files,w]=await Promise.all([API.get('/ingestion/files',{limit:50}),API.get('/ingestion/watcher')]);}catch(e){showError(e.message);return;}
  const m=(DATA&&DATA.meta)||{};
  document.getElementById('admStats').innerHTML=[['Line items in production',fmt(m.line_items)],['Data version',m.data_version||0],
    ['Last refresh',m.last_refresh?new Date(m.last_refresh).toLocaleString('en-IN'):'—'],['Watcher',w.running?(w.busy?'⏳ processing':'✅ watching'):(w.enabled?'⚠ stopped':'disabled')],
    ['Files waiting',fmt((w.incoming_files||[]).length)]].map(s=>`<div class="stat"><div class="l">${s[0]}</div><div class="v">${s[1]}</div></div>`).join('');
  document.getElementById('watchInfo').innerHTML=`Watched folder: <code>${escapeHtml(w.folder||'')}</code>`;
  const latestOk=files.find(f=>/^SUCCESS/.test(f.status)&&f.rows_read>0);
  document.getElementById('ingTable').innerHTML='<thead><tr><th>#</th><th>File</th><th>Status</th><th class="num">Rows</th><th class="num">Rejected</th><th class="num">Inserted</th><th class="num">Updated</th><th class="num">Unchanged</th><th class="num">Deactivated</th><th class="num">Warnings</th><th>Finished</th><th></th></tr></thead><tbody>'+
    files.map(f=>`<tr class="clk" onclick="showIngestion(${f.id})"><td>${f.id}</td><td title="${escapeHtml(f.error_message||'')}">${escapeHtml(f.original_name)}</td><td><span class="pill ${ST_CLS[f.status]||''}">${f.status.replace(/_/g,' ')}</span></td>
      <td class="num">${fmt(f.rows_read)}</td><td class="num">${fmt(f.rows_rejected)}</td><td class="num">${fmt(f.rows_inserted)}</td><td class="num">${fmt(f.rows_updated)}</td><td class="num">${fmt(f.rows_unchanged)}</td><td class="num">${fmt(f.rows_deactivated)}</td><td class="num">${fmt(f.warnings)}</td>
      <td>${f.finished_at?new Date(f.finished_at).toLocaleString('en-IN'):'…'}</td>
      <td>${API.can('ingestion:write')&&latestOk&&latestOk.id===f.id?`<button class="xbtn" onclick="event.stopPropagation();rollbackIngestion(${f.id})" title="Undo this load using the audit history">↶ Roll back</button>`:''}</td></tr>`).join('')+'</tbody>';
  if(!files.length)document.querySelector('#ingTable tbody').innerHTML='<tr><td colspan="12" class="muted">No files processed yet. Drop the master Excel into the incoming folder.</td></tr>';
  if(files.some(f=>['PROCESSING','RECEIVED'].includes(f.status))||w.busy)setTimeout(loadIngestion,3000);
}
async function showIngestion(id){
  const box=document.getElementById('ingDetail'); box.classList.remove('hide'); box.innerHTML='Loading…';
  try{
    const d=await API.get('/ingestion/files/'+id,{per:200});
    const f=d.file;
    box.innerHTML=`<h3>File #${f.id} — ${escapeHtml(f.original_name)} <span class="pill ${ST_CLS[f.status]||''}">${f.status}</span>
      <span class="exp"><button class="xbtn" onclick="viewReport(${f.id})">📄 Full report</button></span></h3>
      ${f.error_message?`<div class="rec r-crit"><div class="ic">⚠</div><div><h4>Result</h4><p>${escapeHtml(f.error_message)}</p></div></div>`:''}
      <div class="desc">SHA-256 <code>${f.sha256}</code> · ${fmt(f.size_bytes)} bytes · sync mode ${escapeHtml(f.sync_mode||'')} · triggered by ${escapeHtml(f.triggered_by)}</div>
      <div class="grid2"><div><b>Worksheets</b><table>${d.sheets.map(s=>`<tr><td>${escapeHtml(s.sheet_name)}</td><td>${s.dataset_type}</td><td class="num">${fmt(s.rows_read)} rows</td><td class="muted">${Object.keys(s.column_map||{}).length} columns mapped${(s.unmapped_columns||[]).length?', '+s.unmapped_columns.length+' unused':''}</td></tr>`).join('')}</table></div>
      <div><b>Issues by type</b><table>${d.issue_summary.map(i=>`<tr><td><span class="pill ${i.severity==='ERROR'?'crit':i.severity==='WARNING'?'med':''}">${i.severity}</span></td><td>${i.code}</td><td class="num">${fmt(i.n)}</td></tr>`).join('')||'<tr><td class="muted">None</td></tr>'}</table></div></div>
      <div style="margin-top:10px"><b>First ${d.issues.length} issues</b><div class="scroll" style="max-height:300px"><table><thead><tr><th>Severity</th><th>Code</th><th>Sheet</th><th class="num">Row</th><th>Field</th><th>Value</th><th>Message</th></tr></thead><tbody>
      ${d.issues.map(i=>`<tr><td>${i.severity}</td><td>${i.code}</td><td>${escapeHtml(i.sheet_name||'')}</td><td class="num">${i.row_no||''}</td><td>${i.field||''}</td><td>${escapeHtml(i.value||'')}</td><td>${escapeHtml(i.message)}</td></tr>`).join('')}</tbody></table></div></div>`;
    box.scrollIntoView({behavior:'smooth'});
  }catch(e){box.textContent=e.message;}
}
async function viewReport(id){
  try{const md=await API.get('/ingestion/files/'+id+'/report');
    const w=window.open('','_blank'); w.document.write('<pre style="white-space:pre-wrap;font:12px/1.5 monospace;padding:16px">'+escapeHtml(md)+'</pre>'); w.document.close();
  }catch(e){showError(e.message);}
}
async function rollbackIngestion(id){
  if(!confirm(`Roll back file #${id}? All line-item changes made by this load will be reverted (inserts deactivated, updates restored, deactivations re-activated). This is recorded in the audit log.`))return;
  try{const r=await API.post('/ingestion/files/'+id+'/rollback',{}); toast(`↶ Rolled back ${fmt(r.changes_reverted)} changes from file #${id}.`,'ok'); loadIngestion();}
  catch(e){showError(e.message);}
}
async function loadRecon(level){
  const t=document.getElementById('recTable'); if(!t)return; t.innerHTML='<tr><td class="muted">Loading…</td></tr>';
  let r; try{r=await API.get('/reconciliation',{level});}catch(e){t.innerHTML=`<tr><td>${escapeHtml(e.message)}</td></tr>`;return;}
  const keys=[['required','Req'],['functional','Func'],['procurement','Proc.'],['budget','Budget ₹'],['gap_pct','Util %']];
  const cell=(m,k)=>{const x=m[k];if(x.legacy==null&&x.live==null)return '<td class="num">—</td>';
    const d=x.diff, ok=d!=null&&Math.abs(d)<0.5; const v=k==='budget'?cr(x.live):k==='gap_pct'?x.live+'%':fmt(x.live);
    return `<td class="num" title="1.0: ${k==='budget'?cr(x.legacy):x.legacy} · 2.0: ${k==='budget'?cr(x.live):x.live}">${v}${ok?'':` <span style="color:#d73027;font-size:10.5px">(${d==null?'n/a':(d>0?'+':'')+(k==='budget'?cr(d):fmt(d))})</span>`}</td>`;};
  t.innerHTML=`<thead><tr><th>${level}</th>${keys.map(k=>`<th class="num">${k[1]}</th>`).join('')}<th>Match</th></tr></thead><tbody>`+
    r.rows.map(x=>`<tr><td>${escapeHtml(x.name)}${x.in_legacy?'':' <span class="muted">(new)</span>'}${x.in_live?'':' <span class="muted">(not in DB)</span>'}</td>${keys.map(k=>cell(x.metrics,k[0])).join('')}<td>${x.match?'✅':'⚠'}</td></tr>`).join('')+
    `</tbody><caption style="caption-side:bottom;text-align:left" class="muted">${r.matched} of ${r.total} match exactly. Hover a value for 1.0 vs 2.0.</caption>`;
}
async function loadAudit(){
  try{const rows=await API.get('/admin/audit',{limit:100});
    document.getElementById('audTable').innerHTML='<thead><tr><th>When</th><th>Who</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead><tbody>'+
      rows.map(a=>`<tr><td>${new Date(a.occurred_at).toLocaleString('en-IN')}</td><td>${escapeHtml(a.actor)}</td><td>${escapeHtml(a.action)}</td><td>${escapeHtml((a.entity||'')+(a.entity_id?' #'+a.entity_id:''))}</td><td class="muted" style="max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(JSON.stringify(a.details))}">${escapeHtml(JSON.stringify(a.details)).slice(0,160)}</td></tr>`).join('')+'</tbody>';
  }catch(e){}
}
