#!/usr/bin/env bash
# Latino Web: /home/chequeos/educacion y /home/chequeos/daruma302.socimedicostools.info -> NAS
# Reemplaza scripts/servidor_latino_web.bat + texts/script_latino_web.txt
# Los nombres reales en el origen van en minusculas: 'educacion' y
# 'daruma302.socimedicostools.info' (este ultimo es el "DARUMA" de WinSCP).
set -euo pipefail
# Corre 3-4 veces al día: espera más por el turno de la cola que los *-bd (hourly).
GATE_WAIT="${GATE_WAIT:-1800}"
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "latino-web"
load_credentials

L_HOST="$LATINO_HOST"
L_PORT="${LATINO_PORT:-2200}"
L_USER="$LATINO_USER"
L_KEY="$BACKUPCSR_KEYS/latino"

# WinSCP: -filemask="|temp/;sessions/;localcache/;cache/" (una sola vez: la usan las
# dos ramas de autenticación, llave y contraseña, para que no se desvíen).
L_EXCL=(temp/ sessions/ localcache/ cache/)
# El montaje CIFS usa iocharset=utf8: un nombre que no sea UTF-8 válido (p. ej.
# RESOLUCI<0xE0>N) no se puede crear en el NAS y lftp lo reporta como "No such file or
# directory" en cada ronda. Se excluye por patrón (sin espacios, para que la
# interpolación de exclusiones de la librería lo pase como un solo argumento).
# El archivo se copió una vez a mano con tools/copiar-nombre-invalido.sh como
# "RESOLUCIàN No 00034.pdf" en UTF-8 (ver README, "Nombres con bytes no UTF-8").
L_EXCL_DARUMA=("${L_EXCL[@]}" "*RESOLUCI*N*No*00034.pdf")

mirror_latino() {
	local remote="$1" local_dir="$2"
	shift 2
	local -a excl=("$@")
	if [ "${#excl[@]}" -eq 0 ]; then
		excl=("${L_EXCL[@]}")
	fi
	if ! mirror_sftp "$L_HOST" "$L_PORT" "$L_USER" "$L_KEY" \
		"$remote" "$local_dir" "${excl[@]}"; then
		if [ -n "${LATINO_PASS:-}" ]; then
			log "latino-web: la llave falló para $remote; reintentando con contraseña"
			mirror_sftp_pass "$L_HOST" "$L_PORT" "$L_USER" "$LATINO_PASS" \
				"$remote" "$local_dir" "${excl[@]}"
		else
			die "latino-web: falló la autenticación por llave para $remote y no hay LATINO_PASS definido"
		fi
	fi
}

mirror_latino "/home/chequeos/educacion" "$BACKUPCSR_NAS_ROOT/latino-web/educacion" "${L_EXCL[@]}"
mirror_latino "/home/chequeos/daruma302.socimedicostools.info" "$BACKUPCSR_NAS_ROOT/latino-web/daruma302.socimedicostools.info" "${L_EXCL_DARUMA[@]}"

log "=== fin latino-web ==="
