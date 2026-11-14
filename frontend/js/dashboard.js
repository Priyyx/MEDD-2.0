/* MEDD Maharashtra 2.0 — dashboard.js
 * Code below is carried over from the MEDD 1.0 index.html (inline script); changes for the
 * PostgreSQL/API integration are marked with  // [2.0]  comments. See docs/05_CHANGE_LOG.md. */
const fmt = n => n==null||isNaN(n)?'—':Math.round(n).toLocaleString('en-IN');
const sfmt = n => n==null||isNaN(n)?'—':(n>0?'+':n<0?'−':'')+Math.abs(Math.round(n)).toLocaleString('en-IN');
const cr = n => n==null||isNaN(n)?'—':'₹'+(n/1e7).toLocaleString('en-IN',{maximumFractionDigits:1})+' Cr';
let charts={};

/* ===== METRIC-AWARE DRILL-THROUGH ===== *
 * One reusable hierarchy (Division→Institute→Department→Equipment) whose displayed
 * metric is chosen by the column/segment the user clicked. All pages share it. */
const METRICS={
  required:   {label:'Required Qty',       field:'required',        fmt:v=>fmt(v)},
  available:  {label:'Available Qty',      field:'available',       fmt:v=>fmt(v)},
  functional: {label:'Functional Qty',     field:'functional',      fmt:v=>fmt(v)},
  nonfunc:    {label:'Non-Functional Qty', field:'non_functional',  fmt:v=>fmt(v)},
  netreq:     {label:'Net Requirement',    field:'net_requirement', fmt:v=>sfmt(v)},
  util:       {label:'Utilisation %',      field:'gap_pct',         fmt:v=>(v==null?'—':v+'%')},
  procurement:{label:'Procurement Requirement', field:'procurement', fmt:v=>fmt(v)},
  budget:     {label:'Budget Requirement', field:'budget',          fmt:v=>cr(v)},
  amc:        {label:'AMC/CMC %',          field:'amc_pct',         fmt:v=>(v==null?'—':v+'%')},
  condemnation:{label:'Proposed Condemnation', field:'condemnation', fmt:v=>fmt(v)},
  eol:        {label:'Approaching End of Life', field:'end_of_life', fmt:v=>fmt(v)},
  esttotal:   {label:'Total Estimated Cost', field:'budget',        fmt:v=>cr(v)},
  unitcost:   {label:'Unit Cost',           field:'unit_cost',      fmt:v=>(v?cr(v):'—')},
};
const METRIC_ALIAS={gap_pct:'util',gap:'util',proc:'procurement',nonfunctional:'nonfunc',
  amc_pct:'amc',end_of_life:'eol',endoflife:'eol',cond:'condemnation',totalcost:'esttotal',estcost:'esttotal'};
function normMetric(m){return METRICS[m]?m:(METRIC_ALIAS[m]||'util');}
function mval(obj,mkey){const M=METRICS[normMetric(mkey)];return obj?obj[M.field]:null;}
function mfmt(obj,mkey){const M=METRICS[normMetric(mkey)];return M.fmt(mval(obj,mkey));}
function drillTo(mkey,level,path){mkey=normMetric(mkey);const enc=(path||[]).map(encodeURIComponent).join('/');go('#drill/'+mkey+'/'+level+(enc?'/'+enc:''));}

