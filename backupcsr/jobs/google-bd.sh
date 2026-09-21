#!/usr/bin/env bash
# Google BD: /var/www/html/backupsAutomaticos -> NAS
# Reemplaza scripts/servidor_google_bd.bat + texts/script_google_bd.txt
# Requiere la llave /etc/backupcsr/keys/google sin passphrase (uso en cron).
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "google-bd"
load_credentials

mirror_sftp "$GOOGLE_BD_HOST" "${GOOGLE_BD_PORT:-22}" "$GOOGLE_BD_USER" "$BACKUPCSR_KEYS/google" \
	"/var/www/html/backupsAutomaticos" "$BACKUPCSR_NAS_ROOT/google/backupsAutomaticos"

log "=== fin google-bd ==="
