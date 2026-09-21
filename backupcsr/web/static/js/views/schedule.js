/* Vista Programación: estado del cron, tabla de horarios y editor visual. */
import { $, el, icon, pill, fmtDate, scheduleText, toast, hideModal, openModal } from '../ui.js';

let ctxRef = null;

const PRESETS = [
  { label: 'Cada hora (6-19)', minute: '20', hour: '6-19' },
  { label: '3×día (6,13,19)', minute: '20', hour: '6,13,19' },
  { label: 'Cada 30 min (6-19)', minute: '0,30', hour: '6-19' },
  { label: 'Cada 15 min', minute: '*/15', hour: '*' },
];

function scheduleFields() {
  return {
    cron_minute: $('schedule-minute').value.trim(),
    cron_hour: $('schedule-hour').value.trim(),
    cron_dom: $('schedule-dom').value.trim(),
    cron_month: $('schedule-month').value.trim(),
    cron_dow: $('schedule-dow').value.trim(),
  };
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

function renderTable(state) {
  const body = $('cron-body');
  const canManage = state.manageCron && state.user && state.user.role === 'admin';
  body.innerHTML = '';
  (state.jobs || []).forEach((job) => {
    const actions = el('td', { class: 'text-nowrap' });
    const button = el('button', {
      type: 'button',
      class: 'btn btn-sm btn-outline-' + (canManage ? 'secondary' : 'light'),
      title: canManage ? 'Editar el horario' : 'Solo lectura: activa BACKUP_MANAGE_CRON=1',
      onclick: () => openEditor(job, canManage),
    });
    button.innerHTML = '<i class="fa-solid fa-pen-to-square"></i><span>' +
      (canManage ? 'Editar' : 'Ver') + '</span>';
    actions.appendChild(button);
    body.appendChild(el('tr', {}, [
      el('td', {}, [
        el('div', { class: 'fw-semibold', text: job.name }),
        el('div', { class: 'muted mono', text: job.slug }),
      ]),
      el('td', {}, [el('code', { text: scheduleText(job) })]),
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

async function save() {
  const slug = $('schedule-slug').value;
  const payload = Object.assign({ enabled: $('schedule-enabled').checked }, scheduleFields());
  try {
    await ctxRef.api.patch('/jobs/' + slug, payload);
    hideModal('scheduleModal');
    toast('Programación actualizada', 'ok');
    await ctxRef.refresh(true);
    if (ctxRef.state.tab === 'programacion') loadCron();
  } catch (err) {
    const box = $('schedule-error');
    box.textContent = err.message;
    box.hidden = false;
  }
}

export function openEditor(job, canManage) {
  $('schedule-slug').value = job.slug;
  $('schedule-title').textContent = (canManage ? 'Horario · ' : 'Horario (solo lectura) · ') + job.name;
  $('schedule-enabled').checked = !!job.enabled;
  $('schedule-enabled').disabled = !canManage;
  ['schedule-minute', 'schedule-hour', 'schedule-dom', 'schedule-month', 'schedule-dow']
    .forEach((id) => { $(id).readOnly = !canManage; });
  $('schedule-minute').value = job.cron_minute;
  $('schedule-hour').value = job.cron_hour;
  $('schedule-dom').value = job.cron_dom;
  $('schedule-month').value = job.cron_month;
  $('schedule-dow').value = job.cron_dow;
  $('schedule-error').hidden = true;
  $('schedule-note').hidden = !!canManage;
  $('schedule-preview').innerHTML = '';
  $('schedule-save').disabled = !canManage;
  document.querySelectorAll('#schedule-presets button').forEach((node) => { node.disabled = !canManage; });
  openModal('scheduleModal');
  preview();
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
