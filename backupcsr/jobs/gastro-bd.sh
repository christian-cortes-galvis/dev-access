#!/usr/bin/env bash
# Gastro BD: taskManager/gastro -> NAS
# Reemplaza scripts/servidor_gastro_bd.bat + texts/script_gastro_bd.txt
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "gastro-bd"
load_credentials

mirror_ftp "$GASTRO_HOST" "$GASTRO_USER" "$GASTRO_PASS" \
	"taskManager/gastro" "$BACKUPCSR_NAS_ROOT/gastro"

log "=== fin gastro-bd ==="
