#!/usr/bin/env bash
# Librería común de los trabajos de copia de seguridad (backupcsr).
# Reemplaza a WinSCP ("synchronize local -mirror") por lftp.
# Cada job espeja el origen remoto DIRECTO a su ruta final en el NAS montado en
# $BACKUPCSR_NAS: no hay staging local ni copia en el disco del equipo.
# Vive en cortexdev-access/backupcsr/lib/common.sh; install.sh la copia a
# /opt/backupcsr/lib/common.sh (modo 0644).
set -euo pipefail

BACKUPCSR_ETC="${BACKUPCSR_ETC:-/etc/backupcsr}"
BACKUPCSR_OPT="${BACKUPCSR_OPT:-/opt/backupcsr}"
BACKUPCSR_LOG="${BACKUPCSR_LOG:-/var/log/backupcsr}"
BACKUPCSR_KEYS="${BACKUPCSR_KEYS:-$BACKUPCSR_ETC/keys}"
BACKUPCSR_NAS="${BACKUPCSR_NAS:-/mnt/nas}"
BACKUPCSR_NAS_ROOT="${BACKUPCSR_NAS_ROOT:-$BACKUPCSR_NAS}"

MIRROR_PARALLEL="${MIRROR_PARALLEL:-2}"
DRY_RUN="${DRY_RUN:-0}"

# --- Presión sobre el anfitrión -------------------------------------------------
# El NAS (CIFS) y la RAM son compartidos con nginx, MySQL, el portal y el stack de
# monitoreo: este host tiene 4 vCPU y ~3,3 GB de RAM con el swap lleno, así que
# lanzar los 6 jobs a la misma hora (:20) bloquea el resto del servidor.
#   MIRROR_GATE  cola global: un solo job de copia a la vez (vacío = sin cola).
#   GATE_WAIT    segundos máximos de espera por el turno antes de fallar claro.
#   JOB_NICE     prioridad de CPU del job y de lftp (hijos heredan).
#   JOB_IONICE_* clase/nivel de I/O de lftp.
#   MIRROR_COMPARE  size = solo nuevos y los que cambiaron de tamaño (por defecto);
#                   size+time = comparación clásica tamaño+fecha.
#   MIRROR_RATE_LIMIT  bytes/s totales por corrida (0 = sin límite).
MIRROR_GATE="${MIRROR_GATE-/run/lock/backupcsr-gate.lock}"
GATE_WAIT="${GATE_WAIT:-1800}"
JOB_NICE="${JOB_NICE:-15}"
JOB_IONICE_CLASS="${JOB_IONICE_CLASS:-2}"
JOB_IONICE_LEVEL="${JOB_IONICE_LEVEL:-7}"
MIRROR_COMPARE="${MIRROR_COMPARE:-size}"
MIRROR_RATE_LIMIT="${MIRROR_RATE_LIMIT:-0}"
MIRROR_MAX_ERRORS="${MIRROR_MAX_ERRORS:-20}"

log() {
	printf '%s [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${JOB:-setup}" "$*"
}

die() {
	log "ERROR: $*"
	exit 1
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || die "falta el comando '$1' en PATH"
}

# Cola global: un solo job de copia a la vez. El lock se libera al salir (fd 8).
# Sin MIRROR_GATE (vacío) no hay cola: cada job corre cuando le toca.
acquire_gate() {
	[ -n "$MIRROR_GATE" ] || return 0
	local start elapsed
	start="$(date +%s)"
	exec 8>"$MIRROR_GATE" || die "no se pudo abrir la cola $MIRROR_GATE"
	if ! flock -w "$GATE_WAIT" 8; then
		die "sin turno tras ${GATE_WAIT}s de espera (otro job tiene la cola $MIRROR_GATE)"
	fi
	elapsed=$(($(date +%s) - start))
	if [ "$elapsed" -gt 2 ]; then
		log "turno conseguido tras esperar ${elapsed}s"
	fi
	return 0
}