/* ===== column definitions + formula captions (make every table self-explanatory) ===== */
const COLDEF={
  'Req':'Quantity Required — from the NMC Minimum Standard Requirements (MSR) column',
  'Required':'Quantity Required per NMC Minimum Standard Requirements (MSR)',
  'Avail':'Quantity of Equipment Available (physically present)',
  'Available':'Quantity of Equipment Available (physically present)',
  'Func':'Quantity of Functional Equipment (available and working)',
  'Functional':'Quantity of Functional Equipment (available and working)',
  'Non-Func':'Non-Functional = Available − Functional',
  'Non-Functional':'Non-Functional = Available − Functional',
  'Proc.':'Quantity Proposed for New Procurement',
  'Procurement':'Quantity Proposed for New Procurement',
  'Gap %':'Utilisation % = Functional ÷ Required (NMC MSR) × 100. Higher = better (≥100% = norm met).',
  'Utilisation %':'Utilisation % = Functional ÷ Required (NMC MSR) × 100. Higher = better (≥100% = norm met).',
  'Net Req':'Net Requirement = Required (NMC MSR) − Functional. Positive = shortfall (procure more), negative = surplus.',
  'Net Requirement':'Net Requirement = Required (NMC MSR) − Functional. Positive = shortfall (procure more), negative = surplus.',
  'Budget ₹':'Budget = Proposed Procurement × unit cost (from the unique-equipment costing list)',
  'Budget (Rs)':'Budget = Proposed Procurement × unit cost',
  'AMC %':'AMC % = Units under active AMC/CMC ÷ Functional × 100',
  'EoL':'Quantity Approaching End-of-Life (<1 financial year of service left)',
  'End-of-Life':'Quantity Approaching End-of-Life (<1 FY of service left)',
  'Condemnation':'Quantity Proposed for Condemnation',
  'Shortfall':'Functional Shortfall = Required − Functional (working units still needed to meet the norm)',
  'Surplus':'Surplus Functional = Functional − Required (working units above the norm)',
};
// wrap a header label with a title tooltip if a definition exists
function defTip(label){const d=COLDEF[label];return d?`<th class="num" title="${d.replace(/"/g,'&quot;')}">${label}</th>`:`<th class="num">${label}</th>`;}
// standard formula caption shown beneath any table containing Utilisation %
function gapCaption(extra){
  return `<div class="tcap"><b>How to read this table:</b> 
   <code>Utilisation % = Functional ÷ Required (NMC MSR) × 100</code> — working equipment against the NMC/NMR norm. 
   <b>Higher is better:</b> ≥100% means the NMC MSR requirement is met or exceeded; below 100% means a shortfall of working equipment. 
   <b>Non-Functional = Available − Functional</b>. <b>Budget = Proposed Procurement × unit cost</b>.${extra?' '+extra:''}</div>`;
}

/* ===== generic table sorting: click a .th-sort header to sort asc/desc ===== */
const _sortState={};
function makeSortable(tableId, rows, rowHtml){
  const t=document.getElementById(tableId); if(!t)return;
  const apply=()=>{const st=_sortState[tableId];
    if(st){rows.sort((a,b)=>{const x=a[st.k],y=b[st.k];
      if(typeof x==='string'||typeof y==='string')return String(x==null?'':x).localeCompare(String(y==null?'':y))*st.dir;
      return ((x||0)-(y||0))*st.dir;});}
    const tb=t.querySelector('tbody'); if(tb)tb.innerHTML=rows.map(rowHtml).join('');
    t.querySelectorAll('th.th-sort').forEach(th=>{th.classList.remove('asc','desc');
      if(st&&st.k===th.dataset.k)th.classList.add(st.dir>0?'asc':'desc');});
  };
  t.querySelectorAll('th.th-sort').forEach(th=>{const k=th.dataset.k;if(!k)return;
    th.onclick=(e)=>{e.stopPropagation();const cur=_sortState[tableId];
      _sortState[tableId]={k,dir:(cur&&cur.k===k)?-cur.dir:1};apply();};});
  apply();
}

/* ===== ROUTING ===== */
function go(hash){if(location.hash===hash)route();else location.hash=hash;}
window.addEventListener('hashchange',route);
const PAGES=['executive','gap','netreq','procurement','financial','condemnation','eol','amc','facility','district','department','equipment','chatbot','admin'];
const PAGE_TITLE={executive:'Executive Dashboard',gap:'Utilisation Analysis',netreq:'Net Requirement',
  condemnation:'Condemnation Dashboard',eol:'End of Life Dashboard',
  procurement:'Procurement Planning',financial:'Budget & Financial',
  amc:'AMC / CMC Coverage',admin:'Data Management',facility:'Institute Dashboard',district:'Division Dashboard',department:'Department Dashboard',equipment:'Equipment Explorer',chatbot:'Decision Support AI'};

