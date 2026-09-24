/* Vista Programación: editor de tarea (ficha + horario) y estado del cron. */
import { $, el, icon, pill, fmtDate, scheduleText, toast, hideModal, openModal } from '../ui.js';

let ctxRef = null;

const PRESETS = [
  { label: 'Cada hora (6-19)', minute: '20', hour: '6-19' },
  { label: '3×día (6,13,19)', minute: '20', hour: '6,13,19' },
  { label: 'Cada 30 min (6-19)', minute: '0,30', hour: '6-19' },
  { label: 'Cada 15 min', minute: '*/15', hour: '*' },
];

/* Estado del modal abierto: qué puede editar el usuario y la pestaña activa. */
const editor = { canEditFicha: false, canManage: false };
const scriptCache = new Map();

function scheduleFields() {
  return {
    cron_minute: $('schedule-minute').value.trim(),
    cron_hour: $('schedule-hour').value.trim(),
    cron_dom: $('schedule-dom').value.trim(),
    cron_month: $('schedule-month').value.trim(),
    cron_dow: $('schedule-dow').value.trim(),
  };
}

function generalFields() {
  return {
    name: $('job-name').value.trim(),
    description: $('job-description').value.trim(),
    origin_type: $('job-origin-type').value,
    source: $('job-source').value.trim(),
    dest_rel: $('job-dest-rel').value.trim(),
    sort: $('job-sort').value.trim(),
    criticality: $('job-criticality').value,
    owner: $('job-owner').value.trim(),
    retention_days: $('job-retention').value.trim(),
    tags: $('job-tags').value.trim(),
    size_exclude: $('job-size-exclude').value.trim(),
    notes: $('job-notes').value,
  };
}

/* Activa una pestaña del modal (usa Bootstrap si está; si no, alterna clases). */
function showTab(which) {
  const target = which === 'programacion' ? 'tab-programacion' : 'tab-general';
  const button = $(target + '-btn');
  if (!button) return;
  if (window.bootstrap && window.bootstrap.Tab) {
    window.bootstrap.Tab.getOrCreateInstance(button).show();
    return;
  }
  ['tab-general', 'tab-programacion'].forEach((id) => {
    const pane = $(id);
    const btn = $(id + '-btn');
    if (pane) {
      pane.classList.toggle('show', id === target);
      pane.classList.toggle('active', id === target);
    }
    if (btn) {
      btn.classList.toggle('active', id === target);
      btn.setAttribute('aria-selected', id === target ? 'true' : 'false');
    }
  });
}

async function loadCron() {
  try {
    const data = await ctxRef.api.get('/cron');
    const readonly = $('cron-readonly');
    if (readonly) readonly.hidden = !!data.manage_cron;
    $('cron-manage').textContent = data.manage_cron ? 'activada' : 'desactivada (solo lectura)';
    $('cron-path').textContent = data.path;
    const diff = data.diff || {};
    $('cron-equal').textContent = diff.igual ? 'sí' : 'no';
    $('cron-diff').textContent = (diff.diferencias || []).length
      ? JSON.stringify(diff.diferencias, null, 2) : 'sin diferencias';
    $('cron-render').textContent = diff.render || '';
  } catch (err) {
    toast('No se pudo leer el cron: ' + err.message, 'err');
  }
}

/* Horario que realmente dispara: el del cron instalado. La BD es el horario
   editable y puede estar desviada (se muestra como "BD:" cuando difiere). */
function effectiveSchedule(job) {
  const cron = job.cron_effective;
  if (!cron) return job;
  return {
    cron_minute: cron.minute,
    cron_hour: cron.hour,
    cron_dom: cron.dom,
    cron_month: cron.month,
    cron_dow: cron.dow,
  };
}

