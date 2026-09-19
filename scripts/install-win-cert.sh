#!/usr/bin/env bash
#
# Certificado publico comodin *.cortexdev.win para la capa de acceso.
# Se ejecuta EN ubuntu-services.
#
# Modos:
#   scripts/install-win-cert.sh              # asegura un par provisional autofirmado
#                                            # (para que nginx arranque antes de emitir)
#   scripts/install-win-cert.sh --issue      # emite e instala con Let's Encrypt (DNS-01 Cloudflare)
#   scripts/install-win-cert.sh --staging    # ensayo en Let's Encrypt staging (no instala)
#   scripts/install-win-cert.sh --status     # muestra que certificado hay hoy
#
# El modo --issue/--staging necesita root (acme.sh) y /etc/cortexdev/acme.env con CF_Token.
# Ver README, seccion "Dominio interno con certificado publico".
#
# Variables:
#   DEST_DIR      destino (default: <repo>/certs/cortexdev.win)
#   DOMAIN        dominio base (default: cortexdev.win)
#   ENV_FILE      credencial Cloudflare (default: /etc/cortexdev/acme.env)
#   ACME_HOME     home de acme.sh (default: /root/.acme.sh)
#   ACME_EMAIL    correo de registro acme.sh (default: admin@<DOMAIN>)
#   NGINX_CONTAINER  contenedor a recargar (default: access_nginx)
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${DEST_DIR:-$REPO_DIR/certs/cortexdev.win}"
DOMAIN="${DOMAIN:-cortexdev.win}"
ENV_FILE="${ENV_FILE:-/etc/cortexdev/acme.env}"
ACME_HOME="${ACME_HOME:-/root/.acme.sh}"
ACME="$ACME_HOME/acme.sh"
ACME_EMAIL="${ACME_EMAIL:-admin@${DOMAIN}}"
NGINX_CONTAINER="${NGINX_CONTAINER:-access_nginx}"

KEY="$DEST_DIR/key.pem"
FULLCHAIN="$DEST_DIR/fullchain.pem"

MODE="ensure"
SERVER="letsencrypt"
for arg in "$@"; do
  case "$arg" in
    --ensure)  MODE="ensure" ;;
    --issue)   MODE="issue" ;;
    --staging) MODE="issue"; SERVER="letsencrypt_test" ;;
    --status)  MODE="status" ;;
    -h|--help)
      sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) printf 'Opcion desconocida: %s (usa --help)\n' "$arg" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Un cert emitido por una CA real tiene issuer != subject; el provisional no.
is_self_signed() {
  [ -s "$FULLCHAIN" ] || return 1
  local iss sub
  iss="$(openssl x509 -in "$FULLCHAIN" -noout -issuer 2>/dev/null | sed 's/^issuer=//')"
  sub="$(openssl x509 -in "$FULLCHAIN" -noout -subject 2>/dev/null | sed 's/^subject=//')"
  [ -n "$iss" ] && [ "$iss" = "$sub" ]
}

show_status() {
  if [ -s "$FULLCHAIN" ]; then
    local iss sub
    iss="$(openssl x509 -in "$FULLCHAIN" -noout -issuer 2>/dev/null || echo '?')"
    sub="$(openssl x509 -in "$FULLCHAIN" -noout -subject 2>/dev/null || echo '?')"
    printf '  archivo: %s\n  %s\n  %s\n' "$FULLCHAIN" "$iss" "$sub"
    openssl x509 -in "$FULLCHAIN" -noout -enddate 2>/dev/null | sed 's/^/  /'
    if is_self_signed; then
      warn "es un certificado provisional autofirmado (los navegadores avisaran); emite con --issue"
    else
      ok "certificado emitido por una CA (no autofirmado)"
    fi
  else
    warn "no hay $FULLCHAIN; corre scripts/install-win-cert.sh"
  fi
  if [ -x "$ACME" ]; then
    "$ACME" --list --home "$ACME_HOME" 2>/dev/null | grep -F "$DOMAIN" || true
  fi
}