async function route(){   // [2.0] async: some detail views fetch complete lists from the API
  if(!DATA) return;
  const h=decodeURIComponent(location.hash||'#executive');
  const [view,...rest]=h.replace(/^#/,'').split('/');const arg=rest.join('/');
  if(view==='uniqeq'){const level=rest[0]||'division';const path=rest.slice(1);openDetail(await detailForUniqEquip(level,path));return;}
  if(view==='drill'){const mkey=rest[0]||'util';const level=rest[1]||'division';const path=rest.slice(2);
    openDetail(await detailForDrill(mkey,level,path));return;}
  if(view==='kpi'){openDetail(detailForKpi(arg));return;}
  if(view==='division'){const d=DATA.divisions.find(x=>x.name===arg);if(d){openDetail(detailForGroup(d,'Division'));return;}}
  if(view==='institute'){const i=DATA.institutes.find(x=>x.name===arg);if(i){openDetail(detailForGroup(i,'Institute'));return;}}
  if(view==='instdept'){const li=arg.lastIndexOf('/');const iname=arg.slice(0,li),dname=arg.slice(li+1);
    const inst=DATA.institutes.find(x=>x.name===iname);const dp=(inst&&inst.departments||[]).find(d=>d.name===dname);
    if(inst&&dp){openDetail(await detailForInstDept(inst,dp));return;}
    if(inst){openDetail(detailForGroup(inst,'Institute'));return;}}
  if(view==='department'&&arg){const dp=DATA.departments.find(x=>x.name===arg);if(dp){openDetail(detailForDepartment(dp));return;}}
  if(view==='equip'){const e=DATA.equipment_catalog.find(x=>x.name===arg);if(e){openDetail(detailForEquipment(e));return;}}
  const page=PAGES.includes(view)?view:'executive';
  showPage(page);
}
function showPage(page){
  state.page=page;
  document.querySelectorAll('.page').forEach(p=>p.classList.add('hide'));
  document.getElementById('page-'+page).classList.remove('hide');
  document.getElementById('pageTitle').textContent=PAGE_TITLE[page];
  document.getElementById('crumb').innerHTML=PAGE_TITLE[page];
  document.querySelectorAll('#nav a').forEach(a=>a.classList.toggle('active',a.dataset.page===page));
  document.getElementById('filterbar').style.display=page==='admin'?'none':'flex';
  window.scrollTo(0,0);
  renderPage(page);
}
function openDetail(D){
  document.querySelectorAll('.page').forEach(p=>p.classList.add('hide'));
  document.getElementById('page-detail').classList.remove('hide');
  document.getElementById('filterbar').style.display='none';
  document.getElementById('pageTitle').textContent=D.title;
  window.scrollTo(0,0);renderDetail(D);
}

/* ===== PAGE RENDERERS ===== */
function renderPage(page){
  if(page==='executive')renderExec();
  else if(page==='facility')renderListPage('facility');
  else if(page==='district')renderListPage('district');
  else if(page==='department')renderDepartmentList();
  else if(page==='equipment')renderEquipmentExplorer();
  else if(page==='chatbot')renderChatbot();
  else if(page==='admin')renderAdmin();   // [2.0] new: ingestion status / upload / reconciliation
  else if(page==='condemnation')renderMetricPage('condemnation','condemnation');
  else if(page==='eol')renderMetricPage('eol','eol');
  else if(page==='amc')renderMetricPage('amc','amc');
  else renderAnalysis(page);
}

function kpiCards(o){
  const netreq=o.net_requirement!=null?o.net_requirement:((o.required||0)-(o.functional||0));
  return [
    {k:'colleges',  l:'Medical Colleges',        v:fmt(o.college_count), n:'institutes in scope'},
    {k:'required',  l:'Equipment Required',      v:fmt(o.required),      n:'NMC / NMR norm'},
    {k:'available', l:'Available Equipment',     v:fmt(o.available),     n:''},
    {k:'functional',l:'Functional Equipment',    v:fmt(o.functional),    n:(o.func_pct!=null?o.func_pct+'% of available':'')},
    {k:'nonfunc',   l:'Non-Functional Equipment',v:fmt(o.non_functional),n:'available − functional'},
    {k:'netreq',    l:'Net Requirement',         v:sfmt(netreq),         n:'Required − Functional · +shortfall / −surplus'},
    {k:'gap',       l:'Utilisation %',           v:(o.gap_pct!=null?o.gap_pct:0)+'%', n:'functional ÷ required · ≥100% = norm met'},
    {k:'procurement',l:'Procurement (Suggested by Colleges)',v:fmt(o.procurement), n:'as proposed by colleges'},
    {k:'budget',    l:'Budget Requirement',      v:cr(o.budget),         n:fmt(o.budget)+' ₹'},
    {k:'eol',       l:'Approaching End of Life',  v:fmt(o.end_of_life),  n:(o.eol_pct!=null?o.eol_pct:0)+'% of functional · <1 yr left'},
    {k:'amc',       l:'Under AMC/CMC',           v:fmt(o.amc),           n:(o.amc_pct!=null?o.amc_pct:0)+'% of functional'},
    {k:'condemnation',l:'Proposed Condemnation', v:fmt(o.condemnation),  n:'flagged for removal'},
    {k:'uniqeq',    l:'Unique Equipment List',  v:fmt(uniqueEquipmentCount()), n:'distinct equipment (filtered)'},
  ];
}
// map each exec KPI to a drill metric (colleges → functional as a sensible default)
const KPI_METRIC={colleges:'functional',required:'required',available:'available',functional:'functional',
  nonfunc:'nonfunc',netreq:'netreq',gap:'util',procurement:'procurement',budget:'budget',
  eol:'eol',amc:'amc',condemnation:'condemnation'};
function renderExec(){
  const o=scope();
  setCrumbScope();
  document.getElementById('kpis').innerHTML=kpiCards(o).map(c=>
    `<div class="kpi" onclick="${c.k==='uniqeq'?"go('#uniqeq/division')":"drillTo('"+(KPI_METRIC[c.k]||'util')+"','division',[])"}"><div class="lbl">${c.l}</div><div class="val">${c.v}</div><div class="note">${c.n}</div></div>`).join('');
  buildMap('mapSvg','mapImg','mapwrap','mapTip','mapLegend','mapDesc');
  renderHotspots('hotspots');renderDivTable();renderInstTable();renderExecCharts();
  renderFooter();
}

function setCrumbScope(){
  const parts=['<a onclick="resetFilters()">Executive</a>'];
  if(state.division.length)parts.push(state.division.length===1?state.division[0]:state.division.length+' divisions');
  if(state.institute.length)parts.push(state.institute.length===1?state.institute[0]:state.institute.length+' institutes');
  if(state.department.length)parts.push(state.department.length===1?state.department[0]:state.department.length+' departments');
  if(state.bedded.length)parts.push('🛏 '+state.bedded.join(','));
  if(state.equipment.length)parts.push('🔬 '+(state.equipment.length===1?state.equipment[0]:state.equipment.length+' items'));
  document.getElementById('crumb').innerHTML=parts.length>1?parts.join(' ▸ '):'Executive Dashboard';
}

let sortDiv={k:'gap_pct',dir:-1},sortInst={k:'gap_pct',dir:-1};
function renderDivTable(){
  const rows=[...scopeDivisions()].sort((a,b)=>cmp(a,b,sortDiv));   // [2.0] filtered server aggregates
  // column → metric key (so clicking a value drills that metric down the hierarchy)
  const colM=[null,'required','available','functional','nonfunc','procurement','util','budget'];
  const cell=(d,mkey,inner)=>`<td class="num drillcell" onclick="event.stopPropagation();drillTo('${mkey}','institute',['${d.name.replace(/'/g,"\\'")}'])" title="Drill ${METRICS[mkey].label} → Institute">${inner}</td>`;
  document.querySelector('#divTable tbody').innerHTML=rows.map(d=>{const[cls]=sev(d.gap_pct);
    return `<tr class="clk" onclick="go('#division/${encodeURIComponent(d.name)}')">
      <td>${d.name}</td>${cell(d,'required',fmt(d.required))}${cell(d,'available',fmt(d.available))}
      ${cell(d,'functional',fmt(d.functional))}${cell(d,'nonfunc',fmt(d.non_functional))}
      ${cell(d,'procurement',fmt(d.procurement))}${cell(d,'util','<span class="pill '+cls+'">'+d.gap_pct+'%</span>')}
      ${cell(d,'budget',fmt(d.budget))}</tr>`;}).join('');
  registerExport('divTable','MEDD_division_comparison',
    ['Division','Required','Available','Functional','Non-Functional','Procurement','Utilisation %','Budget (Rs)'],
    ()=>[...scopeDivisions()].sort((a,b)=>cmp(a,b,sortDiv)).map(d=>[d.name,d.required,d.available,d.functional,d.non_functional,d.procurement,d.gap_pct,Math.round(d.budget)]));
}
function renderInstTable(){
  let list=scopeInstitutes();   // [2.0] exact aggregates under ALL filters (dept / equipment / sub-category too)
  if(state.division.length)list=list.filter(i=>state.division.includes(i.division));
  if(state.institute.length)list=list.filter(i=>state.institute.includes(i.name));
  if(state.bedded.length)list=list.filter(i=>i.seat!=null&&state.bedded.includes(String(i.seat)));
  const sorted=[...list].sort((a,b)=>cmp(a,b,sortInst));
  const rows=sorted.slice(0,25);
  const cell=(i,mkey,inner)=>`<td class="num drillcell" onclick="event.stopPropagation();drillTo('${mkey}','department',['${i.division.replace(/'/g,"\\'")}','${i.name.replace(/'/g,"\\'")}'])" title="Drill ${METRICS[mkey].label} → Department">${inner}</td>`;
  document.querySelector('#instTable tbody').innerHTML=rows.map(i=>
    `<tr class="clk" onclick="go('#institute/${encodeURIComponent(i.name)}')">
      <td>${i.name}</td>${cell(i,'functional',fmt(i.functional))}${cell(i,'nonfunc',fmt(i.non_functional))}
      ${cell(i,'procurement',fmt(i.procurement))}${cell(i,'util',i.gap_pct+'%')}${cell(i,'budget',fmt(i.budget))}</tr>`).join('');
  registerExport('instTable','MEDD_institutes',
    ['Institute','Division','Functional','Non-Functional','Procurement','Utilisation %','Budget (Rs)','Required','Available'],
    ()=>sorted.map(i=>[i.name,i.division,i.functional,i.non_functional,i.procurement,i.gap_pct,Math.round(i.budget),i.required,i.available]));
}
function cmp(a,b,s){const x=a[s.k],y=b[s.k];return (typeof x==='string'?x.localeCompare(y):(x>y?1:x<y?-1:0))*s.dir;}

/* ===== GENERIC ANALYSIS PAGES (gap/procurement/financial/lifecycle/amc) ===== */
function analysisConfig(page){
  const o=scope();
  const C={
    gap:{title:'Utilisation Analysis',metric:'gap_pct',fmt:'pct',
      lede:`Utilisation % = Functional ÷ NMC/NMR requirement × 100. Higher = better (≥100% = norm met). State-wide ${DATA.overview.gap_pct}%. Divisions below are ordered worst (lowest) first.`,
      stats:[['Required',fmt(o.required)],['Functional',fmt(o.functional)],['Utilisation %',(o.gap_pct||0)+'%'],['Net Requirement',sfmt(o.net_requirement||0)]]},
    netreq:{title:'Net Requirement Calculation',metric:'net_requirement',fmt:'num',
      lede:`Net Requirement = NMC MSR Required − Functional. Positive = shortfall (additional procurement required); zero = requirement met; negative = surplus. State-wide ${sfmt(DATA.overview.net_requirement)} units. Divisions ordered by net requirement.`,
      stats:[['Required (NMC/NMR)',fmt(o.required)],['Functional',fmt(o.functional)],['Net Requirement',sfmt(o.net_requirement||0)],['Utilisation %',(o.gap_pct||0)+'%']]},
    procurement:{title:'Procurement Planning',metric:'procurement',fmt:'num',
      lede:`Procurement as suggested by colleges, with indicative budget. Compare against Net Requirement to sanity-check college proposals.`,
      stats:[['Procurement (Suggested)',fmt(o.procurement)],['Net Requirement',sfmt(o.net_requirement||0)],['Budget',cr(o.budget)],['Utilisation %',(o.gap_pct||0)+'%']]},
    financial:{title:'Budget & Financial Planning',metric:'budget',fmt:'cr',
      lede:`Budget = procurement (suggested by colleges) × unique-equipment costing. State-wide ${cr(DATA.overview.budget)}.`,
      stats:[['Budget',cr(o.budget)],['Procurement (Suggested)',fmt(o.procurement)],['Avg ₹/unit',o.procurement?fmt(o.budget/o.procurement):'—']]},
  }[page];
  return C;
}
const MODULE_API={gap:'gap',netreq:'net-requirement',procurement:'procurement',financial:'financial'};
async function renderAnalysis(page){
  setCrumbScope();
  const C=analysisConfig(page);const el=document.getElementById('page-'+page);
  // [2.0] by-division ranking + top equipment come from GET /api/v1/modules/{module} under all active filters
  let mod=null;
  try{ mod=await API.get('/modules/'+MODULE_API[page],{...filterParams(),top:50}); }
  catch(e){ if(page==='financial'&&e.status===403){el.innerHTML='<h2 class="secTitle">Budget &amp; Financial Planning</h2><div class="card">Financial data is restricted for your role.</div>';return;} showError(e.message); return; }
  if(state.page!==page) return;   // user navigated away while loading
  const dv=[...mod.by_division].sort((a,b)=>C.metric==='gap_pct'?((a[C.metric]||0)-(b[C.metric]||0)):((b[C.metric]||0)-(a[C.metric]||0)));
  el.innerHTML=`
    <h2 class="secTitle">${C.title}</h2><p class="muted" style="margin-bottom:16px">${C.lede}</p>
    <div class="statbar">${C.stats.map(s=>`<div class="stat"><div class="l">${s[0]}</div><div class="v">${s[1]}</div></div>`).join('')}</div>
    <div class="grid2">
      <div class="card"><h3>${C.title} by Division</h3><div class="desc">Tap a bar to drill down.</div><div class="chartbox" style="height:320px"><canvas id="anChart-${page}"></canvas></div></div>
      <div class="card"><h3>Decision Support</h3><div class="desc">From MEDD KPI rules.</div><div>${buildAnalysisRecs(page,dv)}</div></div>
    </div>
    <div class="grid2b">
      <div class="card"><h3>Division Ranking ${exportBtns('anDiv-'+page)}</h3><div class="scroll"><table id="anDiv-${page}"></table></div><div id="anDivCap-${page}"></div></div>
      <div class="card"><h3>Top Equipment ${exportBtns('anEq-'+page)}</h3><div class="desc">Tap to open equipment.</div><div class="scroll"><table id="anEq-${page}"></table></div><div id="anEqCap-${page}"></div></div>
    </div>`;
  // chart
  charts['an']&&charts['an'].destroy();
  const tick=C.fmt==='cr'?(v=>'₹'+(v/1e7).toFixed(0)+'Cr'):C.fmt==='pct'?(v=>v+'%'):(v=>fmt(v));
  const pageMetric={gap:'util',netreq:'netreq',procurement:'procurement',financial:'budget',amc:'functional'}[page]||'util';
  charts['an']=new Chart(document.getElementById('anChart-'+page),{type:'bar',
    data:{labels:dv.map(d=>d.name),datasets:[{data:dv.map(d=>d[C.metric]||0),backgroundColor:dv.map(d=>C.metric==='gap_pct'?gapColor(d.gap_pct):'#3182bd')}]},
    options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:22}},
      plugins:{legend:{display:false},datalabels:datalabelCfg(C.fmt)},
      onClick:(e,els)=>{if(els.length)drillTo(pageMetric,'institute',[dv[els[0].index].name]);},
      scales:{y:{ticks:{callback:tick}}}},plugins:[ChartDataLabels]});
  // division ranking table (with Func / Non-Func)
  const dt=document.getElementById('anDiv-'+page);
  const metricCol=C.title.split(' ')[0];
  dt.innerHTML='<thead><tr><th class="th-sort" data-k="name" title="Administrative division">Division</th>'+defTip('Req')+defTip('Func')+defTip('Net Req')+'<th class="num th-sort" data-k="'+C.metric+'" title="'+(COLDEF[metricCol]||C.title)+'">'+metricCol+'</th><th class="num th-sort" data-k="gap_pct" title="Utilisation % = Functional ÷ Required × 100">Utilisation %</th></tr></thead><tbody>'+
    dv.map(d=>{const val=C.fmt==='cr'?fmt(d[C.metric]):C.fmt==='pct'?(d[C.metric]+'%'):fmt(d[C.metric]);
      return `<tr class="clk" onclick="drillTo('${pageMetric}','institute',['${d.name.replace(/'/g,"\\'")}'])"><td>${d.name}</td><td class="num">${fmt(d.required)}</td><td class="num">${fmt(d.functional)}</td><td class="num">${sfmt(d.net_requirement)}</td><td class="num">${val}</td><td class="num">${d.gap_pct}%</td></tr>`;}).join('')+'</tbody>';
  const anRow=d=>{const val=C.fmt==='cr'?fmt(d[C.metric]):C.fmt==='pct'?(d[C.metric]+'%'):fmt(d[C.metric]);
    return `<tr class="clk" onclick="drillTo('${pageMetric}','institute',['${d.name.replace(/'/g,"\\'")}'])"><td>${d.name}</td><td class="num">${fmt(d.required)}</td><td class="num">${fmt(d.functional)}</td><td class="num">${sfmt(d.net_requirement)}</td><td class="num">${val}</td><td class="num">${d.gap_pct}%</td></tr>`;};
  makeSortable('anDiv-'+page, dv, anRow);
  const anDivCap=document.getElementById('anDivCap-'+page); if(anDivCap) anDivCap.innerHTML=gapCaption();
  registerExport('anDiv-'+page,'MEDD_'+page+'_by_division',
    ['Division','Required','Functional','Net Requirement',metricCol,'Utilisation %'],
    ()=>dv.map(d=>[d.name,d.required,d.functional,d.net_requirement,(C.metric==='budget'?Math.round(d[C.metric]):d[C.metric]),d.gap_pct]));
  // top equipment for this metric
  const eqKey=C.metric==='budget'?'budget':C.metric==='end_of_life'?'end_of_life':C.metric==='amc'?'amc':'procurement';
  const eqAll=[...mod.top_equipment].sort((a,b)=>(b[eqKey]||0)-(a[eqKey]||0));
  const eq=eqAll.slice(0,15);
  document.getElementById('anEq-'+page).innerHTML='<thead><tr><th title="Equipment item">Equipment</th>'+defTip('Req')+defTip('Avail')+defTip('Proc.')+defTip('Budget ₹')+'</tr></thead><tbody>'+
    eq.map(e=>`<tr class="clk" onclick="go('#equip/${encodeURIComponent(e.name)}')"><td>${e.name}</td><td class="num">${fmt(e.required)}</td><td class="num">${fmt(e.available)}</td><td class="num">${fmt(e.procurement)}</td><td class="num">${fmt(e.budget)}</td></tr>`).join('')+'</tbody>';
  const anEqCap=document.getElementById('anEqCap-'+page); if(anEqCap) anEqCap.innerHTML='<div class="tcap"><b>Budget</b> = <code>Proposed Procurement × unit cost</code> (unit cost from the unique-equipment costing list). Hover any header for its definition.</div>';
  registerExport('anEq-'+page,'MEDD_'+page+'_top_equipment',
    ['Equipment','Required','Available','Procurement','Budget (Rs)'],
    ()=>eqAll.slice(0,50).map(e=>[e.name,e.required,e.available,e.procurement,Math.round(e.budget)]));
  if(page==='netreq')renderCostMapping();
}

