/* Utilidades de UI compartidas (módulo ES). */
import { iconSvg } from './icons.js';

export const $ = (id) => document.getElementById(id);

export function el(tag, attrs, children) {
  const node = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach((key) => {
      const value = attrs[key];
      if (value === null || value === undefined) return;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'html') node.innerHTML = value;
      else if (key === 'style') node.setAttribute('style', value);
      else if (key === 'onclick') node.addEventListener('click', value);
      else if (key.indexOf('data-') === 0 || key === 'colspan' || key === 'title') node.setAttribute(key, value);
      else node.setAttribute(key, value);
    });
  }
  (children || []).forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  });
  return node;
}

export function icon(name, cls) {
  const span = el('span', { class: 'd-inline-flex align-items-center' });
  span.innerHTML = iconSvg(name, cls);
  return span;
}

const STATUS_META = {
  OK: { pill: 'ok', label: 'OK' },
  EN_CURSO: { pill: 'info', label: 'EN CURSO' },
  TARDE: { pill: 'warn', label: 'TARDE' },
  FALLO: { pill: 'err', label: 'FALLÓ' },
  NUNCA: { pill: 'unknown', label: 'NUNCA' },
  DESHABILITADA: { pill: 'unknown', label: 'DESHABILITADA' },
  INCIERTO: { pill: 'unknown', label: 'INCIERTO' },
};

export function statusClass(status) {
  return (STATUS_META[status] || STATUS_META.INCIERTO).pill;
}

export function statusLabel(status) {
  return (STATUS_META[status] || STATUS_META.INCIERTO).label;
}

export function pill(status, title) {
  const node = el('span', {
    class: 'badge rounded-pill pill-' + statusClass(status),
    text: statusLabel(status),
  });
  if (title) node.title = title;
  return node;
}

export function fmtBytes(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let value = Number(bytes);
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return (i === 0 ? value : value.toFixed(value >= 100 ? 0 : 1)) + ' ' + units[i];
}

export function fmtGb(bytes) {
  if (!bytes) return '0 GB';
  return (bytes / (1024 ** 3)).toFixed(2) + ' GB';
}

/* Fechas sin segundos: "21/9/2026, 11:20". */
export function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString('es-CO', {
    year: 'numeric', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });
}

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return seconds + 's';
  const m = Math.floor(seconds / 60);
  if (m < 60) return m + 'm ' + (seconds % 60) + 's';
  return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
}

export function relTime(value) {
  if (!value) return '—';
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (isNaN(seconds)) return '—';
  if (seconds < 60) return 'hace ' + seconds + 's';
  const m = Math.floor(seconds / 60);
  if (m < 60) return 'hace ' + m + 'm';
  const h = Math.floor(m / 60);
  if (h < 24) return 'hace ' + h + 'h';
  return 'hace ' + Math.floor(h / 24) + 'd';
}

export function scheduleText(job) {
  return [job.cron_minute, job.cron_hour, job.cron_dom, job.cron_month, job.cron_dow].join(' ');
}

export function showBanner(message, kind) {
  const banner = $('banner');
  if (!banner) return;
  banner.className = 'alert alert-' + (kind || 'warning') + ' banner';
  banner.textContent = message;
  banner.hidden = false;
}

export function clearBanner() {
  const banner = $('banner');
  if (banner) banner.hidden = true;
}

export function toast(message, kind) {
  const stack = $('toast-stack');
  if (!stack) return;
  const colors = { ok: 'success', success: 'success', err: 'danger', danger: 'danger', warn: 'warning', info: 'info' };
  const node = el('div', {
    class: 'toast show align-items-center text-bg-' + (colors[kind] || 'secondary'),
    role: 'alert',
  }, [
    el('div', { class: 'd-flex' }, [
      el('div', { class: 'toast-body', text: message }),
      el('button', {
        type: 'button', class: 'btn-close btn-close-white me-2 m-auto',
        'aria-label': 'Cerrar', onclick: () => node.remove(),
      }),
    ]),
  ]);
  stack.appendChild(node);
  setTimeout(() => node.remove(), 4500);
}

export function confirmDialog(title, message, onConfirm, okLabel, okClass) {
  const modal = bootstrap.Modal.getOrCreateInstance($('confirmModal'));
  $('confirm-title').textContent = title;
  $('confirm-text').textContent = message;
  const button = $('confirm-ok');
  button.textContent = okLabel || 'Confirmar';
  button.className = 'btn ' + (okClass || 'btn-danger');
  const fresh = button.cloneNode(true);
  button.replaceWith(fresh);
  fresh.addEventListener('click', () => {
    modal.hide();
    onConfirm();
  });
  modal.show();
}

export function openModal(id) {
  bootstrap.Modal.getOrCreateInstance($(id)).show();
}

export function hideModal(id) {
  bootstrap.Modal.getOrCreateInstance($(id)).hide();
}
