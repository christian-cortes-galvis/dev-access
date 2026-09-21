#!/usr/bin/env bash
# Enter BD: taskManager/pedidos -> NAS
# Reemplaza scripts/servidor_enter_bd.bat + texts/script_enter_bd.txt
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "enter-bd"
load_credentials

mirror_ftp "$ENTER_HOST" "$ENTER_USER" "$ENTER_PASS" \
	"taskManager/pedidos" "$BACKUPCSR_NAS_ROOT/pedidos"

log "=== fin enter-bd ==="
