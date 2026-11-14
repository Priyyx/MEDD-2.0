/* MEDD Maharashtra 2.0 — drilldown.js
 * Code below is carried over from the MEDD 1.0 index.html (inline script); changes for the
 * PostgreSQL/API integration are marked with  // [2.0]  comments. See docs/05_CHANGE_LOG.md. */
/* ===== DETAIL (KPI / group / equipment) ===== */
function kpiStatRow(key,o){
  // Each KPI gets a stat row centred on ITSELF plus the most relevant context.
  const S={
    colleges:[['Medical Colleges',fmt(o.college_count)],['Divisions',fmt(o.divisions)],['Equipment types',fmt(o.equipment_types)],['Line items',fmt(o.line_items)]],
    required:[['Required (NMC MSR)',fmt(o.required)],['Available',fmt(o.available)],['Utilisation %',o.gap_pct+'%'],['Procurement',fmt(o.procurement)]],
    available:[['Available',fmt(o.available)],['Required',fmt(o.required)],['Functional',fmt(o.functional)],['Func %',fmt(o.functional/o.available*100)+'%']],
    functional:[['Functional',fmt(o.functional)],['Available',fmt(o.available)],['Func %',fmt(o.functional/o.available*100)+'%'],['Non-Functional',fmt(o.non_functional)]],
    nonfunc:[['Non-Functional',fmt(o.non_functional)],['Available',fmt(o.available)],['Proposed Condemnation',fmt(o.condemnation)],['Condemn % of NF',fmt(o.condemnation/o.non_functional*100)+'%']],
    procurement:[['New Procurement',fmt(o.procurement)],['Required',fmt(o.required)],['Utilisation %',o.gap_pct+'%'],['Budget',cr(o.budget)]],
    gap:[['Utilisation %',o.gap_pct+'%'],['Required',fmt(o.required)],['Procurement',fmt(o.procurement)],['Budget',cr(o.budget)]],
    budget:[['Budget',cr(o.budget)],['Procurement',fmt(o.procurement)],['Avg ₹/unit',o.procurement?fmt(o.budget/o.procurement):'—'],['Utilisation %',o.gap_pct+'%']],
    eol:[['Approaching EoL',fmt(o.end_of_life)],['EoL % of functional',o.eol_pct+'%'],['Functional',fmt(o.functional)],['Proposed Condemnation',fmt(o.condemnation)]],
    amc:[['Under AMC/CMC',fmt(o.amc)],['AMC % of functional',o.amc_pct+'%'],['Functional',fmt(o.functional)],['Uncovered',fmt(o.functional-o.amc)]],
    condemnation:[['Proposed Condemnation',fmt(o.condemnation)],['Non-Functional',fmt(o.non_functional)],['Condemn % of NF',fmt(o.condemnation/o.non_functional*100)+'%'],['Approaching EoL',fmt(o.end_of_life)]],
  };
  return S[key]||[['Value','—']];
}
function detailForKpi(key){
  const o=DATA.overview;
  const map={colleges:['Medical Colleges','college_count'],required:['Equipment Required','required'],
    available:['Available Equipment','available'],functional:['Functional Equipment','functional'],
    nonfunc:['Non-Functional Equipment','non_functional'],procurement:['Procurement (Suggested by Colleges)','procurement'],
    netreq:['Net Requirement','net_requirement'],
    gap:['Utilisation %','gap_pct'],budget:['Budget Requirement','budget'],
    eol:['Approaching End-of-Life (<1 FY)','end_of_life'],amc:['AMC / CMC Coverage','amc'],condemnation:['Proposed Condemnation','condemnation']};
  const[title,field]=map[key]||['KPI',key];
  const fkind=key==='budget'?'cr':key==='gap'?'pct':'num';
  const gapAsc=(key==='gap'); // Gap%: lower = worse, so ascending puts worst first
  const dupGap=(field==='gap_pct'); // avoid showing the metric column twice as Gap %
  const ord=(a,b)=>gapAsc?((a[field]||0)-(b[field]||0)):((b[field]||0)-(a[field]||0));
  const divs=[...DATA.divisions].sort(ord);
  const insts=[...DATA.institutes].filter(i=>gapAsc?true:(i[field]||0)>0).sort(ord).slice(0,15);
  // department context for this KPI (state-wide)
  const depts=[...DATA.state_depts].filter(d=>gapAsc?true:(d[field]||0)>0).sort(ord).slice(0,12);
  const colors=divs.map(d=>key==='gap'?gapColor(d.gap_pct):'#3182bd');
  return {title,scope:'State-wide · '+title,lede:kpiLede(key,o),
    stats:kpiStatRow(key,o),
    chart:{labels:divs.map(d=>d.name),data:divs.map(d=>d[field]||0),fmt:fkind,colors},
    chartTitle:title+' by Division',chartDesc:'Bars show the actual value. Tap a bar to open that division.',
    barNav:divs.map(d=>d.name),recs:buildKpiRecs(key,o,divs,insts),
    table:{title:'Divisions ranked by '+title,cols:dupGap?['Division','Required','Functional','Utilisation %']:['Division','Required','Proc.',title,'Utilisation %'],rows:divs.map(d=>({nav:'#division/'+encodeURIComponent(d.name),cells:dupGap?[d.name,fmt(d.required),fmt(d.functional),d.gap_pct+'%']:[d.name,fmt(d.required),fmt(d.procurement),fieldFmt(d[field],key),d.gap_pct+'%']}))},
    table2: depts.length?{title:'Departments by '+title,cols:dupGap?['Department','Required','Functional','Utilisation %']:['Department','Required','Proc.',title,'Utilisation %'],rows:depts.map(d=>({nav:'#department/'+encodeURIComponent(d.name),cells:dupGap?[d.name,fmt(d.required),fmt(d.functional),d.gap_pct+'%']:[d.name,fmt(d.required),fmt(d.procurement),fieldFmt(d[field],key),d.gap_pct+'%']}))}
      :{title:'Top institutes by '+title,cols:dupGap?['Institute','Required','Functional','Utilisation %']:['Institute','Required','Proc.',title,'Utilisation %'],rows:insts.map(i=>({nav:'#institute/'+encodeURIComponent(i.name),cells:dupGap?[i.name,fmt(i.required),fmt(i.functional),i.gap_pct+'%']:[i.name,fmt(i.required),fmt(i.procurement),fieldFmt(i[field],key),i.gap_pct+'%']}))}};
}
function fieldFmt(v,key){return key==='budget'?fmt(v):key==='gap'?(v+'%'):fmt(v);}
function kpiLede(key,o){const L={
  gap:`State-wide Utilisation % is ${o.gap_pct}% (Functional ÷ NMC MSR) — ${fmt(o.functional)} functional units against ${fmt(o.required)} required. Above 100% means the norm is met overall; divisions below 100% have a working-equipment shortfall.`,
  budget:`Estimated procurement budget ${cr(o.budget)} (${fmt(o.budget)} ₹) = proposed procurement × unique-equipment costing.`,
  eol:`${fmt(o.end_of_life)} units are approaching end-of-life (<1 financial year of service left) — ${o.eol_pct}% of functional equipment. Plan replacement before failure.`,
  nonfunc:`${fmt(o.non_functional)} units non-functional (available − functional), ${(o.non_functional/o.available*100).toFixed(1)}% of available.`,
  functional:`${fmt(o.functional)} of ${fmt(o.available)} available units functional (${(o.functional/o.available*100).toFixed(1)}%).`,
  amc:`${fmt(o.amc)} units under active AMC/CMC — ${o.amc_pct}% of functional.`,
  procurement:`${fmt(o.procurement)} units proposed for new procurement across ${o.divisions} divisions.`,
  condemnation:`${fmt(o.condemnation)} units proposed for condemnation — ${(o.condemnation/o.non_functional*100).toFixed(1)}% of non-functional stock.`,
  available:`${fmt(o.available)} units available across ${fmt(o.college_count)} institutes.`,
  required:`${fmt(o.required)} units required per NMC Minimum Standard Requirements.`,
  colleges:`${fmt(o.college_count)} government medical colleges/hospitals across ${o.divisions} divisions.`};
  return L[key]||'';}