function renderTable(state) {
  const body = $('cron-body');
  const isAdmin = !!(state.user && state.user.role === 'admin');
  const canManage = state.manageCron && isAdmin;
  body.innerHTML = '';
  (state.jobs || []).forEach((job) => {
    const actions = el('td', { class: 'text-nowrap' });
    const button = el('button', {
      type: 'button',
      class: 'btn btn-sm btn-outline-' + (isAdmin ? 'secondary' : 'light'),
      title: isAdmin ? 'Editar la ficha y el horario' : 'Solo lectura',
      onclick: () => openEditor(job, { isAdmin: isAdmin, canManage: canManage, tab: 'programacion' }),
    });
    button.innerHTML = '<i class="fa-solid fa-pen-to-square"></i><span>' +
      (isAdmin ? 'Editar' : 'Ver') + '</span>';
    actions.appendChild(button);
    const scheduleCell = el('td', {}, [
      el('code', { text: scheduleText(effectiveSchedule(job)) }),
    ]);
    if (job.schedule_drift) {
      scheduleCell.appendChild(el('div', { class: 'd-flex align-items-center gap-1 mt-1' }, [
        el('span', { class: 'badge rounded-pill pill-warn', text: 'desvío' }),
        el('span', { class: 'small muted', text: 'BD: ' + scheduleText(job) }),
      ]));
    }
    body.appendChild(el('tr', {}, [
      el('td', {}, [
        el('div', { class: 'fw-semibold', text: job.name }),
        el('div', { class: 'muted mono', text: job.slug }),
      ]),
      scheduleCell,
      el('td', {}, [el('span', {
        class: 'badge rounded-pill ' + (job.enabled ? 'pill-ok' : 'pill-unknown'),
        text: job.enabled ? 'habilitada' : 'deshabilitada',
      })]),
      actions,
    ]));
  });
}

function renderPresets() {
  const box = $('schedule-presets');
  box.innerHTML = '';
  PRESETS.forEach((preset) => {
    box.appendChild(el('button', {
      type: 'button', class: 'btn btn-sm btn-outline-secondary', text: preset.label,
      onclick: () => {
        $('schedule-minute').value = preset.minute;
        $('schedule-hour').value = preset.hour;
        preview();
      },
    }));
  });
}

async function preview() {
  const slug = $('schedule-slug').value;
  const fields = scheduleFields();
  const params = new URLSearchParams({
    minute: fields.cron_minute, hour: fields.cron_hour, dom: fields.cron_dom,
    month: fields.cron_month, dow: fields.cron_dow, count: '5',
  });
  try {
    const data = await ctxRef.api.get('/jobs/' + slug + '/cron-preview?' + params.toString());
    const list = $('schedule-preview');
    list.innerHTML = '';
    (data.next || []).forEach((when) => list.appendChild(el('li', { text: fmtDate(when) })));
    if (!(data.next || []).length) list.appendChild(el('li', { class: 'muted', text: 'sin ocurrencias' }));
    $('schedule-error').hidden = true;
  } catch (err) {
    const box = $('schedule-error');
    box.textContent = err.message;
    box.hidden = false;
  }
}

async function loadScript(slug) {
  const pre = $('job-script');
  const drift = $('job-script-drift');
  if (!pre) return;
  const cached = scriptCache.get(slug);
  if (cached) {
    paintScript(cached);
    return;
  }
  pre.textContent = 'cargando…';
  let data;
  try {
    data = await ctxRef.api.get('/jobs/' + encodeURIComponent(slug) + '/script');
    scriptCache.set(slug, data);
  } catch (err) {
    data = { exists: false, text: '', drift: false, path: '' };
  }
  if ($('schedule-slug').value !== slug) return;
  paintScript(data);
}

function paintScript(data) {
  const pre = $('job-script');
  const drift = $('job-script-drift');
  if (!pre) return;
  pre.textContent = data.exists
    ? data.text
    : 'No hay script instalado en ' + (data.path || '/opt/backupcsr/jobs/<slug>.sh');
  if (drift) drift.hidden = !data.drift;
}

