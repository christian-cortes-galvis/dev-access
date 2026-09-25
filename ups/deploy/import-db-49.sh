#!/usr/bin/env bash
# Importa el historico de la UPS exportado desde .87 al bind mount de .49.
# Ejecutar EN .49 (ubuntu-services), dentro de ~/cortexdev-access:
#
#   bash ups/deploy/import-db-49.sh
#
# Requiere que en .87 ya se haya corrido ups/deploy/export-db-87.sh.
set -euo pipefail

SRC="${SRC:-christian@192.168.0.87:/tmp/ups-migrate/ups_data.tgz}"
DEST="${DEST:-./ups/data}"

mkdir -p "$DEST"

echo "==> Copiando desde $SRC"
scp "$SRC" /tmp/ups_data.tgz

echo "==> Extrayendo en $DEST"
tar xzf /tmp/ups_data.tgz -C "$DEST"

echo "==> Contenido:"
ls -la "$DEST"
