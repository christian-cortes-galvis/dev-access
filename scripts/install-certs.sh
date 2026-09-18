#!/usr/bin/env bash
#
# Instala el wildcard *.cortexdev.lan y la CA en este equipo (ubuntu-services).
# Los .pem no viven en git (certs/ esta gitignored), se copian por scp desde
# el host donde se emitieron (ubuntu-docker por defecto).
#
# Uso:
#   scripts/install-certs.sh [origen]
#
# Origen puede ser:
#   usuario@host:/ruta/al/dir   (se usa scp)
#   /ruta/local                 (se usa cp)
#
# Variables:
#   SRC       origen          (default: christian@192.168.0.87:/home/christian/dev/nginx/certs/cortexdev.lan)
#   DEST_DIR  destino         (default: <repo>/certs/cortexdev.lan)
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-${SRC:-christian@192.168.0.87:/home/christian/dev/nginx/certs/cortexdev.lan}}"
DEST_DIR="${DEST_DIR:-$REPO_DIR/certs/cortexdev.lan}"

FILES=(cortexdev.lan.pem cortexdev.lan-key.pem ca.pem)

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

mkdir -p "$DEST_DIR"

log "Origen:  $SRC"
log "Destino: $DEST_DIR"

if [[ "$SRC" == *:* ]]; then
  command -v scp >/dev/null || die "scp no esta instalado."
  for f in "${FILES[@]}"; do
    log "scp $f"
    scp "$SRC/$f" "$DEST_DIR/$f"
  done
else
  for f in "${FILES[@]}"; do
    log "cp $f"
    cp "$SRC/$f" "$DEST_DIR/$f"
  done
fi

for f in "${FILES[@]}"; do
  [ -f "$DEST_DIR/$f" ] || die "Falta $DEST_DIR/$f"
done

chmod 600 "$DEST_DIR/cortexdev.lan-key.pem"
chmod 644 "$DEST_DIR/cortexdev.lan.pem" "$DEST_DIR/ca.pem"

log "Certificados instalados en $DEST_DIR"
