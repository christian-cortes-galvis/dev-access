/* Portal de administración de copias — lógica de la UI. */
(function () {
  'use strict';

  var API = window.BackupAPI;
  var REFRESH_MS = 15000;
  var STATUS_PILL = {
    OK: 'ok', EN_CURSO: 'login', TARDE: 'warn', FALLO: 'err', NUNCA: 'unknown',
    INCIERTO: 'unknown'
  };
  var STATUS_LABEL = {
    OK: 'OK', EN_CURSO: 'EN CURSO', TARDE: 'TARDE', FALLO: 'FALLÓ', NUNCA: 'NUNCA',
    INCIERTO: 'INCIERTO'
  };

  var state = { jobs: [], manageCron: false, db: true, nas: true, user: null, tab: 'dashboard' };
  var refreshTimer = null;
  var lastJobs = null;

  /* ----------------------------- utilidades ------------------------------ */

  function $(id) { return document.getElementById(id); }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === 'class') node.className = attrs[key];
        else if (key === 'text') node.textContent = attrs[key];
        else if (key === 'html') node.innerHTML = attrs[key];
        else if (key.indexOf('data-') === 0) node.setAttribute(key, attrs[key]);
        else if (key === 'onclick') node.addEventListener('click', attrs[key]);
        else node.setAttribute(key, attrs[key]);
      });
    }
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    });
    return node;
  }

  function pill(status, extra) {
    var span = el('span', {
      class: 'badge rounded-pill pill-' + (STATUS_PILL[status] || 'unknown'),
      text: STATUS_LABEL[status] || status || '—'
    });
    if (extra) span.title = extra;
    return span;
  }

  function showBanner(message, kind) {
    var banner = $('banner');
    if (!banner) return;
    banner.className = 'alert alert-' + (kind || 'warning') + ' banner';
    banner.textContent = message;
    banner.hidden = false;
  }

  function clearBanner() { var b = $('banner'); if (b) b.hidden = true; }

  function fmtDate(value) {
    if (!value) return '—';
    var d = new Date(value);
    if (isNaN(d.getTime())) return value;
    return d.toLocaleString('es-CO', { hour12: false });
  }

  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined) return '—';
    if (seconds < 60) return seconds + 's';
    var m = Math.floor(seconds / 60);
    if (m < 60) return m + 'm ' + (seconds % 60) + 's';
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
  }

  function fmtBytes(bytes) {
    if (!bytes && bytes !== 0) return '—';
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = 0;
    var value = bytes;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
    return (i === 0 ? value : value.toFixed(1)) + ' ' + units[i];
  }

  function scheduleText(job) {
    return [job.cron_minute, job.cron_hour, job.cron_dom, job.cron_month, job.cron_dow].join(' ');
  }

  /* ------------------------------ dashboard ------------------------------ */

  function renderSummary(counts) {
    var box = $('stats');
    box.innerHTML = '';
    var items = [
      ['Total', counts.total, ''],
      ['OK', counts.OK || 0, 'text-success'],
      ['En curso', counts.EN_CURSO || 0, 'text-info'],
      ['Tarde', counts.TARDE || 0, 'text-warning'],
      ['Falló', counts.FALLO || 0, 'text-danger'],
      ['Nunca', counts.NUNCA || 0, 'text-secondary']
    ];
    items.forEach(function (item) {
      box.appendChild(el('div', { class: 'col' }, [
        el('div', { class: 'card h-100 stat' }, [
          el('div', { class: 'card-body' }, [
            el('div', { class: 'value ' + item[2], text: String(item[1]) }),
            el('div', { class: 'label', text: item[0] })
          ])
        ])
      ]));
    });
  }

  function jobRow(job) {
    var tr = el('tr', { 'data-slug': job.slug });

    var nameCell = el('td', {}, [
      el('div', { class: 'fw-semibold', text: job.name }),
      el('div', { class: 'muted mono', text: job.slug + ' · ' + (job.origin_type || '') })
    ]);
    tr.appendChild(nameCell);

    var statusCell = el('td', {}, [pill(job.status, job.status_detail)]);
    if (job.running) statusCell.appendChild(el('span', { class: 'ms-1 muted small', text: 'ejecutando…' }));
    tr.appendChild(statusCell);

    var last = job.last_run;
    tr.appendChild(el('td', {}, [
      el('div', { text: last ? fmtDate(last.started_at) : '—' }),
      el('div', { class: 'muted small', text: last ? fmtDuration(last.duration_s) + ' · ' + last.files_transferred + ' arch.' : '' })
    ]));
    tr.appendChild(el('td', { text: fmtDate(job.next_run) }));

    var dest = el('td', { class: 'mono', text: '/mnt/nas/' + (job.dest_rel || '') });
    tr.appendChild(dest);

    tr.appendChild(el('td', {}, [
      el('code', { text: scheduleText(job) }),
      el('div', {}, [el('span', {
        class: 'badge rounded-pill ' + (job.enabled ? 'pill-ok' : 'pill-unknown'),
        text: job.enabled ? 'habilitada' : 'deshabilitada'
      })])
    ]));

    var actions = el('td', { class: 'text-nowrap' });
    actions.appendChild(actionButton('Ejecutar', 'run', job, 'btn btn-sm btn-outline-primary'));
    actions.appendChild(actionButton('Dry-run', 'dry', job, 'btn btn-sm btn-outline-secondary'));
    actions.appendChild(actionButton('Log', 'log', job, 'btn btn-sm btn-outline-secondary'));
    actions.appendChild(actionButton('Historial', 'history', job, 'btn btn-sm btn-outline-secondary'));
    actions.appendChild(actionButton('Archivos', 'files', job, 'btn btn-sm btn-outline-secondary'));
    if (state.manageCron && state.user && state.user.role === 'admin') {
      actions.appendChild(actionButton('Horario', 'schedule', job, 'btn btn-sm btn-outline-secondary'));
      actions.appendChild(actionButton(job.enabled ? 'Deshabilitar' : 'Habilitar', 'toggle', job,
        'btn btn-sm btn-outline-' + (job.enabled ? 'warning' : 'success')));
    }
    tr.appendChild(actions);
    return tr;
  }

  function actionButton(label, action, job, cls) {
    return el('button', {
      type: 'button', class: cls + ' me-1 mb-1', text: label,
      'data-action': action, 'data-slug': job.slug
    });
  }

  function renderJobs(jobs) {
    state.jobs = jobs;
    var body = $('jobs-body');
    body.innerHTML = '';
    if (!jobs.length) {
      body.appendChild(el('tr', {}, [el('td', { colspan: '7', class: 'text-center muted py-4', text: 'Sin jobs en el catálogo.' })]));
      return;
    }
    jobs.forEach(function (job) { body.appendChild(jobRow(job)); });
  }

  async function loadDashboard(silent) {
    try {
      var summary = await API.get('/summary');
      renderSummary(summary.counts);
      state.manageCron = summary.manage_cron;
      state.db = summary.db;
      state.nas = summary.nas;
      var data = await API.get('/jobs');
      state.manageCron = data.manage_cron;
      state.db = data.db;
      state.nas = data.nas;
      renderJobs(data.jobs);
      renderConnState(summary);
      if (!silent) clearBanner();
    } catch (err) {
      if (!silent) showBanner('No se pudo cargar el panel: ' + err.message);
    }
  }

  function renderConnState(summary) {
    if (!summary.db) {
      showBanner('MySQL no disponible: modo lectura (no se puede editar horarios ni guardar historial).');
    } else if (!summary.nas) {
      showBanner('El NAS no está montado en /mnt/nas: la vista de archivos no estará disponible.');
    } else {
      clearBanner();
    }
  }

  /* ------------------------------- acciones ------------------------------ */

  async function handleAction(action, slug) {
    var job = state.jobs.filter(function (j) { return j.slug === slug; })[0];
    if (!job) return;
    try {
      if (action === 'run' || action === 'dry') {
        var dry = action === 'dry';
        if (!dry && !window.confirm('Ejecutar "' + job.name + '" AHORA?\nEl mirror usa --delete y puede borrar en el NAS.')) return;
        await API.post('/jobs/' + slug + '/run', { dry_run: dry });
        showBanner('Ejecución lanzada: ' + job.name + (dry ? ' (dry-run)' : ''), 'info');
        setTimeout(function () { loadDashboard(true); }, 1500);
      } else if (action === 'toggle') {
        await API.patch('/jobs/' + slug, { enabled: !job.enabled });
        await loadDashboard(true);
      } else if (action === 'log') {
        await openLog(job);
      } else if (action === 'history') {
        switchTab('historial');
        $('hist-job').value = slug;
        loadHistory();
      } else if (action === 'files') {
        switchTab('archivos');
        $('files-job').value = slug;
        loadFiles('', job);
      } else if (action === 'schedule') {
        openSchedule(job);
      }
    } catch (err) {
      showBanner('Error: ' + err.message, 'danger');
    }
  }

  async function openLog(job) {
    var data = await API.get('/jobs/' + job.slug + '?tail=500');
    $('log-title').textContent = 'Log · ' + job.name;
    $('log-pre').textContent = data.log || '(vacío)';
    bootstrap.Modal.getOrCreateInstance($('logModal')).show();
  }

  function openSchedule(job) {
    $('job-slug').value = job.slug;
    $('jobModalLabel').textContent = 'Horario · ' + job.name;
    $('job-enabled').checked = !!job.enabled;
    $('job-minute').value = job.cron_minute;
    $('job-hour').value = job.cron_hour;
    $('job-dom').value = job.cron_dom;
    $('job-month').value = job.cron_month;
    $('job-dow').value = job.cron_dow;
    $('job-error').hidden = true;
    bootstrap.Modal.getOrCreateInstance($('jobModal')).show();
  }

  async function saveSchedule() {
    var slug = $('job-slug').value;
    var payload = {
      enabled: $('job-enabled').checked,
      cron_minute: $('job-minute').value.trim(),
      cron_hour: $('job-hour').value.trim(),
      cron_dom: $('job-dom').value.trim(),
      cron_month: $('job-month').value.trim(),
      cron_dow: $('job-dow').value.trim()
    };
    try {
      await API.patch('/jobs/' + slug, payload);
      bootstrap.Modal.getOrCreateInstance($('jobModal')).hide();
      await loadDashboard(true);
      showBanner('Programación actualizada y cron reescrito.', 'success');
    } catch (err) {
      var box = $('job-error');
      box.textContent = err.message;
      box.hidden = false;
    }
  }

  /* ------------------------------- historial ----------------------------- */

  async function loadHistory() {
    var job = $('hist-job').value;
    var status = $('hist-status').value;
    var query = '?limit=200';
    if (job) query += '&job=' + encodeURIComponent(job);
    if (status) query += '&status=' + encodeURIComponent(status);
    try {
      var data = await API.get('/runs' + query);
      var body = $('hist-body');
      body.innerHTML = '';
      if (!data.runs.length) {
        body.appendChild(el('tr', {}, [el('td', { colspan: '7', class: 'text-center muted py-4', text: 'Sin ejecuciones.' })]));
        return;
      }
      data.runs.forEach(function (run) {
        var tr = el('tr', { class: 'pointer', 'data-run': String(run.id || '') });
        tr.appendChild(el('td', { class: 'mono', text: run.job_slug || '—' }));
        tr.appendChild(el('td', { text: fmtDate(run.started_at) }));
        tr.appendChild(el('td', { text: fmtDate(run.finished_at) }));
        tr.appendChild(el('td', {}, [pill(run.status, run.error_text)]));
        tr.appendChild(el('td', { text: fmtDuration(run.duration_s) }));
        tr.appendChild(el('td', { text: String(run.files_transferred) + ' / ' + String(run.files_removed) }));
        tr.appendChild(el('td', { text: run.dry_run ? 'dry-run' : 'real' }));
        if (run.id) {
          tr.addEventListener('click', function () { openRun(run.id); });
        }
        body.appendChild(tr);
      });
    } catch (err) {
      showBanner('No se pudo cargar el historial: ' + err.message, 'danger');
    }
  }

  async function openRun(runId) {
    try {
      var data = await API.get('/runs/' + runId);
      $('run-title').textContent = 'Ejecución #' + runId + ' · ' + (data.run.job_slug || '');
      var body = $('run-body');
      body.innerHTML = '';
      var info = el('div', { class: 'row g-2 mb-3' });
      [['Estado', data.run.status], ['Inicio', fmtDate(data.run.started_at)],
       ['Fin', fmtDate(data.run.finished_at)], ['Duración', fmtDuration(data.run.duration_s)],
       ['Transferidos', String(data.run.files_transferred)], ['Eliminados', String(data.run.files_removed)]]
        .forEach(function (pair) {
          info.appendChild(el('div', { class: 'col-6 col-md-4' }, [
            el('div', { class: 'label muted small', text: pair[0] }),
            el('div', { text: pair[1] })
          ]));
        });
      body.appendChild(info);
      if (data.run.error_text) {
        body.appendChild(el('div', { class: 'alert alert-danger', text: data.run.error_text }));
      }
      var list = el('div', { class: 'mb-2' });
      list.appendChild(el('div', { class: 'label muted small mb-1', text: 'Archivos (' + data.files.length + ')' }));
      var ul = el('ul', { class: 'mono', style: 'max-height:320px;overflow:auto' });
      data.files.slice(0, 2000).forEach(function (file) {
        ul.appendChild(el('li', {
          text: (file.action === 'remove' ? '- ' : '+ ') + file.path
        }));
      });
      list.appendChild(ul);
      body.appendChild(list);
      var logBtn = el('button', { type: 'button', class: 'btn btn-sm btn-outline-secondary', text: 'Ver log' });
      logBtn.addEventListener('click', function () { openRunLog(runId); });
      body.appendChild(logBtn);
      bootstrap.Modal.getOrCreateInstance($('runModal')).show();
    } catch (err) {
      showBanner('No se pudo abrir la ejecución: ' + err.message, 'danger');
    }
  }

  async function openRunLog(runId) {
    try {
      var data = await API.get('/runs/' + runId + '/log?tail=800');
      $('log-title').textContent = 'Log · ejecución #' + runId;
      $('log-pre').textContent = data.log || '(vacío)';
      bootstrap.Modal.getOrCreateInstance($('logModal')).show();
    } catch (err) {
      showBanner('No se pudo leer el log: ' + err.message, 'danger');
    }
  }

  /* -------------------------------- archivos ----------------------------- */

  async function loadFiles(path, jobOverride) {
    var select = $('files-job');
    var slug = (jobOverride && jobOverride.slug) || select.value;
    if (!slug) return;
    try {
      var data = await API.get('/jobs/' + slug + '/files?path=' + encodeURIComponent(path || ''));
      renderBreadcrumb(slug, data.path);
      var body = $('files-body');
      body.innerHTML = '';
      if (data.parent !== '' && data.path) {
        var up = el('tr', { class: 'pointer' }, [el('td', { colspan: '4', text: '..' })]);
        up.addEventListener('click', function () { loadFiles(data.parent); });
        body.appendChild(up);
      }
      if (!data.entries.length) {
        body.appendChild(el('tr', {}, [el('td', { colspan: '4', class: 'text-center muted py-3', text: 'Directorio vacío.' })]));
      }
      data.entries.forEach(function (entry) {
        var tr = el('tr', entry.type === 'dir' ? { class: 'pointer' } : {});
        tr.appendChild(el('td', { text: (entry.type === 'dir' ? '📁 ' : '📄 ') + entry.name }));
        tr.appendChild(el('td', { text: entry.type }));
        tr.appendChild(el('td', { text: entry.type === 'file' ? fmtBytes(entry.size) : '—' }));
        tr.appendChild(el('td', { text: fmtDate(entry.mtime) }));
        if (entry.type === 'dir') {
          tr.addEventListener('click', function () { loadFiles(entry.path); });
        }
        body.appendChild(tr);
      });
    } catch (err) {
      showBanner('No se pudo listar los archivos: ' + err.message, 'danger');
    }
  }

  function renderBreadcrumb(slug, path) {
    var box = $('files-breadcrumb');
    box.innerHTML = '';
    var root = el('a', { 'data-path': '', text: '/mnt/nas' });
    root.addEventListener('click', function () { loadFiles(''); });
    box.appendChild(root);
    if (!path) return;
    var parts = path.split('/');
    var acc = '';
    parts.forEach(function (part) {
      acc = acc ? acc + '/' + part : part;
      var here = acc;
      box.appendChild(document.createTextNode(' / '));
      var link = el('a', { 'data-path': here, text: part });
      link.addEventListener('click', function () { loadFiles(here); });
      box.appendChild(link);
    });
  }

  /* --------------------------------- cron -------------------------------- */

  async function loadCron() {
    try {
      var data = await API.get('/cron');
      $('cron-manage').textContent = data.manage_cron ? 'activada' : 'desactivada (solo lectura)';
      $('cron-path').textContent = data.path;
      var diff = data.diff || {};
      $('cron-equal').textContent = diff.igual ? 'sí' : 'no';
      $('cron-diff').textContent = (diff.diferencias || []).length
        ? JSON.stringify(diff.diferencias, null, 2) : 'sin diferencias';
      $('cron-render').textContent = diff.render || '';
    } catch (err) {
      showBanner('No se pudo leer el cron: ' + err.message, 'danger');
    }
  }

  /* --------------------------------- tabs -------------------------------- */

  function switchTab(name) {
    state.tab = name;
    ['dashboard', 'historial', 'archivos', 'cron'].forEach(function (tab) {
      var pane = $('tab-' + tab);
      if (pane) pane.hidden = tab !== name;
    });
    document.querySelectorAll('#main-tabs .nav-link').forEach(function (link) {
      link.classList.toggle('active', link.getAttribute('data-tab') === name);
    });
    if (name === 'historial') loadHistory();
    else if (name === 'archivos') loadFiles('');
    else if (name === 'cron') loadCron();
  }

  /* --------------------------------- tema -------------------------------- */

  function currentTheme() {
    var root = document.documentElement;
    var theme = root.getAttribute('data-bs-theme') || root.getAttribute('data-theme');
    return theme === 'light' ? 'light' : 'dark';
  }

  function renderToggle(btn) {
    var goingLight = currentTheme() !== 'light';
    btn.textContent = goingLight ? '☀' : '☾';
    btn.setAttribute('aria-label', goingLight ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro');
  }

  function setupTheme() {
    var btn = $('theme-toggle');
    if (!btn) return;
    renderToggle(btn);
    btn.addEventListener('click', function () {
      var next = currentTheme() === 'light' ? 'dark' : 'light';
      var root = document.documentElement;
      root.setAttribute('data-theme', next);
      root.setAttribute('data-bs-theme', next);
      try { localStorage.setItem('cortexdev-theme', next); } catch (e) {}
      renderToggle(btn);
    });
  }

  /* --------------------------------- init -------------------------------- */

  function fillJobSelects() {
    ['hist-job', 'files-job'].forEach(function (id) {
      var select = $(id);
      if (!select || select.options.length > 1) return;
      state.jobs.forEach(function (job) {
        select.appendChild(el('option', { value: job.slug, text: job.name }));
      });
    });
  }

  function scheduleRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(function () {
      if (document.hidden || state.tab !== 'dashboard') return;
      loadDashboard(true);
    }, REFRESH_MS);
  }

  document.addEventListener('DOMContentLoaded', async function () {
    setupTheme();
    document.querySelectorAll('#main-tabs .nav-link').forEach(function (link) {
      link.addEventListener('click', function () { switchTab(link.getAttribute('data-tab')); });
    });
    $('jobs-refresh').addEventListener('click', function () { loadDashboard(false); });
    $('hist-refresh').addEventListener('click', loadHistory);
    $('hist-filter').addEventListener('submit', function (event) { event.preventDefault(); loadHistory(); });
    $('files-job').addEventListener('change', function () { loadFiles(''); });
    $('job-save').addEventListener('click', saveSchedule);
    $('logout-btn').addEventListener('click', async function () {
      try { await API.post('/auth/logout'); } catch (e) {}
      location.href = '/login.html';
    });
    $('jobs-body').addEventListener('click', function (event) {
      var button = event.target.closest('button[data-action]');
      if (button) handleAction(button.getAttribute('data-action'), button.getAttribute('data-slug'));
    });

    try {
      state.user = await API.get('/auth/me');
      $('user-name').textContent = state.user.username + ' (' + state.user.role + ')';
    } catch (e) {
      return;
    }
    await loadDashboard(false);
    fillJobSelects();
    scheduleRefresh();
  });
})();
