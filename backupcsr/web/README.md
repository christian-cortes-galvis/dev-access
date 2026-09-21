# backupcsr/web — portal de administración de copias

Portal web (Bootstrap 5) para administrar el subsistema `backupcsr/` que corre en
**ubuntu-services (192.168.0.49)**. Se sirve en **https://copias.cortexdev.win** (no confundir
con `backups.cortexdev.win`/`pbs`, que es Proxmox Backup Server).

## Qué permite

- **Panel**: app-shell empresarial (barra lateral + topbar) con KPIs (GB almacenados, crecimiento
  7/30 días, jobs OK/fallidos, duración media, NAS libre), gráficos de tendencia y tabla de jobs
  con estado (OK / EN CURSO / TARDE / FALLÓ / NUNCA), tamaño, última y próxima ejecución.
  La tabla **no repite botones por fila**: se selecciona una fila y las acciones (ejecutar real,
  `DRY_RUN`, **reintentar**, log, historial, archivos, horario, habilitar/deshabilitar) se aplican
  desde una única barra superior estilo DataTables *Buttons*, con iconos Font Awesome.
- **Tamaño (GB) por tarea**: recorrido cacheado del destino de cada job en `/mnt/nas`, con
  histórico (`size_snapshots`) para ver crecimiento. `ruta56-bd` excluye `storage` (`size_exclude`
  en `jobs.yml`) para no contar dos veces el árbol compartido con `ruta56-web`.
- **Historial**: corridas con duración, tamaño, archivos transferidos/eliminados, log, detalle y
  **export CSV/JSON** del filtro actual.
