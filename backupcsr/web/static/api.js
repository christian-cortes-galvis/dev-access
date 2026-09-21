/* Cliente HTTP del portal de copias. */
window.BackupAPI = (function () {
  'use strict';

  function parseBody(text) {
    if (!text) return null;
    try { return JSON.parse(text); } catch (e) { return text; }
  }

  async function request(path, options) {
    var opts = Object.assign(
      { credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } },
      options || {}
    );
    var res = await fetch('/api' + path, opts);
    var text = await res.text();
    var data = parseBody(text);

    if (res.status === 401) {
      if (!location.pathname.endsWith('login.html')) location.href = '/login.html';
      throw new Error('no autenticado');
    }
    if (!res.ok) {
      var detail = data && data.detail ? data.detail : 'HTTP ' + res.status;
      var err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  return {
    get: function (path) { return request(path); },
    post: function (path, body) { return request(path, { method: 'POST', body: JSON.stringify(body || {}) }); },
    patch: function (path, body) { return request(path, { method: 'PATCH', body: JSON.stringify(body || {}) }); },
    request: request
  };
})();
