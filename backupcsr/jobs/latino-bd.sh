#!/usr/bin/env bash
# Latino BD: /home/chequeos/taskManager/backupsAutomaticos -> NAS
# Reemplaza scripts/servidor_latino_bd.bat + texts/script_latino_bd.txt
# Usa la llave /etc/backupcsr/keys/latino; si falla y hay LATINO_PASS, usa contraseña.
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "latino-bd"
load_credentials

if ! mirror_sftp "$LATINO_HOST" "${LATINO_PORT:-2200}" "$LATINO_USER" "$BACKUPCSR_KEYS/latino" \
	"/home/chequeos/taskManager/backupsAutomaticos" "$BACKUPCSR_NAS_ROOT/latino/backupsAutomaticos"; then
	if [ -n "${LATINO_PASS:-}" ]; then
		log "latino-bd: la llave falló; reintentando con contraseña"
		mirror_sftp_pass "$LATINO_HOST" "${LATINO_PORT:-2200}" "$LATINO_USER" "$LATINO_PASS" \
			"/home/chequeos/taskManager/backupsAutomaticos" "$BACKUPCSR_NAS_ROOT/latino/backupsAutomaticos"
	else
		die "latino-bd: falló la autenticación por llave y no hay LATINO_PASS definido"
	fi
fi

log "=== fin latino-bd ==="
