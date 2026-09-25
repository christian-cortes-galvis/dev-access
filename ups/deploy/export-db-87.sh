#!/usr/bin/env bash
# Exporta el historico de la UPS desde el volumen Docker de .87.
# Ejecutar EN .87 (ubuntu-docker), como usuario christian.
#
#   bash /home/christian/dev/ups/deploy/export-db-87.sh
#
# Deja /tmp/ups-migrate/ups_data.tgz listo para que .49 lo traiga por scp.
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/christian/dev}"
VOLUME="${VOLUME:-dev_ups_data}"
OUT_DIR="${OUT_DIR:-/tmp/ups-migrate}"

mkdir -p "$OUT_DIR"
cd "$COMPOSE_DIR"

echo "==> Deteniendo ups_app para copiar WAL/SHM consistentes"
docker compose stop ups_app
# Reanudar siempre, aunque falle la exportacion (evita dejar .87 caido).
trap 'docker compose start ups_app || true' EXIT

echo "==> Exportando volumen $VOLUME"
docker run --rm -v "$VOLUME":/data -v "$OUT_DIR":/backup alpine \
  sh -c "cd /data && tar czf /backup/ups_data.tgz ."

echo "==> Reanudando ups_app"
docker compose start ups_app

echo "==> Listo:"
ls -la "$OUT_DIR/ups_data.tgz"
