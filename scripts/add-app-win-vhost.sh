#!/usr/bin/env bash
#
# Añade un vhost proxy *.cortexdev.win (cert publico) al nginx de apps.
# Se ejecuta EN ubuntu-docker (192.168.0.87), donde corre nginx_web.
#
# Uso:
#   scripts/add-app-win-vhost.sh                        # atajo: pma -> phpmyadmin:80
#   scripts/add-app-win-vhost.sh <host> <proxy_pass>    # generico
#
# Ejemplos:
#   scripts/add-app-win-vhost.sh pma.cortexdev.win http://phpmyadmin:80
#   scripts/add-app-win-vhost.sh bot-gomedisys.cortexdev.win http://python_scripts:6000
#
# Escribe <host>.conf en el conf.d de apps (con backup si ya existe), valida con
# `nginx -t`, recarga y verifica por loopback. Idempotente salvo que el archivo
# exista: en ese caso exige FORCE=1.
#
# Variables:
#   APPS_NGINX_CONF_DIR  conf.d del nginx de apps (default /home/christian/dev/nginx/conf.d)
#   NGINX_CONTAINER      contenedor nginx de apps (default nginx_web)
#   WIN_CERT / WIN_KEY   rutas de los certs DENTRO del contenedor
#   FORCE=1              sobrescribe <host>.conf si ya existe (hace backup)
#   ALLOW_OTHER_HOST=1   permite ejecutar fuera de 192.168.0.87
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS_NGINX_CONF_DIR="${APPS_NGINX_CONF_DIR:-/home/christian/dev/nginx/conf.d}"
NGINX_CONTAINER="${NGINX_CONTAINER:-nginx_web}"
WIN_CERT="${WIN_CERT:-/etc/nginx/certs/cortexdev.win/cortexdev.win.pem}"
WIN_KEY="${WIN_KEY:-/etc/nginx/certs/cortexdev.win/cortexdev.win-key.pem}"

FAIL=0
info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=1; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$*"; }

if [ "$#" -eq 0 ]; then
  HOST="pma.cortexdev.win"
  UPSTREAM="http://phpmyadmin:80"
elif [ "$#" -eq 2 ]; then
  HOST="$1"
  UPSTREAM="$2"
else
  printf 'Uso: %s [<host> <proxy_pass>]\n\n' "$0" >&2
  printf '  %s                                     # atajo: pma -> phpmyadmin:80\n' "$0" >&2
  printf '  %s pma.cortexdev.win http://phpmyadmin:80\n' "$0" >&2
  exit 2
fi

case "$HOST" in
  *.cortexdev.win) : ;;
  *) printf 'ERROR: el host debe ser de *.cortexdev.win (recibido: %s)\n' "$HOST" >&2; exit 2 ;;
esac

NAME="${HOST%%.*}"
CONF="$APPS_NGINX_CONF_DIR/$NAME.conf"
BAK=""

if [ "${ALLOW_OTHER_HOST:-0}" != "1" ] && ! hostname -I 2>/dev/null | grep -q '192\.168\.0\.87'; then
  printf '\033[1;31mERROR\033[0m este script corre en ubuntu-docker (192.168.0.87); usa ALLOW_OTHER_HOST=1 para forzar\n' >&2
  exit 1
fi

info "1/4 Entorno"
command -v docker >/dev/null || { bad "docker no esta instalado"; exit 1; }
if ! docker inspect --format '{{.State.Status}}' "$NGINX_CONTAINER" >/dev/null 2>&1; then
  bad "el contenedor $NGINX_CONTAINER no existe"; exit 1
fi
st="$(docker inspect --format '{{.State.Status}}' "$NGINX_CONTAINER" 2>/dev/null || true)"
[ "$st" = "running" ] || { bad "$NGINX_CONTAINER no esta running ($st)"; exit 1; }
ok "$NGINX_CONTAINER running"
[ -d "$APPS_NGINX_CONF_DIR" ] || { bad "no existe $APPS_NGINX_CONF_DIR"; exit 1; }
ok "conf.d: $APPS_NGINX_CONF_DIR"
if docker exec "$NGINX_CONTAINER" test -f "$WIN_CERT"; then
  ok "cert .win visible en el contenedor: $WIN_CERT"
else
  bad "el contenedor no ve $WIN_CERT (revisa el mount de certs)"; exit 1
fi

info "2/4 Escribiendo $CONF"
if [ -f "$CONF" ] && [ "${FORCE:-0}" != "1" ]; then
  bad "$CONF ya existe; usa FORCE=1 para sobrescribir (se hace backup)"; exit 1
fi
if [ -f "$CONF" ]; then
  BAK="$CONF.bak-$(date +%Y%m%d-%H%M%S)"
  if cp "$CONF" "$BAK"; then ok "backup: $BAK"; else bad "no pude hacer backup de $CONF"; exit 1; fi
fi

cat > "$CONF" <<EOF
# Generado por cortexdev-access/scripts/add-app-win-vhost.sh
# Vhost publico (*.cortexdev.win) -> proxy a $UPSTREAM
server {
    listen 443 ssl;
    server_name $HOST;

    ssl_certificate     $WIN_CERT;
    ssl_certificate_key $WIN_KEY;

    location / {
        proxy_pass $UPSTREAM;

        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
ok "escrito ($HOST -> $UPSTREAM)"

info "3/4 Validando y recargando nginx"
if ! docker exec "$NGINX_CONTAINER" nginx -t >/dev/null 2>&1; then
  bad "nginx -t fallo"
  docker exec "$NGINX_CONTAINER" nginx -t 2>&1 | sed 's/^/       /' || true
  if [ -n "$BAK" ]; then
    warn "restaurando $BAK"
    cp "$BAK" "$CONF"
  else
    rm -f "$CONF"
  fi
  exit 1
fi
ok "nginx -t ok"
if docker exec "$NGINX_CONTAINER" nginx -s reload >/dev/null 2>&1; then
  ok "nginx recargado"
else
  bad "no se pudo recargar nginx"; exit 1
fi

info "4/4 Verificando https://$HOST/"
code="$(curl -sS -o /dev/null -w '%{http_code}' --resolve "$HOST:443:127.0.0.1" "https://$HOST/" 2>/dev/null || true)"
if [ -n "$code" ] && [ "$code" != "000" ]; then
  ok "https://$HOST/ -> $code (TLS valido)"
else
  bad "https://$HOST/ -> ${code:-000}"
fi

echo
if [ "$FAIL" = "0" ]; then
  printf '\033[1;32mListo\033[0m: si este vhost sustituye a uno .lan, quita el TODO de backend/catalog.yml en cortexdev-access\n'
else
  printf '\033[1;31mHay fallos\033[0m\n'
  exit 1
fi
