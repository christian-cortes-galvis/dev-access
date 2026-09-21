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

Los `*-bd` corren cada hora de 6 a 19 (`20 6-19 * * *`); los `*-web` 3 veces al día
(`20 6,13,19 * * *`). `flock` evita solapes. El mirror usa `--delete`: si el origen remoto
queda incompleto, el destino del NAS refleja ese estado.

`ruta56-bd` y `ruta56-web` comparten `/mnt/nas/ruta56`; por eso `ruta56-bd` excluye `storage`
para no borrar lo que publica `ruta56-web`.

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

Prueba en seco (no descarga ni sube nada) y diagnóstico:

```bash
sudo DRY_RUN=1 /opt/backupcsr/jobs/ruta56-bd.sh
tail -n 50 /var/log/backupcsr/ruta56-bd.log
sudo LFTP_DEBUG=1 DRY_RUN=1 /opt/backupcsr/jobs/ruta56-bd.sh   # detalle de la conexión
sudo bash backupcsr/tools/diagnostico-copias.sh                # NAS + los tres FTP
sudo journalctl -u cron --since today | grep backupcsr
```

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
archivos, navegador de solo lectura de `/mnt/nas` y, opcionalmente, edición del horario.

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
