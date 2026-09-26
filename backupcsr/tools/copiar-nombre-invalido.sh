#!/usr/bin/env bash
# Copia UNA VEZ un archivo con nombre NO-UTF-8 desde el origen a un nombre válido en
# el NAS. El mirror no puede crearlo (CIFS con iocharset=utf8 rechaza el nombre), así
# que el job lo excluye y este script lo trae a mano. NO toca el origen.
#
# Uso (root en ubuntu-services):
#   sudo /opt/backupcsr/tools/copiar-nombre-invalido.sh
#   sudo /opt/backupcsr/tools/copiar-nombre-invalido.sh "<dir remoto>" "<patrón>" "<destino en NAS>"
# Variables:
#   DRY_RUN=1  solo muestra lo que haría (sin descargar ni copiar)
#   FORCE=1    sobrescribe el destino si ya existe
set -euo pipefail

ETC="${BACKUPCSR_ETC:-/etc/backupcsr}"
REMOTE_DIR="${1:-/home/chequeos/daruma302.socimedicostools.info/daruma_original/web/uploads/staff/assets/user14/CONCILIACIONES JUDICIALES Y EXTRAJUDICIALES}"
PATTERN="${2:-RESOLUCI*N No 00034.pdf}"
DEST="${3:-/mnt/nas/latino-web/daruma302.socimedicostools.info/daruma_original/web/uploads/staff/assets/user14/CONCILIACIONES JUDICIALES Y EXTRAJUDICIALES/RESOLUCIàN No 00034.pdf}"
DRY_RUN="${DRY_RUN:-0}"
FORCE="${FORCE:-0}"
KEY="$ETC/keys/latino"

[ -r "$ETC/credentials.env" ] || { echo "ERROR: no se puede leer $ETC/credentials.env (¿sudo?)" >&2; exit 1; }
[ -r "$KEY" ] || { echo "ERROR: no se puede leer $KEY (¿sudo?)" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ETC/credentials.env"
set +a
: "${LATINO_HOST:?falta LATINO_HOST en credentials.env}"
: "${LATINO_USER:?falta LATINO_USER en credentials.env}"
PORT="${LATINO_PORT:-2200}"

if [ -e "$DEST" ] && [ "$FORCE" != "1" ]; then
	echo "AVISO: ya existe $DEST (usa FORCE=1 para sobrescribir)"
	exit 0
fi

echo "Origen:  $REMOTE_DIR"
echo "Patrón:  $PATTERN"
echo "Destino: $DEST"
if [ "$DRY_RUN" = "1" ]; then
	echo "DRY-RUN: se descargaría a un temporal y se copiaría al destino"
	exit 0
fi

WORK="$(mktemp -d)"
prog="$(mktemp)"
trap 'rm -rf "$WORK" "$prog"' EXIT
cat >"$prog" <<EOF
set sftp:connect-program "ssh -a -x -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -i $KEY"
set net:timeout 20
set net:max-retries 3
set sftp:auto-confirm yes
open -u "$LATINO_USER","" "sftp://$LATINO_HOST:$PORT"
lcd $WORK
cd "$REMOTE_DIR"
mget "$PATTERN"
bye
EOF

lftp -f "$prog"
found="$(find "$WORK" -maxdepth 1 -type f -print -quit)"
if [ -z "$found" ]; then
	echo "ERROR: no se descargó ningún archivo que coincida con el patrón" >&2
	exit 1
fi
mkdir -p "$(dirname "$DEST")"
cp -f "$found" "$DEST"
printf 'Copiado: %q -> %s\n' "${found##*/}" "$DEST"
