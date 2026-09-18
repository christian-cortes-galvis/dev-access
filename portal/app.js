(function () {
  'use strict';

  function initials(text) {
    var words = text.trim().split(/\s+/).filter(function (w) { return w.length > 2; });
    if (words.length === 0) words = text.trim().split(/\s+/);
    if (words.length === 1) {
      return words[0].replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase();
    }
    return words.slice(0, 2).map(function (w) { return w.charAt(0); }).join('').toUpperCase();
  }

  function badge(text, color) {
    var el = document.createElement('span');
    el.className = 'app-badge';
    el.style.setProperty('--c', color || '#334155');
    el.textContent = initials(text);
    return el;
  }

  function techImg(name, cls, title) {
    var img = document.createElement('img');
    img.src = '/icons/' + name + '.svg';
    img.alt = title || name;
    img.title = title || name;
    img.className = cls;
    img.loading = 'lazy';
    return img;
  }

  function appImg(file, label, color) {
    var img = document.createElement('img');
    img.className = 'app-icon';
    img.src = '/favicons/' + file;
    img.alt = label;
    img.title = label;
    img.loading = 'lazy';
    img.onerror = function () {
      var b = badge(label, color);
      if (this.parentNode) this.parentNode.replaceChild(b, this);
    };
    return img;
  }

  var names = {
    laravel: 'Laravel', codeigniter: 'CodeIgniter', php: 'PHP', angular: 'Angular',
    react: 'React', python: 'Python', mysql: 'MySQL', docker: 'Docker',
    proxmox: 'Proxmox', pihole: 'Pi-hole', netdata: 'Netdata', nginx: 'Nginx',
    portainer: 'Portainer', phpmyadmin: 'phpMyAdmin', powerbi: 'Power BI',
    'uptime-kuma': 'Uptime Kuma', certificate: 'Certificado local',
    server: 'Infraestructura', linux: 'Linux'
  };

  var SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function renderToggle(btn, theme) {
    var goingLight = theme !== 'light';
    btn.innerHTML = goingLight ? SUN : MOON;
    btn.setAttribute('aria-label', goingLight ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro');
    btn.setAttribute('aria-pressed', theme === 'light' ? 'true' : 'false');
    btn.title = btn.getAttribute('aria-label');
  }

  /* Etiquetas para el layout tipo tarjeta en movil (se repite tras cada render) */
  function addTableLabels() {
    document.querySelectorAll('table.links').forEach(function (table) {
      var ths = Array.prototype.map.call(table.querySelectorAll('thead th'), function (th) {
        return th.textContent.trim();
      });
      table.querySelectorAll('tbody tr').forEach(function (tr) {
        Array.prototype.forEach.call(tr.children, function (td, i) {
          if (ths[i]) td.setAttribute('data-th', ths[i]);
        });
      });
    });
  }

  function addCardIcons() {
    document.querySelectorAll('.card[data-tech]').forEach(function (card) {
      if (card.querySelector('.card-icons')) return;
      var box = document.createElement('div');
      box.className = 'card-icons';
      card.dataset.tech.split(',').forEach(function (t) {
        t = t.trim();
        if (t) box.appendChild(techImg(t, 'card-icon', names[t] || t));
      });
      card.insertBefore(box, card.firstChild);
    });
  }

  function addNameIcons() {
    document.querySelectorAll('td.name[data-tech]').forEach(function (td) {
      if (td.dataset.icons === 'done') return;
      td.dataset.icons = 'done';

      var label = td.dataset.label || td.textContent;
      var noBadge = td.dataset.badge === 'off';

      if (!noBadge && !td.querySelector('.app-badge, .app-icon')) {
        td.insertBefore(
          td.dataset.app ? appImg(td.dataset.app, label, td.dataset.color)
                         : badge(label, td.dataset.color),
          td.firstChild
        );
      }

      td.dataset.tech.split(',').forEach(function (t) {
        t = t.trim();
        if (!t) return;
        var img = techImg(t, noBadge ? 'tech-lg' : 'tech', names[t] || t);
        if (noBadge) {
          td.insertBefore(img, td.firstChild);
        } else {
          td.appendChild(img);
        }
      });
    });
  }

  function addThemeToggle() {
    var header = document.querySelector('header.top');
    if (!header || header.querySelector('.theme-toggle')) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'theme-toggle';
    renderToggle(btn, currentTheme());
    btn.addEventListener('click', function () {
      var next = currentTheme() === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('cortexdev-theme', next); } catch (e) {}
      renderToggle(btn, next);
    });
    header.appendChild(btn);
  }

  function enhance() {
    addTableLabels();
    addCardIcons();
    addNameIcons();
    addThemeToggle();
  }

  document.addEventListener('portal:rendered', enhance);
  enhance();
})();
