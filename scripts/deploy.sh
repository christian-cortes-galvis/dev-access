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

log "git pull --ff-only"
git pull --ff-only

log "docker compose up -d"
docker compose up -d

if [ "${INSTALL_SYSTEMD:-0}" = "1" ]; then
  unit_tmp="$(mktemp)"
  sed -e "s|__REMOTE_DIR__|$REPO_DIR|g" -e "s|__REMOTE_USER__|$(id -un)|g" \
    "$REPO_DIR/systemd/access-ingress.service.template" > "$unit_tmp"
  log "Instalando access-ingress.service"
  sudo cp "$unit_tmp" /etc/systemd/system/access-ingress.service
  rm -f "$unit_tmp"
  sudo systemctl daemon-reload
  sudo systemctl enable --now access-ingress.service
fi

log "Verificando respuestas"
for path in "/" "/infraestructura.html" "/laravel.html"; do
  code="$(curl -sk -o /dev/null -w '%{http_code}' -H 'Host: index.cortexdev.lan' "https://127.0.0.1:$ACCESS_PORT$path" || true)"
  printf '  index.cortexdev.lan%-22s -> %s\n' "$path" "$code"
done
code="$(curl -sk -o /dev/null -w '%{http_code}' -H 'Host: ca.cortexdev.lan' "https://127.0.0.1:$ACCESS_PORT/cortexdev-lan-ca.crt" || true)"
printf '  ca.cortexdev.lan/cortexdev-lan-ca.crt -> %s\n' "$code"

log "Listo."
