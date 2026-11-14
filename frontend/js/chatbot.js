/* MEDD Maharashtra 2.0 — chatbot.js
 * Code below is carried over from the MEDD 1.0 index.html (inline script); changes for the
 * PostgreSQL/API integration are marked with  // [2.0]  comments. See docs/05_CHANGE_LOG.md. */
function renderChatbot(){
  setCrumbScope();
  const el=document.getElementById('page-chatbot');
  el.innerHTML=`<h2 class="secTitle">Decision Support AI</h2>
    <p class="muted" style="margin-bottom:12px">Ask about any equipment, institute, division or department. Answers are computed live from the validated PostgreSQL database (read-only), respect the filters you have selected above, and show how each figure was calculated.</p>
    <div class="cbchips" id="cbchips"></div>
    <div class="cbwrap">
      <div class="cbmsgs" id="cbmsgs"></div>
      <div class="cbinput"><input id="cbin" placeholder="e.g. Ventilator gap in Pune, or budget for ECG Machine"><button id="cbsend">Ask</button></div>
    </div>`;
  const chips=['Overall equipment gap summary','Which divisions have the highest equipment shortages?',
    'Institutes with the most non-functional equipment','What is the estimated procurement budget?',
    'Which departments require immediate procurement?','Equipment approaching end of life',
    'Institutes with inadequate AMC/CMC coverage','Compare Pune and Nagpur','Ventilator requirement',
    'Top 10 net requirement by cost tier','ECG Machine in Amravati'];
  document.getElementById('cbchips').innerHTML=chips.map(c=>`<span class="cbchip">${c}</span>`).join('');
  document.querySelectorAll('.cbchip').forEach(c=>c.onclick=()=>{document.getElementById('cbin').value=c.textContent;cbSend();});
  const msgs=document.getElementById('cbmsgs');
  if(!cbHistory.length){cbHistory.push({role:'a',html:cbWelcome()});}
  msgs.innerHTML=cbHistory.map(m=>`<div class="cbmsg ${m.role}">${m.html}</div>`).join('');
  msgs.scrollTop=msgs.scrollHeight;
  document.getElementById('cbsend').onclick=cbSend;
  document.getElementById('cbin').onkeydown=e=>{if(e.key==='Enter')cbSend();};
  msgs.querySelectorAll('tr.cbdrillrow').forEach(tr=>tr.onclick=()=>cbDrillEquip(tr.dataset.eq));
}
function cbWelcome(){const o=DATA.overview;
  return `Hello 👋 I'm the MEDD decision-support assistant. State-wide right now: <b>${fmt(o.required)}</b> units required (NMC/NMR), <b>${fmt(o.functional)}</b> functional, net requirement <b>${sfmt(o.net_requirement)}</b>, estimated procurement budget <b>${cr(o.budget)}</b>. Ask me about a specific equipment, division, institute or department.`;}
// [2.0] questions are answered by the server (POST /api/v1/chat): parameterised analytical queries on the
//       read-only database role with a statement timeout, active filters + user permissions applied, and the
//       calculation methodology attached. If the server cannot be reached, the 1.0 rule engine below answers
//       from the (database-built) bootstrap data as a deterministic fallback.
let _cbBusy=false;
async function cbSend(){
  const inp=document.getElementById('cbin');const q=inp.value.trim();if(!q||_cbBusy)return;
  _cbBusy=true;
  cbHistory.push({role:'u',html:escapeHtml(q)});
  cbHistory.push({role:'a',html:'<span class="muted">Querying the database…</span>',pending:true});
  inp.value='';renderChatbot();
  let html;
  try{ const r=await API.post('/chat',{question:q,filters:filterParams()}); html=r.html; }
  catch(e){ if(e.status===401){html='Please sign in again.';}
    else html=`<div class="rec">⚠ Live analytics unavailable (${escapeHtml(e.message)}). Offline answer from the last loaded dataset:</div>`+cbAnswer(q); }
  cbHistory=cbHistory.filter(m=>!m.pending);
  cbHistory.push({role:'a',html});
  _cbBusy=false;
  if(state.page==='chatbot')renderChatbot();
}

