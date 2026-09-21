/* Cliente HTTP del portal de copias (módulo ES). */

function parseBody(text) {
  if (!text) return null;
  try { return JSON.parse(text); } catch (e) { return text; }
}

async function request(path, options) {
  const opts = Object.assign(
    { credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } },
    options || {}
  );
  const res = await fetch('/api' + path, opts);
  const text = await res.text();
  const data = parseBody(text);

  if (res.status === 401) {
    if (!location.pathname.endsWith('login.html')) location.href = '/login.html';
    const err = new Error('no autenticado');
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : ('HTTP ' + res.status);
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body || {}) }),
  patch: (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body || {}) }),
  request,
};
