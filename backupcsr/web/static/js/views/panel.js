/* Vista Panel: KPIs, tendencia de tamaño, duraciones y tabla de jobs.

   La tabla no repite botones por fila: se selecciona una fila y las acciones se
   aplican desde una única barra tipo DataTables (Buttons) superior. */
import {
  $, el, icon, pill, statusClass, statusLabel, fmtGb, fmtDate, fmtDuration,
  scheduleText, toast, confirmDialog,
} from '../ui.js';
import { sparkline, barList, emptyChart, diskGauge } from '../chart.js';

let ctxRef = null;

function kpi(label, value, sub, extra) {
  return el('div', { class: 'col' }, [
    el('div', { class: 'card kpi h-100 ' + (extra || '') }, [
      el('div', { class: 'card-body' }, [
        el('div', { class: 'kpi-label' }, [el('span', { text: label })]),
        el('div', { class: 'kpi-value', text: value }),
        el('div', { class: 'kpi-sub', text: sub || '' }),
      ]),
    ]),
  ]);
}

function deltaLabel(growth, key) {
  const item = growth && growth[key];
  if (!item) return 'sin histórico';
  const sign = item.bytes > 0 ? '+' : '';
  const pct = item.percent === null || item.percent === undefined ? '' : ' (' + sign + item.percent + '%)';
  return sign + fmtGb(item.bytes) + pct + ' vs ' + key.replace('d', '') + 'd';
}

function renderKpis(summary) {
  const counts = summary.counts || {};
  const nas = summary.nas_stats;
  const growth = summary.growth || {};
  const bad = (counts.FALLO || 0) + (counts.NUNCA || 0);
  const row = $('kpi-row');
  if (!row) return;
  row.innerHTML = '';
  row.appendChild(kpi('GB almacenados', fmtGb(summary.bytes_total),
    (summary.files_total || 0).toLocaleString('es-CO') + ' archivos'));
  row.appendChild(kpi('Crecimiento 7d', deltaLabel(growth, 'd7'),
    deltaLabel(growth, 'd30'), (growth.d7 && growth.d7.bytes > 0) ? 'warn' : 'okv'));
  row.appendChild(kpi('Jobs OK', String(counts.OK || 0), 'de ' + (counts.total || 0) + ' · ' +
    (counts.habilitados || 0) + ' habilitadas', 'okv'));
  row.appendChild(kpi('Fallos / sin datos', String(bad),
    (counts.EN_CURSO || 0) + ' en curso · ' + (counts.TARDE || 0) + ' tarde', bad ? 'err' : ''));
  row.appendChild(kpi('Duración media', summary.avg_duration_s ? fmtDuration(summary.avg_duration_s) : '—',
    'última ejecución'));
  row.appendChild(kpi('NAS libre', nas ? fmtGb(nas.free) : '—',
    nas ? (nas.percent + '% usado de ' + fmtGb(nas.total)) : 'no montado',
    nas && nas.percent >= 80 ? 'warn' : ''));
}

function alertRow(alert) {
  return el('div', {
    class: 'alert alert-' + alert.level + ' mb-0 d-flex align-items-center gap-2',
  }, [icon('alert'), el('span', { text: alert.text })]);
}