function buildKpiRecs(key,o,divs,insts){
  const out=[];const wd=divs[0],wi=insts[0];
  if(key==='gap'){
    out.push(rec(wd.gap_pct<50?'crit':wd.gap_pct<100?'warn':'ok','🚑',`Lowest utilisation: ${wd.name}`,`Utilisation ${wd.gap_pct}% (Functional ÷ NMC MSR)${wd.gap_pct<100?` — ${fmt(wd.functional_shortfall)} working units short`:' — norm met'}. Prioritise here.`));
    out.push(rec('warn','🏥',`Institute to watch: ${wi.name}`,`${wi.gap_pct}% utilisation. Field-verify before sanctioning — extreme ratios can signal NMC MSR data gaps.`));
    out.push(rec('info','📦','Redistribution','Divisions above 100% utilisation hold working surplus that could offset lower ones.'));
  }
  if(['procurement','budget'].includes(key)){
    out.push(rec('crit','🚑',`Prioritise ${wd.name}`,`Highest ${key==='budget'?'budget':'procurement'} need: ${fmt(wd.procurement)} units, ${cr(wd.budget)} (utilisation ${wd.gap_pct}%).`));
    out.push(rec('warn','🏥',`Institute hotspot: ${wi.name}`,`${fmt(wi.procurement)} units proposed. Field-verify before sanctioning.`));
    out.push(rec('info','📦','Pool high-volume equipment','Concentrate tenders on top equipment types for volume discounts.'));
  }
  if(key==='eol'){out.push(rec('warn','♻',`${fmt(o.end_of_life)} units near end-of-life`,`${o.eol_pct}% of functional stock. Build a replacement calendar before failures hit service.`));
    out.push(rec('info','📅','Sequence replacements',`Lead with divisions topping the ranking below.`));}
  if(['nonfunc','condemnation'].includes(key)){out.push(rec('crit','🔧',`${fmt(o.non_functional)} non-functional`,`${fmt(o.condemnation)} flagged for condemnation. Schedule disposal + replacement together.`));
    out.push(rec('warn','🛠️','Repair-vs-replace triage','High non-functional but low condemnation → run a repair audit under AMC.'));}
  if(key==='amc'){out.push(rec(o.amc_pct<70?'warn':'ok','🛡',`AMC coverage ${o.amc_pct}%`,`${fmt(o.functional-o.amc)} functional units uncovered. Contract critical equipment.`));}
  if(['functional','available','required','colleges'].includes(key)){out.push(rec('info','⚖️','Redistribution opportunity','Divisions where available ≫ required may hold surplus to offset shortages.'));
    out.push(rec('ok','✅','Functional ratio',`State functional ratio ${(o.functional/o.available*100).toFixed(1)}%. Focus on lowest-ratio divisions.`));}
  if(!out.length)out.push(rec('info','ℹ️','Review division ranking','Open the worst division for department-level detail.'));
  return out.join('');
}
/* ===== Unique Equipment List drill (Division→Institute→Department→full list) ===== */
function uniqCountFor(level,name,parentPath){
  const IX=DATA.eq_index;
  if(level==='division')return (IX.div[name]||[]).length;
  if(level==='institute')return (IX.inst[name]||[]).length;
  if(level==='department'){const inst=parentPath&&parentPath[1];
    if(inst&&IX.instdept[inst]&&IX.instdept[inst][name])return IX.instdept[inst][name].length;
    return (IX.dept[name]||[]).length;}
  return 0;
}
async function detailForUniqEquip(level,path){
  const IX=DATA.eq_index;
  const levelName={division:'Division',institute:'Institute',department:'Department',equipment:'Equipment'}[level];
  const crumbExtra=[['#uniqeq/division','Unique Equipment by Division']];
  const levels=['division','institute','department','equipment'];
  for(let i=0;i<path.length;i++){const lv=levels[i+1];const sub=path.slice(0,i+1);
    if(lv)crumbExtra.push(['#uniqeq/'+lv+'/'+sub.map(encodeURIComponent).join('/'),path[i]]);}
  const scopeLabel=path.length?path[path.length-1]:'State-wide';

  if(level==='equipment'){
    const [dname,iname,depname]=path;
    const inst=DATA.institutes.find(x=>x.name===iname);
    const dp=(inst&&inst.departments||[]).find(d=>d.name===depname);
    // [2.0] complete list from the API (1.0 showed top_equipment, truncated to 12)
    let rows=(await API.get('/drill',{...filterParams(),level:'equipment',path:[dname,iname,depname].join('||')})).rows;
    const title=`Unique Equipment List — ${depname} @ ${iname}`;
    return {title,scope:`Unique Equipment · ${dname} › ${iname} › ${depname}`,crumbExtra,
      lede:`Complete equipment list for <b>${depname}</b> at <b>${iname}</b> — ${rows.length} items, with Required, Available, Functional, Net Requirement, Utilisation % and Budget.`,
      stats:[['Unique Equipment',fmt(rows.length)],['Required',fmt(dp?dp.required:0)],['Functional',fmt(dp?dp.functional:0)],
        ['Net Requirement',sfmt(dp?dp.net_requirement:0)],['Utilisation %',(dp?dp.gap_pct:0)+'%'],['Budget',cr(dp?dp.budget:0)]],
      table:{title:'Unique equipment ('+rows.length+')',cols:['Equipment','Department','Required','Available','Functional','Net Req','Utilisation %','Budget ₹'],
        rows:rows.map(e=>({nav:null,cells:[e.name,depname,fmt(e.required),fmt(e.available),fmt(e.functional),sfmt(e.net_requirement),(e.gap_pct!=null?e.gap_pct:'—')+'%',fmt(e.budget)]}))}};
  }

  let childLevel, rows, parentObj;
  if(level==='division'){
    childLevel='institute';
    let divs=DATA.divisions.slice(); if(state.division.length)divs=divs.filter(d=>state.division.includes(d.name));
    rows=divs.map(d=>({name:d.name,count:uniqCountFor('division',d.name),path:[d.name],obj:d}));
    parentObj=DATA.overview;
  } else if(level==='institute'){
    childLevel='department';
    const [dname]=path;
    let insts=DATA.institutes.filter(i=>i.division===dname);
    if(state.institute.length)insts=insts.filter(i=>state.institute.includes(i.name));
    if(state.bedded.length)insts=insts.filter(i=>i.seat!=null&&state.bedded.includes(String(i.seat)));
    rows=insts.map(i=>({name:i.name,count:uniqCountFor('institute',i.name),path:[dname,i.name],obj:i}));
    parentObj=DATA.divisions.find(x=>x.name===dname);
  } else {
    childLevel='equipment';
    const [dname,iname]=path; const inst=DATA.institutes.find(x=>x.name===iname);
    let deps=(inst&&inst.departments||[]); if(state.department.length)deps=deps.filter(d=>state.department.includes(d.name));
    rows=deps.map(dp=>({name:dp.name,count:uniqCountFor('department',dp.name,[dname,iname]),path:[dname,iname,dp.name],obj:dp}));
    parentObj=inst;
  }
  rows.sort((a,b)=>b.count-a.count);
  const childName={institute:'Institute',department:'Department',equipment:'Equipment'}[childLevel];
  const totalUniq=path.length?uniqCountFor(level,scopeLabel,path.length>=2?path:null):(DATA.overview.equipment_types);
  const p=parentObj||DATA.overview;
  return {
    title:`Unique Equipment by ${levelName}`+(path.length?` — ${scopeLabel}`:''),
    scope:'Unique Equipment List · drill-through'+(path.length?(' · '+scopeLabel):''),
    crumbExtra,
    lede:`Distinct equipment names by <b>${levelName}</b>${path.length?(' within '+scopeLabel):''}. Click a bar or row to drill down to ${childName==='Equipment'?'the full equipment list':childName}. Counts reflect all active filters.`,
    stats:[['Unique Equipment',fmt(path.length?totalUniq:DATA.overview.equipment_types)],['Required',fmt(p.required)],['Functional',fmt(p.functional)],
      ['Net Requirement',sfmt(p.net_requirement)],['Utilisation %',(p.gap_pct!=null?p.gap_pct:'—')+'%'],['Budget',cr(p.budget)]],
    chart:{labels:rows.slice(0,14).map(r=>r.name),data:rows.slice(0,14).map(r=>r.count),fmt:'num'},
    chartTitle:`Unique Equipment by ${levelName}`,chartDesc:`Tap a bar to drill into that ${levelName.toLowerCase()}.`,
    _uniqTop:rows.slice(0,14),_uniqChild:childLevel,
    table:{title:`Unique Equipment by ${levelName}`,cols:[levelName,'Unique Equipment','Required','Functional','Net Req','Utilisation %','Budget ₹'],
      rows:rows.map(r=>({nav:'#uniqeq/'+childLevel+'/'+r.path.map(encodeURIComponent).join('/'),
        cells:[r.name,fmt(r.count),fmt(r.obj.required),fmt(r.obj.functional),sfmt(r.obj.net_requirement),(r.obj.gap_pct!=null?r.obj.gap_pct:'—')+'%',cr(r.obj.budget)]}))}
  };
}
/* ===== reusable metric-aware drill detail =====
 * level: 'division' | 'institute' | 'department' | 'equipment'
 * path:  [] | [division] | [division,institute] | [division,institute,department] etc.
 * The metric (mkey) is preserved down the whole path. Global slicer filters still apply. */
