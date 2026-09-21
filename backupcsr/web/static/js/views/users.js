/* Vista Usuarios: alta, rol, activación y reseteo de contraseña. */
import { $, el, fmtDate, toast, confirmDialog } from '../ui.js';

let ctxRef = null;

async function load() {
  try {
    const data = await ctxRef.api.get('/users');
    const body = $('users-body');
    body.innerHTML = '';
    data.users.forEach((user) => {
      const roleSelect = el('select', { class: 'form-select form-select-sm', style: 'max-width:120px' });
      ['viewer', 'admin'].forEach((role) => roleSelect.appendChild(el('option', {
        value: role, text: role, selected: user.role === role ? 'selected' : null,
      })));
      roleSelect.addEventListener('change', () => update(user.username, { role: roleSelect.value }));

      const actions = el('td', { class: 'text-nowrap' });
      actions.appendChild(el('button', {
        type: 'button', class: 'btn btn-sm btn-outline-secondary me-1',
        html: '<i class="fa-solid fa-key"></i><span>Contraseña</span>',
        onclick: () => ctxRef.openPassword(user.username, false),
      }));
      actions.appendChild(el('button', {
        type: 'button',
        class: 'btn btn-sm btn-outline-' + (user.active ? 'warning' : 'success'),
        html: '<i class="fa-solid ' + (user.active ? 'fa-user-slash' : 'fa-user-check') +
          '"></i><span>' + (user.active ? 'Desactivar' : 'Activar') + '</span>',
        onclick: () => confirmDialog(
          user.active ? 'Desactivar usuario' : 'Activar usuario',
          user.active ? 'Se bloqueará el acceso de "' + user.username + '".' : 'Se restaurará el acceso de "' + user.username + '".',
          () => update(user.username, { active: !user.active }),
          user.active ? 'Desactivar' : 'Activar',
          user.active ? 'btn-warning' : 'btn-success'
        ),
      }));

      body.appendChild(el('tr', {}, [
        el('td', { class: 'mono', text: user.username }),
        el('td', {}, [roleSelect]),
        el('td', {}, [el('span', {
          class: 'badge rounded-pill ' + (user.active ? 'pill-ok' : 'pill-unknown'),
          text: user.active ? 'activo' : 'inactivo',
        })]),
        el('td', { text: fmtDate(user.created_at) }),
        actions,
      ]));
    });
  } catch (err) {
    toast('No se pudieron cargar los usuarios: ' + err.message, 'err');
    const body = $('users-body');
    if (body) {
      body.innerHTML = '';
      body.appendChild(el('tr', {}, [el('td', {
        colspan: '5', class: 'empty',
        text: 'No se pudieron cargar los usuarios: ' + err.message,
      })]));
    }
  }
}

async function update(username, patch) {
  try {
    await ctxRef.api.patch('/users/' + encodeURIComponent(username), patch);
    toast('Usuario actualizado', 'ok');
    await load();
  } catch (err) {
    toast('Error: ' + err.message, 'err');
    await load();
  }
}

export const users = {
  id: 'usuarios',
  admin: true,
  mount(ctx) {
    ctxRef = ctx;
    $('user-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        await ctxRef.api.post('/users', {
          username: $('user-new-name').value.trim(),
          password: $('user-new-pass').value,
          role: $('user-new-role').value,
        });
        $('user-new-name').value = '';
        $('user-new-pass').value = '';
        toast('Usuario creado', 'ok');
        await load();
      } catch (err) {
        toast('Error: ' + err.message, 'err');
      }
    });
  },
  render(ctx) {
    ctxRef = ctx;
    load();
  },
};
