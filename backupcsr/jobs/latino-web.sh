#!/usr/bin/env bash
# Latino Web: /home/chequeos/EDUCACION y /home/chequeos/DARUMA -> NAS
# Reemplaza scripts/servidor_latino_web.bat + texts/script_latino_web.txt
# El nombre local de DARUMA es daruma302.socimedicostools.info (igual que en WinSCP).
set -euo pipefail
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

mirror_latino() {
	local remote="$1" local_dir="$2"
	if ! mirror_sftp "$L_HOST" "$L_PORT" "$L_USER" "$L_KEY" \
		"$remote" "$local_dir" "${L_EXCL[@]}"; then
		if [ -n "${LATINO_PASS:-}" ]; then
			log "latino-web: la llave falló para $remote; reintentando con contraseña"
			mirror_sftp_pass "$L_HOST" "$L_PORT" "$L_USER" "$LATINO_PASS" \
				"$remote" "$local_dir" "${L_EXCL[@]}"
		else
			die "latino-web: falló la autenticación por llave para $remote y no hay LATINO_PASS definido"
		fi
	fi
}

mirror_latino "/home/chequeos/EDUCACION" "$BACKUPCSR_NAS_ROOT/latino-web/educacion"
mirror_latino "/home/chequeos/DARUMA" "$BACKUPCSR_NAS_ROOT/latino-web/daruma302.socimedicostools.info"

log "=== fin latino-web ==="