/* El aviso de NAS no es una alerta de texto: es un disco con anillo de uso. */
function nasCard(alert, stats, copies) {
  const level = !stats ? 'off' : (alert.level === 'danger' ? 'danger' : 'warn');
  const parsed = parseFloat((String(alert.text).match(/([\d.]+)\s*%/) || [])[1]);
  const percent = stats ? Number(stats.percent) || 0 : (isNaN(parsed) ? 0 : parsed);

  /* Copias: parte del uso ocupada por las tareas (bytes medidos por el backend). */
  const bytes = copies && copies.bytes ? Math.min(Number(copies.bytes), Number(stats.total) || 0) : 0;
  const copiesPercent = stats && Number(stats.total) ? (bytes / Number(stats.total)) * 100 : 0;
  const otherBytes = copies ? Math.max(0, (Number(stats.used) || 0) - bytes) : 0;

  const ring = el('div', { class: 'disk-ring' });
  ring.innerHTML = diskGauge(percent, level, copiesPercent);
  ring.appendChild(el('div', { class: 'disk-center' }, [
    el('span', { class: 'disk-percent', text: stats ? percent.toFixed(1) + '%' : '—' }),
    el('span', { class: 'disk-caption', text: stats ? 'usado' : 'sin datos' }),
  ]));

  const bars = [];
  if (copies && bytes) {
    bars.push(el('div', {
      class: 'progress-bar disk-bar-copies',
      style: 'width:' + Math.max(0, Math.min(100, copiesPercent)).toFixed(2) + '%',
      title: 'Copias de seguridad: ' + fmtGb(bytes) + (copies.partial ? ' (medición parcial)' : ''),
    }));
  }
  bars.push(el('div', {
    class: 'progress-bar ' + (level === 'danger' ? 'bg-danger' : level === 'warn' ? 'bg-warning' : level === 'off' ? 'bg-secondary' : 'bg-success'),
    style: 'width:' + Math.max(0, Math.min(100, percent - (copies && bytes ? copiesPercent : 0))).toFixed(2) + '%',
    title: copies && bytes ? 'Otro uso del NAS' : 'Uso del NAS',
  }));
  const bar = el('div', { class: 'progress disk-bar', role: 'progressbar', 'aria-valuenow': String(percent), 'aria-valuemin': '0', 'aria-valuemax': '100' }, bars);

  let legend = null;
  if (stats) {
    const keys = [];
    if (copies) {
      keys.push(el('span', {
        class: 'disk-key disk-key-copies',
        title: (copies.partial ? 'Medición parcial: alguna tarea no tiene tamaño calculado. ' : '') +
          (copies.files ? copies.files.toLocaleString('es-CO') + ' archivos en las tareas' : 'Bytes medidos por las tareas'),
      }, [
        el('i'), el('b', { text: (copies.partial ? '≥ ' : '') + fmtGb(bytes) }),
        document.createTextNode(' en copias'),
      ]));
      keys.push(el('span', { class: 'disk-key disk-key-other' }, [
        el('i'), el('b', { text: fmtGb(otherBytes) }), document.createTextNode(' otro uso'),
      ]));
    } else {
      keys.push(el('span', {}, [el('b', { text: fmtGb(stats.used) }), document.createTextNode(' usados')]));
    }
    keys.push(el('span', { class: 'disk-key disk-key-free' }, [
      el('i'), el('b', { text: fmtGb(stats.free) }), document.createTextNode(' libres'),
    ]));
    keys.push(el('span', { class: 'disk-key disk-key-total' }, [
      el('b', { text: fmtGb(stats.total) }), document.createTextNode(' total'),
    ]));
    legend = el('div', { class: 'disk-legend' }, keys);
  }

  return el('div', { class: 'disk-card disk-' + level }, [
    ring,
    el('div', { class: 'disk-body' }, [
      el('div', { class: 'disk-title' }, [
        el('i', { class: 'fa-solid fa-hard-drive' }),
        el('span', { text: 'Almacenamiento NAS' }),
      ]),
      bar,
      legend,
      el('div', { class: 'disk-note' }, [
        el('i', { class: level === 'off' ? 'fa-solid fa-plug-circle-xmark' : 'fa-solid fa-triangle-exclamation' }),
        el('span', {
          text: level === 'off' ? alert.text
            : (level === 'danger' ? 'Espacio crítico: ' : 'Aviso: ') + alert.text,
        }),
      ]),
    ]),
  ]);
}

/* Tamaño de las copias: lo que el backend ya midió para las tareas. */
function copiesInfo(summary, state) {
  if (summary.bytes_total === null || summary.bytes_total === undefined) return null;
  const bytes = Number(summary.bytes_total) || 0;
  if (!bytes) return null;  /* sin mediciones: leyenda clásica de usados/libres */
  const jobs = (state && state.jobs) || [];
  const measured = jobs.filter((job) => job.size && job.size.bytes !== null && job.size.bytes !== undefined);
  return { bytes, files: Number(summary.files_total) || 0, partial: jobs.length > 0 && measured.length < jobs.length };
}

function renderAlerts(summary, state) {
  const box = $('alert-box');
  if (!box) return;
  const alerts = summary.alerts || [];
  const stats = summary.nas_stats || null;
  const copies = stats ? copiesInfo(summary, state) : null;
  box.innerHTML = '';
  alerts.slice(0, 6).forEach((alert) => {
    box.appendChild(alert.kind === 'nas' ? nasCard(alert, stats, copies) : alertRow(alert));
  });
  box.hidden = alerts.length === 0;
}