async function save() {
  const slug = $('schedule-slug').value;
  const payload = {};
  if (editor.canEditFicha) Object.assign(payload, generalFields());
  if (editor.canManage) {
    Object.assign(payload, scheduleFields(), {
      enabled: $('schedule-enabled').checked,
      lockfile: $('schedule-lockfile').value.trim(),
    });
  }
  if (!Object.keys(payload).length) return;
  // Numéricos: sort vacío se omite (lo conserva el servidor); retención vacía = limpiar.
  if ('sort' in payload) {
    if (payload.sort === '') delete payload.sort;
    else payload.sort = Number(payload.sort);
  }
  if ('retention_days' in payload) {
    payload.retention_days = payload.retention_days === '' ? null : Number(payload.retention_days);
  }
  // Las tareas deshabilitadas pueden no tener destino; en blanco se omite (el
  // servidor rechaza un dest_rel vacío) en vez de bloquear el guardado de la ficha.
  if (payload.dest_rel === '') delete payload.dest_rel;
  try {
    await ctxRef.api.patch('/jobs/' + slug, payload);
    scriptCache.delete(slug);
    hideModal('scheduleModal');
    toast('Tarea actualizada', 'ok');
    await ctxRef.refresh(true);
    if (ctxRef.state.tab === 'programacion') loadCron();
  } catch (err) {
    const box = $('schedule-error');
    box.textContent = err.message;
    box.hidden = false;
  }
}

export function openEditor(job, opts) {
  const options = opts || {};
  const isAdmin = !!options.isAdmin;
  const canManage = !!options.canManage; // admin && BACKUP_MANAGE_CRON=1
  editor.canEditFicha = isAdmin;
  editor.canManage = canManage;

  $('schedule-slug').value = job.slug;
  $('schedule-title').textContent = (isAdmin ? 'Tarea · ' : 'Tarea (solo lectura) · ') + job.name;

  // --- Ficha ---
  $('job-name').value = job.name || '';
  $('job-description').value = job.description || '';
  $('job-origin-type').value = job.origin_type || 'ftp';
  $('job-source').value = job.source || '';
  $('job-dest-rel').value = job.dest_rel || '';
  $('job-sort').value = job.sort === null || job.sort === undefined ? '' : job.sort;
  $('job-criticality').value = job.criticality || 'media';
  $('job-owner').value = job.owner || '';
  $('job-retention').value = job.retention_days === null || job.retention_days === undefined
    ? '' : job.retention_days;
  $('job-tags').value = job.tags || '';
  $('job-size-exclude').value = Array.isArray(job.size_exclude)
    ? job.size_exclude.join(', ') : (job.size_exclude || '');
  $('job-notes').value = job.notes || '';
  ['job-name', 'job-description', 'job-origin-type', 'job-source', 'job-dest-rel', 'job-sort',
    'job-criticality', 'job-owner', 'job-retention', 'job-tags', 'job-size-exclude',
    'job-notes'].forEach((id) => { $(id).disabled = !isAdmin; });

  // --- Programación ---
  $('schedule-enabled').checked = !!job.enabled;
  $('schedule-enabled').disabled = !canManage;
  ['schedule-minute', 'schedule-hour', 'schedule-dom', 'schedule-month', 'schedule-dow',
    'schedule-lockfile'].forEach((id) => { $(id).readOnly = !canManage; });
  // Si el cron instalado difiere de la BD, el editor arranca con el horario efectivo
  // para que Guardar (MANAGE_CRON=1) adopte el real y limpie el desvío.
  const source = job.schedule_drift ? effectiveSchedule(job) : job;
  $('schedule-minute').value = source.cron_minute;
  $('schedule-hour').value = source.cron_hour;
  $('schedule-dom').value = source.cron_dom;
  $('schedule-month').value = source.cron_month;
  $('schedule-dow').value = source.cron_dow;
  $('schedule-lockfile').value = job.lockfile || '';

  $('schedule-error').hidden = true;
  $('schedule-note').hidden = canManage;
  $('schedule-preview').innerHTML = '';
  $('schedule-save').disabled = !isAdmin;
  document.querySelectorAll('#schedule-presets button').forEach((node) => { node.disabled = !canManage; });

  showTab(options.tab || 'general');
  openModal('scheduleModal');
  loadScript(job.slug);
  if (canManage) preview();
}

export const schedule = {
  id: 'programacion',
  admin: false,
  mount(ctx) {
    ctxRef = ctx;
    renderPresets();
    $('schedule-preview-btn').addEventListener('click', preview);
    $('schedule-save').addEventListener('click', save);
  },
  render(ctx) {
    ctxRef = ctx;
    renderTable(ctx.state);
    loadCron();
  },
  openEditor,
};
