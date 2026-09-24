#!/usr/bin/env bash
# Latino Web: /home/chequeos/EDUCACION y /home/chequeos/DARUMA -> OneDrive
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

# WinSCP: -filemask="|temp/;sessions/;localcache/;cache/"
mirror_sftp "$L_HOST" "$L_PORT" "$L_USER" "$L_KEY" \
	"/home/chequeos/EDUCACION" "$JOB_STAGING/educacion" \
	"temp/" "sessions/" "localcache/" "cache/"

mirror_sftp "$L_HOST" "$L_PORT" "$L_USER" "$L_KEY" \
	"/home/chequeos/DARUMA" "$JOB_STAGING/daruma302.socimedicostools.info"

publish_onedrive "$JOB_STAGING/educacion" "$ONEDRIVE_ROOT/educacion"
publish_onedrive "$JOB_STAGING/daruma302.socimedicostools.info" "$ONEDRIVE_ROOT/daruma302.socimedicostools.info"

log "=== fin latino-web ==="