function buildAnalysisRecs(page,dv){
  const w=dv[0],o=scope();const R=[];
  if(!w)return rec('info','ℹ️','No data in scope','No line items match the current filters.');
  if(page==='gap')R.push(rec(w.gap_pct<50?'crit':w.gap_pct<100?'warn':'ok','🚑',`Lowest utilisation: ${w.name}`,`${w.gap_pct}% (Functional ÷ NMC MSR)${w.gap_pct<100?` · ${fmt(w.functional_shortfall)} working units short`:' · norm met'}. Prioritise here.`));
  if(page==='procurement')R.push(rec('crit','🚑',`Prioritise ${w.name}`,`${fmt(w.procurement)} units · ${cr(w.budget)}. Front-load procurement here.`));
  if(page==='financial')R.push(rec('info','₹',`Largest budget: ${w.name}`,`${cr(w.budget)} of the ${cr(o.budget)} state requirement.`));
  if(page==='amc')R.push(rec(o.amc_pct<70?'warn':'ok','🛡',`AMC coverage ${o.amc_pct}%`,`${fmt(o.functional-o.amc)} functional units uncovered. Contract the critical ones.`));
  R.push(rec('info','📦','Pool high-volume equipment','Concentrate tenders on the top equipment types for volume discounts.'));
  R.push(rec('info','⚖️','Check redistribution','Divisions with available ≫ required may hold surplus to offset shortages elsewhere.'));
  return R.join('');
}
function rec(t,i,h,b){return `<div class="rec r-${t}"><div class="ic">${i}</div><div><h4>${h}</h4><p>${b}</p></div></div>`;}