placeholder() {
  command -v openssl >/dev/null || die "openssl no esta instalado"
  mkdir -p "$DEST_DIR"
  info "Generando certificado provisional autofirmado (*.${DOMAIN})"
  if openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
      -keyout "$KEY" -out "$FULLCHAIN" \
      -subj "/CN=${DOMAIN}" \
      -addext "subjectAltName=DNS:*.${DOMAIN},DNS:${DOMAIN}" >/dev/null 2>&1; then
    chmod 600 "$KEY"
    chmod 644 "$FULLCHAIN"
    warn "provisional instalado; los navegadores avisaran hasta emitir el real con --issue"
  else
    die "no pude generar el certificado provisional"
  fi
}

ensure() {
  mkdir -p "$DEST_DIR"
  if [ -s "$FULLCHAIN" ] && [ -s "$KEY" ]; then
    if is_self_signed; then
      warn "ya hay un certificado provisional autofirmado en $DEST_DIR"
    else
      ok "certificado *.${DOMAIN} presente en $DEST_DIR"
    fi
    return 0
  fi
  placeholder
}

need_root() {
  [ "$(id -u)" = "0" ] || die "este modo instala acme.sh en $ACME_HOME y necesita root: sudo scripts/install-win-cert.sh $*"
}

issue() {
  need_root "$@"
  command -v curl >/dev/null || die "curl no esta instalado"
  [ -r "$ENV_FILE" ] || die "falta $ENV_FILE (chmod 600) con CF_Token=<token>; ver README"

  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
  [ -n "${CF_Token:-}" ] || die "$ENV_FILE no define CF_Token"

  if [ ! -x "$ACME" ]; then
    info "Instalando acme.sh en $ACME_HOME (sin cron propio; usamos systemd timer)"
    curl -s https://get.acme.sh | sh -s "email=${ACME_EMAIL}" --nocron || die "fallo la instalacion de acme.sh"
  fi
  [ -x "$ACME" ] || die "acme.sh no quedo en $ACME"

  "$ACME" --set-default-ca --server letsencrypt --home "$ACME_HOME" >/dev/null 2>&1 || true

  info "Emitiendo *.${DOMAIN} con DNS-01 Cloudflare (server: ${SERVER})"
  # --force: reutiliza el flujo aunque exista la clave de dominio de un ensayo
  # previo en staging (acme.sh pide sobrescribirla y sin esto aborta).
  if ! "$ACME" --issue --dns dns_cf -d "*.${DOMAIN}" --keylength ec-256 --force \
      --server "$SERVER" --home "$ACME_HOME"; then
    die "la emision fallo; revisa el token Cloudflare (Zone:DNS:Edit sobre ${DOMAIN})"
  fi

  if [ "$SERVER" != "letsencrypt" ]; then
    ok "ensayo en staging correcto; ahora corre: sudo scripts/install-win-cert.sh --issue"
    warn "borra el cert de staging con: sudo $ACME --remove -d '*.${DOMAIN}' --ecc --server letsencrypt_test --home $ACME_HOME"
    return 0
  fi

  mkdir -p "$DEST_DIR"
  info "Instalando el certificado en $DEST_DIR"
  if "$ACME" --install-cert -d "*.${DOMAIN}" --ecc --server "$SERVER" --home "$ACME_HOME" \
      --key-file "$KEY" \
      --fullchain-file "$FULLCHAIN" \
      --reloadcmd "docker exec $NGINX_CONTAINER nginx -s reload"; then
    chmod 600 "$KEY"
    chmod 644 "$FULLCHAIN"
    ok "certificado instalado y nginx recargado"
  else
    die "acme.sh emitio pero fallo --install-cert"
  fi
}

case "$MODE" in
  ensure) ensure ;;
  status) show_status ;;
  issue)  issue "$@" ;;
esac
