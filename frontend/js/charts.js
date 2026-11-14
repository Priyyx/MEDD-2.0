/* MEDD Maharashtra 2.0 — charts.js
 * Code below is carried over from the MEDD 1.0 index.html (inline script); changes for the
 * PostgreSQL/API integration are marked with  // [2.0]  comments. See docs/05_CHANGE_LOG.md. */
function dlFmt(kind){return kind==='cr'?(v=>'₹'+(v/1e7).toFixed(1)+'Cr'):kind==='pct'?(v=>v+'%'):(v=>v>=1000?(v/1000).toFixed(v>=10000?0:1)+'k':Math.round(v));}
function datalabelCfg(kind){return {anchor:'end',align:'end',clamp:true,offset:2,
  color:'#0b3d6b',font:{weight:'600',size:10},formatter:v=>v?dlFmt(kind)(v):''};}
function withDL(opts,kind){opts.plugins=opts.plugins||{};opts.plugins.datalabels=datalabelCfg(kind);
  opts.plugins.legend={display:false};
  // give headroom so top labels aren't clipped
  return opts;}

/* ===== government colour coding ===== */
// GAP% = Functional ÷ NMC MSR × 100. HIGHER = BETTER (norm met).
// green = adequate (norm met), red = critical shortfall.
const GAP_BANDS=[
  {min:100, c:'#1a9850', lbl:'Adequate (≥100%)',     cls:'low'},   // norm met/exceeded
  {min:75,  c:'#a6d96a', lbl:'Near-adequate (75–100%)',cls:'low'},
  {min:50,  c:'#fee08b', lbl:'Moderate (50–75%)',     cls:'med'},
  {min:25,  c:'#fc8d59', lbl:'Low (25–50%)',          cls:'high'},
  {min:-1,  c:'#d73027', lbl:'Critical (<25%)',       cls:'crit'},
];
function gapColor(g){for(const b of GAP_BANDS)if(g>=b.min)return b.c;return '#d73027';}
function gapBandLabel(g){for(const b of GAP_BANDS)if(g>=b.min)return b;return GAP_BANDS[GAP_BANDS.length-1];}
// Quartiles for count metrics (procurement, budget). 4 government shades blue->dark.
const COUNT_RAMP=['#c6dbef','#6baed6','#3182bd','#08519c'];
function quartiles(vals){const s=[...vals].sort((a,b)=>a-b);const q=p=>{const i=p*(s.length-1);const lo=Math.floor(i),hi=Math.ceil(i);return s[lo]+(s[hi]-s[lo])*(i-lo);};return [q(.25),q(.5),q(.75)];}
function countClass(v,qs){let c=0;for(const t of qs)if(v>t)c++;return c;}
function divColor(d){
  if(state.metric==='gap_pct')return gapColor(d.gap_pct);
  const qs=quartiles(DATA.divisions.map(x=>x[state.metric]));
  return COUNT_RAMP[countClass(d[state.metric],qs)];
}
const METRIC_LABEL={gap_pct:'Utilisation % (Functional ÷ MSR)',procurement:'Procurement (units)',budget:'Budget (₹)'};
const metricDisplay=d=>state.metric==='gap_pct'?d.gap_pct+'%':state.metric==='budget'?cr(d.budget):fmt(d.procurement);
// gap severity: <25% Critical, 25–50 Low, 50–75 Moderate, 75+ Adequate
function sev(gap){const b=gapBandLabel(gap);return [b.cls,b.cls==='crit'?'Critical':b.cls==='high'?'Low':b.cls==='med'?'Moderate':'Adequate'];}

/* ===== map region matching ===== */
const DIV_KEYS=['amravati','sambhajinagar','kokan','nagpur','nashik','pune'];
const norm=s=>(s||'').toLowerCase().replace(/[^a-z]/g,'').replace('chhatrapati','').replace('sambhajinagar','sambhaji').replace('konkan','kokan');
function regionKey(name){const t=norm(name);return DIV_KEYS.find(k=>{const r=norm(k).replace('sambhajinagar','sambhaji');return r.includes(t)||t.includes(r);});}