/* ===== DECISION SUPPORT CHATBOT (client-side, rule-based over embedded data) ===== */
let cbHistory=[];
/* ===== dedicated metric dashboard pages (Condemnation, End of Life, AMC/CMC) ===== */
function renderMetricPage(page,mkey){
  setCrumbScope();
  const el=document.getElementById('page-'+page);
  const M=METRICS[normMetric(mkey)];
  let divs=scopeDivisions().slice();   // [2.0] exact filtered aggregates
  if(state.division.length)divs=divs.filter(d=>state.division.includes(d.name));
  const asc=(mkey==='util'||mkey==='amc');
  divs=[...divs].sort((a,b)=>{const x=mval(a,mkey)||0,y=mval(b,mkey)||0;return asc?x-y:y-x;});
  const o=scope();
  el.innerHTML=`<h2 class="secTitle">${PAGE_TITLE[page]}</h2>
    <p class="muted" style="margin-bottom:14px"><b>${M.label}</b> by Division. Click any bar or row to drill down: <b>Division → Institute → Department → Equipment</b>, keeping this metric and all active filters.</p>
    <div class="kpis" id="mp-kpis-${page}"></div>
    <div class="card"><h3>${M.label} by Division</h3><div class="desc">Tap a bar to drill into that division.</div>
      <div class="chartbox" style="height:340px"><canvas id="mpChart-${page}"></canvas></div></div>
    <div class="card"><h3 style="margin-bottom:10px">${M.label} by Division ${exportBtns('mpTable-'+page)}</h3>
      <div class="scroll tall"><table id="mpTable-${page}">
        <thead><tr><th class="th-sort" data-k="name">Division</th><th class="num th-sort" data-k="${M.field}">${M.label}</th>${defTip('Req')}${defTip('Func')}${defTip('Net Req')}<th class="num th-sort" data-k="gap_pct">Utilisation %</th><th class="num th-sort" data-k="budget">Budget ₹</th></tr></thead>
        <tbody></tbody></table></div></div>`;
  const kpis=[[M.label,mfmt(o,mkey)],['Required',fmt(o.required)],['Functional',fmt(o.functional)],
    ['Net Requirement',sfmt(o.net_requirement)],['Budget',cr(o.budget)]];
  document.getElementById('mp-kpis-'+page).innerHTML=kpis.map(k=>`<div class="kpi"><div class="lbl">${k[0]}</div><div class="val">${k[1]}</div></div>`).join('');
  const top=divs.slice(0,14);
  charts['mp']&&charts['mp'].destroy();
  const dlKind=mkey==='budget'?'cr':(mkey==='util'||mkey==='amc')?'pct':'num';
  const tick=dlKind==='cr'?(v=>'₹'+(v/1e7).toFixed(0)+'Cr'):dlKind==='pct'?(v=>v+'%'):(v=>fmt(v));
  charts['mp']=new Chart(document.getElementById('mpChart-'+page),{type:'bar',
    data:{labels:top.map(d=>d.name),datasets:[{data:top.map(d=>mval(d,mkey)||0),backgroundColor:top.map(d=>mkey==='util'?gapColor(d.gap_pct):'#3182bd')}]},
    options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:22}},
      plugins:{legend:{display:false},datalabels:datalabelCfg(dlKind)},
      onClick:(e,els)=>{if(els.length)drillTo(mkey,'institute',[top[els[0].index].name]);},
      scales:{y:{ticks:{callback:tick}}}},plugins:[ChartDataLabels]});
  const rowHtml=d=>`<tr class="clk" onclick="drillTo('${mkey}','institute',['${d.name.replace(/'/g,"\\'")}'])"><td>${d.name}</td><td class="num"><b>${mfmt(d,mkey)}</b></td><td class="num">${fmt(d.required)}</td><td class="num">${fmt(d.functional)}</td><td class="num">${sfmt(d.net_requirement)}</td><td class="num">${d.gap_pct}%</td><td class="num">${fmt(d.budget)}</td></tr>`;
  makeSortable('mpTable-'+page, divs, rowHtml);
  registerExport('mpTable-'+page,'MEDD_'+page,
    ['Division',M.label,'Required','Functional','Net Requirement','Utilisation %','Budget (Rs)'],
    ()=>divs.map(d=>[d.name,mval(d,mkey),d.required,d.functional,d.net_requirement,d.gap_pct,Math.round(d.budget)]));
}

// [2.0] footer reflects the live database, not a build-time snapshot
function renderFooter(){
  const ov=DATA.overview, m=DATA.meta||{};
  const when=m.last_refresh?new Date(m.last_refresh).toLocaleString('en-IN'):'never';
  document.getElementById('foot').textContent=
    `MEDD Maharashtra DSS 2.0 · FY 2025-26 · live from PostgreSQL (data version ${m.data_version||0}, refreshed ${when}) · Budget ${ov.budget==null?'restricted':'₹'+fmt(ov.budget)} · Utilisation ${ov.gap_pct}% · ${fmt(ov.college_count)} institutes · ${ov.divisions} divisions · ${fmt(ov.line_items)} line items`;
}
