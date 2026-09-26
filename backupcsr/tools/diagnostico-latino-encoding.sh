#!/usr/bin/env bash
# Diagnóstico SOLO LECTURA (salida corta) del error de nombre en latino-web:
#   mirror: .../RESOLUCI<0xE0>N No 00034.pdf: No such file or directory
#
# No escribe en el NAS ni en el origen. Muestra solo lo relevante: si el padre
# existe, si el archivo (patrón) está en cada lado y los nombres "sospechosos"
# (bytes no ASCII o espacio/punto final), acotado a 20 líneas por sección.
#
# Uso (root, para leer la llave):
#   sudo /opt/backupcsr/tools/diagnostico-latino-encoding.sh
#   sudo /opt/backupcsr/tools/diagnostico-latino-encoding.sh "<subdir bajo daruma302...>" "<patrón>"
#   sudo /opt/backupcsr/tools/diagnostico-latino-encoding.sh \
#        "daruma_original/web/uploads/staff/assets/user14/CONCILIACIONES JUDICIALES Y EXTRAJUDICIALES" "RESOLU*"
set -euo pipefail
export LC_ALL=C

ETC="${BACKUPCSR_ETC:-/etc/backupcsr}"
NAS="${BACKUPCSR_NAS:-/mnt/nas}"
REL="${1:-daruma_original/web/uploads/staff/assets/user14/CONCILIACIONES JUDICIALES Y EXTRAJUDICIALES}"
PATTERN="${2:-RESOLU*}"
LIMIT=20
LEAF="daruma302.socimedicostools.info"
REMOTE_ROOT="/home/chequeos/$LEAF"
NAS_ROOT="$NAS/latino-web/$LEAF"
NAS_DIR="$NAS_ROOT/$REL"
REMOTE_DIR="$REMOTE_ROOT/$REL"
KEY="$ETC/keys/latino"

if [ -r "$ETC/credentials.env" ]; then
	set -a
	# shellcheck disable=SC1090
	. "$ETC/credentials.env"
	set +a
fi
HOST_="${LATINO_HOST:-}"
USER_="${LATINO_USER:-chequeos}"
PORT_="${LATINO_PORT:-2200}"

say() { printf '\n== %s ==\n' "$*"; }
# Nombre "sospechoso": byte fuera de ASCII imprimible, o espacio/punto final.
suspicious() {
	local n="$1"
	[[ "$n" =~ [^[:print:]] ]] && return 0
	[[ "$n" == *" " || "$n" == *"." ]] && return 0
	return 1
}

say "Rutas"
echo "NAS_DIR=$NAS_DIR"
echo "REMOTE_DIR=$REMOTE_DIR"
mountpoint -q "$NAS" && echo "NAS montado" || echo "AVISO: NAS NO montado"

say "El padre existe"
[ -d "$NAS_DIR" ] && echo "NAS: sí" || echo "NAS: no"
echo -n "ORIGEN: "
if [ -r "$KEY" ]; then
	lftp -c "
set sftp:connect-program \"ssh -a -x -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -i $KEY\"
set net:timeout 20
set net:max-retries 2
set sftp:auto-confirm yes
open -u \"$USER_\",\"\" \"sftp://$HOST_:$PORT_\"
cls -1 \"$REMOTE_DIR\" >/dev/null
bye" >/dev/null 2>&1 && echo "sí" || echo "no/ilegible"
else
	echo "sin llave (sudo)"
fi

say "Coincidencias de '$PATTERN' en el NAS (nombre real + bytes)"
matches=0
if [ -d "$NAS_DIR" ]; then
	while IFS= read -r -d '' p; do
		base="${p##*/}"
		matches=$((matches + 1))
		if [ "$matches" -le "$LIMIT" ]; then
			printf '  %q  (hex: %s)\n' "$base" "$(printf '%s' "$base" | od -An -tx1 | tr -d ' \n')"
		fi
	done < <(find "$NAS_DIR" -maxdepth 1 -iname "$PATTERN" -print0 2>/dev/null)
fi
[ "$matches" -eq 0 ] && echo "  (ninguna: el archivo no se creó en el NAS)"
[ "$matches" -gt "$LIMIT" ] && echo "  (+$((matches - LIMIT)) más)"

say "Coincidencias de '$PATTERN' en el ORIGEN (nombre real + bytes)"
tmp="$(mktemp)"
if [ -r "$KEY" ]; then
	lftp -c "
set sftp:connect-program \"ssh -a -x -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -i $KEY\"
set net:timeout 20
set net:max-retries 2
set sftp:auto-confirm yes
open -u \"$USER_\",\"\" \"sftp://$HOST_:$PORT_\"
cls -1 \"$REMOTE_DIR\"
bye" >"$tmp" 2>&1 || true
	shown=0
	while IFS= read -r name; do
		[ -n "$name" ] || continue
		base="${name##*/}"
		if [[ "$base" == $PATTERN ]]; then
			shown=$((shown + 1))
			if [ "$shown" -le "$LIMIT" ]; then
				printf '  %q  (hex: %s)\n' "$base" "$(printf '%s' "$base" | od -An -tx1 | tr -d ' \n')"
			fi
		fi
	done <"$tmp"
	[ "$shown" -eq 0 ] && echo "  (ninguna)"
else
	echo "  (sin llave: ejecuta con sudo)"
fi

say "Nombres SOSPECHOSOS en el padre (máx. $LIMIT)"
echo "--- NAS ---"
if [ -d "$NAS_DIR" ]; then
	cnt=0
	while IFS= read -r -d '' p; do
		name="${p##*/}"
		if suspicious "$name"; then
			cnt=$((cnt + 1))
			[ "$cnt" -le "$LIMIT" ] && printf '  %q\n' "$name"
		fi
	done < <(find "$NAS_DIR" -maxdepth 1 -mindepth 1 -print0 2>/dev/null)
	[ "$cnt" -eq 0 ] && echo "  (ninguno)"
else
	echo "  (el padre no existe)"
fi
echo "--- ORIGEN ---"
cnt=0
while IFS= read -r name; do
	[ -n "$name" ] || continue
	base="${name##*/}"
	if suspicious "$base"; then
		cnt=$((cnt + 1))
		[ "$cnt" -le "$LIMIT" ] && printf '  %q\n' "$base"
	fi
done <"$tmp"
[ "$cnt" -eq 0 ] && echo "  (ninguno)"
[ "$cnt" -gt "$LIMIT" ] && echo "  (+$((cnt - LIMIT)) más)"
rm -f "$tmp"

say "Fin (solo lectura)"