# Prepara el log del job y exige el NAS (los jobs escriben solo en /mnt/nas).
# Sin este guard, un NAS desmontado haría que el mirror escribiera en / (disco local).
job_init() {
	JOB="$1"
	mkdir -p "$BACKUPCSR_LOG"
	exec >>"$BACKUPCSR_LOG/$JOB.log" 2>&1
	set -E
	trap 'log "FALLO: exit=$? linea=$LINENO comando=$BASH_COMMAND"' ERR
	# Las copias no deben competir con nginx/MySQL/panel por CPU ni por I/O.
	renice -n "$JOB_NICE" -p $$ >/dev/null 2>&1 || true
	ionice -c "$JOB_IONICE_CLASS" -n "$JOB_IONICE_LEVEL" -p $$ >/dev/null 2>&1 || true
	log "=== inicio $JOB (dry_run=$DRY_RUN nice=$JOB_NICE) ==="
	require_nas
	acquire_gate
}

# Carga /etc/backupcsr/credentials.env (chmod 600, root:root).
load_credentials() {
	local file="$BACKUPCSR_ETC/credentials.env"
	[ -r "$file" ] || die "no se puede leer $file"
	if grep -v '^[[:space:]]*#' "$file" | grep -q 'CAMBIAR'; then
		die "quedan valores sin reemplazar (CAMBIAR) en $file"
	fi
	set -a
	# shellcheck disable=SC1090
	. "$file"
	set +a
}

# El NAS debe estar montado y escribible antes de publicar.
require_nas() {
	mountpoint -q "$BACKUPCSR_NAS" || die "el NAS no está montado en $BACKUPCSR_NAS"
	[ -w "$BACKUPCSR_NAS" ] || die "sin permiso de escritura en $BACKUPCSR_NAS"
}

# Ejecuta un programa de lftp leído por stdin; conserva y devuelve el exit code.
lftp_program() {
	local program
	local rc=0
	program="$(mktemp "${TMPDIR:-/tmp}/backupcsr-lftp.XXXXXX")"
	cat >"$program"
	lftp -f "$program" || rc=$?
	rm -f "$program"
	return "$rc"
}

# Ajustes comunes a los tres protocolos. Se interpolan en el programa de lftp.
lftp_common_settings() {
	cat <<'EOF'
set xfer:clobber on
set mirror:set-permissions false
set mirror:overwrite true
set xfer:use-temp-file true
set xfer:temp-file-name *.lftp
set mirror:skip-noaccess true
EOF
	if [ "$MIRROR_RATE_LIMIT" != "0" ]; then
		printf 'set net:limit-total-rate %s\n' "$MIRROR_RATE_LIMIT"
	fi
}

# Opciones de `mirror` (sin exclusiones) en MIRROR_OPTS.
# MIRROR_COMPARE=size -> --ignore-time: transfiere solo lo nuevo y lo que cambió de
# tamaño. Es lo que evita rebajar cada hora archivos idénticos (el NAS es lento y el
# anfitrión tiene poca RAM). DRY_RUN usa --dry-run de lftp (¡`-n` en mirror es
# --only-newer, no simulación!).
mirror_options() {
	MIRROR_OPTS=(--delete --verbose "--parallel=$MIRROR_PARALLEL" "--max-errors=$MIRROR_MAX_ERRORS")
	if [ "$MIRROR_COMPARE" = "size" ]; then
		MIRROR_OPTS+=(--ignore-time)
	fi
	if [ "$DRY_RUN" = "1" ]; then
		MIRROR_OPTS+=(--dry-run)
	fi
}

