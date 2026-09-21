#!/usr/bin/env bash
# Validador de solo lectura de las copias de seguridad de backupcsr.
#
# Responde: ¿los jobs que install.sh dejó en /etc/cron.d/backupcsr se están ejecutando
# y cerrando bien? No monta nada, no ejecuta jobs y no crea archivos de prueba.
#
# Uso:
#   sudo validar-copias.sh [--quiet] [--grace MIN] [--help]
#
#   --quiet       imprime solo problemas (WARN/ERROR) y el resumen final.
#   --grace MIN   minutos de gracia antes de considerar un job colgado/atrasado (def. 90).
#   --help        muestra esta ayuda.
#
# Salida: 0 = todo OK, 1 = advertencias, 2 = errores.
set -euo pipefail

ETC_DIR="${BACKUPCSR_ETC:-/etc/backupcsr}"
OPT_DIR="${BACKUPCSR_OPT:-/opt/backupcsr}"
LOG_DIR="${BACKUPCSR_LOG:-/var/log/backupcsr}"
NAS_MOUNT="${BACKUPCSR_NAS:-/mnt/nas}"
NAS_ROOT="${BACKUPCSR_NAS_ROOT:-$NAS_MOUNT}"
CRON_FILE="${BACKUPCSR_CRON:-/etc/cron.d/backupcsr}"
CRED_FILE="$ETC_DIR/credentials.env"
NAS_CREDS="$ETC_DIR/nas.creds"
CRON_TZ_NAME=America/Bogota

GRACE_MIN=90
QUIET=0

ERRORS=0
WARNINGS=0
OKS=0

say() { [ "$QUIET" = "1" ] || printf '%s\n' "$*"; }
ok() { OKS=$((OKS + 1)); [ "$QUIET" = "1" ] || printf 'OK    %s\n' "$*"; }
warn() { WARNINGS=$((WARNINGS + 1)); printf 'WARN  %s\n' "$*"; }
err() { ERRORS=$((ERRORS + 1)); printf 'ERROR %s\n' "$*"; }
row() { [ "$QUIET" = "1" ] || printf '%-14s %-9s %-19s %s\n' "$1" "$2" "$3" "$4"; }

usage() {
	cat <<'EOF'
Validador de solo lectura de backupcsr.

Uso: sudo validar-copias.sh [--quiet] [--grace MIN] [--help]

  --quiet       imprime solo problemas (WARN/ERROR) y el resumen final.
  --grace MIN   minutos de gracia antes de considerar un job colgado/atrasado (def. 90).
  --help        muestra esta ayuda.

Criterio: un job está OK si su log cierra con "=== fin <job> ===" en o después de la
última ejecución que le corresponde según /etc/cron.d/backupcsr (zona America/Bogota).

Salida: 0 = todo OK, 1 = advertencias, 2 = errores.
EOF
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--quiet) QUIET=1 ;;
		--grace)
			shift
			[ "$#" -gt 0 ] || { echo "ERROR: --grace requiere un valor en minutos" >&2; exit 2; }
			GRACE_MIN="$1"
			;;
		--help | -h) usage; exit 0 ;;
		*) echo "Opción desconocida: $1" >&2; usage >&2; exit 2 ;;
	esac
	shift
done

case "$GRACE_MIN" in
	'' | *[!0-9]*) echo "ERROR: --grace debe ser un número de minutos" >&2; exit 2 ;;
esac

[ "$(id -u)" -eq 0 ] || warn "sin root: se omiten checks de permisos y NAS"

# ---------------------------------------------------------------------------
# Precondiciones
# ---------------------------------------------------------------------------

check_cron_service() {
	if command -v systemctl >/dev/null 2>&1; then
		if systemctl is-active --quiet cron; then
			ok "servicio cron activo"
		else
			err "el servicio cron NO está activo (los jobs no se dispararán)"
		fi
	else
		warn "systemctl no disponible: no se pudo verificar el servicio cron"
	fi
}

