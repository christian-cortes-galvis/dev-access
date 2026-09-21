# backupcsr — copias de seguridad

Subsistema de copias que corre en **ubuntu-services (192.168.0.49)**. Cada job espeja el
origen remoto (FTP o SFTP) **directo a su ruta final en el NAS** montado en `/mnt/nas`
(`//192.168.0.179/Backups`), sin staging local. Reemplaza las tareas de Windows (WinSCP/VBS)
y el cron de `ubuntu-docker`.

> `backups.cortexdev.win` es el Proxmox Backup Server; este subsistema es aparte.

## Estructura

```
lib/common.sh                 # helpers lftp: mirror_ftp, mirror_sftp, mirror_sftp_pass
jobs/*.sh                     # un job por origen (ver horarios abajo)
tools/validar-copias.sh       # validador de solo lectura (frescura de cada job)
tools/diagnostico-copias.sh   # monta el NAS y prueba los FTP
tools/subir-historiasclinicas.sh  # NAS -> VPS Google (manual, rsync)
conf/*.example                # credenciales y fstab de referencia (los reales NO van a git)
cron/backupcsr.cron           # se instala en /etc/cron.d/backupcsr
logrotate/backupcsr           # se instala en /etc/logrotate.d/backupcsr
install.sh                    # instalador idempotente
web/                          # portal web de administración (copias.cortexdev.win)
```

Rutas en runtime: `/opt/backupcsr` (scripts), `/etc/backupcsr` (credenciales y llaves),
`/var/log/backupcsr/*.log`.

## Instalación

En `ubuntu-services`, desde el checkout del repo:

```bash
sudo backupcsr/install.sh            # paquetes, archivos, credenciales, cron, logrotate y NAS
sudo backupcsr/install.sh --no-apt   # si los paquetes ya están
sudo backupcsr/install.sh --no-nas   # sin tocar /etc/fstab
```

Antes de instalar, colocar los secretos (no versionados):

- `backupcsr/conf/credentials.env` y `backupcsr/conf/nas.creds` (0600), copiados de
  `conf/*.example` y sin valores `CAMBIAR`; o directamente en `/etc/backupcsr/`.
- Llaves de `google-bd` y `latino-bd` en `/etc/backupcsr/keys/{google,latino}` (0600, sin
  passphrase). Vienen de los `.ppk`; alternativa: dejar `backupcsr/keys/*.ppk` (ignorado por
  git) y usar `sudo INSTALL_KEYS=1 backupcsr/install.sh`.

## Jobs y horarios

`cron/backupcsr.cron` (hora Bogotá, `CRON_TZ`):

| Job | Origen | Destino NAS |
|-----|--------|-------------|
| `google-bd` | SFTP `GOOGLE_BD_HOST` `/var/www/html/backupsAutomaticos` | `google/backupsAutomaticos` |
| `latino-bd` | SFTP `LATINO_HOST:2200` `/home/chequeos/taskManager/backupsAutomaticos` | `latino/backupsAutomaticos` |
| `ruta56-bd` | FTP `taskManager/ruta56` | `ruta56` (excluye `storage`) |
| `ruta56-web` | FTP `ruta56/storage` | `ruta56/storage/app` |
| `gastro-bd` | FTP `taskManager/gastro` | `gastro` |
| `enter-bd` | FTP `taskManager/pedidos` | `pedidos` |

Los `*-bd` corren cada hora de 6 a 19 con los minutos **escalonados** (`2`, `14`, `26`,
`38`, `50`); los `*-web` 3 veces al día (`20 6,13,19 * * *`). `flock` evita solapes. El mirror
usa `--delete`: si el origen remoto queda incompleto, el destino del NAS refleja ese estado.

`ruta56-bd` y `ruta56-web` comparten `/mnt/nas/ruta56`; por eso `ruta56-bd` excluye `storage`
para no borrar lo que publica `ruta56-web`.

### Tareas deshabilitadas

Quedaron fuera de la migración y están **registradas, deshabilitadas, en el catálogo**
(`web/jobs.yml`) para no perderlas: no tienen script en `/opt/backupcsr/jobs`, así que no
entran al cron, ni al validador, ni se miden en el panel (y el portal no avisa por ellas).

| Tarea | Origen | Destino | Por qué quedó fuera |
|-------|--------|---------|---------------------|
| `google-web` | SFTP `GOOGLE_WEB_HOST` `/var/www/html/historiasclinicas/files` | `files` (provisional) | Publicaba a OneDrive (vetado) |
| `latino-web` | SFTP `LATINO_HOST:2200`, ruta por confirmar | por confirmar | Publicaba a OneDrive (vetado) |
| `ticware-bd` | FTP `TICWARE_HOST`, ruta por confirmar | por confirmar | Ticware no debe llenar el NAS |
| `ticware-web` | FTP `TICWARE_HOST`, ruta por confirmar | por confirmar | Ticware no debe llenar el NAS |

