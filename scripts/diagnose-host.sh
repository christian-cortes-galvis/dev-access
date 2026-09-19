#!/usr/bin/env bash
#
# Diagnostica conectividad y servicios de un host de la red interna.
# Se puede ejecutar en cualquier host de la LAN (p. ej. ubuntu-services).
#
# Uso:
#   scripts/diagnose-host.sh                          # 192.168.0.166, puertos PBS/netdata
#   scripts/diagnose-host.sh 192.168.0.224 8006 19999
#   scripts/diagnose-host.sh backups.cortexdev.win 8007
#
# Variables:
#   TIMEOUT_TCP  segundos por puerto (default 3)
#
set -uo pipefail

TARGET="${1:-192.168.0.166}"
if [ "$#" -gt 0 ]; then shift; fi
PORTS="${*:-22 80 443 8007 19999}"
TIMEOUT_TCP="${TIMEOUT_TCP:-3}"

info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$*"; }

info "Resolucion de $TARGET"
ip="$TARGET"
if printf '%s' "$TARGET" | grep -qE '^[0-9]+(\.[0-9]+){3}$'; then
  ok "IP literal: $ip"
else
  ip="$(getent ahostsv4 "$TARGET" 2>/dev/null | awk 'NR==1{print $1}')"
  if [ -n "$ip" ]; then ok "$TARGET -> $ip"; else bad "$TARGET no resuelve"; exit 1; fi
fi

info "Ruta hacia $ip"
if command -v ip >/dev/null; then
  ip route get "$ip" 2>&1 | sed 's/^/     /' || true
fi

info "Alcanzabilidad (ICMP)"
if command -v ping >/dev/null; then
  if ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then ok "responde a ping"; else warn "no responde a ping"; fi
else
  warn "ping no instalado; omito ICMP"
fi

info "Puertos TCP"
for p in $PORTS; do
  if timeout "$TIMEOUT_TCP" bash -c "</dev/tcp/$ip/$p" 2>/dev/null; then
    ok "tcp $ip:$p abierto"
  else
    bad "tcp $ip:$p cerrado/inalcanzable"
  fi
done

info "HTTP/HTTPS"
if command -v curl >/dev/null; then
  for p in $PORTS; do
    for scheme in http https; do
      code="$(curl -k -sS -o /dev/null -w '%{http_code}' --max-time 5 "$scheme://$ip:$p/" 2>/dev/null || true)"
      if [ -n "$code" ] && [ "$code" != "000" ]; then
        ok "$scheme://$ip:$p/ -> $code"
      fi
    done
  done
  printf '  (solo se listan los que responden)\n'
else
  warn "curl no instalado; omito HTTP"
fi

printf '\nSi todos los puertos dan "inalcanzable", el host esta apagado o sin ruta:\n'
printf '  - revisa que %s este encendido y en la misma red\n' "$TARGET"
printf '  - desde ubuntu-docker: docker compose up -d del stack correspondiente\n'
