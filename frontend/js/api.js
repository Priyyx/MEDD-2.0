/* MEDD Maharashtra 2.0 — api.js : the only module that talks to the backend.
 * Adds the bearer token, serialises the shared dashboard filters, handles 401 (sign-in) and errors. */
const API = (() => {
  const base = (window.MEDD_CONFIG && window.MEDD_CONFIG.API_BASE) || '/api/v1';
  const TK = 'medd2_token', UK = 'medd2_user';
  let token = sessionStorage.getItem(TK);
  let user = JSON.parse(sessionStorage.getItem(UK) || 'null');
  const qs = (params) => {
    const u = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v == null || v === '') return;
      if (Array.isArray(v)) v.forEach(x => u.append(k, x)); else u.append(k, v);
    });
    const s = u.toString(); return s ? '?' + s : '';
  };
  async function request(method, path, { params, body, raw } = {}) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), (window.MEDD_CONFIG || {}).REQUEST_TIMEOUT_MS || 60000);
    const headers = {};
    if (token) headers['Authorization'] = 'Bearer ' + token;
    if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
    let res;
    try {
      res = await fetch(base + path + qs(params), { method, headers, signal: ctl.signal,
        body: body ? (body instanceof FormData ? body : JSON.stringify(body)) : undefined });
    } catch (e) {
      throw new ApiError(0, e.name === 'AbortError' ? 'The server took too long to respond.' : 'Cannot reach the MEDD server. Is the backend running?');
    } finally { clearTimeout(t); }
    if (res.status === 401) { clearSession(); if (window.showLogin) window.showLogin('Your session has ended — please sign in.'); throw new ApiError(401, 'Authentication required'); }
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); msg = j.detail ? (typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)) : msg; } catch (_) {}
      throw new ApiError(res.status, msg);
    }
    if (raw) return res;
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text();
  }
  class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
  function setSession(tok, u) { token = tok; user = u; sessionStorage.setItem(TK, tok); sessionStorage.setItem(UK, JSON.stringify(u)); }
  function clearSession() { token = null; user = null; sessionStorage.removeItem(TK); sessionStorage.removeItem(UK); }
  async function download(path, params, filename) {
    const res = await request('GET', path, { params, raw: true });
    const blob = await res.blob(); const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename; document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  }
  return {
    get: (p, params) => request('GET', p, { params }),
    post: (p, body, params) => request('POST', p, { body, params }),
    put: (p, body) => request('PUT', p, { body }),
    download, setSession, clearSession, ApiError, qs,
    get token() { return token; }, get user() { return user; },
    can: (perm) => !!(user && (user.permissions || []).includes(perm)),
  };
})();
