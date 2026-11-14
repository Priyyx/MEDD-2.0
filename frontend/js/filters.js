/* MEDD Maharashtra 2.0 — filters.js
 * Code below is carried over from the MEDD 1.0 index.html (inline script); changes for the
 * PostgreSQL/API integration are marked with  // [2.0]  comments. See docs/05_CHANGE_LOG.md. */
/* ===== Unique Equipment List KPI — distinct equipment names under active filters ===== */
function uniqueEquipmentSet(){
  const IX=DATA.eq_index; if(!IX) return null;
  const inter=(a,b)=>{const S=new Set(b);return a.filter(x=>S.has(x));};
  let ids=null; // null = all
  const applyUnion=(sets)=>{const u=new Set();sets.forEach(s=>s&&s.forEach(x=>u.add(x)));return [...u];};
  // Division / Institute / Department each contribute a UNION of their own selections,
  // then those groups are INTERSECTED together (equipment must exist in all active dims).
  if(state.institute.length){ids=merge(ids, applyUnion(state.institute.map(n=>IX.inst[n])), inter);}
  else if(state.division.length){ids=merge(ids, applyUnion(state.division.map(n=>IX.div[n])), inter);}
  if(state.department.length){
    // department equipment: if institutes are also chosen, use instdept; else state-wide dept
    let deptSets=[];
    if(state.institute.length){state.institute.forEach(inN=>{const dd=IX.instdept[inN]||{};state.department.forEach(dp=>{if(dd[dp])deptSets.push(dd[dp]);});});}
    else state.department.forEach(dp=>{if(IX.dept[dp])deptSets.push(IX.dept[dp]);});
    ids=merge(ids, applyUnion(deptSets), inter);
  }
  if(state.equipment.length){const eqIds=state.equipment.map(n=>IX.names.indexOf(n)).filter(i=>i>=0);ids=merge(ids,eqIds,inter);}
  if(state.subcat.length){const scIds=new Set();state.subcat.forEach(sc=>{(IX.subcat[sc]||[]).forEach(i=>scIds.add(i));});ids=merge(ids,[...scIds],inter);}
  if(state.bedded.length){
    // institutes matching bedded, union their equipment, intersect
    const insts=DATA.institutes.filter(i=>i.seat!=null&&state.bedded.includes(String(i.seat)));
    ids=merge(ids, applyUnion(insts.map(i=>IX.inst[i.name])), inter);
  }
  return ids==null? IX.names.map((_,i)=>i) : ids;
  function merge(cur,add,fn){return cur==null?add:fn(cur,add);}
}
function uniqueEquipmentCount(){const s=uniqueEquipmentSet();return s?s.length:(DATA.overview.equipment_types||0);}
function uniqueEquipmentNames(){const s=uniqueEquipmentSet();const IX=DATA.eq_index;return (s||[]).map(i=>IX.names[i]).sort();}
// Set of equipment NAMES that are "applicable" under the active equipment + sub-category filters.
// Returns null when neither filter is active (meaning: no restriction).
function applicableEquipNames(){
  const IX=DATA.eq_index; if(!IX) return null;
  if(!state.equipment.length && !state.subcat.length) return null;
  let set=null;
  if(state.subcat.length){const ids=new Set();state.subcat.forEach(sc=>{(IX.subcat[sc]||[]).forEach(i=>ids.add(i));});set=new Set([...ids].map(i=>IX.names[i]));}
  if(state.equipment.length){const es=new Set(state.equipment);set = set? new Set([...set].filter(n=>es.has(n))) : es;}
  return set;
}
// Does an entity (division/institute/department) contain any applicable equipment?
function entityHasApplicable(idSet){
  const app=applicableEquipNames(); if(!app) return true;
  const IX=DATA.eq_index;
  return (idSet||[]).some(i=>app.has(IX.names[i]));
}

/* ===== SCOPE: combine division + institute + equipment filters =====
   When equipment is selected we recompute from equipment_catalog intersected
   with the chosen division/institute (those carry per-equipment rollups only
   at top level, so for equipment+geo we approximate using the global catalog). */