# El cron de Ubuntu/Debian NO implementa CRON_TZ (la cadena no existe en /usr/sbin/cron):
# `CRON_TZ=` se ignora al programar y los horarios se evalúan en la zona del anfitrión.
# Con el host en UTC, los jobs 6-19 corren 01:00-14:00 en Colombia y no disparan por la
# tarde; el log del job queda en hora del host y el validador/portal lo interpretan mal.
check_timezone() {
	local host_tz
	host_tz="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || true)"
	if [ -z "$host_tz" ]; then
		warn "no se pudo determinar la zona horaria del host"
		return
	fi
	if [ "$host_tz" = "$CRON_TZ_NAME" ]; then
		ok "zona horaria del host $host_tz coincide con $CRON_TZ_NAME"
	elif [ -n "$(grep -a CRON_TZ /usr/sbin/cron 2>/dev/null)" ]; then
		ok "host en $host_tz; este cron soporta CRON_TZ ($CRON_TZ_NAME)"
	else
		err "host en $host_tz y este cron NO honra CRON_TZ: los horarios se disparan en $host_tz, no en $CRON_TZ_NAME (ajustar: timedatectl set-timezone $CRON_TZ_NAME)"
	fi
}

check_cron_file() {
	if [ ! -f "$CRON_FILE" ]; then
		err "no existe $CRON_FILE (ejecutar install.sh)"
		return
	fi
	local mode owner
	mode="$(stat -c '%a' "$CRON_FILE")"
	owner="$(stat -c '%U' "$CRON_FILE")"
	if [ "$mode" = "644" ] && [ "$owner" = "root" ]; then
		ok "$CRON_FILE presente (0644 root)"
	else
		warn "$CRON_FILE con modo/owner inesperado: $mode $owner (cron exige 0644 root)"
	fi
	if grep -q $'\r' "$CRON_FILE"; then
		err "$CRON_FILE contiene CRLF (\\r); cron lo rechaza"
	fi
}

