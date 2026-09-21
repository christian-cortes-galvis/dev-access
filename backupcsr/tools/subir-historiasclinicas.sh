#!/usr/bin/env bash
# Subida puntual NAS -> VPS Google: /mnt/nas/files -> /var/www/html/historiasclinicas/files
# Inversa de google-web. rsync sobre SSH con llave, sin borrados en el VPS.
#
# Muestra en consola, en vivo, el progreso y (opcionalmente) los archivos que sube;
# además lo guarda en /var/log/backupcsr/subir-historiasclinicas.log.
#
# Nota: rsync arma la lista de archivos al iniciar. Los archivos creados en el NAS
# después de esa lista no entran en esta pasada (se suben en la siguiente ejecución), y
# los que aún se están escribiendo pueden copiarse incompletos. Conviene ejecutar cuando
# termine la carga local al NAS, o volver a ejecutar al finalizar.
#
# Uso:
#   sudo tools/subir-historiasclinicas.sh                  # sube solo lo que falta
#   sudo DRY_RUN=1 tools/subir-historiasclinicas.sh        # solo lista lo que subiría
#   sudo COUNT_FILES=1 tools/subir-historiasclinicas.sh    # incluye conteo total (lento)
#   sudo RSYNC_VERBOSE=1 tools/subir-historiasclinicas.sh  # lista cada archivo subido
#
# Por defecto usa --ignore-existing: sube solo los archivos que NO existen en el destino,
# saltando los existentes (no compara tamaño/fecha ni los vuelve a subir).
# Con ONLY_MISSING=0 usa el modo normal: compara tamaño/fecha y actualiza los que difieran.
#
# Antes de enumerar/subir valida el origen (NAS) y el destino (conexión SSH + permiso de
# escritura); si algo falla, aborta en segundos con un error claro.
#
# Las transferencias parciales van a .rsync-partial/ del destino: si se corta, vuelve a
# ejecutar el mismo comando y reanuda donde quedó.
#
# Variables opcionales: SRC_DIR, DST_DIR, ALLOW_EMPTY, ONLY_MISSING (0 = comparar y
#                       actualizar; por defecto solo lo que falta), COUNT_FILES
#                       (1 = contar archivos; por defecto no cuenta), SKIP_PREFLIGHT
#                       (1 = omitir el preflight), RSYNC_VERBOSE (1 = listar cada archivo;
#                       por defecto solo progreso global), BACKUPCSR_LIB
#
# Volumen grande (p. ej. 51k archivos / 170 GB): ejecutar dentro de tmux (tarda horas) y
# verificar antes el espacio libre en el VPS con `df -h /var/www/html`.
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

JOB="subir-historiasclinicas"
mkdir -p "$BACKUPCSR_LOG"
LOG_FILE="$BACKUPCSR_LOG/$JOB.log"

# log(): escribe en consola y en el log a la vez (reemplaza el log() de common.sh,
# que solo redirigía a archivo). Así el operador ve el avance mientras se ejecuta.
log() {
	local line
	line="$(printf '%s [%s] %s' "$(date '+%Y-%m-%d %H:%M:%S')" "$JOB" "$*")"
	printf '%s\n' "$line"
	printf '%s\n' "$line" >>"$LOG_FILE"
}

# preflight_dest host port user key dst
# Comprueba en segundos conexión SSH, autenticación y permiso de escritura en el destino,
# antes de la enumeración/transferencia (que puede tardar). Crea y borra una carpeta
# temporal: no cambia permisos ni deja residuos.
preflight_dest() {
	local host="$1" port="$2" user="$3" key="$4" dst="$5"
	log "comprobando destino SSH $user@$host:$port (conexión + escritura) ..."
	if ! ssh -p "$port" -i "$key" \
		-o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes \
		-o StrictHostKeyChecking=accept-new \
		"$user@$host" sh -s -- "$dst" <<'REMOTE'
set -e
dst="$1"
parent="$(dirname "$dst")"
if [ -d "$dst" ]; then dir="$dst"; else dir="$parent"; fi
tmp=".__backupcsr_preflight__.$(date +%s).$$"
mkdir "$dir/$tmp"
rmdir "$dir/$tmp"
REMOTE
	then
		die "no se pudo conectar/escribir en el VPS $user@$host:$port ($dst). Revisar red/firewall, llave $key, usuario/host/puerto y permisos de escritura."
	fi
	log "destino OK: conexión SSH y escritura en $user@$host:$port ($dst)"
}

