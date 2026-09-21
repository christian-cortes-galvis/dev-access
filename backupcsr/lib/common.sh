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

# Prepara el log del job y exige el NAS (los jobs escriben solo en /mnt/nas).
# Sin este guard, un NAS desmontado haría que el mirror escribiera en / (disco local).
job_init() {
	JOB="$1"
	mkdir -p "$BACKUPCSR_LOG"
	exec >>"$BACKUPCSR_LOG/$JOB.log" 2>&1
	set -E
	trap 'log "FALLO: exit=$? linea=$LINENO comando=$BASH_COMMAND"' ERR
	log "=== inicio $JOB (dry_run=$DRY_RUN) ==="
	require_nas
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

# mirror_sftp host port user key remote local [exclusion...]
# Equivale a: "synchronize local -mirror -nopermissions -preservetime <remote> <local>"
mirror_sftp() {
	local host="$1" port="$2" user="$3" key="$4" remote="$5" local_dir="$6"
	shift 6
	local -a excl=() mirror_opts=(--delete --verbose "--parallel=$MIRROR_PARALLEL")
	local item
	for item in "$@"; do
		excl+=(-x "$item")
	done
	if [ "$DRY_RUN" = "1" ]; then
		mirror_opts+=(-n)
	fi
	require_cmd lftp
	[ -r "$key" ] || die "no se puede leer la llave privada $key"
	require_nas
	mkdir -p "$local_dir"
	log "SFTP $user@$host:$port '$remote' -> '$local_dir'"
	if ! lftp_program <<EOF
set sftp:connect-program "ssh -a -x -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -i $key"
set net:timeout 20
set net:max-retries 2
set net:reconnect-interval-base 5
set sftp:auto-confirm yes
set xfer:clobber on
set mirror:set-permissions false
open -u "$user","" "sftp://$host:$port"
mirror ${mirror_opts[*]} ${excl[*]:-} "$remote" "$local_dir"
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
	local -a excl=() mirror_opts=(--delete --verbose "--parallel=$MIRROR_PARALLEL")
	local item
	for item in "$@"; do
		excl+=(-x "$item")
	done
	if [ "$DRY_RUN" = "1" ]; then
		mirror_opts+=(-n)
	fi
	require_cmd lftp
	require_cmd sshpass
	require_nas
	mkdir -p "$local_dir"
	log "SFTP(pass) $user@$host:$port '$remote' -> '$local_dir'"
	export SSHPASS="$pass"
	if ! lftp_program <<EOF
set sftp:connect-program "sshpass -e ssh -a -x -o BatchMode=no -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=accept-new"
set net:timeout 20
set net:max-retries 2
set net:reconnect-interval-base 5
set sftp:auto-confirm yes
set xfer:clobber on
set mirror:set-permissions false
open -u "$user","" "sftp://$host:$port"
mirror ${mirror_opts[*]} ${excl[*]:-} "$remote" "$local_dir"
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
	local -a excl=() mirror_opts=(--delete --verbose "--parallel=$MIRROR_PARALLEL")
	local item
	for item in "$@"; do
		excl+=(-x "$item")
	done
	if [ "$DRY_RUN" = "1" ]; then
		mirror_opts+=(-n)
	fi
	require_cmd lftp
	require_nas
	mkdir -p "$local_dir"
	log "FTP $user@$host '$remote' -> '$local_dir'"
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
set xfer:clobber on
set mirror:set-permissions false
${debug_opts:-}
open -u "$user","$pass" "ftp://$host"
mirror ${mirror_opts[*]} ${excl[*]:-} "$remote" "$local_dir"
bye
EOF
	then
		log "ERROR: lftp falló para $user@$host '$remote' (credenciales, TLS o red; ver líneas anteriores)"
		return 1
	fi
}

# Nota: cada job espeja el origen remoto directo a su ruta final en el NAS mediante
# mirror_* (con --delete); no hay staging local.