check_jobs() {
	local found=0 f
	for f in "$OPT_DIR"/jobs/*.sh; do
		[ -e "$f" ] || continue
		found=1
		if ! bash -n "$f" 2>/dev/null; then
			err "sintaxis inválida en $f"
		fi
	done
	if [ "$found" = "1" ]; then
		ok "jobs instalados con sintaxis válida en $OPT_DIR/jobs"
	else
		err "no hay jobs en $OPT_DIR/jobs (ejecutar install.sh)"
	fi
}

check_secret_perms() {
	local file="$1" label="$2"
	if [ ! -e "$file" ]; then
		err "falta $label ($file)"
		return
	fi
	local mode
	mode="$(stat -c '%a' "$file")"
	if [ "$mode" = "600" ]; then
		ok "$label presente (0600)"
	else
		warn "$label con modo $mode (se espera 600)"
	fi
}

check_credentials() {
	[ -e "$CRED_FILE" ] || return 0
	if [ "$(id -u)" -ne 0 ] && [ ! -r "$CRED_FILE" ]; then
		warn "no se puede leer $CRED_FILE sin root: no se verifican CAMBIAR ni variables"
		return
	fi
	if grep -v '^[[:space:]]*#' "$CRED_FILE" | grep -q 'CAMBIAR'; then
		err "$CRED_FILE conserva valores CAMBIAR: los jobs FTP abortan en load_credentials"
	else
		ok "$CRED_FILE sin valores CAMBIAR"
	fi

	local job vars var missing
	for job in "${CRON_JOBS[@]}"; do
		vars="$(required_vars "$job")"
		missing=""
		for var in $vars; do
			grep -qE "^[[:space:]]*$var=" "$CRED_FILE" || missing="$missing $var"
		done
		[ -z "$missing" ] || err "faltan variables para $job en credentials.env:$missing"
	done
}

check_keys() {
	local job key seen=""
	for job in "${CRON_JOBS[@]}"; do
		key="$(needed_key "$job")"
		[ -n "$key" ] || continue
		case " $seen " in *" $key "*) continue ;; esac
		seen="$seen $key"
		local path="$ETC_DIR/keys/$key"
		if [ ! -e "$path" ]; then
			err "falta la llave $path (job $job no puede conectar)"
			continue
		fi
		local mode
		mode="$(stat -c '%a' "$path")"
		[ "$mode" = "600" ] || warn "llave $path con modo $mode (se espera 600)"
		if [ ! -r "$path" ]; then
			warn "sin root no se puede verificar la llave $key"
			continue
		fi
		if ssh-keygen -y -f "$path" </dev/null >/dev/null 2>&1; then
			ok "llave $key carga sin passphrase"
		else
			err "la llave $key requiere passphrase o es inválida (cron no puede usarla)"
		fi
	done
}

check_nas() {
	local mounted=0
	if grep -qE "^[^ ]+ $NAS_MOUNT cifs " /proc/mounts 2>/dev/null; then
		mounted=1
	fi
	if [ "$mounted" = "1" ]; then
		if [ -w "$NAS_MOUNT" ]; then
			ok "NAS montado (cifs) en $NAS_MOUNT y escribible"
		else
			err "NAS montado en $NAS_MOUNT pero sin permiso de escritura"
		fi
		if [ -w "$NAS_ROOT" ]; then
			ok "raíz de destino NAS $NAS_ROOT escribible"
		else
			err "raíz de destino NAS $NAS_ROOT no existe o no es escribible"
		fi
	else
		err "NAS no montado (cifs) en $NAS_MOUNT: los jobs ruta56/gastro/enter fallan en require_nas"
		if [ -f /etc/fstab ] && ! grep -q "$NAS_MOUNT" /etc/fstab; then
			warn "/etc/fstab no tiene entrada para $NAS_MOUNT (revisar conf/fstab.backupcsr)"
		else
			warn "hay entrada en /etc/fstab para $NAS_MOUNT pero no está montado (revisar credenciales/vers)"
		fi
	fi
}

# ---------------------------------------------------------------------------
# Cron: jobs habilitados y última ejecución esperada
# ---------------------------------------------------------------------------

declare -A CRON_MIN=()
declare -A CRON_HOUR=()
declare -A CRON_UNSUPPORTED=()
CRON_JOBS=()

parse_cron() {
	while IFS= read -r line; do
		line="${line#"${line%%[![:space:]]*}"}"
		case "$line" in '' | '#'*) continue ;; esac
		case "$line" in *"/jobs/"*) : ;; *) continue ;; esac
		local job
		if [[ "$line" =~ /jobs/([A-Za-z0-9_.-]+)\.sh ]]; then
			job="${BASH_REMATCH[1]}"
		else
			continue
		fi
		local -a f=()
		read -r -a f <<<"$line"
		if [ "${#f[@]}" -lt 7 ]; then
			warn "línea de cron no reconocida: $line"
			continue
		fi
		local dom="${f[2]}" mon="${f[3]}" dow="${f[4]}"
		CRON_MIN[$job]="${f[0]}"
		CRON_HOUR[$job]="${f[1]}"
		if [ "$dom" != "*" ] || [ "$mon" != "*" ] || [ "$dow" != "*" ]; then
			CRON_UNSUPPORTED[$job]=1
		fi
		CRON_JOBS+=("$job")
	done <"$CRON_FILE"
}

# expand_field "6-19" 0 23 -> FIELD_OUT=(6 ... 19)
FIELD_OUT=()
expand_field() {
	local spec="$1" lo="$2" hi="$3"
	FIELD_OUT=()
	local -a parts=()
	IFS=',' read -r -a parts <<<"$spec"
	local part a b step i start want_step
	for part in "${parts[@]}"; do
		case "$part" in
			'*')
				for ((i = lo; i <= hi; i++)); do FIELD_OUT+=("$i"); done
				;;
			*/*)
				a="${part%%/*}"
				step="${part##*/}"
				case "$a" in
					*-*) start="${a%-*}"; b="${a#*-}" ;;
					*) start="$lo"; b="$hi" ;;
				esac
				want_step=1
				case "$step" in '' | *[!0-9]*) : ;; *) [ "$step" -gt 0 ] && want_step="$step" ;; esac
				for ((i = start; i <= b; i += want_step)); do FIELD_OUT+=("$i"); done
				;;
			*-*)
				a="${part%-*}"
				b="${part#*-}"
				for ((i = a; i <= b; i++)); do FIELD_OUT+=("$i"); done
				;;
			*)
				FIELD_OUT+=("$part")
				;;
		esac
	done
}

# Última ocurrencia del par min/hour <= ahora, interpretada en America/Bogota.
cron_last_epoch() {
	local min_spec="$1" hour_spec="$2"
	local now base cand best=0 d h m minhour
	now="$(date +%s)"
	expand_field "$min_spec" 0 59
	local -a mins=("${FIELD_OUT[@]}")
	expand_field "$hour_spec" 0 23
	local -a hours=("${FIELD_OUT[@]}")
	for d in 0 1 2 3 4 5 6 7; do
		for h in "${hours[@]}"; do
			for m in "${mins[@]}"; do
				printf -v minhour '%02d:%02d' "$h" "$m"
				base="$(TZ="$CRON_TZ_NAME" date -d "today $minhour" +%s 2>/dev/null)" || continue
				cand=$((base - d * 86400))
				if [ "$cand" -le "$now" ] && [ "$cand" -gt "$best" ]; then
					best="$cand"
				fi
			done
		done
	done
	printf '%s' "$best"
}

