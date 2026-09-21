/* Vista Archivos: navegador de solo lectura de /mnt/nas por job. */
import { $, el, fmtBytes, fmtDate, fmtGb, relTime, toast } from '../ui.js';

let ctxRef = null;

function jobBySlug(slug) {
  return (ctxRef.state.jobs || []).filter((job) => job.slug === slug)[0];
}

function ensureOptions(state) {
  const select = $('files-job');
  if (select.options.length === 0) {
    (state.jobs || []).forEach((job) => select.appendChild(el('option', { value: job.slug, text: job.name })));
  }
  if (state.filesJob) {
    select.value = state.filesJob;
    state.filesJob = '';
  }
}

function renderSizeInfo(slug) {
  const job = jobBySlug(slug);
  const size = (job && job.size) || {};
  const box = $('files-size');
  if (!job) { box.textContent = '—'; return; }
  if (size.bytes === null || size.bytes === undefined) {
    box.textContent = size.pending ? 'midiendo…' : (size.error || 'sin datos de tamaño');
    return;
  }
  box.textContent = fmtGb(size.bytes) + ' · ' + (size.files || 0) + ' archivos · medido ' +
    relTime(size.computed_at) + (size.truncated ? ' (parcial)' : '');
}

async function loadFiles(path, slugOverride) {
  const slug = slugOverride || $('files-job').value;
  if (!slug) return;
  try {
    const data = await ctxRef.api.get('/jobs/' + slug + '/files?path=' + encodeURIComponent(path || ''));
    renderBreadcrumb(data.path);
    const body = $('files-body');
    body.innerHTML = '';
    if (data.parent !== '' && data.path) {
      const up = el('tr', { class: 'clickable' }, [el('td', { colspan: '4', text: '..' })]);
      up.addEventListener('click', () => loadFiles(data.parent));
      body.appendChild(up);
    }
    if (!data.entries.length) {
      body.appendChild(el('tr', {}, [el('td', { colspan: '4', class: 'empty', text: 'Directorio vacío.' })]));
    }
    data.entries.forEach((entry) => {
      const tr = el('tr', entry.type === 'dir' ? { class: 'clickable' } : {});
      tr.appendChild(el('td', {}, [
        el('i', {
          class: 'fa-solid me-2 ' +
            (entry.type === 'dir' ? 'fa-folder text-warning' : 'fa-file text-body-secondary'),
        }),
        el('span', { class: 'mono', text: entry.name }),
      ]));
      tr.appendChild(el('td', { text: entry.type === 'dir' ? 'carpeta' : 'archivo' }));
      tr.appendChild(el('td', { text: entry.type === 'file' ? fmtBytes(entry.size) : '—' }));
      tr.appendChild(el('td', { text: fmtDate(entry.mtime) }));
      if (entry.type === 'dir') tr.addEventListener('click', () => loadFiles(entry.path));
      body.appendChild(tr);
    });
    renderSizeInfo(slug);
  } catch (err) {
    toast('No se pudo listar los archivos: ' + err.message, 'err');
  }
}

function renderBreadcrumb(path) {
  const box = $('files-breadcrumb');
  box.innerHTML = '';
  const root = el('a', { text: '/mnt/nas' });
  root.addEventListener('click', () => loadFiles(''));
  box.appendChild(root);
  if (!path) return;
  let acc = '';
  path.split('/').forEach((part) => {
    acc = acc ? acc + '/' + part : part;
    const here = acc;
    box.appendChild(document.createTextNode(' / '));
    const link = el('a', { text: part });
    link.addEventListener('click', () => loadFiles(here));
    box.appendChild(link);
  });
}

export const files = {
  id: 'archivos',
  admin: false,
  mount(ctx) {
    ctxRef = ctx;
    $('files-job').addEventListener('change', () => loadFiles(''));
    $('files-refresh-size').addEventListener('click', async () => {
      const slug = $('files-job').value;
      if (!slug) return;
      try {
        await ctxRef.api.post('/jobs/' + slug + '/size/refresh');
        toast('Tamaño recalculado', 'ok');
        await ctxRef.refresh(true);
        renderSizeInfo(slug);
      } catch (err) {
        toast('No se pudo medir: ' + err.message, 'err');
      }
    });
  },
  render(ctx) {
    ctxRef = ctx;
    ensureOptions(ctx.state);
    loadFiles('');
  },
};