- **Archivos**: navegador de `/mnt/nas` por job, con tamaño medido y **gestión** (admin):
  nueva carpeta, renombrar, mover, subir, descargar y eliminar, con confirmación y auditoría.
  Ver [Gestión de archivos](#gestión-de-archivos-pestaña-archivos).
- **Programación**: habilitar, deshabilitar y editar el horario con **presets y previsualización**
  de las próximas 5 ejecuciones; con la gestión activa reescribe `/etc/cron.d/backupcsr`.
- **Usuarios** (admin): alta, rol `admin`/`viewer`, activar/desactivar y reseteo de contraseña;
  cada usuario puede cambiar la suya.
- **Auditoría** (admin): quién ejecutó, editó, deshabilitó o gestionó usuarios y cuándo.
- **Alertas**: banner con jobs fallidos/atrasados, NAS sin montar o por encima del umbral de uso.

## Tema

Bootstrap 5.3 y **Font Awesome 6.5.2** vendoreados en `static/vendor/` (CSS + webfonts), y
**tema claro por defecto** (oscuro con el mismo toggle, persistido en `localStorage['cortexdev-theme']`).
Los gráficos del panel son SVG propios embebidos (`static/js/chart.js`): sin Chart.js, sin CDN ni
build, para que el portal funcione en LAN/Tailscale sin red.

El frontend se sirve **en vivo** desde `backupcsr/web/static` (bind mount de nginx), pero el backend
corre desde `/opt/backupcsr/web`: tras cambiar `app/` hay que **reinstalar** (`install.sh`) y
reiniciar el servicio, o el navegador pedirá endpoints que el backend viejo no tiene (404).

## Zona horaria y datos derivados

Los jobs escriben sus logs con la **hora local del host**, no con `CRON_TZ`. El portal interpreta
esos timestamps en la zona del host y los convierte a `BACKUP_TZ` (por defecto `America/Bogota`)
antes de comparar, así que duraciones, `TARDE` y la alerta de desfase son correctas aunque el host
no esté en `BACKUP_TZ`. Si el host está en UTC verás la advertencia "logs por delante del reloj"
solo cuando el desfase real supere 10 min.

`runs`/`run_files` son datos **derivados** de los logs. Si se corrige la zona horaria con que se
guardaron, hay que regenerarlos (si no, se duplicarían con horas desplazadas):

```bash
cd /opt/backupcsr/web && venv/bin/python -m app.cli resync-runs --dry-run   # ver qué haría
cd /opt/backupcsr/web && venv/bin/python -m app.cli resync-runs             # aplicar
```

Los tamaños (`size_snapshots`) se miden con `snapshot-sizes` o al cerrar cada corrida.

## Arquitectura

```
navegador → nginx (access_nginx :443) → /api/ → 127.0.0.1:8089 (backupcsr-web, systemd, root)
                                                    ├─ MySQL (ubuntu-docker .87, esquema backupcsr)
                                                    ├─ /var/log/backupcsr/*.log[.1|.gz]
                                                    ├─ /etc/cron.d/backupcsr   (solo MANAGE_CRON=1)
                                                    ├─ /opt/backupcsr/jobs/*.sh (flock)
                                                    └─ /mnt/nas (solo lectura)
```

El backend corre **nativo con systemd** (no en contenedor) porque necesita root para leer el NAS
y los logs, y para lanzar los jobs con el mismo `flock` que usa cron. nginx (contenedor con
`network_mode: host`) proxifica `/api/`.

## Requisitos previos

1. **MySQL del docker de ubuntu-docker** publicado en la LAN. Por defecto `mysql_ci` escucha solo
   en `127.0.0.1:3306`; hay que mapearlo a `192.168.0.87:3306:3306` en su compose y recrear el
   contenedor (`docker compose up -d`). Confirmar antes que el contenedor tenga un volumen
   persistente (`docker inspect mysql_ci --format '{{json .Mounts}}'`): si no lo tiene o un
   pipeline de CI lo limpia, usar un MySQL dedicado con volumen propio.
2. **Base y usuario**: ejecutar `sql/bootstrap.sql` como admin de MySQL (cambiar la clave). El
   usuario `backupcsr_web` siempre lleva password fuerte; nunca vacío.
3. **`/etc/backupcsr/web.env`** (0600 root) a partir de `conf/web.env.example`, con `BACKUP_DB_*`,
   `BACKUP_SECRET_KEY` y `BACKUP_MANAGE_CRON`.

## Instalación

```bash
# En ubuntu-services, desde el checkout del repo:
sudo backupcsr/web/install.sh          # venv + deps + systemd + schema + admin
sudo backupcsr/web/install.sh --no-apt # si python3-venv ya está
```

Luego, para publicar la UI:

```bash
docker compose up -d --force-recreate ingress
docker exec access_nginx nginx -t && docker exec access_nginx nginx -s reload
scripts/dns-overrides.sh               # agrega copias.cortexdev.win -> 192.168.0.49
scripts/check.sh
```

Si no defines `BACKUP_ADMIN_PASSWORD`, el instalador genera una y la deja en
`/etc/backupcsr/admin-password` (0600). Para fijarla o cambiarla a mano:

```bash
cd /opt/backupcsr/web && venv/bin/python -m app.cli create-admin --username admin
```

## Fases (gestión de cron)

- **Fase 1** (`BACKUP_MANAGE_CRON=0`, por defecto): el portal observa, ejecuta e historifica; el
  horario se muestra pero no se edita. La vista *Programación* muestra un aviso y el editor abre
  en modo solo lectura (el botón Guardar se deshabilita), en lugar de fallar al guardar.
- **Fase 2**: validar que el render coincide con el archivo actual:
  ```bash
  cd /opt/backupcsr/web && venv/bin/python -m app.cli render-cron   # 0 = coincide
  ```
- **Fase 3** (`BACKUP_MANAGE_CRON=1`): habilitar/deshabilitar/editar pasa a reescribir
  `/etc/cron.d/backupcsr` (backup en `/etc/backupcsr/cron-backups/` fuera de `cron.d`, escritura
  atómica, validación de sintaxis y `systemctl reload cron`). Reiniciar:
  `systemctl restart backupcsr-web`.

`tools/validar-copias.sh` no se modifica y sigue leyendo el cron generado.

## API

Todo bajo `/api/`, con sesión salvo `/api/health` y `/api/auth/login`.

- `GET /api/health`, `GET /api/summary`, `GET /api/jobs`, `GET /api/jobs/{slug}`
- `GET /api/sizes?days=30` (series de tamaño), `POST /api/jobs/{slug}/size/refresh` (admin)
- `POST /api/jobs/{slug}/run` `{dry_run,retry}` (admin), `PATCH /api/jobs/{slug}` (admin),
  `POST /api/jobs/{slug}/reset-schedule` (admin), `GET /api/jobs/{slug}/cron-preview` (admin)
- `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/log`,
  `GET /api/runs/export?format=csv|json` (filtros `job`, `status`, `desde`, `hasta`)
- `GET /api/files`, `GET /api/jobs/{slug}/files`, `GET /api/cron`
- `GET /api/jobs/{slug}/files/entry?path=` (datos para confirmar), `GET /api/jobs/{slug}/files/download?path=`
- `POST /api/jobs/{slug}/files/mkdir|rename|move|delete` (admin)
- `POST /api/jobs/{slug}/files/upload?path=&name=&overwrite=` (admin; el archivo va como **cuerpo en crudo**)
- `GET/POST /api/users`, `PATCH /api/users/{username}`, `POST /api/users/{username}/password`
  (admin), `POST /api/auth/password` (propia)
- `GET /api/audit` (admin)
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`

### Tamaño almacenado

`app/sizes.py` recorre el `dest_rel` de cada job con `os.scandir` (sin seguir symlinks, con tope de
entradas y timeout). El resultado se cachea `BACKUP_SIZE_TTL` y nunca bloquea la petición: si aún
no hay medida, la API responde `pending:true` y un hilo en segundo plano (`warm`) la calcula. El
sondeo guarda un snapshot en `size_snapshots` al cerrar cada corrida y, si falta, uno diario.

### Gestión de archivos (pestaña Archivos)

`app/files.py` resuelve cada ruta **por partes**: el directorio padre debe quedar dentro del ancla
(la raíz del NAS, o el `dest_rel` del job) y el último segmento se trata como hoja **sin seguir
enlaces**, de modo que borrar o renombrar un enlace nunca actúe sobre su destino. Navegar *a
través* de un enlace que sale del ancla (p. ej. `enlace-a-/etc/passwd`) se rechaza con `400`.

Reglas de las operaciones (todas auditadas e invalidando el tamaño medido):

| Regla | Detalle |
|-------|---------|
| Rol | Solo `admin`; un `viewer` ve el listado y puede descargar |
| Job en curso | `409`: si el `flock` del job está tomado, la gestión se bloquea hasta que termine |
| Interruptor | `BACKUP_MANAGE_FILES=0` deshabilita la escritura (el listado queda de solo lectura) |
| Base de datos | Requiere MySQL: la auditoría es obligatoria (`503` si no está) |
| Raíz protegida | No se puede borrar, renombrar ni mover la raíz del ancla ni la del NAS |
| Nombres | Sin `/ \ : * ? " < > \|` ni caracteres de control; no vacíos, sin espacios en los extremos, sin punto final, ni nombres reservados (`CON`, `NUL`, `COM1`…) |
| No pisar | Crear/renombrar/mover/subir falla con `409` si el destino existe (subir admite `overwrite=1`) |
| Borrado | Exige `confirm` igual al nombre; el portal lo pide escrito para carpetas, enlaces y archivos ≥ `BACKUP_FILES_CONFIRM_MB` |
| Subida | Tope `BACKUP_FILES_MAX_UPLOAD_MB`; se escribe en un temporal del mismo directorio y se renombra (atómico). Usa el cuerpo en crudo, así que **no** necesita `python-multipart` |
| Descarga | `FileResponse` en streaming; si el enlace apunta fuera del ancla, `400` |

Variables en `/etc/backupcsr/web.env`:

```ini
BACKUP_MANAGE_FILES=1              # 0 = pestaña Archivos de solo lectura
BACKUP_FILES_MAX_UPLOAD_MB=512     # tope por archivo subido
BACKUP_FILES_CONFIRM_MB=100        # desde este tamaño hay que escribir el nombre para borrar
```

Aviso que se muestra en la propia pestaña: lo que se elimina o cambia es la **copia del NAS**; la
próxima corrida del job volverá a bajar del origen lo que siga existiendo allí. Acciones
registradas en la Auditoría: `file-mkdir`, `file-rename`, `file-move`, `file-delete`,
`file-upload`, `file-download`.

## Degradación

- **Sin MySQL**: el panel y el historial por logs siguen funcionando (solo lectura); editar
  horarios y el detalle de corridas almacenadas responden `503`. Al volver MySQL, el sondeo
  rellena las corridas.
- **Sin NAS**: `/api/jobs/{slug}/files` responde `503`; el resto sigue.
- **Sin cron accesible**: el estado usa el horario del YAML cuando no puede leer el archivo.

## Seguridad

- El servicio escucha solo en `127.0.0.1:8089`; nginx termina TLS con el comodín `*.cortexdev.win`.
- Login con bcrypt y cookie de sesión firmada (`HttpOnly`, `Secure`, `SameSite=Lax`).
- No hay ejecución arbitraria: solo se lanzan slugs del catálogo (`jobs.yml`).
- NAS y logs se confinan con `realpath`; la escritura (crear, renombrar, mover, subir, borrar) es
  solo para `admin`, queda auditada y se bloquea mientras el job corre.
- `backupcsr_web` con password fuerte y `GRANT` limitado a `192.168.0.49`.

## Diagnóstico

```bash
systemctl status backupcsr-web
journalctl -u backupcsr-web -n 100
curl -fsS http://127.0.0.1:8089/api/health | jq
cd /opt/backupcsr/web && venv/bin/python -m app.cli status

# Pruebas de la gestión de archivos (NAS temporal; no toca /mnt/nas, ni MySQL, ni /run/lock):
cd <checkout> && /opt/backupcsr/web/venv/bin/python backupcsr/web/tests/test_files_manage.py
```

### El Panel no lista tareas ("Sin tareas que mostrar")

La tabla **nunca se vacía por un fallo de API**: conserva la última información válida y muestra
un banner con el endpoint que falló (`/api/summary → HTTP 500`, por ejemplo). El mensaje del
centro de la tabla indica el motivo real:

| Mensaje | Significado | Acción |
| --- | --- | --- |
| `Cargando tareas…` | Primera carga en curso | Esperar; si no cambia, mirar el banner |
| `No se pudieron cargar las tareas (…)` | Falló `/api/jobs` o `/api/auth/me` | Ver el banner y pulsar **Reintentar**; `journalctl -u backupcsr-web` |
| `El catálogo no tiene tareas` | `jobs.yml` + `/etc/cron.d/backupcsr` vacíos | Revisar `jobs.yml` y `app.cli sync-jobs` |
| `Sin coincidencias para «X»` | Hay filtro activo | **Quitar filtro** o borrar «Buscar job…» |

Comprobaciones rápidas:

```bash
# ¿El backend desplegado es el actual? (la versión nueva incluye nas_stats)
curl -fsS http://127.0.0.1:8089/api/health | jq                       # sin nas_stats => hay que reinstalar
diff -rq /opt/backupcsr/web/app backupcsr/web/app                     # diferencias => install.sh pendiente
ls -l /run/lock/backupcsr-*.lock                                      # deben ser legibles por el usuario del servicio
```

Desde la consola del navegador: `__backupcsr.state` (jobs, errores de API, filtro activo y
selección) y `__backupcsr.reload()` para recargar sin refrescar la página.

Si el frontend está al día pero el backend no, varios botones fallan por diseño: Usuarios,
Auditoría, Tamaños y «Exportar CSV/JSON» (`/api/runs/export` navega a un 404). Reinstala con
`backupcsr/web/install.sh --no-apt`.

### El buscador se rellena solo con el usuario guardado

Firefox (y a veces Chrome) autocompletan los campos de texto con el usuario de la plataforma
porque la página tiene un modal con contraseñas. Están puestos los dos frenos:

- `autocomplete="off"` (más `name`, `type="search"` y `data-form-type="other"`) en `#global-search`
  y `#jobs-search`, y `autocomplete="off"` en los formularios de filtros. Firefox ignora `off` en
  los campos que cree de login, así que esto solo no basta.
- **`readonly`** en los dos buscadores (atributo en el HTML): los navegadores no rellenan campos de
  solo lectura. Se libera en cuanto hay intención real (`pointerdown`, `touchstart`, `focusin`,
  `keydown`), así que escribir funciona igual.
- Guardia en `shell.js` (`setupFilters`): solo `keydown`, `paste` y `compositionstart` marcan el
  campo como escrito por la persona. El `input` del autofill —llega a veces **después** del clic—
  se descarta y se limpia el valor, de modo que nunca deja la tabla filtrada y vacía. También se
  limpia al enfocar si el valor no lo escribió nadie.

El modal de contraseñas conserva `autocomplete="current-password"` para que el gestor de
contraseñas funcione. Si tras el cambio de código el navegador sigue rellenándolos, recarga con
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>: el atributo `readonly` viaja en `index.html`, que es
lo único que puede quedar en caché.

### Las tareas desaparecen al seleccionar una fila

- Seleccionar **no** cambia de vista ni reconstruye la tabla (solo resalta la fila y habilita la
  barra superior); el log se abre con el botón **Log**.
- El contenedor de la tabla usa `overflow-y: clip` a propósito: si fuera un scrollport vertical,
  al enfocar una fila el navegador podía desplazarlo y dejar la tabla fuera de vista.
- El refresco automático de 30 s no repinta si los datos no cambiaron y se pausa con un modal
  abierto, para no reconstruir la tabla mientras se opera.