# epoch de un timestamp "YYYY-mm-dd HH:MM:SS"; prueba hora del servidor y Bogota.
log_epoch_of() {
	local ts="$1" best="" e
	[ -n "$ts" ] || { printf ''; return; }
	for e in "$(date -d "$ts" +%s 2>/dev/null || true)" "$(TZ="$CRON_TZ_NAME" date -d "$ts" +%s 2>/dev/null || true)"; do
		[ -n "$e" ] || continue
		if [ -z "$best" ] || [ "$e" -gt "$best" ]; then best="$e"; fi
	done
	printf '%s' "$best"
}

# Timestamp "YYYY-mm-dd HH:MM:SS" de una línea de log.
ts_of() { printf '%s' "$1" | cut -d' ' -f1-2; }

# Devuelve (como string) el timestamp más reciente entre varias líneas de log.
latest_ts() {
	local best_e="" best_s="-" l e ts
	for l in "$@"; do
		[ -n "$l" ] || continue
		ts="$(ts_of "$l")"
		e="$(log_epoch_of "$ts")"
		if [ -n "$e" ] && { [ -z "$best_e" ] || [ "$e" -gt "$best_e" ]; }; then
			best_e="$e"
			best_s="$ts"
		fi
	done
	printf '%s' "$best_s"
}

required_vars() {
	case "$1" in
		google-bd) echo "GOOGLE_BD_HOST GOOGLE_BD_USER" ;;
		google-web) echo "GOOGLE_WEB_HOST GOOGLE_WEB_USER" ;;
		latino-bd | latino-web) echo "LATINO_HOST LATINO_USER" ;;
		ruta56-bd | ruta56-web) echo "RUTA56_HOST RUTA56_USER RUTA56_PASS" ;;
		gastro-bd) echo "GASTRO_HOST GASTRO_USER GASTRO_PASS" ;;
		enter-bd) echo "ENTER_HOST ENTER_USER ENTER_PASS" ;;
		ticware-bd | ticware-web) echo "TICWARE_HOST TICWARE_USER TICWARE_PASS" ;;
	esac
}

needed_key() {
	case "$1" in
		google-*) echo google ;;
		latino-*) echo latino ;;
	esac
}

job_dest() {
	echo "$NAS_ROOT"
}

# ¿El job está corriendo ahora? (cron lo lanza como /opt/backupcsr/jobs/<job>.sh)
job_running() {
	pgrep -f "$OPT_DIR/jobs/$1.sh" >/dev/null 2>&1
}

# Última salida del log que no sea una línea con timestamp de log() (p.ej. error de lftp).
last_raw_output() {
	grep -v '^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9] \[' "$1" |
		grep -v '^[[:space:]]*$' | tail -n 1 || true
}

# ---------------------------------------------------------------------------
# Ejecución y frescura por job
# ---------------------------------------------------------------------------

