#!/usr/bin/env bash
#
# Audita referencias a *.cortexdev.lan en la configuracion de las apps (ubuntu-docker).
# Solo reporta; NO modifica nada. Se ejecuta EN ubuntu-docker.
#
# Sirve para detectar APP_URL, SESSION_DOMAIN, SANCTUM_STATEFUL_DOMAINS, CORS,
# baseHref/apiUrl, etc. que sigan apuntando a .lan y puedan dejar el login mixto
# al entrar por .win.
#
# Variables:
#   SEARCH_DIRS   directorios a revisar, separados por espacios (default /home/christian/dev)
#   ALLOW_OTHER_HOST=1 permite ejecutar fuera de 192.168.0.87
#
set -uo pipefail

SEARCH_DIRS="${SEARCH_DIRS:-/home/christian/dev}"
FAIL=0

info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=1; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$*"; }

if [ "${ALLOW_OTHER_HOST:-0}" != "1" ] && ! hostname -I 2>/dev/null | grep -q '192\.168\.0\.87'; then
  printf '\033[1;31mERROR\033[0m este script corre en ubuntu-docker (192.168.0.87); usa ALLOW_OTHER_HOST=1 para forzar\n' >&2
  exit 1
fi

info "Auditando referencias a cortexdev.lan"
printf '  dirs: %s\n' "$SEARCH_DIRS"

found=0
for dir in $SEARCH_DIRS; do
  [ -d "$dir" ] || { warn "no existe $dir"; continue; }
  # Configs tipicas de apps; se excluye nginx (su .lan es el catch-all de respaldo),
  # dependencias y artefactos.
  hits="$(grep -rInE 'cortexdev\.lan' "$dir" \
    --include='.env' --include='.env.*' --include='*.env' \
    --include='docker-compose*.yml' --include='docker-compose*.yaml' \
    --include='*.conf' --include='*.properties' --include='*.ini' \
    --include='environment*.ts' --include='*.env.ts' \
    --exclude-dir=nginx --exclude-dir=node_modules --exclude-dir=.git \
    --exclude-dir=vendor --exclude-dir=storage --exclude-dir=dist \
    2>/dev/null || true)"
  [ -n "$hits" ] || continue
  found=1
  printf '\n  \033[1m%s\033[0m\n' "$dir"
  printf '%s\n' "$hits" | sed 's/^/     /'
done

echo
if [ "$found" = "0" ]; then
  ok "sin referencias a .lan en la configuracion auditada"
else
  bad "hay referencias a .lan; revisa APP_URL/SESSION_DOMAIN/CORS/baseHref por app"
  printf '     Corrige esos valores a .win en el equipo/app correspondiente y reinicia el servicio.\n'
  printf '     (.lan sigue siendo valido como respaldo; solo ajusta si quieres forzar .win.)\n'
fi

# Pistas concretas por clave
info "Pistas (claves sensibles a dominio)"
for dir in $SEARCH_DIRS; do
  [ -d "$dir" ] || continue
  grep -rInE '(APP_URL|SESSION_DOMAIN|SANCTUM_STATEFUL_DOMAINS|CORS|FRONTEND_URL|BASE_URL|baseHref|apiUrl).*cortexdev' "$dir" \
    --include='.env' --include='.env.*' --include='*.env' \
    --include='*.conf' --include='environment*.ts' \
    --exclude-dir=nginx --exclude-dir=node_modules --exclude-dir=.git \
    --exclude-dir=vendor --exclude-dir=storage --exclude-dir=dist \
    2>/dev/null | sed 's/^/     /' || true
done

exit "$FAIL"