function cbAnswer(q){
  const ql=' '+q.toLowerCase()+' ';
  const wordMatch=(name)=>{const n=name.toLowerCase();
    // require the full name to appear, or all significant words (len>3) to appear as word-ish
    if(ql.includes(n))return true;
    const words=n.split(/[^a-z0-9]+/).filter(t=>t.length>3);
    return words.length>0 && words.every(t=>ql.includes(t));};
  // 1) equipment first, prefer the LONGEST matching name (so "Ventilator" beats nothing, avoids dept "ENT")
  let eq=null;{let cands=DATA.equipment_catalog.filter(e=>ql.includes(e.name.toLowerCase()));
    if(!cands.length)DATA.equipment_catalog.forEach(e=>{if(wordMatch(e.name))cands.push(e);});
    // fuzzy: match on a distinctive keyword from the query against equipment names
    if(!cands.length){const qwords=ql.split(/[^a-z0-9]+/).filter(t=>t.length>4);
      cands=DATA.equipment_catalog.filter(e=>{const n=e.name.toLowerCase();return qwords.some(w=>n.includes(w));});}
    // prefer highest net requirement among matches (most decision-relevant), then longest name
    cands.sort((a,b)=>(b.net_requirement-a.net_requirement)||(b.name.length-a.name.length));eq=cands[0]||null;}
  // 2) geo/department — require word-boundary-ish to avoid 'ENT' inside 'Ventilator'
  const div=DATA.divisions.find(d=>ql.includes(' '+d.name.toLowerCase()+' ')||ql.includes(' '+d.name.split(' ')[0].toLowerCase()+' '));
  const inst=DATA.institutes.find(i=>ql.includes(i.name.toLowerCase()));
  const dept=DATA.departments.find(d=>{const n=d.name.toLowerCase();return ql.includes(' '+n+' ')||ql.includes(' '+n+',')||ql.includes(' '+n+'?');});

  if(/top\s*\d*/.test(ql)&&(ql.includes('net')||ql.includes('requirement')||ql.includes('gap')||ql.includes('equipment')||ql.includes('utilis')||ql.includes('cost'))){
    const n=parseInt((ql.match(/top\s*(\d+)/)||[])[1]||'10');
    // respect active equipment/sub-category filter
    const app=applicableEquipNames();
    let cat=[...DATA.equipment_catalog];
    if(app)cat=cat.filter(e=>app.has(e.name));
    const scopeNote=app?' (filtered)':' (state-wide)';
    const tier=(min)=>cat.filter(e=>(e.unit_cost||0)>min && e.net_requirement>0)
      .sort((a,b)=>b.net_requirement-a.net_requirement).slice(0,n);
    const sec=(label,min)=>{const rows=tier(min);
      return `<div style="margin-top:10px"><b>${label}</b>`+(rows.length?cbTable(rows):' <span class="muted">— none in this scope</span>')+`</div>`;};
    return `<b>Top ${n} Net Requirement Equipments by cost tier${scopeNote}:</b>`+
      sec(`A · Unit Cost &gt; ₹1,00,000`,100000)+
      sec(`B · Unit Cost &gt; ₹5,00,000`,500000)+
      sec(`C · Unit Cost &gt; ₹10,00,000`,1000000);
  }
  if(eq){return cbEquipmentCard(eq, div||inst||dept, ql.includes('budget')?'budget':null);}
  if(inst)return cbScopeCard(inst,'institute');
  if(div)return cbScopeCard(div,'division');
  if(dept)return cbScopeCard(dept,'department');
  if(ql.includes('summary')||ql.includes('overall')||ql.includes('gap')||ql.includes('overview')||ql.includes('utilis')){
    const o=DATA.overview;
    const worst=[...DATA.divisions].sort((a,b)=>a.gap_pct-b.gap_pct)[0];
    return `<b>State-wide summary (FY 2025-26):</b>`+cbKV([
      ['Equipment required (NMC/NMR)',fmt(o.required)],['Available',fmt(o.available)],['Functional',fmt(o.functional)],
      ['Net requirement',sfmt(o.net_requirement)],['Utilisation %',o.gap_pct+'%'],
      ['Procurement suggested by colleges',fmt(o.procurement)],['Estimated budget',cr(o.budget)]])+
      `<div class="rec">🩺 Lowest utilisation division: <b>${worst.name}</b> at ${worst.gap_pct}% (net requirement ${sfmt(worst.net_requirement)}). Prioritise there.</div>`;
  }
  return `I couldn't match that to a specific equipment, division, institute or department. Try naming one — e.g. <i>"Ventilator"</i>, <i>"Pune"</i>, <i>"budget for CT Scan"</i>, or <i>"top 10 equipment by net requirement"</i>.`;
}
function cbKV(pairs){return '<table>'+pairs.map(p=>`<tr><td style="color:var(--mut)">${p[0]}</td><td class="num"><b>${p[1]}</b></td></tr>`).join('')+'</table>';}
function cbTable(rows){
  return '<table class="cbdrill"><thead><tr><th>Equipment</th><th class="num">Req</th><th class="num">Func</th><th class="num">Net Req</th><th class="num">Unit Cost</th><th class="num">Est. Cost</th></tr></thead><tbody>'+
    rows.map(e=>`<tr onclick="cbDrillEquip('${String(e.name).replace(/'/g,"\\'")}')" style="cursor:pointer" title="Drill this equipment: Division → Institute → Department → Equipment"><td>${e.name}</td><td class="num">${fmt(e.required)}</td><td class="num">${fmt(e.functional)}</td><td class="num">${sfmt(e.net_requirement)}</td><td class="num">${cr(e.unit_cost||0)}</td><td class="num">${cr(Math.max(0,e.net_requirement)*(e.unit_cost||0))}</td></tr>`).join('')+'</tbody></table>';
}
// From an AI table, drilling an equipment sets it as the filter and opens the metric-drill
// hierarchy (Division→Institute→Department→Equipment) scoped to that equipment.
function cbDrillEquip(name){
  setFilterAndDrill('equipment',[name],'netreq');   // [2.0] also refreshes server aggregates
}
function cbSelectRow(tr){const tbl=tr.closest('table');tbl.querySelectorAll('tr.cbsel').forEach(x=>x.classList.remove('cbsel'));tr.classList.add('cbsel');}
function cbRecommend(e){
  // procurement recommendation: net requirement is the true need; colleges suggested e.procurement
  const net=e.net_requirement, sug=e.procurement;
  if(net<=0)return `✅ Functional stock meets the NMC/NMR norm — <b>no net procurement needed</b>. Colleges suggested ${fmt(sug)} units; review before sanctioning.`;
  const est=Math.round((e.required?e.budget/Math.max(1,e.procurement):0)); // approx unit cost from suggested
  let msg=`🛒 Net requirement is <b>${fmt(net)}</b> units to reach the norm. Colleges suggested <b>${fmt(sug)}</b>. `;
  if(sug>net*1.25)msg+=`College suggestion exceeds net need by a wide margin — verify before sanctioning.`;
  else if(sug<net*0.75)msg+=`College suggestion is below the computed net need — may under-provision.`;
  else msg+=`College suggestion is broadly in line with the net requirement.`;
  return `<div class="rec">${msg}</div>`;
}
function cbEquipmentCard(e,scope,intent){
  let head=`<b>${e.name}</b>`+(scope?` — note: figures below are state-wide (per-equipment × location detail isn't precomputed).`:'');
  return head+cbKV([
    ['Required (NMC/NMR)',fmt(e.required)],['Available',fmt(e.available)],['Functional',fmt(e.functional)],
    ['Net requirement',sfmt(e.net_requirement)],['Utilisation %',e.gap_pct+'%'],
    ['Procurement suggested by colleges',fmt(e.procurement)],['Estimated budget',cr(e.budget)]])+cbRecommend(e);
}
function cbScopeCard(s,kind){
  const netreq=s.net_requirement!=null?s.net_requirement:(s.required-s.functional);
  let out=`<b>${s.name}</b> (${kind}) — FY 2025-26`+cbKV([
    ['Equipment required (NMC/NMR)',fmt(s.required)],['Available',fmt(s.available)],['Functional',fmt(s.functional)],
    ['Net requirement',sfmt(netreq)],['Utilisation %',s.gap_pct+'%'],
    ['Procurement suggested by colleges',fmt(s.procurement)],['Estimated budget',cr(s.budget)]]);
  // top equipment needs within scope
  const te=(s.top_equipment||[]).filter(e=>e.net_requirement>0).slice(0,5);
  if(te.length)out+=`<div style="margin-top:8px"><b>Top equipment needs here:</b>`+cbTable(te)+`</div>`;
  out+=`<div class="rec">🛒 Net requirement ${sfmt(netreq)} units; colleges suggested ${fmt(s.procurement)}. Estimated budget ${cr(s.budget)}.</div>`;
  return out;
}
