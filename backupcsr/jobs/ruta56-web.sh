#!/usr/bin/env bash
# Ruta56 Web: ruta56/storage -> NAS (ruta56/storage/app)
# Reemplaza scripts/servidor_ruta56_web.bat + texts/script_ruta56_web.txt
# WinSCP: cd ruta56 ; synchronize local ... ruta56/storage storage/app
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "ruta56-web"
load_credentials

mirror_ftp "$RUTA56_HOST" "$RUTA56_USER" "$RUTA56_PASS" \
	"ruta56/storage" "$BACKUPCSR_NAS_ROOT/ruta56/storage/app"

log "=== fin ruta56-web ==="
