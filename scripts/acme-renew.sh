#!/usr/bin/env bash
#
# Renueva el certificado publico comodin *.cortexdev.win via acme.sh.
# Pensado para systemd (acme-renew.timer) o cron; se ejecuta como root.
#
# acme.sh guarda el --reloadcmd en la config del cert, asi que al renovar
# tambien recarga nginx (si el contenedor access_nginx esta corriendo).
#
# Uso:
#   sudo scripts/acme-renew.sh
#
# Variables:
#   ENV_FILE   credencial Cloudflare (default: /etc/cortexdev/acme.env)
#   ACME_HOME  home de acme.sh (default: /root/.acme.sh)
#
set -uo pipefail

ENV_FILE="${ENV_FILE:-/etc/cortexdev/acme.env}"
ACME_HOME="${ACME_HOME:-/root/.acme.sh}"
ACME="$ACME_HOME/acme.sh"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "acme-renew.sh necesita root: sudo scripts/acme-renew.sh"
[ -x "$ACME" ] || die "acme.sh no esta en $ACME (corre scripts/install-win-cert.sh --issue)"

# acme.sh puede reusar las credenciales guardadas en account.conf, pero si existe
# el env file lo cargamos para no depender de ese estado.
if [ -r "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
fi

info "Ejecutando acme.sh --cron (home: $ACME_HOME)"
"$ACME" --cron --home "$ACME_HOME"
rc=$?
if [ "$rc" = "0" ] || [ "$rc" = "2" ]; then
  # acme.sh devuelve 2 cuando no habia nada que renovar.
  printf '\033[1;32mRenovacion revisada (rc=%s)\033[0m\n' "$rc"
  exit 0
fi
printf '\033[1;31macme.sh --cron fallo (rc=%s)\033[0m\n' "$rc" >&2
exit "$rc"
