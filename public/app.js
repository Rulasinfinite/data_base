// public/app.js — Utilidades globales SIDEC v2

// ── Tema (claro / oscuro) ─────────────────────────────────
const Theme = {
  key: 'sidec_theme',
  get()  { return localStorage.getItem(this.key) || 'light'; },
  set(t) { localStorage.setItem(this.key, t); document.documentElement.setAttribute('data-theme', t); },
  toggle() { this.set(this.get() === 'dark' ? 'light' : 'dark'); },
  init()   { document.documentElement.setAttribute('data-theme', this.get()); }
};
Theme.init();

// ── Auth ──────────────────────────────────────────────────
const Auth = {
  getToken()  { return localStorage.getItem('sidec_token'); },
  getUser()   { try { return JSON.parse(localStorage.getItem('sidec_user')); } catch { return null; } },
  setSession(token, usuario) {
    localStorage.setItem('sidec_token', token);
    localStorage.setItem('sidec_user', JSON.stringify(usuario));
  },
  clear() { localStorage.removeItem('sidec_token'); localStorage.removeItem('sidec_user'); },
  isLoggedIn()  { return !!this.getToken(); },
  requireLogin(){ if (!this.isLoggedIn()) { window.location.href = '/login.html'; return false; } return true; },
  hasRole(rolMinimo) {
    const niveles = { certificaciones:1, reportes:2, calidad:3, admin:4 };
    const u = this.getUser();
    return u ? (niveles[u.rol]||0) >= (niveles[rolMinimo]||99) : false;
  },
};

// ── API helper ────────────────────────────────────────────
async function api(path, options = {}) {
  const token = Auth.getToken();
  const res = await fetch('/api' + path, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
    },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (res.status === 401) {
    Auth.clear();
    if (!window.location.pathname.endsWith('/login.html') && !window.location.pathname.endsWith('/login')) {
      window.location.href = '/login.html';
      return;
    }
  }

  const data = await res.json();
  if (!res.ok || data?.error) {
    throw new Error(data?.error || 'Error en la solicitud');
  }

  return data; // ✅ CORRECCIÓN: faltaba este return
}

// ── Navbar ────────────────────────────────────────────────
function renderNavbar(paginaActual = '') {
  const usuario = Auth.getUser();
  if (!usuario) return;
  const nav = document.getElementById('navbar');
  if (!nav) return;

  const iniciales = usuario.nombre.split(' ').map(p => p[0]).join('').slice(0,2).toUpperCase();
  const rolColores = { admin:'#1a56db', calidad:'#057a55', reportes:'#92400e', certificaciones:'#6b7280' };
  const rolColor = rolColores[usuario.rol] || '#6b7280';
  const isDark = Theme.get() === 'dark';

  nav.innerHTML = `
    <div class="navbar-brand">
      <a href="/dashboard.html" style="display:flex;align-items:center;text-decoration:none;gap:10px;height:36px">
        <img src="/assets/images/logo.jpg" alt="SIDEC" style="height:36px;object-fit:contain;flex-shrink:0">
      </a>
    </div>
    <div class="navbar-right">
      <nav style="display:flex;gap:2px;align-items:center">
        <a href="/dashboard.html" class="nav-link ${paginaActual==='inicio'?'active':''}">Certificados</a>
        ${Auth.hasRole('reportes') ? `<a href="/reportes.html" class="nav-link ${paginaActual==='reportes'?'active':''}">Reportes</a>` : ''}
        ${Auth.hasRole('admin') ? `<a href="/admin.html"   class="nav-link ${paginaActual==='admin'  ?'active':''}">Admin</a>` : ''}
        ${Auth.hasRole('admin') ? `<a href="/importar.html" class="nav-link ${paginaActual==='importar'?'active':''}">📂 Importar</a>` : ''}
      </nav>
      <div style="width:1px;height:20px;background:var(--border)"></div>
      <button class="theme-btn" onclick="Theme.toggle();location.reload()" title="Cambiar tema">
        ${isDark ? '☀️' : '🌙'}
      </button>
      <div style="display:flex;align-items:center;gap:8px">
        <div style="width:30px;height:30px;border-radius:50%;background:${rolColor}22;border:1.5px solid ${rolColor}55;
            display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:${rolColor}">
          ${iniciales}
        </div>
        <div style="line-height:1.2">
          <div style="font-size:13px;font-weight:500;color:var(--text)">${usuario.nombre.split(' ')[0]}</div>
          <div style="font-size:11px;color:${rolColor};font-weight:500;text-transform:capitalize">${usuario.rol}</div>
        </div>
      </div>
      <button class="btn btn-outline btn-sm" onclick="logout()" style="font-size:12px;padding:5px 10px">Salir</button>
    </div>
  `;
}

function logout() { Auth.clear(); window.location.href = '/login.html'; }

// ── Utilidades ────────────────────────────────────────────
function formatFecha(fecha) {
  if (!fecha) return '—';
  const d = new Date(fecha);
  if (isNaN(d)) return fecha;
  return d.toLocaleDateString('es-MX', { day:'2-digit', month:'2-digit', year:'numeric' });
}

function showAlert(msg, tipo='error', contenedorId='alert-container') {
  const el = document.getElementById(contenedorId);
  if (!el) return;
  el.innerHTML = `<div class="alert alert-${tipo}">${msg}</div>`;
  setTimeout(() => { el.innerHTML=''; }, 5000);
}
