/* Vista Auditoría: quién hizo qué y cuándo. */
import { $, el, fmtDate, toast } from '../ui.js';

let ctxRef = null;

async function load() {
  const params = new URLSearchParams({ limit: '200' });
  const username = $('audit-user').value.trim();
  const action = $('audit-action').value;
  if (username) params.set('username', username);
  if (action) params.set('action', action);
  try {
    const data = await ctxRef.api.get('/audit?' + params.toString());
    const body = $('audit-body');
    body.innerHTML = '';
    if (!data.entries.length) {
      body.appendChild(el('tr', {}, [el('td', { colspan: '5', class: 'empty', text: 'Sin registros.' })]));
      return;
    }
    data.entries.forEach((entry) => {
      body.appendChild(el('tr', {}, [
        el('td', { text: fmtDate(entry.created_at) }),
        el('td', { class: 'mono', text: entry.username }),
        el('td', { text: entry.action }),
        el('td', { class: 'mono', text: entry.job_slug || '—' }),
        el('td', { class: 'mono', text: entry.detail ? JSON.stringify(entry.detail) : '—' }),
      ]));
    });
  } catch (err) {
    toast('No se pudo cargar la auditoría: ' + err.message, 'err');
    const body = $('audit-body');
    if (body) {
      body.innerHTML = '';
      body.appendChild(el('tr', {}, [el('td', {
        colspan: '5', class: 'empty',
        text: 'No se pudo cargar la auditoría: ' + err.message,
      })]));
    }
  }
}

export const audit = {
  id: 'auditoria',
  admin: true,
  mount(ctx) {
    ctxRef = ctx;
    $('audit-filter').addEventListener('submit', (event) => { event.preventDefault(); load(); });
    $('audit-refresh').addEventListener('click', load);
  },
  render(ctx) {
    ctxRef = ctx;
    load();
  },
};
