/* Vista Archivos: navegador y gestor de /mnt/nas por job.

   Solo lectura para todos; las operaciones de escritura (nueva carpeta, renombrar,
   mover, subir y eliminar) las habilita el servidor para administradores y con el
   job parado. Ver app/files.py y app/api.py. */
import { $, el, fmtBytes, fmtDate, fmtGb, relTime, toast, hideModal, openModal } from '../ui.js';

let ctxRef = null;
let currentPath = '';
let lastData = null;
let busy = false;
let pendingDelete = null;
let promptAction = null;

function state() {
  return ctxRef.state;
}

function isAdmin() {
  return !!(state().user && state().user.role === 'admin');
}

function manageAllowed() {
  return isAdmin() && !!lastData && !!lastData.manage && !lastData.running && !busy;
}

function jobBySlug(slug) {
  return (state().jobs || []).filter((job) => job.slug === slug)[0];
}

function currentSlug() {
  return $('files-job').value;
}

/* ------------------------------- cabecera -------------------------------- */

function ensureOptions(st) {
  const select = $('files-job');
  if (select.options.length === 0) {
    (st.jobs || []).forEach((job) => select.appendChild(el('option', { value: job.slug, text: job.name })));
  }
  if (st.filesJob) {
    select.value = st.filesJob;
    st.filesJob = '';
    currentPath = '';
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

function renderNote() {
  const box = $('files-note');
  const text = $('files-note-text');
  const notes = [];
  if (lastData && lastData.running) {
    notes.push('La tarea de copia está corriendo: la gestión de archivos queda bloqueada ' +
      'hasta que termine.');
  } else if (lastData && !lastData.manage) {
    notes.push('Gestión de archivos deshabilitada (BACKUP_MANAGE_FILES=0): pestaña de solo lectura.');
  } else if (lastData && !isAdmin()) {
    notes.push('Solo un administrador puede crear, renombrar, mover, subir o eliminar.');
  }
  if (lastData && lastData.truncated) {
    notes.push('Esta carpeta tiene más entradas de las que se listan (se muestran las primeras 2000).');
  }
  if (busy) notes.push('Operación en curso…');
  text.innerHTML = '';
  notes.forEach((note, index) => {
    if (index) text.appendChild(el('br'));
    text.appendChild(document.createTextNode(note));
  });
  box.hidden = notes.length === 0;
  const write = manageAllowed();
  $('files-mkdir').disabled = !write;
  $('files-upload').disabled = !write;
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

/* -------------------------------- acciones ------------------------------- */

function actionButton(icon, title, kind, onClick) {
  const button = el('button', { type: 'button', class: 'btn btn-sm btn-outline-' + kind, title: title });
  button.innerHTML = '<i class="fa-solid ' + icon + '"></i>';
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    onClick();
  });
  return button;
}

function actionsCell(entry) {
  const cell = el('td', { class: 'files-actions' });
  cell.addEventListener('click', (event) => event.stopPropagation());
  const canWrite = manageAllowed();
  const add = (icon, title, kind, onClick, needsWrite) => {
    const button = actionButton(icon, title, kind, onClick);
    if (needsWrite && !canWrite) button.disabled = true;
    cell.appendChild(button);
  };
  if (entry.type === 'file') {
    add('fa-download', 'Descargar', 'secondary', () => download(entry), false);
  }
  add('fa-i-cursor', 'Renombrar', 'secondary', () => askRename(entry), true);
  add('fa-arrow-right-arrow-left', 'Mover a otra carpeta', 'secondary', () => askMove(entry), true);
  add('fa-trash', 'Eliminar', 'danger', () => askDelete(entry), true);
  return cell;
}

function download(entry) {
  const slug = currentSlug();
  const link = el('a', {
    href: '/api/jobs/' + encodeURIComponent(slug) + '/files/download?path=' +
      encodeURIComponent(entry.path),
  });
  document.body.appendChild(link);
  link.click();
  link.remove();
  toast('Descargando ' + entry.name + '…', 'info');
}

/* --------------------------- modales de gestión -------------------------- */

function askPrompt(config) {
  $('files-prompt-title').textContent = config.title;
  $('files-prompt-label').textContent = config.label;
  $('files-prompt-context').textContent = config.context || '';
  $('files-prompt-hint').textContent = config.hint || '';
  const input = $('files-prompt-input');
  input.value = config.value || '';
  const ok = $('files-prompt-ok');
  ok.className = 'btn ' + (config.okClass || 'btn-primary');
  ok.innerHTML = '<i class="fa-solid fa-check"></i><span>' + (config.okLabel || 'Guardar') + '</span>';
  promptAction = config.onOk;
  openModal('files-prompt-modal');
  setTimeout(() => { input.focus(); input.select(); }, 200);
}

function askRename(entry) {
  const slug = currentSlug();
  askPrompt({
    title: 'Renombrar',
    context: (entry.type === 'dir' ? 'Carpeta' : (entry.link ? 'Enlace' : 'Archivo')) +
      ': ' + entry.path,
    label: 'Nuevo nombre',
    value: entry.name,
    hint: entry.link
      ? 'Se renombra el enlace, no el archivo al que apunta.'
      : 'No puede llevar / \\ : * ? " < > | ni terminar en punto.',
    okLabel: 'Renombrar',
    onOk: async () => {
      const name = $('files-prompt-input').value.trim();
      if (!name || name === entry.name) { hideModal('files-prompt-modal'); return; }
      hideModal('files-prompt-modal');
      await mutate(async () => {
        await ctxRef.api.post('/jobs/' + slug + '/files/rename', { path: entry.path, name: name });
        return name;
      }, (name) => '«' + entry.name + '» ahora es «' + name + '»');
    },
  });
}

function askMove(entry) {
  const slug = currentSlug();
  askPrompt({
    title: 'Mover',
    context: 'Origen: ' + entry.path,
    label: 'Carpeta destino (relativa a la raíz del job)',
    value: currentPath,
    hint: 'Déjalo vacío para moverlo a la raíz del job. La carpeta debe existir.',
    okLabel: 'Mover',
    onOk: async () => {
      const dest = $('files-prompt-input').value.trim().replace(/^\/+|\/+$/g, '');
      hideModal('files-prompt-modal');
      await mutate(async () => {
        await ctxRef.api.post('/jobs/' + slug + '/files/move', { path: entry.path, dest: dest });
        return dest || '/';
      }, (dest) => '«' + entry.name + '» movido a ' + dest);
    },
  });
}

function askMkdir() {
  const slug = currentSlug();
  askPrompt({
    title: 'Nueva carpeta',
    context: 'Dentro de: ' + (currentPath || '/ (raíz del job)'),
    label: 'Nombre de la carpeta',
    value: '',
    hint: 'No puede llevar / \\ : * ? " < > | ni terminar en punto.',
    okLabel: 'Crear',
    onOk: async () => {
      const name = $('files-prompt-input').value.trim();
      if (!name) { hideModal('files-prompt-modal'); return; }
      hideModal('files-prompt-modal');
      await mutate(async () => {
        await ctxRef.api.post('/jobs/' + slug + '/files/mkdir', { path: currentPath, name: name });
        return name;
      }, (name) => 'Carpeta «' + name + '» creada');
    },
  });
}

async function askDelete(entry) {
  const slug = currentSlug();
  let info = null;
  try {
    const data = await ctxRef.api.get('/jobs/' + slug + '/files/entry?path=' +
      encodeURIComponent(entry.path));
    info = data.entry;
  } catch (err) {
    info = null;
  }
  if (!info) {
    toast('No se pudo leer la entrada: ' + (entry.name), 'err');
    return;
  }
  const limitBytes = (lastData && lastData.confirm_mb ? lastData.confirm_mb : 100) * 1024 * 1024;
  const isDir = info.type === 'dir';
  const needsTyping = isDir || info.type === 'link' || (info.bytes || 0) >= limitBytes;

  const text = $('files-delete-text');
  text.innerHTML = '';
  text.appendChild(el('p', { class: 'mb-1' }, [
    el('span', { class: 'mono', text: info.path }),
  ]));
  text.appendChild(el('p', { class: 'mb-1 small text-body-secondary' }, [
    isDir
      ? 'Carpeta con ' + (info.entries || 0).toLocaleString('es-CO') + ' entradas (' +
        fmtBytes(info.bytes) + (info.partial ? ', recuento parcial' : '') + ').'
      : (info.type === 'link'
        ? 'Enlace simbólico' + (info.target ? ' → ' + info.target : ' (fuera del ancla)') +
          ': se elimina el enlace, no el destino.'
        : 'Archivo de ' + fmtBytes(info.bytes) + '.'),
  ]));
  const warn = $('files-delete-warn');
  warn.hidden = false;
  warn.textContent = 'Se borra de la copia en el NAS. Si el archivo sigue en el origen, ' +
    'la próxima corrida lo volverá a bajar. Queda registrado en la Auditoría.';

  $('files-delete-name').textContent = info.name;
  $('files-delete-confirm-box').hidden = !needsTyping;
  const input = $('files-delete-confirm');
  input.value = '';
  $('files-delete-ok').disabled = needsTyping;
  pendingDelete = { slug: slug, info: info, needsTyping: needsTyping };
  openModal('files-delete-modal');
  if (needsTyping) setTimeout(() => input.focus(), 200);
}

function askUpload() {
  $('files-upload-dest').textContent = currentPath || '/ (raíz del job)';
  $('files-upload-file').value = '';
  $('files-upload-name').value = '';
  $('files-upload-overwrite').checked = false;
  $('files-upload-ok').disabled = true;
  const limit = lastData && lastData.max_upload_mb ? lastData.max_upload_mb : 512;
  $('files-upload-hint').textContent = 'Máximo ' + limit + ' MB por archivo. Se escribe en un ' +
    'temporal y se renombra al terminar.';
  openModal('files-upload-modal');
}

async function submitUpload() {
  const slug = currentSlug();
  const input = $('files-upload-file');
  const file = input.files && input.files[0];
  if (!file) return;
  const name = $('files-upload-name').value.trim() || file.name;
  const overwrite = $('files-upload-overwrite').checked;
  const query = '?path=' + encodeURIComponent(currentPath) + '&name=' + encodeURIComponent(name) +
    '&overwrite=' + (overwrite ? 'true' : 'false');
  const button = $('files-upload-ok');
  button.disabled = true;
  hideModal('files-upload-modal');
  await mutate(async () => {
    const result = await ctxRef.api.upload('/jobs/' + slug + '/files/upload' + query, file);
    return { name: result.name, bytes: result.bytes };
  }, (result) => 'Subido «' + result.name + '» (' + fmtBytes(result.bytes) + ')');
  button.disabled = false;
}

async function mutate(run, message) {
  if (busy) return;
  busy = true;
  renderNote();
  try {
    const result = await run();
    toast(message(result), 'ok');
    await ctxRef.refresh(true);
    await loadFiles(currentPath);
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    busy = false;
    renderNote();
  }
}

/* -------------------------------- listado -------------------------------- */

function renderRows(data) {
  const body = $('files-body');
  body.innerHTML = '';
  const columns = isAdmin() ? 5 : 4;
  if (data.path) {
    const up = el('tr', { class: 'clickable' }, [
      el('td', { colspan: String(columns) }, [el('i', { class: 'fa-solid fa-turn-up me-2' }), '..']),
    ]);
    up.addEventListener('click', () => loadFiles(data.parent));
    body.appendChild(up);
  }
  if (!data.entries.length) {
    body.appendChild(el('tr', {}, [
      el('td', { colspan: String(columns), class: 'empty', text: 'Directorio vacío.' }),
    ]));
    return;
  }
  data.entries.forEach((entry) => {
    const tr = el('tr', entry.type === 'dir' ? { class: 'clickable' } : {});
    tr.appendChild(el('td', {}, [
      el('i', {
        class: 'fa-solid me-2 ' + (entry.type === 'dir'
          ? 'fa-folder text-warning'
          : (entry.link ? 'fa-link text-info' : 'fa-file text-body-secondary')),
      }),
      el('span', { class: 'mono', text: entry.name }),
      entry.link && entry.type === 'dir' ? el('span', { class: 'badge text-bg-light ms-2', text: 'enlace' }) : null,
    ]));
    tr.appendChild(el('td', {
      text: entry.type === 'dir' ? 'carpeta' : (entry.link ? 'enlace' : 'archivo'),
    }));
    tr.appendChild(el('td', { text: entry.type === 'file' || entry.link ? fmtBytes(entry.size) : '—' }));
    tr.appendChild(el('td', { text: fmtDate(entry.mtime) }));
    if (isAdmin()) tr.appendChild(actionsCell(entry));
    if (entry.type === 'dir') tr.addEventListener('click', () => loadFiles(entry.path));
    body.appendChild(tr);
  });
}

async function loadFiles(path, slugOverride) {
  const slug = slugOverride || currentSlug();
  if (!slug) return;
  try {
    const data = await ctxRef.api.get('/jobs/' + slug + '/files?path=' + encodeURIComponent(path || ''));
    currentPath = data.path || '';
    lastData = data;
    $('files-actions-head').hidden = !isAdmin();
    renderBreadcrumb(data.path);
    renderRows(data);
    renderSizeInfo(slug);
    renderNote();
  } catch (err) {
    toast('No se pudo listar los archivos: ' + err.message, 'err');
  }
}

export const files = {
  id: 'archivos',
  admin: false,
  mount(ctx) {
    ctxRef = ctx;
    $('files-job').addEventListener('change', () => {
      currentPath = '';
      loadFiles('');
    });
    $('files-refresh').addEventListener('click', () => loadFiles(currentPath));
    $('files-refresh-size').addEventListener('click', async () => {
      const slug = currentSlug();
      if (!slug) return;
      try {
        await ctxRef.api.post('/jobs/' + slug + '/size/refresh');
        toast('Tamaño recalculado', 'ok');
        await ctxRef.refresh(true);
        renderSizeInfo(slug);
        renderNote();
      } catch (err) {
        toast('No se pudo medir: ' + err.message, 'err');
      }
    });
    $('files-mkdir').addEventListener('click', askMkdir);
    $('files-upload').addEventListener('click', askUpload);
    $('files-upload-file').addEventListener('change', () => {
      const file = $('files-upload-file').files && $('files-upload-file').files[0];
      $('files-upload-name').value = file ? file.name : '';
      $('files-upload-ok').disabled = !file;
    });
    $('files-upload-ok').addEventListener('click', submitUpload);
    $('files-prompt-ok').addEventListener('click', () => {
      const action = promptAction;
      promptAction = null;
      if (action) action();
    });
    $('files-prompt-input').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') $('files-prompt-ok').click();
    });
    $('files-delete-confirm').addEventListener('input', () => {
      const typed = $('files-delete-confirm').value;
      $('files-delete-ok').disabled = !(pendingDelete && typed === pendingDelete.info.name);
    });
    $('files-delete-ok').addEventListener('click', async () => {
      const pending = pendingDelete;
      if (!pending) return;
      const typed = $('files-delete-confirm').value;
      if (pending.needsTyping && typed !== pending.info.name) return;
      pendingDelete = null;
      hideModal('files-delete-modal');
      await mutate(async () => {
        const result = await ctxRef.api.post('/jobs/' + pending.slug + '/files/delete', {
          path: pending.info.path, confirm: pending.info.name,
        });
        return result;
      }, (result) => 'Eliminado «' + pending.info.name + '» (' +
        String(result.entries) + ' entradas, ' + fmtBytes(result.bytes) + ')');
    });
  },
  render(ctx) {
    ctxRef = ctx;
    ensureOptions(ctx.state);
    loadFiles(currentPath);
  },
};