function sumBlocks(rows){
  if(!rows.length) return null;
  const S=(k)=>rows.reduce((a,b)=>a+(b[k]||0),0);
  const req=S('required'),fn=S('functional'),av=S('available'),amc=S('amc');
  return {college_count:new Set(rows.map(r=>r._college||r.name)).size||S('college_count'),
    required:req,available:av,functional:fn,non_functional:S('non_functional'),
    procurement:S('procurement'),net_requirement:(req-fn),budget:S('budget'),
    end_of_life:S('end_of_life'),condemnation:S('condemnation'),amc:amc,
    gap_pct:req?+(fn/req*100).toFixed(2):0,util_pct:req?+(fn/req*100).toFixed(2):0,
    amc_pct:fn?+(amc/fn*100).toFixed(2):0,func_pct:av?+(fn/av*100).toFixed(2):0,
    eol_pct:fn?+(S('end_of_life')/fn*100).toFixed(2):0,
    divisions:DATA.overview.divisions};
}
// institutes filtered by division + bedded selections
function filteredInstitutes(){
  let l=DATA.institutes.slice();
  if(state.division.length)l=l.filter(i=>state.division.includes(i.division));
  if(state.institute.length)l=l.filter(i=>state.institute.includes(i.name));
  if(state.bedded.length)l=l.filter(i=>i.seat!=null&&state.bedded.includes(String(i.seat)));
  return l;
}
function baseScope(){
  // If any geo/bedded filter is active, aggregate the matching institutes.
  if(state.institute.length||state.division.length||state.bedded.length){
    const l=filteredInstitutes();
    const agg=sumBlocks(l.map(i=>({...i,_college:i.name})));
    if(agg){agg.college_count=l.length; return agg;}
  }
  return DATA.overview;
}
// [2.0] scope() now returns the EXACT server-side aggregate for every active filter combination
//       (GET /api/v1/dashboard/scope). The MEDD 1.0 client-side approximation is retained below as
//       scopeLegacy() for reference only (audit finding A5: equipment+geo used state-wide totals).
function scope(){ return (SCOPE && SCOPE.summary) || DATA.overview; }
function scopeLegacy(){
  let b=baseScope();
  // department filter refines (using department rollups intersected with geo where possible)
  if(state.department.length){
    // sum selected departments (state-wide or within selected divisions)
    let deptRows=[];
    state.department.forEach(dn=>{
      const dp=DATA.departments.find(x=>x.name===dn); if(!dp)return;
      if(state.division.length){(dp.divisions_bd||[]).filter(v=>state.division.includes(v.name)).forEach(v=>deptRows.push(v));}
      else if(state.institute.length){(dp.institutes||[]).filter(i=>state.institute.includes(i.name)).forEach(i=>deptRows.push(i));}
      else deptRows.push(dp);
    });
    const agg=sumBlocks(deptRows); if(agg){agg.college_count=b.college_count; b=agg;}
  }
  if(!state.equipment.length) return b;
  // equipment selected: sum those equipment rollups (state-wide catalog)
  const rows=state.equipment.map(en=>DATA.equipment_catalog.find(e=>e.name===en)).filter(Boolean);
  const agg=sumBlocks(rows);
  if(!agg) return b;
  agg.college_count=b.college_count;agg._equipment=true;
  return agg;
}

