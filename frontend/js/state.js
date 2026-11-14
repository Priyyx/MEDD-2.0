/* MEDD Maharashtra 2.0 — state.js : shared UI state and the live data held in the browser. */
let state={division:[],institute:[],equipment:[],department:[],bedded:[],subcat:[],metric:'gap_pct',page:'executive'};

// [2.0] DATA is no longer embedded in the page. It is the MEDD 1.0 data contract, built live from PostgreSQL by
//       GET /api/v1/dashboard/bootstrap and replaced automatically after every successful Excel ingestion.
let DATA = null;
// [2.0] SCOPE = exact server-side aggregates for the active filters (GET /api/v1/dashboard/scope):
//       {summary, divisions[], institutes[], departments[]}. Every KPI card, map colour, chart and list uses it.
let SCOPE = null;

function filterParams(){
  return {division:state.division,institute:state.institute,department:state.department,
    subcat:state.subcat,equipment:state.equipment,bedded:state.bedded};
}
async function loadBootstrap(){
  DATA = await API.get('/dashboard/bootstrap');
  return DATA;
}
let _scopeSeq = 0;
async function refreshScope(){
  const seq = ++_scopeSeq;
  const s = await API.get('/dashboard/scope', filterParams());
  if (seq === _scopeSeq) SCOPE = s;   // ignore out-of-order responses
  return SCOPE;
}
// scoped lists with a safe fallback to the unfiltered payload
const scopeDivisions = () => (SCOPE && SCOPE.divisions) || (DATA ? DATA.divisions : []);
const scopeInstitutes = () => (SCOPE && SCOPE.institutes) || (DATA ? DATA.institutes : []);
const scopeDepartments = () => (SCOPE && SCOPE.departments) || (DATA ? DATA.state_depts : []);
function escapeHtml(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function showBusy(on){const b=document.getElementById('busyBar');if(b)b.style.display=on?'block':'none';}
function showError(msg){
  const el=document.getElementById('errBanner'); if(!el){alert(msg);return;}
  el.innerHTML='⚠ '+escapeHtml(msg)+' <button class="btn" style="padding:2px 8px;margin-left:8px" onclick="this.parentNode.style.display=\'none\'">Dismiss</button>';
  el.style.display='block';
}