`borrar_lista.sh` (limpieza destructiva con rutas del VPS) tampoco se registró: no es una copia.

Para habilitar una: escribir `jobs/<slug>.sh` (usar `lib/common.sh` como los demás), ajustar
`source`/`dest_rel` en `web/jobs.yml`, reinstalar (`sudo install -m 0755 jobs/<slug>.sh
/opt/backupcsr/jobs/`) y habilitarla en el panel. El portal **rechaza habilitarla si falta el
script** (`409`), para que no quede un horario apuntando a un archivo inexistente. Ojo con
`google-web`: con `--delete` sobre `/mnt/nas/files` borraría del NAS lo que aún no esté en el
VPS; revisar ese destino antes de activarla.

## Validación

```bash
sudo validar-copias              # informe completo
sudo validar-copias --quiet      # solo problemas (útil en cron/monitoreo)
sudo validar-copias --grace 120  # tolerancia para jobs en curso
```

Salida: `0` = todo OK, `1` = advertencias, `2` = errores. Revisa cron, credenciales, llaves,
NAS y la frescura de cada job (leyendo `/etc/cron.d/backupcsr`).

| Estado | Significado |
|--------|-------------|
| `OK` | Cerró con `=== fin <job> ===` después de su última ejecución esperada |
| `EN_CURSO` | Empezó y aún no cierra, dentro de la gracia |
| `TARDE` | Cerró bien pero antes de la última ejecución esperada (revisar horario/zona) |
| `NUNCA` | No existe el log del job |
| `FALLO` | Terminó en `FALLO:` o quedó a medias pasada la gracia |
| `DESCONOCIDO` | No se pudo interpretar el log |

## Cuándo compite con el servidor (RAM, NAS, CPU)

Síntoma: durante las copias el servidor se siente bloqueado (panel lento, SSH que no
responde). Medido en `ubuntu-services`: 4 vCPU, ~3,3 GB de RAM, `SwapFree` en 84 kB,
`Committed_AS` 6,7 GB contra un `CommitLimit` de 2,8 GB y load 15 con los 6 jobs de las `:20`
corriendo a la vez. No es un problema de CPU de las copias (son I/O), es **memoria**: el
recorrido y la escritura del NAS (CIFS) llenan la caché, el kernel tiene que reclamar y
manda al swap a todo lo demás (nginx, MySQL, panel, agentes).

Lo que ya hace el repo:

| Medida | Dónde | Efecto |
|--------|-------|--------|
| `--ignore-time` (`MIRROR_COMPARE=size`) | `lib/common.sh` | Transfiere solo lo nuevo y lo que cambió de tamaño: se acabaron las rebajas de miles de archivos idénticos cada hora |
| `mirror:overwrite` + `xfer:use-temp-file` | `lib/common.sh` | Reemplaza el archivo sin borrarlo antes; la escritura es temporal+rename (atómica) |
| Cola global (`MIRROR_GATE`) | `lib/common.sh` | Un solo job de copia a la vez; los demás esperan turno (máx. `GATE_WAIT`, 1800 s) |
| `nice`/`ionice` (`JOB_NICE=15`, clase 2 prio 7) | `lib/common.sh` | Las copias ceden CPU e I/O al resto de servicios |
| Minutos escalonados | `cron/backupcsr.cron`, `jobs.yml` | Los 6 jobs ya no arrancan en el mismo minuto |
| No medir tamaños mientras el job corre | `web/app/sizes.py` | El portal no recorre con `du` un árbol que se está escribiendo (`force=True` —refresco manual— sí lo hace) |
| Tope de memoria por contenedor | `docker-compose.yml` | nginx 96 MB, portal-api 192 MB, prometheus/grafana 384 MB |

Ajustes por job (se ponen antes del `source` de la librería en `jobs/*.sh` o en
`/etc/backupcsr/credentials.env`): `MIRROR_PARALLEL`, `MIRROR_COMPARE`, `MIRROR_GATE` (vacío =
sin cola), `GATE_WAIT`, `JOB_NICE`, `MIRROR_RATE_LIMIT` (p. ej. `5M`).

Recomendaciones de anfitrión (fuera del repo):

1. Dar aire al swap: `zram` o un swapfile extra. Con 3,3 GB y esta pila de servicios, 1 GB de
   swap no alcanza; `Committed_AS` ya supera el `CommitLimit`.
2. Mover fuera de este servidor las sesiones interactivas (VS Code/agentes): entre sus procesos
   sumaban ~1 GB de RSS y ~450 MB de swap.