check_jobs_freshness() {
	local now job log ini_line fin_line fail_line err_line last_ts raw
	local ini_epoch fin_epoch fail_epoch err_epoch expected grace_secs status detail
	now="$(date +%s)"
	grace_secs=$((GRACE_MIN * 60))

	[ "$QUIET" = "1" ] || printf '\n%-14s %-9s %-19s %s\n' "JOB" "ESTADO" "ÚLTIMA ACTIVIDAD" "DETALLE"
	for job in "${CRON_JOBS[@]}"; do
		log="$LOG_DIR/$job.log"
		if [ ! -f "$log" ]; then
			warn "job $job: NUNCA se ha ejecutado (no existe $log)"
			row "$job" "NUNCA" "-" "$(job_dest "$job")"
			continue
		fi

		ini_line="$(grep -F "] === inicio $job (" "$log" | tail -n 1 || true)"
		fin_line="$(grep -F "] === fin $job ===" "$log" | tail -n 1 || true)"
		fail_line="$(grep -F "] FALLO:" "$log" | tail -n 1 || true)"
		err_line="$(grep -F "] ERROR:" "$log" | tail -n 1 || true)"
		ini_epoch="$(log_epoch_of "$(ts_of "$ini_line")")"
		fin_epoch="$(log_epoch_of "$(ts_of "$fin_line")")"
		fail_epoch="$(log_epoch_of "$(ts_of "$fail_line")")"
		err_epoch="$(log_epoch_of "$(ts_of "$err_line")")"
		last_ts="$(latest_ts "$ini_line" "$fin_line" "$fail_line" "$err_line")"

		if [ "${CRON_UNSUPPORTED[$job]:-0}" = "1" ]; then
			warn "job $job: expresión de cron con día/mes no soportada; no se juzga frescura"
			expected=0
		else
			expected="$(cron_last_epoch "${CRON_MIN[$job]}" "${CRON_HOUR[$job]}")"
		fi

		status="DESCONOCIDO"
		detail="no se pudo interpretar el log"
		if [ -n "$fin_epoch" ] && { [ -z "$ini_epoch" ] || [ "$fin_epoch" -ge "$ini_epoch" ]; }; then
			if [ "$expected" = "0" ]; then
				status="OK?"
				detail="cierre correcto; horario de cron no verificable"
			elif [ "$fin_epoch" -ge "$((expected - 60))" ]; then
				status="OK"
				detail="$(job_dest "$job")"
			else
				status="TARDE"
				detail="último fin anterior a la ejecución esperada"
			fi
		elif [ -n "$ini_epoch" ]; then
			raw="$(last_raw_output "$log")"
			if [ -n "$fail_epoch" ] && [ "$fail_epoch" -ge "$ini_epoch" ]; then
				status="FALLO"
				detail="${fail_line#*] }"
			elif [ -n "$err_epoch" ] && [ "$err_epoch" -ge "$ini_epoch" ]; then
				status="FALLO"
				detail="${err_line#*] }"
			elif job_running "$job"; then
				status="EN_CURSO"
				detail="corriendo desde $(ts_of "$ini_line")"
			elif [ -n "$raw" ] && printf '%s' "$raw" | grep -qiE 'fatal|error|failed|refused|denied|no such|timeout|retries'; then
				status="FALLO"
				detail="inicio sin cierre y proceso ausente: $raw"
			elif [ "$((now - ini_epoch))" -le "$grace_secs" ]; then
				status="EN_CURSO"
				detail="inicio sin cierre, dentro de la gracia (${GRACE_MIN}m)"
			else
				status="FALLO"
				detail="inicio sin cierre y proceso ausente (revisar $log)"
			fi
		elif [ -n "$fail_epoch" ]; then
			status="FALLO"
			detail="${fail_line#*] }"
		elif [ -n "$err_epoch" ]; then
			status="FALLO"
			detail="${err_line#*] }"
		fi

		case "$status" in
			OK | OK? | EN_CURSO) OKS=$((OKS + 1)) ;;
			TARDE) warn "job $job TARDE: $detail" ;;
			DESCONOCIDO) warn "job $job: $detail" ;;
			FALLO) err "job $job FALLÓ: $detail" ;;
		esac
		row "$job" "$status" "$last_ts" "$detail"
	done
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if [ ! -f "$CRON_FILE" ]; then
	check_cron_file
	err "no se puede continuar sin $CRON_FILE"
else
	say "== Precondiciones =="
	check_cron_service
	check_timezone
	check_cron_file
	check_jobs
	check_secret_perms "$CRED_FILE" "credentials.env"
	check_secret_perms "$NAS_CREDS" "nas.creds"
	parse_cron
	if [ "${#CRON_JOBS[@]}" -eq 0 ]; then
		err "no hay jobs habilitados en $CRON_FILE"
	fi
	check_credentials
	check_keys
	check_nas

	say ""
	say "== Ejecución de copias =="
	check_jobs_freshness
fi

printf '\n== Resumen ==\n'
printf 'OK: %d   WARN: %d   ERROR: %d\n' "$OKS" "$WARNINGS" "$ERRORS"
if [ "$ERRORS" -gt 0 ]; then
	printf 'Resultado: ERROR (hay copias fallando o precondiciones sin cumplir)\n'
	exit 2
elif [ "$WARNINGS" -gt 0 ]; then
	printf 'Resultado: ADVERTENCIAS (revisar los WARN)\n'
	exit 1
fi
printf 'Resultado: TODO OK\n'
exit 0