function seriesPoints(series, slug) {
  const byStamp = {};
  series.forEach((point) => {
    if (slug && point.job_slug !== slug) return;
    const key = point.taken_at;
    if (!key) return;
    byStamp[key] = (byStamp[key] || 0) + Number(point.bytes || 0);
  });
  return Object.keys(byStamp).sort().map((key) => ({ t: key, v: byStamp[key] }));
}

function renderCharts(state) {
  const series = state.series || [];
  const select = $('chart-job');
  const jobs = state.jobs || [];
  if (select && select.options.length === 0) {
    select.appendChild(el('option', { value: '', text: 'Total' }));
    jobs.forEach((job) => select.appendChild(el('option', { value: job.slug, text: job.name })));
  }
  const slug = select ? select.value : '';
  const sizeBox = $('chart-size');
  if (sizeBox) {
    sizeBox.innerHTML = series.length
      ? sparkline(seriesPoints(series, slug))
      : emptyChart('aún no hay snapshots de tamaño');
  }

  const durations = jobs
    .filter((job) => job.last_run && job.last_run.duration_s)
    .map((job) => ({ label: job.name, value: job.last_run.duration_s }))
    .sort((a, b) => b.value - a.value);
  const durationBox = $('chart-duration');
  if (durationBox) {
    durationBox.innerHTML = durations.length
      ? barList(durations, fmtDuration)
      : emptyChart('sin ejecuciones recientes');
  }
}

/* KPIs, alertas y gráficos: se pueden repintar sin tocar la tabla de jobs. */
function renderSummary(state) {
  const summary = state.summary || { counts: {} };
  renderKpis(summary);
  renderAlerts(summary, state);
  renderCharts(state);
}

/* ------------------------------ tabla de jobs ------------------------------ */

function jobRow(job) {
  const tr = el('tr', { class: 'clickable', 'data-slug': job.slug, tabindex: '0' });
  tr.appendChild(el('td', {}, [
    el('div', { class: 'fw-semibold', text: job.name }),
    el('div', { class: 'muted mono', text: job.slug + ' · ' + (job.origin_type || '') }),
  ]));
  const statusCell = el('td', {}, [pill(job.status, job.status_detail)]);
  tr.appendChild(statusCell);

  const size = job.size || {};
  tr.appendChild(el('td', {}, [
    el('div', { text: size.bytes === null || size.bytes === undefined ? '—' : fmtGb(size.bytes) }),
    el('div', { class: 'muted small', text: size.pending ? 'midiendo…' :
      (size.error ? size.error : (size.files || 0) + ' archivos') }),
  ]));

  const last = job.last_run;
  tr.appendChild(el('td', {}, [
    el('div', { text: last ? fmtDate(last.started_at) : '—' }),
    el('div', { class: 'muted small', text: last ? fmtDuration(last.duration_s) + ' · ' +
      (last.files_transferred || 0) + ' arch.' : '' }),
  ]));
  tr.appendChild(el('td', { text: fmtDate(job.next_run) }));
  tr.appendChild(el('td', { class: 'mono', text: '/mnt/nas/' + (job.dest_rel || '') }));
  tr.appendChild(el('td', {}, [
    el('code', { text: scheduleText(job) }),
    el('div', {}, [el('span', {
      class: 'badge rounded-pill ' + (job.enabled ? 'pill-ok' : 'pill-unknown'),
      text: job.enabled ? 'habilitada' : 'deshabilitada',
    })]),
  ]));
  return tr;
}

function selectedJob() {
  if (!ctxRef) return null;
  const state = ctxRef.state;
  return (state.jobs || []).filter((job) => job.slug === state.selected)[0] || null;
}

function applySelection() {
  if (!ctxRef) return;
  const slug = ctxRef.state.selected;
  document.querySelectorAll('#jobs-body tr[data-slug]').forEach((tr) => {
    tr.classList.toggle('selected-row', tr.getAttribute('data-slug') === slug);
  });
}

function setButton(action, enabled, options) {
  const button = document.querySelector('#jobs-actionbar button[data-action="' + action + '"]');
  if (!button) return;
  button.disabled = !enabled;
  const opts = options || {};
  if (opts.label) {
    const span = button.querySelector('span');
    if (span) span.textContent = opts.label;
  }
  if (opts.icon) {
    const node = button.querySelector('i');
    if (node) node.className = opts.icon;
  }
  if (opts.cls) button.className = opts.cls;
  if (opts.title !== undefined) button.title = opts.title;
}