set -E
trap 'log "FALLO: exit=$? linea=$LINENO comando=$BASH_COMMAND"' ERR
log "=== inicio $JOB (dry_run=$DRY_RUN) ==="
log "verificando NAS en $BACKUPCSR_NAS (puede tardar si aún no estaba montado) ..."
require_nas
log "NAS montado y escribible"

load_credentials

G_HOST="$GOOGLE_WEB_HOST"
G_PORT="${GOOGLE_WEB_PORT:-22}"
G_USER="$GOOGLE_WEB_USER"
G_KEY="$BACKUPCSR_KEYS/google"
SRC_DIR="${SRC_DIR:-$BACKUPCSR_NAS/files}"
DST_DIR="${DST_DIR:-/var/www/html/historiasclinicas/files}"

log "comprobando origen $SRC_DIR ..."
[ -d "$SRC_DIR" ] || die "no existe el origen $SRC_DIR (¿NAS montado?)"
[ -r "$SRC_DIR" ] || die "sin permiso de lectura en el origen $SRC_DIR"
[ -x "$SRC_DIR" ] || die "sin permiso de acceso (x) al origen $SRC_DIR"
if [ -z "$(ls -A "$SRC_DIR")" ] && [ "${ALLOW_EMPTY:-0}" != "1" ]; then
	die "el origen $SRC_DIR está vacío; abortado (usa ALLOW_EMPTY=1 para forzar)"
fi
log "origen OK: $SRC_DIR"

[ -r "$G_KEY" ] || die "no se puede leer la llave $G_KEY"
require_cmd rsync
require_cmd ssh

log "destino: $G_USER@$G_HOST:$G_PORT '$DST_DIR'"
if [ "$DRY_RUN" = "1" ]; then
	log "modo DRY_RUN: no se sube nada, solo se listan los archivos"
fi
if [ "${SKIP_PREFLIGHT:-0}" = "1" ]; then
	log "preflight omitido (SKIP_PREFLIGHT=1)"
else
	preflight_dest "$G_HOST" "$G_PORT" "$G_USER" "$G_KEY" "$DST_DIR"
fi

if [ "${COUNT_FILES:-0}" = "1" ]; then
	log "contando archivos en $SRC_DIR (recorre el NAS completo; puede tardar) ..."
	N_FILES="$(find "$SRC_DIR" -type f 2>/dev/null | wc -l)"
	log "origen : $SRC_DIR ($N_FILES archivos)"
else
	log "origen : $SRC_DIR (conteo omitido; usa COUNT_FILES=1 para contarlos)"
fi

RSYNC_SSH="ssh -i $G_KEY -p $G_PORT -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=6"

# -r recursivo; -t conserva fechas; --no-perms NO toca permisos/owner en el VPS.
# --partial-dir guarda lo transferido a medias para poder reanudar sin dejar basura.
RSYNC_OPTS=(-rt --no-perms --human-readable --stats --partial-dir=.rsync-partial)
if [ "${RSYNC_VERBOSE:-0}" = "1" ]; then
	RSYNC_OPTS+=(--info=progress2 --info=name)
else
	RSYNC_OPTS+=(--info=progress2)
fi
if [ "${ONLY_MISSING:-1}" = "1" ]; then
	RSYNC_OPTS+=(--ignore-existing)
	log "modo: subir solo lo que falta en el destino (--ignore-existing)"
else
	log "modo: comparar tamaño/fecha y actualizar lo que difiera (ONLY_MISSING=0)"
fi
if [ "$DRY_RUN" = "1" ]; then
	RSYNC_OPTS+=(--dry-run)
fi

START_TS="$(date +%s)"
log "SUBIDA $G_USER@$G_HOST:$G_PORT '$SRC_DIR/' -> '$DST_DIR/' (dry_run=$DRY_RUN)"
# $SRC_DIR/ copia el CONTENIDO (recursivo, con subcarpetas) dentro de $DST_DIR/,
# sin nivel extra: /mnt/nas/files/* -> /var/www/html/historiasclinicas/files/*.
# La salida se muestra en vivo y se agrega al log.
if ! rsync "${RSYNC_OPTS[@]}" -e "$RSYNC_SSH" "$SRC_DIR/" "$G_USER@$G_HOST:$DST_DIR/" 2>&1 | tee -a "$LOG_FILE"; then
	die "rsync falló subiendo '$SRC_DIR' -> $G_USER@$G_HOST:$G_PORT '$DST_DIR' (llave, permiso de escritura o red; ver líneas anteriores)"
fi

ELAPSED=$(( $(date +%s) - START_TS ))
log "=== fin $JOB (${ELAPSED}s) ==="