function renderGIS(){
  buildMap('mapSvg2','mapImg2','mapwrap2','mapTip2','mapLegend2','mapDesc2');
  renderHotspots('hotspots2');
}

/* ===== MAP ===== */
function buildMap(svgId,imgId,wrapId,tipId,legId,descId){
  const svg=document.getElementById(svgId);if(!svg)return;
  const img=document.getElementById(imgId); if(img) img.style.display='none';
  const M=DATA.map; svg.setAttribute('viewBox',`0 0 ${M.W} ${M.H}`);
  // Effective per-division values — recomputed from ALL active filters (division, institute,
  // department, bedded capacity, equipment) so the map, markers and legend all stay in sync.
  const eqSel=state.equipment, instSel=state.institute, deptSel=state.department, bedSel=state.bedded, scSel=state.subcat;
  const anyFilter = eqSel.length||instSel.length||deptSel.length||bedSel.length||scSel.length;
  function effDiv(d){
    if(!anyFilter) return d;
    // [2.0] exact per-division aggregate for ALL active filters from the server (replaces the approximation below)
    if(SCOPE&&SCOPE.divisions){const sd=SCOPE.divisions.find(x=>x.name===d.name);
      if(!sd||!sd.line_items)return {...d,required:0,functional:0,available:0,procurement:0,budget:0,net_requirement:0,gap_pct:0,_empty:true};
      return {...sd,_empty:false};}
    // effective equipment set from equipment + sub-category filters
    const appSet=applicableEquipNames(); // null if neither eq nor subcat active
    const eqNames = appSet? [...appSet] : (eqSel.length?eqSel.slice():null);
    let insts=DATA.institutes.filter(i=>i.division===d.name);
    if(instSel.length)insts=insts.filter(i=>instSel.includes(i.name));
    if(bedSel.length)insts=insts.filter(i=>i.seat!=null&&bedSel.includes(String(i.seat)));
    if(!insts.length)return {...d,required:0,functional:0,procurement:0,budget:0,net_requirement:0,gap_pct:0,_empty:true};
    let req=0,fn=0,av=0,proc=0,bud=0;
    if(eqNames){
      // sum the applicable equipment for this division via the equipment→division map
      eqNames.forEach(en=>{const m=(DATA.equipment_div_map[en]||{})[d.name]; if(m){req+=m.r;fn+=m.f;proc+=m.p;bud+=m.b;}});
    } else if(deptSel.length){
      insts.forEach(i=>(i.departments||[]).filter(dp=>deptSel.includes(dp.name)).forEach(dp=>{req+=dp.required;fn+=dp.functional;av+=dp.available;proc+=dp.procurement;bud+=dp.budget;}));
    } else {
      insts.forEach(i=>{req+=i.required;fn+=i.functional;av+=i.available;proc+=i.procurement;bud+=i.budget;});
    }
    const empty=(req===0&&fn===0&&proc===0);
    return {...d,required:req,functional:fn,available:av,procurement:proc,budget:bud,net_requirement:req-fn,gap_pct:req?+(fn/req*100).toFixed(2):0,_empty:empty};
  }
  const divBy={}; DATA.divisions.forEach(d=>{const k=regionKey(d.name); if(k)divBy[k]=effDiv(d);});
  const eqNote = anyFilter?` · filtered`:'';
  let html='<rect x="0" y="0" width="'+M.W+'" height="'+M.H+'" fill="#f6f9fc"/>';
  // 35 district shapes, coloured by their division's (possibly equipment-scoped) value
  M.districts.forEach(dist=>{const dv=divBy[dist.division]; if(!dv)return;
    const active=!state.division.length||state.division.includes(dv.name);
    html+=`<path d="${dist.d}" fill="${dv._empty?'#e5e9ee':divColor(dv)}" fill-opacity="${active?1:0.3}" stroke="#ffffff" stroke-width="0.7" style="cursor:pointer" data-div="${dv.name}" data-dist="${dist.name}"><title>${dist.name} (${dv.name}): Utilisation ${dv.gap_pct}%${eqNote}</title></path>`;});
  // district name labels (white halo for readability). Hidden for a division when it's dimmed.
  M.districts.forEach(dist=>{const dv=divBy[dist.division]; if(!dv)return;
    const active=!state.division.length||state.division.includes(dv.name);
    html+=`<text x="${dist.cx}" y="${dist.cy}" text-anchor="middle" font-size="7.5" font-weight="600" fill="#1f2937" opacity="${active?0.92:0.3}" style="paint-order:stroke;stroke:#ffffff;stroke-width:2.2px;stroke-linejoin:round;pointer-events:none">${dist.name}</text>`;});
  // division VALUE markers (compact pill — react to equipment filter too)
  DATA.divisions.forEach(d0=>{const k=regionKey(d0.name); if(!k)return; const c=(M.div_centroids||{})[k]; if(!c)return; const d=divBy[k];
    const active=!state.division.length||state.division.includes(d.name);
    const val=state.metric==='gap_pct'?Math.round(d.gap_pct)+'%':state.metric==='budget'?'₹'+(d.budget/1e7).toFixed(0)+'Cr':fmt(d.procurement);
    const wpx=Math.max(val.length*7.5+14,34);
    html+=`<g style="cursor:pointer;opacity:${active?1:.5}" data-div="${d.name}"><title>${d.name}: ${val}${eqNote}</title>
      <rect x="${c[0]-wpx/2}" y="${c[1]+6}" width="${wpx}" height="18" rx="9" fill="#0b3d6b" stroke="#fff" stroke-width="1.4"/>
      <text x="${c[0]}" y="${c[1]+18}" text-anchor="middle" font-size="10.5" font-weight="700" fill="#fff">${val}</text></g>`;});
  svg.innerHTML=html;
  const tip=document.getElementById(tipId),wrap=document.getElementById(wrapId);
  svg.querySelectorAll('[data-div]').forEach(el=>{const dn=el.getAttribute('data-div');const dist=el.getAttribute('data-dist');const d=DATA.divisions.find(x=>x.name===dn);
    el.addEventListener('click',()=>{const mk=normMetric(state.metric);drillTo(mk,'institute',[dn]);});
    el.addEventListener('mousemove',e=>{const rc=wrap.getBoundingClientRect();tip.style.left=(e.clientX-rc.left)+'px';tip.style.top=(e.clientY-rc.top)+'px';tip.style.display='block';
      const[cls,lbl]=sev(d.gap_pct);tip.innerHTML=(dist?`<b>${dist}</b> district<br>`:'')+`${dn} division<br>${METRIC_LABEL[state.metric]}: ${metricDisplay(d)} · ${lbl}<br><span style="opacity:.7">Click to drill ${METRICS[normMetric(state.metric)].label}</span>`;});
    el.addEventListener('mouseleave',()=>tip.style.display='none');});
  // colour legend (identical colours to fills)
  let lg='';
  if(state.metric==='gap_pct'){
    lg=GAP_BANDS.map(b=>`<span class="item"><span class="sw" style="background:${b.c}"></span>${b.lbl}</span>`).join('');
    document.getElementById(descId).textContent='All 35 districts shown with real boundaries, coloured by their division\'s Utilisation % (Functional ÷ NMC MSR). Green = adequate (≥100%), red = critical shortfall.'+(anyFilter?' Filtered by your slicer selections — grey = no matching equipment in that division.':'');
  } else {
    const vals=DATA.divisions.map(x=>x[state.metric]);const qs=quartiles(vals);
    const edges=[Math.min(...vals),...qs,Math.max(...vals)];
    const f=state.metric==='budget'?(x=>'₹'+(x/1e7).toFixed(0)+'Cr'):(x=>fmt(x));
    for(let i=0;i<4;i++)lg+=`<span class="item"><span class="sw" style="background:${COUNT_RAMP[i]}"></span>Q${i+1}: ${f(edges[i])}–${f(edges[i+1])}</span>`;
    document.getElementById(descId).textContent=`Districts coloured by their division's ${METRIC_LABEL[state.metric]} quartile (darker = higher).`;
  }
  document.getElementById(legId).innerHTML=lg;
  // division-name legend (all 6, high→low) — reflects equipment filter
  const dlId=legId==='mapLegend'?'divLegend':'divLegend2';const dlEl=document.getElementById(dlId);
  if(dlEl){const ranked=Object.values(divBy).sort((a,b)=>(b[state.metric]||0)-(a[state.metric]||0));
    let rows=`<div class="ttl">Divisions (${METRIC_LABEL[state.metric]}) — high to low${anyFilter?' · filtered':''}</div>`;
    ranked.forEach(d=>{const val=state.metric==='gap_pct'?d.gap_pct+'%':state.metric==='budget'?cr(d.budget):fmt(d.procurement)+' units';
      rows+=`<div class="row" onclick="go('#division/${encodeURIComponent(d.name)}')"><span class="sw" style="background:${d._empty?'#e5e9ee':divColor(d)}"></span><span class="nm">${d.name}</span><span class="vv">${val}</span></div>`;});
    dlEl.innerHTML=rows;}
}