function updateActionbar() {
  if (!ctxRef) return;
  const state = ctxRef.state;
  const job = selectedJob();
  const isAdmin = !!(state.user && state.user.role === 'admin');
  const canManage = isAdmin && !!state.manageCron;

  const label = $('jobs-selected');
  if (label) {
    label.innerHTML = '';
    if (job) {
      label.appendChild(el('i', { class: 'fa-solid fa-hand-pointer me-1' }));
      label.appendChild(el('span', { class: 'fw-semibold', text: job.name }));
      label.appendChild(document.createTextNode(' '));
      label.appendChild(el('span', {
        class: 'badge rounded-pill pill-' + statusClass(job.status),
        text: statusLabel(job.status),
      }));
    } else {
      label.innerHTML = '<i class="fa-solid fa-hand-pointer me-1"></i>Selecciona una fila para operar';
    }
  }

  const idle = !!job && !job.running;
  setButton('run', idle && isAdmin, {
    title: isAdmin ? 'Ejecutar ahora (mirror con --delete)' : 'Requiere rol admin',
  });
  setButton('dry', idle && isAdmin, {
    title: isAdmin ? 'Ejecución de prueba (sin borrar)' : 'Requiere rol admin',
  });
  setButton('retry', idle && isAdmin && job.status === 'FALLO', {
    title: job && job.status === 'FALLO' ? 'Reintentar la copia fallida' : 'Solo disponible si la tarea falló',
  });
  setButton('log', !!job, { title: 'Ver el log de la tarea' });
  setButton('history', !!job, { title: 'Ver ejecuciones de la tarea' });
  setButton('files', !!job, { title: 'Explorar el destino en el NAS' });
  setButton('schedule', !!job && canManage, {
    title: canManage ? 'Editar el horario' : 'Requiere admin y BACKUP_MANAGE_CRON=1',
  });
  setButton('toggle', !!job && canManage && !job.running, {
    label: job && job.enabled ? 'Deshabilitar' : 'Habilitar',
    icon: job && job.enabled ? 'fa-solid fa-toggle-off' : 'fa-solid fa-toggle-on',
    cls: 'btn btn-outline-' + (job && job.enabled ? 'warning' : 'success'),
    title: canManage ? 'Habilitar o deshabilitar la tarea' : 'Requiere admin y BACKUP_MANAGE_CRON=1',
  });
}

/* El estado vacío dice POR QUÉ está vacío: cargando, error de API, catálogo
   vacío o filtro sin coincidencias (con botón para quitarlo). */
function reasonCell(message, actionLabel, action) {
  const box = el('div', { class: 'empty-state' }, [el('span', { text: message })]);
  if (action) {
    const button = el('button', {
      type: 'button', class: 'btn btn-sm btn-outline-secondary', text: actionLabel,
    });
    button.addEventListener('click', action);
    box.appendChild(button);
  }
  return el('td', { colspan: '7', class: 'empty' }, [box]);
}

function clearFilter() {
  if (!ctxRef) return;
  ctxRef.state.jobsSearch = '';
  ctxRef.state.search = '';
  const box = $('jobs-search');
  if (box) box.value = '';
  renderJobs(ctxRef.state);
}

function renderJobs(state) {
  const body = $('jobs-body');
  if (!body) return;
  const count = $('jobs-count');
  const jobs = Array.isArray(state.jobs) ? state.jobs : [];
  const term = String(state.jobsSearch || '').trim().toLowerCase();
  const rows = term
    ? jobs.filter((job) => String(job.name || '').toLowerCase().includes(term)
      || String(job.slug || '').toLowerCase().includes(term))
    : jobs;

  // La selección solo se conserva si la tarea sigue existiendo.
  if (state.selected && !jobs.some((job) => job.slug === state.selected)) {
    state.selected = '';
  }

  const fragment = document.createDocumentFragment();
  const filtered = state.loaded && jobs.length > 0 && rows.length === 0;
  let message = '';
  if (state.loading) {
    message = 'Cargando tareas…';
  } else if (!state.loaded) {
    const failures = (state.apiErrors || []).map((item) => item.endpoint + ' → ' + item.message).join('; ');
    message = failures
      ? 'No se pudieron cargar las tareas (' + failures + ').'
      : 'No se pudieron cargar las tareas: el servidor no devolvió la lista.';
  } else if (!jobs.length) {
    message = 'El catálogo no tiene tareas (/etc/cron.d/backupcsr + jobs.yml).';
  } else if (filtered) {
    message = 'Sin coincidencias para «' + String(state.jobsSearch || '').trim() + '».';
  }

  if (message) {
    fragment.appendChild(el('tr', {}, [
      reasonCell(message, filtered ? 'Quitar filtro' : '', filtered ? clearFilter : null),
    ]));
  } else {
    rows.forEach((job) => {
      try {
        fragment.appendChild(jobRow(job));
      } catch (err) {
        console.error('jobRow', job && job.slug, err);
        fragment.appendChild(el('tr', {}, [
          reasonCell('No se pudo dibujar la tarea "' + (job && job.slug ? job.slug : '?') + '".'),
        ]));
      }
    });
  }

  // Sustitución atómica: la tabla nunca queda a medias.
  body.replaceChildren(fragment);
  if (count) count.textContent = state.loaded ? String(rows.length) : '—';
  applySelection();
  updateActionbar();
}

