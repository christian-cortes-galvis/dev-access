#!/usr/bin/env bash
# Diagnóstico de las copias backupcsr: NAS (CIFS) y FTP.
# Intenta montar /mnt/nas y prueba conexión/login FTP. No descarga ni sube archivos.
#
# Uso: sudo tools/diagnostico-copias.sh
set -uo pipefail

ETC_DIR=/etc/backupcsr
CRED="$ETC_DIR/credentials.env"
NAS_MOUNT=/mnt/nas
NAS_SERVER="${NAS_SERVER:-192.168.0.179}"

if [ "$(id -u)" -ne 0 ]; then
	echo "ERROR: ejecutar con sudo." >&2
	exit 1
fi

echo "== NAS =="
if grep -q "$NAS_MOUNT" /etc/fstab; then
	grep "$NAS_MOUNT" /etc/fstab
else
	echo "(no hay entrada en /etc/fstab para $NAS_MOUNT)"
fi

if grep -qE "^[^ ]+ $NAS_MOUNT cifs " /proc/mounts 2>/dev/null; then
	echo "ya está montado en $NAS_MOUNT"
else
	echo "intentando montar $NAS_MOUNT ..."
	if mount "$NAS_MOUNT"; then
		echo "montaje OK"
	else
		echo "montaje FALLÓ (ver mensaje arriba)"
	fi
fi

if mountpoint -q "$NAS_MOUNT"; then
	echo "contenido de $NAS_MOUNT:"
	ls -la "$NAS_MOUNT"
else
	echo "NO montado. Comprobaciones:"
	echo -n "  resolución de $NAS_SERVER: "
	getent hosts "$NAS_SERVER" || echo "NO resuelve (usar la IP del NAS en /etc/fstab)"
	echo "  prueba manual alternativa:"
	echo "    sudo mount -v -t cifs //$NAS_SERVER/Backups $NAS_MOUNT -o credentials=$ETC_DIR/nas.creds,vers=3.0"
	echo "    (si falla, probar vers=3.1.1 y luego vers=2.1)"
fi

echo
echo "== FTP =="
if [ ! -r "$CRED" ]; then
	echo "no se puede leer $CRED"
	exit 1
fi
set -a
# shellcheck disable=SC1090
. "$CRED"
set +a

test_ftp() {
	local name="$1" host="$2" user="$3" pass="$4"
	echo "-- $name: $user@$host"
	echo -n "  DNS: "
	getent hosts "$host" || echo "no resuelve"
	if timeout 10 bash -c "exec 3<>/dev/tcp/$host/21" 2>/dev/null; then
		echo "  TCP 21: abierto"
	else
		echo "  TCP 21: NO accesible (firewall, red o servidor caído)"
	fi
	echo "  lftp (config de los jobs, TLS sin verificar):"
	timeout 40 lftp -u "$user","$pass" "ftp://$host" -e \
		"set ftp:ssl-force false; set ftp:ssl-protect-data false; set ftp:ssl-allow true; set ssl:verify-certificate no; set ssl:check-hostname no; set ftp:passive-mode on; set net:timeout 30; set net:max-retries 2; pwd; ls; bye" 2>&1 |
		sed 's/^/    /'
	echo "  lftp (alternativa sin TLS):"
	timeout 40 lftp -u "$user","$pass" "ftp://$host" -e \
		"set ftp:ssl-allow no; set ftp:passive-mode on; set net:timeout 30; set net:max-retries 2; pwd; ls; bye" 2>&1 |
		sed 's/^/    /'
}

test_ftp ruta56 "${RUTA56_HOST:-}" "${RUTA56_USER:-}" "${RUTA56_PASS:-}"
test_ftp gastro "${GASTRO_HOST:-}" "${GASTRO_USER:-}" "${GASTRO_PASS:-}"
test_ftp enter "${ENTER_HOST:-}" "${ENTER_USER:-}" "${ENTER_PASS:-}"

echo
echo "Listo. Comparte esta salida para ajustar fstab/vers o las credenciales."
