#!/usr/bin/env bash
# Ruta56 BD: taskManager/ruta56 -> NAS
# Reemplaza scripts/servidor_ruta56_bd.bat + texts/script_ruta56_bd.txt
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "ruta56-bd"
load_credentials

# OJO: ruta56-bd y ruta56-web comparten el árbol /mnt/nas/ruta56. Como el mirror
# usa --delete, hay que excluir 'storage' para que ruta56-bd no borre el contenido
# que publica ruta56-web en /mnt/nas/ruta56/storage/app. En lftp un patrón excluido
# no se borra del destino (solo con --delete-excluded), que no usamos.
mirror_ftp "$RUTA56_HOST" "$RUTA56_USER" "$RUTA56_PASS" \
	"taskManager/ruta56" "$BACKUPCSR_NAS_ROOT/ruta56" \
	"storage" "storage/"

log "=== fin ruta56-bd ==="
