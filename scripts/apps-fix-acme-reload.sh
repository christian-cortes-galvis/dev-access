#!/usr/bin/env bash
#
# Asegura que la renovacion del comodin *.cortexdev.win en ubuntu-docker recargue
# nginx_web (reloadcmd guardado por acme.sh). Se ejecuta EN ubuntu-docker.
#
# Si el reloadcmd falta o esta vacio, lo instala con `acme.sh --install-cert`
# reutilizando el cert ya emitido (no vuelve a emitir ni necesita el token).
#
# Variables:
#   ACME_HOME        home de acme.sh (default: ~/.acme.sh)
#   NGINX_CONTAINER  contenedor nginx de apps (default: nginx_web)
#   DOMAIN           comodin (default: *.cortexdev.win)
#   ALLOW_OTHER_HOST=1 permite ejecutar fuera de 192.168.0.87
#
set -uo pipefail

ACME_HOME="${ACME_HOME:-$HOME/.acme.sh}"
NGINX_CONTAINER="${NGINX_CONTAINER:-nginx_web}"
DOMAIN="${DOMAIN:-*.cortexdev.win}"
ACME="$ACME_HOME/acme.sh"
CONF="$ACME_HOME/cortexdev.win_ecc/cortexdev.win.conf"

info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; exit 1; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$*"; }

if [ "${ALLOW_OTHER_HOST:-0}" != "1" ] && ! hostname -I 2>/dev/null | grep -q '192\.168\.0\.87'; then
  printf '\033[1;31mERROR\033[0m este script corre en ubuntu-docker (192.168.0.87); usa ALLOW_OTHER_HOST=1 para forzar\n' >&2
  exit 1
fi

info "1/3 Comprobando acme.sh y el contenedor"
[ -x "$ACME" ] || bad "acme.sh no esta en $ACME (revisa ACME_HOME)"
ok "acme.sh: $ACME"
[ -f "$CONF" ] || bad "no existe $CONF (el comodin no se emitio en este host)"
ok "conf: $CONF"
docker inspect --format '{{.State.Status}}' "$NGINX_CONTAINER" 2>/dev/null | grep -q running \
  || bad "$NGINX_CONTAINER no esta running"
ok "$NGINX_CONTAINER running"

info "2/3 Reloadcmd guardado"
reloadcmd="$(grep -E '^Le_ReloadCmd=' "$CONF" 2>/dev/null | head -n1 | cut -d= -f2- || true)"
reloadcmd="${reloadcmd%\"}"; reloadcmd="${reloadcmd#\"}"
reloadcmd="${reloadcmd%\'}"; reloadcmd="${reloadcmd#\'}"

if [ -n "$reloadcmd" ]; then
  ok "reloadcmd: $reloadcmd"
else
  warn "reloadcmd vacio; instalando uno para recargar $NGINX_CONTAINER"
  key="$(grep -E '^Le_RealKeyPath=' "$CONF" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d "'\"")"
  full="$(grep -E '^Le_RealFullChainPath=' "$CONF" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d "'\"")"
  key="${key:-/home/christian/dev/nginx/certs/cortexdev.win/cortexdev.win-key.pem}"
  full="${full:-/home/christian/dev/nginx/certs/cortexdev.win/cortexdev.win.pem}"
  if "$ACME" --install-cert -d "$DOMAIN" --ecc --home "$ACME_HOME" \
      --key-file "$key" --fullchain-file "$full" \
      --reloadcmd "docker exec $NGINX_CONTAINER nginx -s reload"; then
    ok "reloadcmd instalado (key: $key)"
  else
    bad "no pude instalar el reloadcmd"
  fi
fi

# Verifica que el reloadcmd sea coherente con el contenedor actual (no recarga otro)
case "$reloadcmd" in
  *"$NGINX_CONTAINER"*) : ;;
  "") : ;;
  *) warn "el reloadcmd no menciona $NGINX_CONTAINER: $reloadcmd" ;;
esac

info "3/3 Prueba de recarga"
if docker exec "$NGINX_CONTAINER" nginx -t >/dev/null 2>&1 && \
   docker exec "$NGINX_CONTAINER" nginx -s reload >/dev/null 2>&1; then
  ok "nginx -t + reload OK"
else
  bad "no pude validar/recargar $NGINX_CONTAINER"
fi

printf '\n\033[1;32mListo\033[0m. Comprueba el cron de acme.sh:\n'
printf '  crontab -l | grep acme.sh\n'
