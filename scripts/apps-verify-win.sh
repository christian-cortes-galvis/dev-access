#!/usr/bin/env bash
#
# Verifica los vhosts *.cortexdev.win servidos por nginx_web (ubuntu-docker).
# Se ejecuta EN ubuntu-docker: scripts/apps-verify-win.sh
#
# No modifica nada. Comprueba:
#   1. nginx_web corriendo
#   2. lista de server_name *.cortexdev.win en la config cargada
#   3. TLS con cert Let's Encrypt y respuesta HTTP por loopback para cada vhost
#   4. que cada host .win del catalogo (backend/catalog.yml) tenga vhost en nginx_web
#
# Variables:
#   NGINX_CONTAINER    contenedor nginx de apps (default nginx_web)
#   CATALOG            ruta del catalogo (default <repo>/backend/catalog.yml)
#   ALLOW_OTHER_HOST=1 permite ejecutar fuera de 192.168.0.87
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NGINX_CONTAINER="${NGINX_CONTAINER:-nginx_web}"
CATALOG="${CATALOG:-$REPO_DIR/backend/catalog.yml}"

FAIL=0
info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=1; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$*"; }

if [ "${ALLOW_OTHER_HOST:-0}" != "1" ] && ! hostname -I 2>/dev/null | grep -q '192\.168\.0\.87'; then
  printf '\033[1;31mERROR\033[0m este script corre en ubuntu-docker (192.168.0.87); usa ALLOW_OTHER_HOST=1 para forzar\n' >&2
  exit 1
fi

info "1/4 nginx_web"
command -v docker >/dev/null || { bad "docker no esta instalado"; exit 1; }
st="$(docker inspect --format '{{.State.Status}}' "$NGINX_CONTAINER" 2>/dev/null || true)"
if [ "$st" = "running" ]; then
  ok "$NGINX_CONTAINER running"
else
  bad "$NGINX_CONTAINER no esta running (${st:-inexistente})"; exit 1
fi

info "2/4 Vhosts .win en la config cargada"
names="$(docker exec "$NGINX_CONTAINER" nginx -T 2>/dev/null \
  | awk '/^[[:space:]]*server_name/{gsub(/;/,"");for(i=2;i<=NF;i++) print $i}' \
  | grep -E '\.cortexdev\.win$' | grep -v '^\*' | sort -u || true)"
if [ -z "$names" ]; then
  bad "no encontre ningun server_name *.cortexdev.win"
else
  printf '  %s\n' "$names" | sed 's/^/     - /'
  ok "$(printf '%s\n' "$names" | grep -c .) vhosts .win"
fi

info "3/4 TLS + HTTP por loopback"
if ! command -v curl >/dev/null || ! command -v openssl >/dev/null; then
  warn "curl/openssl no disponibles; omito la comprobacion"
else
  while IFS= read -r h; do
    [ -n "$h" ] || continue
    code="$(curl -sS -o /dev/null -w '%{http_code}' --resolve "$h:443:127.0.0.1" "https://$h/" 2>/dev/null || true)"
    issuer="$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$h" 2>/dev/null \
      | openssl x509 -noout -issuer 2>/dev/null || true)"
    if [ -n "$code" ] && [ "$code" != "000" ] && printf '%s' "$issuer" | grep -q "Let's Encrypt"; then
      ok "$h -> $code ($issuer)"
    else
      bad "$h -> ${code:-000} (${issuer:-sin cert})"
    fi
  done <<< "$names"
fi

info "4/4 Catalogo vs vhosts de apps"
if [ ! -f "$CATALOG" ]; then
  warn "no encontre $CATALOG; omito la comparacion (haz git pull en este host)"
else
  cat_hosts="$(grep -oE '[a-z0-9-]+\.cortexdev\.win' "$CATALOG" | sort -u || true)"
  while IFS= read -r h; do
    [ -n "$h" ] || continue
    # index/ca solo existen en la capa de acceso (.49), no en nginx_web
    case "$h" in index.cortexdev.win|ca.cortexdev.win) continue ;; esac
    if printf '%s\n' "$names" | grep -qx "$h"; then
      ok "$h tiene vhost .win"
    else
      bad "$h (catalogo) sin vhost .win en $NGINX_CONTAINER"
      printf '       agrega el vhost: scripts/add-app-win-vhost.sh %s <proxy_pass>\n' "$h"
    fi
  done <<< "$cat_hosts"
fi

echo
if [ "$FAIL" = "0" ]; then
  printf '\033[1;32mApps .win OK\033[0m\n'
else
  printf '\033[1;31mHay fallos en los vhosts .win\033[0m\n'
  exit 1
fi