/* ===== filters / controls ===== */
/* ===== multi-select searchable slicers ===== */
function msOptions(key){
  // scoped institute set based on division + bedded
  const scopedInsts=()=>{let l=DATA.institutes;
    if(state.division.length)l=l.filter(i=>state.division.includes(i.division));
    if(state.bedded.length)l=l.filter(i=>i.seat!=null&&state.bedded.includes(String(i.seat)));
    if(state.institute.length)l=l.filter(i=>state.institute.includes(i.name));
    return l;};
  if(key==='division')return DATA.divisions.map(d=>d.name).sort();
  if(key==='bedded')return (DATA.bedded_capacities||[]).map(String);
  if(key==='institute'){let l=DATA.institutes;
    if(state.division.length)l=l.filter(i=>state.division.includes(i.division));
    if(state.bedded.length)l=l.filter(i=>i.seat!=null&&state.bedded.includes(String(i.seat)));
    return l.map(i=>i.name).sort();}
  if(key==='department'){
    // departments present in the scoped institutes
    const insts=scopedInsts();
    if(state.division.length||state.institute.length||state.bedded.length){
      const s=new Set();insts.forEach(i=>(i.departments||[]).forEach(d=>s.add(d.name)));
      return [...s].sort();}
    return [...DATA.departments].map(d=>d.name).sort();}
  if(key==='subcat')return (DATA.sub_categories||[]).slice().sort();
  if(key==='equipment'){
    // equipment restricted by scope (division/institute/bedded/department) AND sub-category
    let names=null;
    if(state.subcat.length){const ids=new Set();state.subcat.forEach(sc=>{(DATA.eq_index.subcat[sc]||[]).forEach(i=>ids.add(i));});names=[...ids].map(i=>DATA.eq_index.names[i]);}
    if(state.division.length||state.institute.length||state.bedded.length||state.department.length){
      const insts=scopedInsts();const s=new Set();
      // [2.0] complete equipment index per institute×department (1.0 used top_equipment, truncated to 12)
      const IX=DATA.eq_index;
      insts.forEach(i=>Object.entries((IX.instdept||{})[i.name]||{}).forEach(([dn,ids])=>{
        if(state.department.length&&!state.department.includes(dn))return;
        ids.forEach(x=>s.add(IX.names[x]));}));
      if(s.size){let arr=[...s];if(names)arr=arr.filter(n=>names.includes(n));return arr.sort();}}
    if(names)return names.sort();
    return DATA.equipment_names;}
  return [];
}
function msRender(key){
  const host=document.getElementById('ms-'+key);if(!host)return;
  const label=host.dataset.label;const sel=state[key];
  const opts=msOptions(key);
  const valTxt=sel.length===0?('All '+label.toLowerCase()+'s'):sel.length===1?sel[0]:sel.length+' selected';
  host.innerHTML=`<button class="ms-btn" type="button"><span class="msl">${label}</span><span class="msv">${valTxt}</span></button>
    <div class="ms-pop"><input class="ms-search" placeholder="Search ${label.toLowerCase()}…">
      <div class="ms-list"></div>
      <div class="ms-actions"><button class="ms-all">Select all</button><button class="ms-none">Clear</button></div></div>`;
  const btn=host.querySelector('.ms-btn'),pop=host.querySelector('.ms-pop'),search=host.querySelector('.ms-search'),list=host.querySelector('.ms-list');
  function drawList(q){q=(q||'').toLowerCase();
    list.innerHTML=opts.filter(o=>o.toLowerCase().includes(q)).slice(0,300).map(o=>
      `<label class="ms-opt"><input type="checkbox" ${sel.includes(o)?'checked':''} data-v="${escapeHtml(o)}"><span>${escapeHtml(o)}</span></label>`).join('')||'<div class="muted" style="padding:6px">No matches</div>';
    list.querySelectorAll('input').forEach(cb=>cb.onchange=()=>{const v=cb.dataset.v;
      if(cb.checked){if(!state[key].includes(v))state[key].push(v);}else{state[key]=state[key].filter(x=>x!==v);}
      if(key==='division')state.institute=[]; // reset dependent
      onFilterChange();});
  }
  btn.onclick=()=>{document.querySelectorAll('.ms-pop').forEach(p=>{if(p!==pop)p.classList.remove('show');});pop.classList.toggle('show');search.value='';drawList('');search.focus();};
  search.oninput=()=>drawList(search.value);
  host.querySelector('.ms-all').onclick=()=>{const q=search.value.toLowerCase();opts.filter(o=>o.toLowerCase().includes(q)).forEach(o=>{if(!state[key].includes(o))state[key].push(o);});if(key==='division')state.institute=[];onFilterChange();};
  host.querySelector('.ms-none').onclick=()=>{state[key]=[];if(key==='division')state.institute=[];onFilterChange();};
  drawList('');
}
function renderSlicers(){['division','institute','department','subcat','equipment','bedded'].forEach(msRender);}
async function onFilterChange(){
  // prune selections that are no longer valid options given upstream filters
  const validInst=new Set(msOptions('institute'));state.institute=state.institute.filter(x=>validInst.has(x));
  const validDept=new Set(msOptions('department'));state.department=state.department.filter(x=>validDept.has(x));
  const validEq=new Set(msOptions('equipment'));state.equipment=state.equipment.filter(x=>validEq.has(x));
  renderSlicers();
  await applyFilters();   // [2.0] server-side aggregation for the new filter set
}
// [2.0] fetch exact aggregates for the current filters, then re-render the visible page
async function applyFilters(){
  showBusy(true);
  try{ await refreshScope(); }catch(e){ if(e.status!==401) showError('Could not load filtered data: '+e.message); }
  finally{ showBusy(false); }
  _cmState.page=0; if(typeof _eqxState!=='undefined') _eqxState.page=0;
  if(document.getElementById('page-detail').classList.contains('hide')) renderPage(state.page); else route();
}
document.addEventListener('click',e=>{if(!e.target.closest('.ms'))document.querySelectorAll('.ms-pop').forEach(p=>p.classList.remove('show'));});

function resetFilters(){state.division=[];state.institute=[];state.equipment=[];state.department=[];state.bedded=[];state.subcat=[];renderSlicers();applyFilters();}

// [2.0] set one slicer, refresh the exact server aggregates, then open the metric drill-through
async function setFilterAndDrill(key,vals,mkey,level,path){
  state[key]=vals; renderSlicers();
  try{ await refreshScope(); }catch(e){}
  drillTo(mkey,level||'division',path||[]);
}