function select(slug) {
  if (ctxRef.state.selected === slug) return;
  ctxRef.state.selected = slug;
  console.debug('[panel] tarea seleccionada:', slug,
    '· filas:', document.querySelectorAll('#jobs-body tr[data-slug]').length);
  applySelection();
  updateActionbar();
}

async function handleAction(action) {
  const job = selectedJob();
  if (!job) {
    toast('Selecciona una tarea en la tabla', 'warn');
    return;
  }
  const slug = job.slug;
  try {
    if (action === 'run' || action === 'dry' || action === 'retry') {
      const dry = action === 'dry';
      const retry = action === 'retry';
      const message = retry
        ? 'Reintentar "' + job.name + '" AHORA? El mirror usa --delete.'
        : 'Ejecutar "' + job.name + '" AHORA? El mirror usa --delete y puede borrar en el NAS.';
      const launch = async () => {
        await ctxRef.api.post('/jobs/' + slug + '/run', { dry_run: dry, retry });
        toast('Ejecución lanzada: ' + job.name + (dry ? ' (dry-run)' : ''), 'info');
        setTimeout(() => ctxRef.refresh(true), 1500);
      };
      if (dry) await launch();
      else confirmDialog(retry ? 'Reintentar copia' : 'Ejecutar copia', message, launch,
        retry ? 'Reintentar' : 'Ejecutar', 'btn-warning');
    } else if (action === 'toggle') {
      await ctxRef.api.patch('/jobs/' + slug, { enabled: !job.enabled });
      toast((job.enabled ? 'Deshabilitada: ' : 'Habilitada: ') + job.name, 'ok');
      await ctxRef.refresh(true);
    } else if (action === 'log') {
      await ctxRef.openLog(slug, job.name);
    } else if (action === 'history') {
      ctxRef.state.histJob = slug;
      ctxRef.go('historial');
    } else if (action === 'files') {
      ctxRef.state.filesJob = slug;
      ctxRef.go('archivos');
    } else if (action === 'schedule') {
      ctxRef.openSchedule(job);
    }
  } catch (err) {
    toast('Error: ' + err.message, 'err');
  }
}

export const panel = {
  id: 'panel',
  admin: false,
  mount(ctx) {
    ctxRef = ctx;
    const body = $('jobs-body');
    if (body) {
      body.addEventListener('click', (event) => {
        const row = event.target.closest('tr[data-slug]');
        if (row) select(row.getAttribute('data-slug'));
      });
      body.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const row = event.target.closest('tr[data-slug]');
        if (!row) return;
        event.preventDefault();
        select(row.getAttribute('data-slug'));
      });
    }
    const bar = $('jobs-actionbar');
    if (bar) {
      bar.addEventListener('click', (event) => {
        const button = event.target.closest('button[data-action]');
        if (button && !button.disabled) handleAction(button.getAttribute('data-action'));
      });
    }
    // El filtro de #jobs-search lo gobierna shell.js (setupFilters), que además
    // descarta el autofill del navegador.
    const selectJob = $('chart-job');
    if (selectJob) selectJob.addEventListener('change', () => renderCharts(ctxRef.state));
  },
  render(ctx) {
    ctxRef = ctx;
    renderSummary(ctx.state);
    renderJobs(ctx.state);
  },
  renderSummary(state) { renderSummary(state); },
  renderCharts(state) { renderCharts(state); },
  renderJobs(state) { renderJobs(state); },
};
