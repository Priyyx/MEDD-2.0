/* MEDD Maharashtra 2.0 — dataset-explorer.js
 * Code below is carried over from the MEDD 1.0 index.html (inline script); changes for the
 * PostgreSQL/API integration are marked with  // [2.0]  comments. See docs/05_CHANGE_LOG.md. */
/* ===== Cost Mapping Table (Net Requirement page) ===== */
let _cmState={page:0,per:25,q:'',sortK:8,sortDir:-1};
function costMapRows(){
  const CM=DATA.cost_map; if(!CM) return [];
  const appEq=applicableEquipNames();
  const divOk=state.division.length?new Set(state.division):null;
  const instOk=state.institute.length?new Set(state.institute):null;
  const deptOk=state.department.length?new Set(state.department):null;
  const catOk=(_cmState.cat)?_cmState.cat:null;
  const out=[];
  for(const r of rows_iter(CM)){
    const eqName=CM.eq[r[0]], divName=CM.div[r[1]], instName=CM.inst[r[2]], deptName=CM.dept[r[3]];
    if(divOk&&!divOk.has(divName))continue;
    if(instOk&&!instOk.has(instName))continue;
    if(deptOk&&!deptOk.has(deptName))continue;
    if(appEq&&!appEq.has(eqName))continue;
    if(state.bedded.length){const inst=DATA.institutes.find(i=>i.name===instName);if(!inst||inst.seat==null||!state.bedded.includes(String(inst.seat)))continue;}
    out.push({eq:eqName,div:divName,inst:instName,dept:deptName,req:r[4],avail:r[5],func:r[6],netreq:r[7],uc:r[8],total:r[9],cat:['Low','Medium','High'][r[10]]});
  }
  return out;
}
function rows_iter(CM){return CM.rows;}
function renderCostMapping(){
  const host=document.getElementById('page-netreq');
  if(document.getElementById('costMapWrap'))return renderCostMapBody(); // already built, just refresh
  const div=document.createElement('div');div.id='costMapWrap';div.className='card';div.style.marginTop='18px';
  div.innerHTML=`<h3 style="margin-bottom:6px">Cost Mapping Table <span id="cmExport"></span></h3>
    <div class="muted" style="margin-bottom:10px">Estimated procurement cost for each equipment shortfall (Net Requirement &gt; 0) by institute. <b>Total Estimated Cost = Net Requirement × Unit Cost.</b> Responds to all active slicers.</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
      <input id="cmSearch" placeholder="Search equipment / institute / division…" style="flex:1;min-width:220px;padding:8px 11px;border:1px solid var(--bd);border-radius:8px;font-size:13px">
      <select id="cmCat" style="padding:8px;border:1px solid var(--bd);border-radius:8px;font-size:13px"><option value="">All cost categories</option><option>Low</option><option>Medium</option><option>High</option></select>
      <div id="cmTotal" class="pill" style="background:var(--primary);color:#fff;font-weight:700"></div>
    </div>
    <div class="scroll" style="max-height:520px"><table id="cmTable"></table></div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px">
      <div id="cmInfo" class="muted"></div>
      <div id="cmPager" style="display:flex;gap:6px"></div>
    </div>`;
  host.appendChild(div);
  let _cmT=null;  // [2.0] debounce server search
  document.getElementById('cmSearch').oninput=e=>{clearTimeout(_cmT);_cmT=setTimeout(()=>{_cmState.q=e.target.value.trim();_cmState.page=0;renderCostMapBody();},300);};
  document.getElementById('cmCat').onchange=e=>{_cmState.cat=e.target.value;_cmState.page=0;renderCostMapBody();};
  renderCostMapBody();
}
// [2.0] Cost Mapping is filtered, searched, sorted and paginated SERVER-SIDE
//       (GET /api/v1/net-requirement/cost-mapping). The 1.0 embedded DATA.cost_map no longer exists.
const CM_KEYS=['eq','div','inst','dept','req','avail','func','netreq','uc','total','cat'];
let _cmSeq=0;
async function renderCostMapBody(){
  if(!document.getElementById('cmTable'))return;
  const seq=++_cmSeq;
  let res;
  try{ res=await API.get('/net-requirement/cost-mapping',{...filterParams(),q:_cmState.q,cat:_cmState.cat,
        sort:CM_KEYS[_cmState.sortK],dir:_cmState.sortDir>0?'asc':'desc',page:_cmState.page,per:_cmState.per}); }
  catch(e){ showError('Cost mapping: '+e.message); return; }
  if(seq!==_cmSeq||!document.getElementById('cmTable'))return;
  const rows=res.rows;
  document.getElementById('cmTotal').textContent='Total Estimated Cost: '+(res.grand_total==null?'restricted':cr(res.grand_total));
  const per=res.per, total=res.total, pages=res.pages;
  const start=_cmState.page*per, pageRows=rows;
  const cols=[['Equipment','eq',0],['Division','div',1],['Institute','inst',2],['Department','dept',3],['Req','req',4],['Avail','avail',5],['Func','func',6],['Net Req','netreq',7],['Unit Cost ₹','uc',8],['Total Est. Cost ₹','total',9],['Cost Cat.','cat',10]];
  const head='<thead><tr>'+cols.map(c=>{const arrow=_cmState.sortK===c[2]?(_cmState.sortDir>0?' ↑':' ↓'):'';return `<th class="${c[2]>=4&&c[2]<=9?'num':''}" style="cursor:pointer" onclick="cmSort(${c[2]})">${c[0]}${arrow}</th>`;}).join('')+'</tr></thead>';
  const catColor={Low:'#1a9850',Medium:'#fee08b',High:'#d73027'};
  const body='<tbody>'+pageRows.map((r,idx)=>{
    const q=s=>"'"+String(s).replace(/'/g,"\\'")+"'";
    const dcell=(mkey,lvl,path,inner,tip)=>`<td class="drillcell" onclick="event.stopPropagation();drillTo('${mkey}','${lvl}',[${path}])" title="${tip}">${inner}</td>`;
    return `<tr class="cmrow" onclick="cmSelectRow(this)">`+
      `<td>${escapeHtml(r.eq)}</td>`+
      dcell('esttotal','institute',q(r.div),r.div,'Drill: Total Estimated Cost by Institute (this Division)')+
      dcell('esttotal','department',q(r.div)+','+q(r.inst),r.inst,'Drill: by Department (this Division + Institute)')+
      dcell('esttotal','equipment',q(r.div)+','+q(r.inst)+','+q(r.dept),r.dept,'Drill: by Equipment (final level)')+
      `<td class="num">${fmt(r.req)}</td><td class="num">${fmt(r.avail)}</td><td class="num">${fmt(r.func)}</td><td class="num">${sfmt(r.netreq)}</td><td class="num">${fmt(r.uc)}</td><td class="num">${fmt(r.total)}</td><td>${r.cat?`<span class="pill" style="background:${catColor[r.cat]||'#999'};color:${r.cat==='Medium'?'#333':'#fff'}">${r.cat}</span>`:'—'}</td></tr>`;}).join('')+'</tbody>';
  document.getElementById('cmTable').innerHTML=head+body;
  document.getElementById('cmInfo').textContent=`Showing ${total?start+1:0}–${Math.min(start+per,total)} of ${fmt(total)} rows`;
  // pager
  const pg=document.getElementById('cmPager');let ph='';
  const mk=(lbl,pg2,dis)=>`<button class="btn" ${dis?'disabled':''} onclick="cmPage(${pg2})" style="padding:5px 10px;font-size:12px${dis?';opacity:.4':''}">${lbl}</button>`;
  ph+=mk('‹ Prev',_cmState.page-1,_cmState.page<=0);
  ph+=`<span class="muted" style="padding:5px 8px">Page ${_cmState.page+1} / ${pages}</span>`;
  ph+=mk('Next ›',_cmState.page+1,_cmState.page>=pages-1);
  pg.innerHTML=ph;
  // export of ALL filtered rows is generated server-side (see runExport in exports.js)
  document.getElementById('cmExport').innerHTML=exportBtns('cmTable');
}
function cmSort(k){if(_cmState.sortK===k)_cmState.sortDir*=-1;else{_cmState.sortK=k;_cmState.sortDir=(k>=3&&k<=8)?-1:1;}renderCostMapBody();}
function cmPage(p){_cmState.page=p;renderCostMapBody();}
function cmSelectRow(tr){ // equipment row is terminal: highlight/select only, no navigation
  document.querySelectorAll('#cmTable tbody tr.cmsel').forEach(x=>x.classList.remove('cmsel'));
  tr.classList.add('cmsel');
}

/* ===== LIST PAGES (institute / division explorers) ===== */
function renderListPage(page){
  setCrumbScope();
  const el=document.getElementById('page-'+page);
  const isInst=page==='facility';
  let list=isInst?scopeInstitutes().slice():scopeDivisions().slice();   // [2.0] exact filtered aggregates
  if(isInst){
    if(state.division.length)list=list.filter(i=>state.division.includes(i.division));
    if(state.institute.length)list=list.filter(i=>state.institute.includes(i.name));
    if(state.bedded.length)list=list.filter(i=>i.seat!=null&&state.bedded.includes(String(i.seat)));
  } else {
    if(state.division.length)list=list.filter(dv=>state.division.includes(dv.name));
  }
  list.sort((a,b)=>b.gap_pct-a.gap_pct);
  const eid='listTable-'+page;
  el.innerHTML=`<h2 class="secTitle">${isInst?'Institute':'Division'} Dashboard</h2>
    <p class="muted" style="margin-bottom:14px">Tap any ${isInst?'institute':'division'} to open its full decision-support page.</p>
    <div class="card"><h3 style="margin-bottom:10px">${isInst?'All institutes':'All divisions'} ${exportBtns(eid)}</h3><div class="scroll tall"><table id="${eid}">
      <thead><tr><th class="th-sort" data-k="name">${isInst?'Institute':'Division'}</th>${isInst?'<th class="th-sort" data-k="division" title="Administrative division">Division</th>':''}<th class="num th-sort" data-k="required" title="Quantity Required per NMC/NMR">Req</th><th class="num th-sort" data-k="available" title="Available">Avail</th><th class="num th-sort" data-k="functional" title="Functional">Func</th><th class="num th-sort" data-k="net_requirement" title="Net Requirement = Required − Functional (+ shortfall / − surplus)">Net Req</th><th class="num th-sort" data-k="procurement" title="Procurement suggested by colleges">Proc.</th><th class="num th-sort" data-k="gap_pct" title="Utilisation % = Functional ÷ Required × 100">Utilisation %</th><th class="num th-sort" data-k="budget" title="Budget">Budget ₹</th><th class="num th-sort" data-k="amc_pct" title="AMC % = AMC ÷ Functional × 100">AMC %</th></tr></thead>
      <tbody></tbody></table></div>
      ${gapCaption('<b>AMC %</b> = Units under active AMC/CMC ÷ Functional × 100. <b>Net Req</b> = Required − Functional (+ shortfall / − surplus).')}</div>`;
  const nav=isInst?'#institute/':'#division/';
  const rowHtml=x=>{const[cls]=sev(x.gap_pct);
    // each metric cell drills by its own metric. Institute rows start at department, division rows at institute.
    const dc=(mkey,inner)=>{const startLvl=isInst?'department':'institute';
      const pathArr=isInst?[x.division,x.name]:[x.name];
      const pj=pathArr.map(s=>"'"+String(s).replace(/'/g,"\\'")+"'").join(',');
      return `<td class="num drillcell" onclick="event.stopPropagation();drillTo('${mkey}','${startLvl}',[${pj}])" title="Drill ${METRICS[mkey].label}">${inner}</td>`;};
    return `<tr class="clk" onclick="go('${nav}${encodeURIComponent(x.name)}')"><td>${x.name}</td>${isInst?`<td>${x.division}</td>`:''}${dc('required',fmt(x.required))}${dc('available',fmt(x.available))}${dc('functional',fmt(x.functional))}${dc('netreq',sfmt(x.net_requirement))}${dc('procurement',fmt(x.procurement))}${dc('util','<span class="pill '+cls+'">'+x.gap_pct+'%</span>')}${dc('budget',fmt(x.budget))}${dc('amc',x.amc_pct+'%')}</tr>`;};
  makeSortable(eid, list, rowHtml);
  registerExport(eid,'MEDD_'+(isInst?'institutes':'divisions'),
    [isInst?'Institute':'Division'].concat(isInst?['Division']:[]).concat(['Required','Available','Functional','Net Requirement','Procurement','Utilisation %','Budget (Rs)','AMC %']),
    ()=>list.map(x=>[x.name].concat(isInst?[x.division]:[]).concat([x.required,x.available,x.functional,x.net_requirement,x.procurement,x.gap_pct,Math.round(x.budget),x.amc_pct])));
}

/* ===== EQUIPMENT EXPLORER ===== */
let eqSort={k:'procurement',dir:-1};
/* ===== DEPARTMENT DASHBOARD (list) ===== */
let deptSort={k:'gap_pct',dir:-1};
function renderDepartmentList(){
  setCrumbScope();
  const el=document.getElementById('page-department');
  // Build rows, scoped to the active division/institute filter where possible
  // [2.0] exact per-department aggregates under ALL active filters (1.0 approximated from rollups)
  let list=scopeDepartments().slice();
  if(state.department.length)list=list.filter(x=>state.department.includes(x.name));
  list.sort((a,b)=>cmp(a,b,deptSort));
  const scopeNote = state.institute.length?`scoped to ${state.institute.length} institute(s)`:state.division.length?`scoped to ${state.division.length} division(s)`:'state-wide';
  el.innerHTML=`<h2 class="secTitle">Department Dashboard</h2>
    <p class="muted" style="margin-bottom:14px">${fmt(list.length)} departments (${scopeNote}). Tap any department to open its full decision-support drill-down with division, institute and equipment breakdowns.</p>
    <div class="card"><h3 style="margin-bottom:10px">Departments (${scopeNote}) ${exportBtns('deptTable')}</h3><div class="scroll tall"><table id="deptTable">
      <thead><tr><th class="th-sort" data-k="name">Department</th><th class="num th-sort" data-k="required" title="Required per NMC/NMR">Req</th><th class="num th-sort" data-k="available" title="Available">Avail</th><th class="num th-sort" data-k="functional" title="Functional">Func</th><th class="num th-sort" data-k="net_requirement" title="Net Requirement = Required − Functional (+ shortfall / − surplus)">Net Req</th><th class="num th-sort" data-k="procurement" title="Procurement suggested by colleges">Proc.</th><th class="num th-sort" data-k="gap_pct" title="Utilisation % = Functional ÷ Required × 100">Utilisation %</th><th class="num th-sort" data-k="budget" title="Budget">Budget ₹</th></tr></thead>
      <tbody></tbody></table></div>
      ${gapCaption('<b>Net Req</b> = Required − Functional (+ shortfall / − surplus).')}</div>`;
  const drow=x=>{const[cls]=sev(x.gap_pct);
    const dc=(mkey,inner)=>`<td class="num drillcell" onclick="event.stopPropagation();setFilterAndDrill('department',['${String(x.name).replace(/'/g,"\\'")}'],'${mkey}')" title="Drill ${METRICS[mkey].label} (scoped to ${x.name})">${inner}</td>`;
    return `<tr class="clk" onclick="go('#department/${encodeURIComponent(x.name)}')"><td>${x.name}</td>${dc('required',fmt(x.required))}${dc('available',fmt(x.available))}${dc('functional',fmt(x.functional))}${dc('netreq',sfmt(x.net_requirement))}${dc('procurement',fmt(x.procurement))}${dc('util','<span class="pill '+cls+'">'+x.gap_pct+'%</span>')}${dc('budget',fmt(x.budget))}</tr>`;};
  makeSortable('deptTable', list, drow);
  registerExport('deptTable','MEDD_departments',
    ['Department','Required','Available','Functional','Net Requirement','Procurement','Utilisation %','Budget (Rs)'],
    ()=>list.map(x=>[x.name,x.required,x.available,x.functional,x.net_requirement,x.procurement,x.gap_pct,Math.round(x.budget)]));
}
function detailForDepartment(dp){
  const ddivs=(dp.divisions_bd||[]).slice().sort((a,b)=>a.gap_pct-b.gap_pct); // worst (lowest Gap %) first
  return {title:dp.name+' — Department',scope:'State-wide · '+dp.name,
    lede:`${dp.name} · ${fmt(dp.required)} required (NMC MSR), ${fmt(dp.functional)} functional → ${dp.gap_pct}% utilisation${dp.functional_shortfall>0?` (${fmt(dp.functional_shortfall)} working units short)`:' (norm met)'}. ${fmt(dp.procurement)} proposed for procurement · budget ${cr(dp.budget)}. Present in ${(dp.divisions_bd||[]).length} divisions.`,
    stats:[['Required',fmt(dp.required)],['Available',fmt(dp.available)],['Functional',fmt(dp.functional)],['Non-Functional',fmt(dp.non_functional)],
      ['Functional Shortfall',fmt(dp.functional_shortfall)],['Utilisation %',dp.gap_pct+'%'],['Procurement',fmt(dp.procurement)],['Budget',cr(dp.budget)],['Approaching EoL',fmt(dp.end_of_life)]],
    chart:{labels:ddivs.map(d=>d.name),data:ddivs.map(d=>d.gap_pct),fmt:'pct',colors:ddivs.map(d=>gapColor(d.gap_pct))},
    chartTitle:'Utilisation % by division (this department)',chartDesc:'Utilisation % (Functional ÷ NMC MSR) for '+dp.name+'. Lower = worse. Tap a bar to open the division.',
    barNav:ddivs.map(d=>d.name),
    recs:buildDeptRecs(dp,ddivs),
    table:{title:'Divisions (this department)',cols:['Division','Required','Func','Shortfall','Proc.','Utilisation %'],
      rows:ddivs.map(d=>({nav:'#division/'+encodeURIComponent(d.name),cells:[d.name,fmt(d.required),fmt(d.functional),fmt(d.functional_shortfall),fmt(d.procurement),d.gap_pct+'%']}))},
    table2:{title:'Institutes (this department)',cols:['Institute','Required','Func','Shortfall','Utilisation %'],
      rows:(dp.institutes||[]).map(i=>({nav:'#institute/'+encodeURIComponent(i.name),cells:[i.name,fmt(i.required),fmt(i.functional),fmt(i.functional_shortfall),i.gap_pct+'%']}))}};
}
function buildDeptRecs(dp,ddivs){
  const out=[];const[cls,lbl]=sev(dp.gap_pct);const wd=ddivs[0];
  out.push(rec(dp.gap_pct<50?'crit':dp.gap_pct<100?'warn':'ok','🩺',`${lbl} utilisation (${dp.gap_pct}%)`,
    dp.gap_pct<100?`${fmt(dp.functional_shortfall)} working units short of the NMC MSR norm across the state.`:`Functional equipment meets or exceeds the norm state-wide for ${dp.name}.`));
  if(wd&&wd.gap_pct<100)out.push(rec('warn','📍',`Lowest utilisation division: ${wd.name}`,`${wd.gap_pct}% utilisation · ${fmt(wd.functional_shortfall)} units short. Prioritise ${dp.name} here.`));
  const te=(dp.top_equipment||[])[0];
  if(te)out.push(rec('info','🔬',`Key equipment: ${te.name}`,`${fmt(te.procurement)} units proposed · ${cr(te.budget)}.`));
  if(dp.end_of_life>0)out.push(rec('warn','♻',`${fmt(dp.end_of_life)} units near end-of-life`,`Plan replacement to protect functional utilisation.`));
  if(dp.procurement>0)out.push(rec('info','🛒','Procurement in plan',`${fmt(dp.procurement)} units proposed · budget ${cr(dp.budget)}.`));
  return out.join('');
}
// [2.0] Equipment Explorer: server-side filtering (ALL slicers), search, sort and pagination
//       (GET /api/v1/equipment). 1.0 showed the top 60 of the state-wide catalog and ignored geo filters.
let _eqxState={page:0,per:60,q:''};
async function renderEquipmentExplorer(){
  setCrumbScope();
  const el=document.getElementById('page-equipment');
  if(!document.getElementById('eqTable')){
  el.innerHTML=`<h2 class="secTitle">Equipment Explorer</h2>
    <p class="muted" style="margin-bottom:14px"><span id="eqCount"></span> equipment types in scope. Tap a row for its decision-support page. All filters above apply. Click any column header to sort.</p>
    <div class="card"><h3 style="margin-bottom:10px">Equipment catalog <span id="eqScopeNote"></span> ${exportBtns('eqTable')}</h3>
      <div style="display:flex;gap:8px;margin:0 0 8px"><input id="eqSearch" placeholder="Search equipment…" style="flex:1;max-width:340px;padding:7px 10px;border:1px solid var(--bd);border-radius:8px;font-size:13px"></div>
      <div class="scroll tall"><table id="eqTable">
      <thead><tr><th class="th-sort" data-k="name" title="Equipment item">Equipment</th><th class="num th-sort" data-k="required" title="Required per NMC/NMR">Req</th><th class="num th-sort" data-k="available" title="Available">Avail</th>
      <th class="num th-sort" data-k="functional" title="Functional (working)">Func</th><th class="num th-sort" data-k="net_requirement" title="Net Requirement = Required − Functional (+ shortfall / − surplus)">Net Req</th><th class="num th-sort" data-k="end_of_life" title="Approaching End of Life (<1 yr)">EoL</th><th class="num th-sort" data-k="procurement" title="Procurement suggested by colleges">Proc.</th><th class="num th-sort" data-k="gap_pct" title="Utilisation % = Functional ÷ Required × 100. Higher = better.">Utilisation %</th><th class="num th-sort" data-k="budget" title="Budget = Procurement × unit cost">Budget ₹</th></tr></thead>
      <tbody></tbody></table></div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px"><div id="eqInfo" class="muted"></div><div id="eqPager" style="display:flex;gap:6px"></div></div>
      ${gapCaption('<b>Net Req</b> = Required − Functional (+ shortfall / − surplus). <b>EoL</b> = units approaching end of life (&lt;1 year of service left).')}</div>`;
    let t=null;
    document.getElementById('eqSearch').oninput=e=>{clearTimeout(t);t=setTimeout(()=>{_eqxState.q=e.target.value.trim();_eqxState.page=0;renderEquipmentExplorer();},300);};
    document.querySelectorAll('#eqTable th.th-sort').forEach(th=>th.onclick=()=>{const k=th.dataset.k;
      eqSort.dir=eqSort.k===k?-eqSort.dir:(k==='name'?1:-1);eqSort.k=k;_eqxState.page=0;renderEquipmentExplorer();});
  }
  let res;
  try{ res=await API.get('/equipment',{...filterParams(),sort:eqSort.k,dir:eqSort.dir>0?'asc':'desc',page:_eqxState.page,per:_eqxState.per,q:_eqxState.q}); }
  catch(e){ showError('Equipment explorer: '+e.message); return; }
  if(state.page!=='equipment'||!document.getElementById('eqTable'))return;
  const anyF=Object.values(filterParams()).some(v=>v.length);
  document.getElementById('eqCount').textContent=fmt(res.total);
  document.getElementById('eqScopeNote').textContent=`(${fmt(res.total)}${anyF?' · filtered':''})`;
  const q=s=>String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  const erow=e=>{const dc=(mkey,inner)=>`<td class="num drillcell" onclick="event.stopPropagation();setFilterAndDrill('equipment',['${q(e.name)}'],'${mkey}')" title="Drill ${METRICS[mkey].label} (scoped to ${escapeHtml(e.name)})">${inner}</td>`;
    return `<tr class="clk" onclick="go('#equip/${encodeURIComponent(e.name)}')"><td>${escapeHtml(e.name)}</td>${dc('required',fmt(e.required))}${dc('available',fmt(e.available))}${dc('functional',fmt(e.functional))}${dc('netreq',sfmt(e.net_requirement))}${dc('eol',fmt(e.end_of_life))}${dc('procurement',fmt(e.procurement))}${dc('util',e.gap_pct+'%')}${dc('budget',fmt(e.budget))}</tr>`;};
  document.querySelector('#eqTable tbody').innerHTML=res.rows.map(erow).join('')||'<tr><td colspan="9" class="muted">No equipment in this scope.</td></tr>';
  document.querySelectorAll('#eqTable th.th-sort').forEach(th=>{th.classList.remove('asc','desc');if(th.dataset.k===eqSort.k)th.classList.add(eqSort.dir>0?'asc':'desc');});
  const start=_eqxState.page*res.per;
  document.getElementById('eqInfo').textContent=`Showing ${res.total?start+1:0}–${Math.min(start+res.per,res.total)} of ${fmt(res.total)}`;
  const mk=(l,p,dis)=>`<button class="btn" ${dis?'disabled':''} onclick="_eqxState.page=${p};renderEquipmentExplorer()" style="padding:5px 10px;font-size:12px${dis?';opacity:.4':''}">${l}</button>`;
  document.getElementById('eqPager').innerHTML=mk('‹ Prev',_eqxState.page-1,_eqxState.page<=0)+`<span class="muted" style="padding:5px 8px">Page ${_eqxState.page+1} / ${res.pages}</span>`+mk('Next ›',_eqxState.page+1,_eqxState.page>=res.pages-1);
  registerExport('eqTable','MEDD_equipment_catalog',
    ['Equipment','Required','Available','Functional','Net Requirement','End of Life','Procurement','Utilisation %','Budget (Rs)'],
    ()=>res.rows.map(e=>[e.name,e.required,e.available,e.functional,e.net_requirement,e.end_of_life,e.procurement,e.gap_pct,e.budget==null?'':Math.round(e.budget)]));
}