function renderHotspots(id){
  const host=document.getElementById(id); if(!host) return; // panel removed from layout
  const ranked=[...DATA.divisions].sort((a,b)=>b[state.metric]-a[state.metric]).slice(0,5);
  host.innerHTML=ranked.map(d=>{const[cls,lbl]=sev(d.gap_pct);
    return `<button class="hotspot" onclick="go('#division/${encodeURIComponent(d.name)}')">
      <span><b>${d.name}</b><br><span class="muted">${fmt(d.procurement)} units · ${cr(d.budget)}</span></span>
      <span style="text-align:right"><span class="pill ${cls}">${lbl}</span><br><span class="muted">${d.gap_pct}% gap</span></span></button>`;}).join('');
}

function renderExecCharts(){
  ['proc','bud'].forEach(k=>charts[k]&&charts[k].destroy());
  const dv=[...scopeDivisions()].sort((a,b)=>b.procurement-a.procurement);   // [2.0] filtered
  const base={responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}}};
  charts.proc=new Chart(procChart,{type:'bar',data:{labels:dv.map(d=>d.name),
    datasets:[{data:dv.map(d=>d.procurement),backgroundColor:dv.map(d=>divColor(d)),datalabels:datalabelCfg('num')}]},
    options:{...base,layout:{padding:{top:22}},plugins:{legend:{display:false},datalabels:datalabelCfg('num')},
      onClick:(e,el)=>{if(el.length)drillTo('procurement','institute',[dv[el[0].index].name]);}},plugins:[ChartDataLabels]});
  const dvb=[...scopeDivisions()].sort((a,b)=>(b.budget||0)-(a.budget||0));
  charts.bud=new Chart(budChart,{type:'bar',data:{labels:dvb.map(d=>d.name),
    datasets:[{data:dvb.map(d=>d.budget),backgroundColor:'#08519c'}]},
    options:{...base,layout:{padding:{top:22}},plugins:{legend:{display:false},datalabels:datalabelCfg('cr')},
      onClick:(e,el)=>{if(el.length)drillTo('budget','institute',[dvb[el[0].index].name]);},
      scales:{y:{ticks:{callback:v=>'₹'+(v/1e7).toFixed(0)+'Cr'}}}},plugins:[ChartDataLabels]});
}
