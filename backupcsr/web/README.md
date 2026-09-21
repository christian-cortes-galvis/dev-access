# backupcsr/web — portal de administración de copias

Portal web (Bootstrap 5) para administrar el subsistema `backupcsr/` que corre en
**ubuntu-services (192.168.0.49)**. Se sirve en **https://copias.cortexdev.win** (no confundir
con `backups.cortexdev.win`/`pbs`, que es Proxmox Backup Server).

## Qué permite

- **Panel**: estado por job (OK / EN CURSO / TARDE / FALLÓ / NUNCA), última y próxima ejecución,
  origen/destino, y ejecutar ahora (real o `DRY_RUN`).
- **Historial**: corridas registradas con duración, archivos transferidos/eliminados y log.
- **Archivos**: navegador de solo lectura de `/mnt/nas` por job.
- **Programación**: habilitar, deshabilitar y editar el horario; con la gestión activa reescribe
  `/etc/cron.d/backupcsr` (con backup y validación).

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
  horario se muestra pero no se edita.
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
- `POST /api/jobs/{slug}/run` `{dry_run}` (admin), `PATCH /api/jobs/{slug}` (admin),
  `POST /api/jobs/{slug}/reset-schedule` (admin)
- `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/log`
- `GET /api/files`, `GET /api/jobs/{slug}/files`, `GET /api/cron`
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`

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
- NAS y logs se confinan con `realpath`; la v1 no permite descargar ni borrar desde la UI.
- `backupcsr_web` con password fuerte y `GRANT` limitado a `192.168.0.49`.

## Diagnóstico

```bash
systemctl status backupcsr-web
journalctl -u backupcsr-web -n 100
curl -fsS http://127.0.0.1:8089/api/health | jq
cd /opt/backupcsr/web && venv/bin/python -m app.cli status
```
