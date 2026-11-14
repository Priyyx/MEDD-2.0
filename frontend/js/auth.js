/* MEDD Maharashtra 2.0 — auth.js : sign-in overlay and session handling (JWT kept in sessionStorage only). */
function showLogin(msg){
  stopRealtime();
  const o=document.getElementById('loginOverlay'); o.style.display='flex';
  document.getElementById('loginMsg').textContent=msg||'';
  setTimeout(()=>document.getElementById('loginUser').focus(),50);
}
async function doLogin(ev){
  ev.preventDefault();
  const u=document.getElementById('loginUser').value.trim(), p=document.getElementById('loginPass').value;
  const btn=document.getElementById('loginBtn'); btn.disabled=true; document.getElementById('loginMsg').textContent='Signing in…';
  try{
    const r=await fetch((window.MEDD_CONFIG.API_BASE||'/api/v1')+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
    const j=await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(j.detail||'Sign-in failed');
    API.setSession(j.access_token,j.user);
    document.getElementById('loginPass').value='';
    document.getElementById('loginOverlay').style.display='none';
    await boot();
  }catch(e){ document.getElementById('loginMsg').textContent=e.message; }
  finally{ btn.disabled=false; }
}
function logout(){ API.clearSession(); DATA=null; SCOPE=null; showLogin('Signed out.'); }
function renderUserBadge(){
  const el=document.getElementById('userBadge'); if(!el)return; const u=API.user;
  el.innerHTML=u?`👤 ${escapeHtml(u.full_name||u.username)} <span class="muted">(${escapeHtml(u.role.replace('_',' '))}${u.allowed_divisions?' · '+escapeHtml(u.allowed_divisions.join(', ')):''})</span> <a onclick="logout()" style="cursor:pointer;margin-left:6px">Sign out</a>`:'';
  document.querySelectorAll('[data-perm]').forEach(n=>n.style.display=API.can(n.dataset.perm)?'':'none');
}