// [2.0] Drill children are aggregated by the server for ALL active filters (GET /api/v1/drill).
//       1.0 showed unfiltered rollups and, at equipment level, only the top 12 items per department.
async function drillChildren(mkey,level,path){
  const res=await API.get('/drill',{...filterParams(),level,path:(path||[]).join('||')});
  const next={division:'institute',institute:'department',department:'equipment',equipment:null}[level];
  return {parent:res.parent,childLevel:next,
    rows:res.rows.filter(r=>r.line_items>0).map(r=>({name:r.name,obj:r,path:[...(path||[]),r.name]}))};
}
async function detailForDrill(mkey,level,path){
  mkey=normMetric(mkey); const M=METRICS[mkey];
  const {parent,childLevel,rows}=await drillChildren(mkey,level,path);
  const levelName={division:'Division',institute:'Institute',department:'Department',equipment:'Equipment'}[level];
  const childName={institute:'Institute',department:'Department',equipment:'Equipment'}[childLevel]||'';
  // sort rows by the metric (Utilisation ascending=worst-first, others descending)
  const asc=(mkey==='util');
  rows.sort((a,b)=>{const x=mval(a.obj,mkey)||0,y=mval(b.obj,mkey)||0;return asc?x-y:y-x;});
  // breadcrumb chain within the drill (each step keeps the metric)
  const crumbExtra=[['#drill/'+mkey+'/division',M.label+' by Division']];
  const levels=['division','institute','department','equipment'];
  for(let i=0;i<path.length;i++){
    const lv=levels[i+1]; const sub=path.slice(0,i+1);
    if(lv)crumbExtra.push(['#drill/'+mkey+'/'+lv+'/'+sub.map(encodeURIComponent).join('/'), path[i]]);
  }
  const scopeLabel = path.length?path[path.length-1]:'State-wide';
  const title = `${M.label} by ${levelName}`+(path.length?` — ${scopeLabel}`:'');
  // KPI stat cards for the parent scope, with the active metric first
  const p=parent||DATA.overview;
  const stats=[
    [M.label, mfmt(p,mkey)],
    ['Required',fmt(p.required)],['Available',fmt(p.available)],['Functional',fmt(p.functional)],
    ['Non-Functional',fmt(p.non_functional)],['Net Requirement',sfmt(p.net_requirement)],
    ['Utilisation %',(p.gap_pct!=null?p.gap_pct:'—')+'%'],['Procurement',fmt(p.procurement)],['Budget',cr(p.budget)],
    ['Unique Equipment',fmt(p.equipment_types!=null?p.equipment_types:DATA.overview.equipment_types)],
  ];
  // chart of children by the active metric
  const top=rows.slice(0,14);
  const chart={labels:top.map(r=>r.name),data:top.map(r=>mval(r.obj,mkey)||0),
    fmt: mkey==='budget'?'cr':mkey==='util'?'pct':'num',
    colors: mkey==='util'?top.map(r=>gapColor(mval(r.obj,mkey))):undefined};
  const canDrill = childLevel!=null;
  return {
    title, scope:`${M.label} · drill-through`+(path.length?(' · '+scopeLabel):''),
    metricDrill:{mkey, childLevel, childRows:rows},
    crumbExtra,
    lede:`Showing <b>${M.label}</b> by ${levelName}${path.length?(' within '+scopeLabel):''}. Click a bar or row to drill down${canDrill?(' to '+childName):''}, keeping this metric and all active filters.`,
    stats,
    chart, chartTitle:`${M.label} by ${levelName}`,
    chartDesc: canDrill?`Tap a bar to drill into that ${levelName.toLowerCase()} → ${childName.toLowerCase()}.`:'Equipment level — this is the lowest level of the drill-through.',
    barNav: canDrill?top.map(r=>null):null,
    _drillTop:top,
    recs:'',
    table:{
      title:`${M.label} by ${levelName}`,
      cols:[levelName, M.label,'Required','Available','Functional','Net Req','Utilisation %','Budget ₹'],
      rows:rows.map(r=>({
        nav: canDrill?('#drill/'+mkey+'/'+childLevel+'/'+r.path.map(encodeURIComponent).join('/')):null,
        cells:[r.name, mfmt(r.obj,mkey), fmt(r.obj.required), fmt(r.obj.available), fmt(r.obj.functional), sfmt(r.obj.net_requirement), (r.obj.gap_pct!=null?r.obj.gap_pct:'—')+'%', cr(r.obj.budget)]
      }))
    }
  };
}