# mirror_sftp host port user key remote local [exclusion...]
# Equivale a: "synchronize local -mirror -nopermissions -preservetime <remote> <local>"
mirror_sftp() {
	local host="$1" port="$2" user="$3" key="$4" remote="$5" local_dir="$6"
	shift 6
	local -a excl=()
	local item
	for item in "$@"; do
		excl+=(-x "$item")
	done
	mirror_options
	require_cmd lftp
	[ -r "$key" ] || die "no se puede leer la llave privada $key"
	require_nas
	mkdir -p "$local_dir"
	log "SFTP $user@$host:$port '$remote' -> '$local_dir' (compare=$MIRROR_COMPARE)"
	if ! lftp_program <<EOF
set sftp:connect-program "ssh -a -x -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -i $key"
set net:timeout 20
set net:max-retries 2
set net:reconnect-interval-base 5
set sftp:auto-confirm yes
$(lftp_common_settings)
open -u "$user","" "sftp://$host:$port"
mirror ${MIRROR_OPTS[*]} ${excl[*]:-} "$remote" "$local_dir"
bye
EOF
	then
		log "ERROR: lftp falló para $user@$host:$port '$remote' (llave, host o red; ver líneas anteriores)"
		return 1
	fi
}

# mirror_sftp_pass host port user pass remote local [exclusion...]
# Igual que mirror_sftp pero con autenticación por contraseña (sshpass -e).
mirror_sftp_pass() {
	local host="$1" port="$2" user="$3" pass="$4" remote="$5" local_dir="$6"
	shift 6
	local -a excl=()
	local item
	for item in "$@"; do
		excl+=(-x "$item")
	done
	mirror_options
	require_cmd lftp
	require_cmd sshpass
	require_nas
	mkdir -p "$local_dir"
	log "SFTP(pass) $user@$host:$port '$remote' -> '$local_dir' (compare=$MIRROR_COMPARE)"
	export SSHPASS="$pass"
	if ! lftp_program <<EOF
set sftp:connect-program "sshpass -e ssh -a -x -o BatchMode=no -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=accept-new"
set net:timeout 20
set net:max-retries 2
set net:reconnect-interval-base 5
set sftp:auto-confirm yes
$(lftp_common_settings)
open -u "$user","" "sftp://$host:$port"
mirror ${MIRROR_OPTS[*]} ${excl[*]:-} "$remote" "$local_dir"
bye
EOF
	then
		unset SSHPASS
		log "ERROR: lftp (password) falló para $user@$host:$port '$remote' (contraseña, host o red; ver líneas anteriores)"
		return 1
	fi
	unset SSHPASS
}

# mirror_ftp host user pass remote local [exclusion...]
mirror_ftp() {
	local host="$1" user="$2" pass="$3" remote="$4" local_dir="$5"
	shift 5
	local -a excl=()
	local item
	for item in "$@"; do
		excl+=(-x "$item")
	done
	mirror_options
	require_cmd lftp
	require_nas
	mkdir -p "$local_dir"
	log "FTP $user@$host '$remote' -> '$local_dir' (compare=$MIRROR_COMPARE)"
	# Los servidores FTP usan certificados autofirmados o con CN que no coincide:
	# se acepta el TLS sin verificar en vez de fallar. LFTP_DEBUG=1 añade trazas.
	local debug_opts=""
	if [ "${LFTP_DEBUG:-0}" = "1" ]; then
		debug_opts=$'debug 5\nset net:verbose true'
	fi
	if ! lftp_program <<EOF
set ftp:ssl-force false
set ftp:ssl-protect-data false
set ftp:ssl-allow true
set ssl:verify-certificate no
set ssl:check-hostname no
set ftp:passive-mode on
set net:timeout 30
set net:max-retries 3
$(lftp_common_settings)
${debug_opts:-}
open -u "$user","$pass" "ftp://$host"
mirror ${MIRROR_OPTS[*]} ${excl[*]:-} "$remote" "$local_dir"
bye
EOF
	then
		log "ERROR: lftp falló para $user@$host '$remote' (credenciales, TLS o red; ver líneas anteriores)"
		return 1
	fi
}

# Nota: cada job espeja el origen remoto directo a su ruta final en el NAS mediante
# mirror_* (con --delete); no hay staging local.

