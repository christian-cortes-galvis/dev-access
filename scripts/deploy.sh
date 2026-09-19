#!/usr/bin/env bash
#
# Actualiza y levanta la capa de acceso (nginx) en ubuntu-services.
#
# Uso:
#   scripts/deploy.sh
#
# Variables:
#   INSTALL_SYSTEMD=1  instala/actualiza systemd/access-ingress.service
#   ACCESS_PORT        puerto HTTPS para la verificacion (default: 443)
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACCESS_PORT="${ACCESS_PORT:-443}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

cd "$REPO_DIR"

if [ "${ALLOW_OTHER_HOST:-0}" != "1" ] && ! hostname -I 2>/dev/null | grep -q '192\.168\.0\.49'; then
  printf '\033[1;31mERROR\033[0m deploy.sh debe correr en ubuntu-services (192.168.0.49); usa ALLOW_OTHER_HOST=1 para forzar\n' >&2
  exit 1
fi

log "git pull --ff-only"
git pull --ff-only

if ! ls nginx/conf.d/*.conf >/dev/null 2>&1; then
  printf '\033[1;31mERROR\033[0m nginx/conf.d no tiene *.conf en %s\n' "$REPO_DIR" >&2
  printf '        repo incompleto: mira git status --short y restaura con git checkout -- .\n' >&2
  exit 1
fi

# nginx referencia el par .win; si no existe, nginx no arranca. Genera un
# provisional autofirmado (se reemplaza al emitir con install-win-cert.sh --issue).
if [ -x scripts/install-win-cert.sh ]; then
  scripts/install-win-cert.sh --ensure || log "AVISO: no pude asegurar el certificado *.cortexdev.win"
fi

log "docker compose up -d --build"
docker compose up -d --build

status="$(docker inspect --format '{{.State.Status}}' access_nginx 2>/dev/null || true)"
if [ "$status" = "running" ] && ! docker exec access_nginx sh -c 'ls /etc/nginx/conf.d/*.conf >/dev/null 2>&1'; then
  log "access_nginx no tiene conf.d montado (contenedor viejo); recreando ingress"
  docker compose up -d --force-recreate ingress || true
  status="$(docker inspect --format '{{.State.Status}}' access_nginx 2>/dev/null || true)"
fi

if [ "$status" = "running" ]; then
  if docker exec access_nginx nginx -t && docker exec access_nginx nginx -s reload; then
    log "nginx recargado (aplica conf.d montado)"
  else
    log "nginx no pudo cargar la config; recreando ingress"
    docker compose up -d --force-recreate ingress || true
  fi
fi

if [ "${INSTALL_SYSTEMD:-0}" = "1" ]; then
  unit_tmp="$(mktemp)"
  sed -e "s|__REMOTE_DIR__|$REPO_DIR|g" -e "s|__REMOTE_USER__|$(id -un)|g" \
    "$REPO_DIR/systemd/access-ingress.service.template" > "$unit_tmp"
  log "Instalando access-ingress.service"
  sudo cp "$unit_tmp" /etc/systemd/system/access-ingress.service
  rm -f "$unit_tmp"
  sudo systemctl daemon-reload
  sudo systemctl enable --now access-ingress.service

  if [ -f "$REPO_DIR/systemd/acme-renew.timer" ]; then
    acme_tmp="$(mktemp)"
    sed -e "s|__REMOTE_DIR__|$REPO_DIR|g" -e "s|__REMOTE_USER__|$(id -un)|g" \
      "$REPO_DIR/systemd/acme-renew.service.template" > "$acme_tmp"
    log "Instalando acme-renew.service + .timer"
    sudo cp "$acme_tmp" /etc/systemd/system/acme-renew.service
    rm -f "$acme_tmp"
    sudo cp "$REPO_DIR/systemd/acme-renew.timer" /etc/systemd/system/acme-renew.timer
    sudo systemctl daemon-reload
    sudo systemctl enable --now acme-renew.timer
  fi
fi

log "Verificando respuestas"
verify_fail=0
for path in "/" "/infraestructura.html" "/laravel.html"; do
  code="$(curl -sk -o /dev/null -w '%{http_code}' -H 'Host: index.cortexdev.lan' "https://127.0.0.1:$ACCESS_PORT$path" || true)"
  printf '  index.cortexdev.lan%-22s -> %s\n' "$path" "$code"
  [ "$code" = "200" ] || verify_fail=1
done
code="$(curl -sk -o /dev/null -w '%{http_code}' -H 'Host: ca.cortexdev.lan' "https://127.0.0.1:$ACCESS_PORT/cortexdev-lan-ca.crt" || true)"
printf '  ca.cortexdev.lan/cortexdev-lan-ca.crt -> %s\n' "$code"
[ "$code" = "200" ] || verify_fail=1

if [ "$verify_fail" != "0" ]; then
  log "Diagnostico:"
  docker inspect access_nginx --format '  NetworkMode={{.HostConfig.NetworkMode}}' 2>/dev/null || true
  docker inspect access_nginx --format '{{range .Mounts}}  mount {{.Source}} -> {{.Destination}}{{println}}{{end}}' 2>/dev/null || true
  git status --short 2>/dev/null || true
  ls -la nginx/conf.d 2>/dev/null || true
  docker exec access_nginx ls -la /etc/nginx/conf.d 2>/dev/null || true
  docker exec access_nginx nginx -T 2>&1 | grep -E 'nginx:|listen|server_name' || true
fi

log "Listo."