function detailForGroup(g,kind){
  const depts=(g.departments||[]).slice(0,12);
  const isInst=kind==='Institute';
  const deptNav = isInst ? (d=>'#instdept/'+encodeURIComponent(g.name)+'/'+encodeURIComponent(d.name)) : (d=>'#department/'+encodeURIComponent(d.name));
  // Bar chart drills to the NEXT hierarchy level:
  //   Division → Institutes ;  Institute → its Departments
  const insts=(g.institutes||[]).slice(0,14);
  const chart = isInst
    ? {labels:depts.map(d=>d.name),data:depts.map(d=>d.procurement),fmt:'num'}
    : {labels:insts.map(i=>i.name),data:insts.map(i=>i.procurement),fmt:'num'};
  const chartTitle = isInst?'Procurement by department (this institute)':'Procurement by institute (this division)';
  const chartDesc = isInst?'Tap a bar to drill into that department → equipment.':'Tap a bar to drill into that institute → department → equipment.';
  const barNav = isInst?depts.map(d=>d.name):insts.map(i=>i.name);
  const navPrefix = isInst?('#instdept/'+encodeURIComponent(g.name)+'/'):'#institute/';
  return {title:g.name,scope:isInst?('Division: '+g.division):`${(g.institutes||[]).length} institutes · ${fmt(g.college_count)} colleges`,
    lede:`${kind} scope · ${fmt(g.required)} required, ${fmt(g.available)} available, ${fmt(g.procurement)} proposed (utilisation ${g.gap_pct}%). Budget ${cr(g.budget)}. ${fmt(g.end_of_life)} units near end of life.`,
    stats:[['Required',fmt(g.required)],['Available',fmt(g.available)],['Functional',fmt(g.functional)],['Net Requirement',sfmt(g.net_requirement)],
      ['Procurement',fmt(g.procurement)],['Utilisation %',g.gap_pct+'%'],['Budget',cr(g.budget)],['Approaching EoL',fmt(g.end_of_life)],['Under AMC',fmt(g.amc)],['Unique Equipment',fmt(g.equipment_types!=null?g.equipment_types:DATA.overview.equipment_types)]],
    chart,chartTitle,chartDesc,barNav,navPrefix,
    recs:buildGroupRecs(g,kind),
    table:{title:isInst?'Departments (in this institute)':'Departments',cols:['Department','Req','Func','Net Req','Proc.','Utilisation %'],rows:depts.map(d=>({nav:deptNav(d),cells:[d.name,fmt(d.required),fmt(d.functional),sfmt(d.net_requirement),fmt(d.procurement),d.gap_pct+'%']}))},
    table2: kind==='Division'?{title:'Institutes in division (tap to drill in)',cols:['Institute','Required','Func','Net Req','Proc.','Utilisation %'],rows:(g.institutes||[]).map(i=>({nav:'#institute/'+encodeURIComponent(i.name),cells:[i.name,fmt(i.required),fmt(i.functional),sfmt(i.net_requirement),fmt(i.procurement),i.gap_pct+'%']}))}
      :{title:'Top equipment (lowest level)',cols:['Equipment','Req','Func','Net Req','Proc.','Budget ₹'],rows:(g.top_equipment||[]).map(e=>({nav:null,cells:[e.name,fmt(e.required),fmt(e.functional),sfmt(e.net_requirement),fmt(e.procurement),fmt(e.budget)]}))}};
}
function buildGroupRecs(g,kind){
  const out=[];const[cls,lbl]=sev(g.gap_pct);
  out.push(rec(g.gap_pct>=100?'crit':g.gap_pct>=50?'warn':'info','📊',`${lbl} gap (${g.gap_pct}%)`,`${fmt(g.procurement)} units vs ${fmt(g.required)} required. Budget ${cr(g.budget)}.`));
  const td=(g.departments||[])[0];if(td)out.push(rec('warn','🏷️',`Lead department: ${td.name}`,`${fmt(td.procurement)} units (${Math.round(td.procurement/g.procurement*100)||0}% of procurement). Sequence first.`));
  const te=(g.top_equipment||[])[0];if(te)out.push(rec('info','📦',`Costliest line: ${te.name}`,`${fmt(te.procurement)} units · ${cr(te.budget)}. Consider a framework contract.`));
  if(g.end_of_life>0)out.push(rec('warn','♻',`${fmt(g.end_of_life)} near end-of-life`,`${g.eol_pct}% of functional. Plan replacement.`));
  const ag=(g.functional||0)-(g.amc||0);if(ag>0)out.push(rec(g.amc_pct<70?'warn':'ok','🛡',`AMC coverage ${g.amc_pct}%`,`${fmt(ag)} functional units uncovered.`));
  return out.join('');
}
async function detailForInstDept(inst,dp){
  // [2.0] complete equipment list for this institute × department from the API (1.0: top 12 only)
  let eq=(dp.top_equipment||[]).slice();
  try{ eq=(await API.get('/drill',{level:'equipment',path:[inst.division,inst.name,dp.name].join('||')})).rows
        .sort((a,b)=>(b.procurement-a.procurement)||((b.budget||0)-(a.budget||0))); }catch(e){}
  return {title:dp.name+' — '+inst.name,scope:'Institute › Department · '+inst.division,
    lede:`${dp.name} at ${inst.name} · ${fmt(dp.required)} required, ${fmt(dp.functional)} functional, net requirement ${sfmt(dp.net_requirement)} (utilisation ${dp.gap_pct}%). ${fmt(dp.procurement)} proposed · budget ${cr(dp.budget)}.`,
    stats:[['Required',fmt(dp.required)],['Available',fmt(dp.available)],['Functional',fmt(dp.functional)],['Net Requirement',sfmt(dp.net_requirement)],
      ['Utilisation %',dp.gap_pct+'%'],['Procurement',fmt(dp.procurement)],['Budget',cr(dp.budget)],['Approaching EoL',fmt(dp.end_of_life)]],
    chart:{labels:eq.slice(0,12).map(e=>e.name),data:eq.slice(0,12).map(e=>e.procurement),fmt:'num'},
    chartTitle:'Equipment procurement (this department here)',chartDesc:'Equipment proposed within '+dp.name+' at this institute. Tap a bar to open the equipment.',
    barNav:eq.slice(0,12).map(e=>e.name),navPrefix:'#equip/',
    recs:'',
    crumbExtra:[['#division/'+encodeURIComponent(inst.division),inst.division],['#institute/'+encodeURIComponent(inst.name),inst.name]],
    table:{title:'Equipment in this department (lowest level)',cols:['Equipment','Req','Avail','Func','Net Req','Proc.','Budget ₹'],
      rows:eq.map(e=>({nav:null,cells:[e.name,fmt(e.required),fmt(e.available),fmt(e.functional),sfmt(e.net_requirement),fmt(e.procurement),fmt(e.budget)]}))}};
}
function detailForEquipment(e){
  return {title:e.name,scope:'Equipment · state-wide',
    lede:`${fmt(e.required)} required, ${fmt(e.available)} available, ${fmt(e.procurement)} proposed for procurement (gap ${e.gap_pct}%). Indicative budget ${cr(e.budget)}. ${fmt(e.end_of_life)} units near end-of-life.`,
    stats:[['Required',fmt(e.required)],['Available',fmt(e.available)],['Functional',fmt(e.functional)],['Procurement',fmt(e.procurement)],
      ['Utilisation %',e.gap_pct+'%'],['Budget',cr(e.budget)],['Approaching EoL',fmt(e.end_of_life)],['Under AMC',fmt(e.amc)]],
    chart:{labels:['Required','Available','Functional','Procurement'],data:[e.required,e.available,e.functional,e.procurement],fmt:'num'},
    chartTitle:'Quantity profile',chartDesc:'Required vs available vs functional vs proposed.',barNav:null,
    recs:rec(e.gap_pct>=100?'crit':e.gap_pct>=50?'warn':'info','🔬',`Gap ${e.gap_pct}%`,`${fmt(e.procurement)} units proposed. Budget ${cr(e.budget)}.`)+
      (e.end_of_life>0?rec('warn','♻',`${fmt(e.end_of_life)} units near end-of-life`,'Plan phased replacement.'):'')+
      rec('info','📦','Framework contract','High-volume single-equipment procurement is a candidate for a rate contract across institutes.'),
    table:{title:'Profile',cols:['Metric','Value'],rows:[['Required',fmt(e.required)],['Available',fmt(e.available)],['Functional',fmt(e.functional)],
      ['Non-functional',fmt(Math.max(0,e.available-e.functional))],['Proposed condemnation',fmt(e.condemnation)],['Under AMC',fmt(e.amc)]].map(r=>({cells:r}))},
    table2:null};
}