3. Reducir el trabajo en el NAS: con los dumps diarios, los `*-bd` pueden pasar a
   `6-19/2` (cada 2 h) o a horas fijas; el `--ignore-time` ya baja el volumen por corrida.
4. Opcional, en el montaje CIFS: bajar `rsize/wsize` de 4M a 1M en
   `conf/fstab.backupcsr.example` (menos memoria en vuelo por operación).

Prueba en seco (no descarga ni sube nada — `DRY_RUN=1` usa `--dry-run` de lftp; ojo: `-n` en
`mirror` es `--only-newer`, no simulación) y diagnóstico:

```bash
sudo DRY_RUN=1 /opt/backupcsr/jobs/ruta56-bd.sh
tail -n 50 /var/log/backupcsr/ruta56-bd.log
sudo LFTP_DEBUG=1 DRY_RUN=1 /opt/backupcsr/jobs/ruta56-bd.sh   # detalle de la conexión
sudo bash backupcsr/tools/diagnostico-copias.sh                # NAS + los tres FTP
sudo journalctl -u cron --since today | grep backupcsr
free -m; cat /proc/loadavg; grep -E "SwapFree|Committed_AS|CommitLimit" /proc/meminfo
```

Aplicar estos cambios en el servidor (los jobs viven en `/opt`, no en el repo):

```bash
sudo backupcsr/install.sh --no-apt                     # lib/ + jobs/ + tools/ a /opt
sudo install -m 0644 backupcsr/cron/backupcsr.cron /etc/cron.d/backupcsr   # minutos escalonados
sudo docker compose up -d                              # topes de memoria de los contenedores
sudo DRY_RUN=1 /opt/backupcsr/jobs/enter-bd.sh && tail -n 5 /var/log/backupcsr/enter-bd.log
sudo /opt/backupcsr/jobs/enter-bd.sh && grep -c "Transferring file" /var/log/backupcsr/enter-bd.log
```

Si el portal tiene `BACKUP_MANAGE_CRON=1`, el horario efectivo sale de la tabla `jobs`: cambia
los minutos en el panel de Programación (o en la BD) para que el escalonado no se pierda al
reescribir el cron. La cola global de `lib/common.sh` protege en cualquier caso.

## Subida puntual al VPS (`subir-historiasclinicas`)

`tools/subir-historiasclinicas.sh` sube `/mnt/nas/files` a
`/var/www/html/historiasclinicas/files` del VPS Google con `rsync` sobre SSH (aditivo, sin
`--delete`, reanudable). Es manual, no está en cron:

```bash
sudo DRY_RUN=1 subir-historiasclinicas            # o tools/subir-historiasclinicas.sh
sudo subir-historiasclinicas
```

Variables: `DRY_RUN`, `ONLY_MISSING` (por defecto 1), `COUNT_FILES`, `RSYNC_VERBOSE`,
`SKIP_PREFLIGHT`, `SRC_DIR`, `DST_DIR`. Log en `/var/log/backupcsr/subir-historiasclinicas.log`.

## Portal web (web/)

Interfaz de administración en **https://copias.cortexdev.win** (no es `backups.cortexdev.win`,
que es PBS): estado de los jobs, ejecución manual (real o `DRY_RUN`), historial de corridas con
archivos, navegador y **gestión de `/mnt/nas`** (nueva carpeta, renombrar, mover, subir, descargar
y eliminar; solo admin, auditado y bloqueado mientras el job corre) y, opcionalmente, edición del
horario.

```bash
sudo backupcsr/web/install.sh     # venv + deps + systemd (backupcsr-web) + schema + admin
sudo BACKUP_MANAGE_CRON=1 ...     # fase 2: el portal reescribe /etc/cron.d/backupcsr
```

Detalle (requisitos de MySQL, fases, API, seguridad y diagnóstico) en
[`web/README.md`](web/README.md). El backend corre nativo por systemd (127.0.0.1:8089) y usa el
mismo `flock` que cron; `validar-copias.sh` no cambia.

## Monitoreo continuo

```cron
30 8 * * *  root  /opt/backupcsr/tools/validar-copias.sh --quiet || echo "backupcsr: revisar" | mail -s "backupcsr" tu@correo
```

## Corte desde ubuntu-docker

Nunca deben correr los dos hosts a la vez (ambos espejan con `--delete` al mismo destino).
Tras validar en `ubuntu-services`:

```bash
sudo mv /etc/cron.d/backupcsr /etc/cron.d/backupcsr.disabled
sudo systemctl reload cron
```

## Secretos

`conf/credentials.env`, `conf/nas.creds` y las llaves están en `.gitignore`: **nunca** se
versionan (solo los `.example`). El repo debe ser privado.