/* ===== detail renderer ===== */
function renderDetail(D){
  let crumb=`<a onclick="go('#'+state.page)">${PAGE_TITLE[state.page]}</a>`;
  (D.crumbExtra||[]).forEach(c=>{crumb+=` ▸ <a onclick="go('${c[0]}')">${c[1]}</a>`;});
  crumb+=` ▸ ${D.title}`;
  document.getElementById('crumb').innerHTML=crumb;
  document.getElementById('detailScope').textContent=D.scope||'';
  document.getElementById('detailTitle').textContent=D.title;
  document.getElementById('detailLede').textContent=D.lede;
  document.getElementById('detailStats').innerHTML=D.stats.map(s=>`<div class="stat"><div class="l">${s[0]}</div><div class="v">${s[1]}</div></div>`).join('');
  document.getElementById('recs').innerHTML=D.recs;
  charts.detail&&charts.detail.destroy();
  const chartCard=document.getElementById('detailChart').closest('.card');
  if(!D.chart){ if(chartCard)chartCard.style.display='none'; }
  else{
  if(chartCard)chartCard.style.display='';
  document.getElementById('detailChartTitle').textContent=D.chartTitle;
  document.getElementById('detailChartDesc').textContent=D.chartDesc;
  const tick=D.chart.fmt==='cr'?(v=>'₹'+(v/1e7).toFixed(0)+'Cr'):D.chart.fmt==='pct'?(v=>v+'%'):(v=>fmt(v));
  const horiz=D.chart.labels.length>7;
  const dlKind=D.chart.fmt;
  charts.detail=new Chart(document.getElementById('detailChart'),{type:'bar',
    data:{labels:D.chart.labels,datasets:[{data:D.chart.data,backgroundColor:D.chart.colors||'#3182bd'}]},
    options:{indexAxis:horiz?'y':'x',responsive:true,maintainAspectRatio:false,
      layout:{padding:horiz?{right:46}:{top:22}},
      plugins:{legend:{display:false},datalabels:{anchor:'end',align:'end',clamp:true,offset:3,
        color:'#0b3d6b',font:{weight:'600',size:10},formatter:v=>v?dlFmt(dlKind)(v):''}},
      onClick:(e,els)=>{if(!els.length)return;const idx=els[0].index;
        if(D._uniqTop){const r=D._uniqTop[idx];if(r)go('#uniqeq/'+D._uniqChild+'/'+r.path.map(encodeURIComponent).join('/'));return;}
        if(D.metricDrill){const md=D.metricDrill;const r=(D._drillTop||[])[idx];
          if(r&&md.childLevel)drillTo(md.mkey,md.childLevel,r.path);
          // equipment level: terminal, no further navigation
          return;}
        if(D.barNav&&D.barNav[idx]!=null)go((D.navPrefix||'#division/')+encodeURIComponent(D.barNav[idx]));},
      scales:{[horiz?'x':'y']:{ticks:{callback:tick}}}},plugins:[ChartDataLabels]});
  }
  detailTable('detailTable','detailTableTitle',D.table);
  detailTable('detailTable2','detailTable2Title',D.table2);
  // exports for detail tables
  const safe=(D.title||'detail').replace(/[^a-z0-9]+/gi,'_').slice(0,40);
  if(D.table){registerExport('detailTable','MEDD_'+safe+'_1',D.table.cols,()=>D.table.rows.map(r=>r.cells));
    document.getElementById('detailTableTitle').innerHTML=D.table.title+' '+exportBtns('detailTable');}
  if(D.table2){registerExport('detailTable2','MEDD_'+safe+'_2',D.table2.cols,()=>D.table2.rows.map(r=>r.cells));
    document.getElementById('detailTable2Title').innerHTML=D.table2.title+' '+exportBtns('detailTable2');}
}
let _dtState={};  // per-table id: {q, page, per, sortK, sortDir, rows, cols, nav}
function detailTable(id,titleId,T){
  if(!T){document.getElementById(id).innerHTML='';document.getElementById(titleId).textContent='';
    const c=document.getElementById(id+'Controls'); if(c)c.innerHTML='';
    const pg=document.getElementById(id+'Pager'); if(pg)pg.innerHTML='';return;}
  document.getElementById(titleId).textContent=T.title;
  // store full row set + reset paging/search when a new table loads
  _dtState[id]={q:'',page:0,per:15,sortK:null,sortDir:1,rows:T.rows.slice(),cols:T.cols,capBase:T};
  // inject search box into the controls slot (create if missing)
  let ctrl=document.getElementById(id+'Controls');
  if(!ctrl){ctrl=document.createElement('div');ctrl.id=id+'Controls';ctrl.style.cssText='display:flex;gap:8px;margin:6px 0 8px;align-items:center';
    const tbl=document.getElementById(id);tbl.parentNode.insertBefore(ctrl,tbl);}
  ctrl.innerHTML=`<input id="${id}Search" placeholder="Search…" style="flex:1;min-width:160px;max-width:300px;padding:6px 10px;border:1px solid var(--bd);border-radius:7px;font-size:12.5px">`;
  document.getElementById(id+'Search').oninput=e=>{_dtState[id].q=e.target.value.toLowerCase();_dtState[id].page=0;dtBody(id,titleId);};
  // pager slot
  let pg=document.getElementById(id+'Pager');
  if(!pg){pg=document.createElement('div');pg.id=id+'Pager';pg.style.cssText='display:flex;justify-content:space-between;align-items:center;margin-top:8px';
    const tbl=document.getElementById(id);tbl.parentNode.insertBefore(pg,tbl.nextSibling);}
  dtBody(id,titleId);
  const capEl=document.getElementById(id+'Cap');
  if(capEl)capEl.innerHTML=T.cols.includes('Utilisation %')?'<div class="tcap"><b>Utilisation %</b> = <code>Functional ÷ Required (NMC MSR) × 100</code>. Higher = better; ≥100% means the NMC MSR norm is met. Hover a header for its definition.</div>':'';
}
function dtBody(id,titleId){
  const S=_dtState[id]; if(!S)return;
  let rows=S.rows;
  if(S.q)rows=rows.filter(r=>r.cells.some(c=>String(c).toLowerCase().includes(S.q)));
  if(S.sortK!=null){const k=S.sortK,dir=S.sortDir;
    rows=[...rows].sort((a,b)=>{const x=a.cells[k],y=b.cells[k];
      const nx=parseFloat(String(x).replace(/[^0-9.\-−]/g,'').replace('−','-')),ny=parseFloat(String(y).replace(/[^0-9.\-−]/g,'').replace('−','-'));
      if(!isNaN(nx)&&!isNaN(ny))return (nx-ny)*dir;
      return String(x).localeCompare(String(y))*dir;});}
  const total=rows.length,per=S.per,pages=Math.max(1,Math.ceil(total/per));
  if(S.page>=pages)S.page=0;
  const pageRows=rows.slice(S.page*per,S.page*per+per);
  const head='<thead><tr>'+S.cols.map((c,i)=>{const def=COLDEF[c];const t=def?` title="${def.replace(/"/g,'&quot;')}"`:'';const ar=S.sortK===i?(S.sortDir>0?' ↑':' ↓'):'';return `<th class="${i?'num':''}" style="cursor:pointer"${t} onclick="dtSort('${id}','${titleId}',${i})">${c}${ar}</th>`;}).join('')+'</tr></thead>';
  const body='<tbody>'+pageRows.map(r=>{const cells=r.cells.map((c,i)=>`<td class="${i?'num':''}">${i?c:escapeHtml(c)}</td>`).join('');return r.nav?`<tr class="clk" onclick="go('${r.nav}')">${cells}</tr>`:`<tr class="dtrow" onclick="dtSelect(this)">${cells}</tr>`;}).join('')+'</tbody>';
  document.getElementById(id).innerHTML=head+body;
  const pg=document.getElementById(id+'Pager');
  if(pg){const mk=(l,p,dis)=>`<button class="btn" ${dis?'disabled':''} onclick="dtPage('${id}','${titleId}',${p})" style="padding:4px 9px;font-size:12px${dis?';opacity:.4':''}">${l}</button>`;
    pg.innerHTML=`<span class="muted" style="font-size:11.5px">Showing ${total?S.page*per+1:0}–${Math.min(S.page*per+per,total)} of ${fmt(total)}</span>`+
      `<span style="display:flex;gap:6px;align-items:center">${mk('‹',S.page-1,S.page<=0)}<span class="muted" style="font-size:11.5px">Page ${S.page+1}/${pages}</span>${mk('›',S.page+1,S.page>=pages-1)}</span>`;}
}
function dtSort(id,titleId,k){const S=_dtState[id];if(S.sortK===k)S.sortDir*=-1;else{S.sortK=k;S.sortDir=k?-1:1;}dtBody(id,titleId);}
function dtPage(id,titleId,p){_dtState[id].page=p;dtBody(id,titleId);}
function dtSelect(tr){const tb=tr.closest('tbody');tb.querySelectorAll('tr.dtsel').forEach(x=>x.classList.remove('dtsel'));tr.classList.add('dtsel');}
