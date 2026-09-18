#!/usr/bin/env bash
#
# Valida la capa de acceso en ubuntu-services (192.168.0.49).
# Se ejecuta EN ubuntu-services: scripts/check.sh
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAIL=0

ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=1; }
info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

info "Certificados"
for f in cortexdev.lan.pem cortexdev.lan-key.pem ca.pem; do
  if [ -f "$REPO_DIR/certs/cortexdev.lan/$f" ]; then
    ok "$f"
  else
    bad "falta certs/cortexdev.lan/$f (corre scripts/install-certs.sh)"
  fi
done

info "Contenedor"
status="$(docker inspect --format '{{.State.Status}}' access_nginx 2>/dev/null || true)"
if [ "$status" = "running" ]; then
  ok "access_nginx running"
else
  bad "access_nginx no esta corriendo (docker compose up -d)"
fi

info "HTTP local (Host header, sin depender del DNS)"
code() { curl -sk -o /dev/null -w '%{http_code}' -H "Host: $1" "https://127.0.0.1$2" || true; }

c="$(code index.cortexdev.lan /)"
if [ "$c" = "200" ]; then
  ok "index.cortexdev.lan / -> 200"
else
  bad "index.cortexdev.lan / -> $c"
  echo "       Si es 403/404, Pi-hole sigue ocupando el 443:"
  echo "         - compose con puertos: usa 'docker compose up -d' (recrear, no 'restart')"
  echo "         - Pi-hole con network_mode: host: cambia 'webserver.port' (p. ej. 8080o,8443s) en pihole.toml"
fi

c="$(code index.cortexdev.lan /laravel.html)"
if [ "$c" = "200" ]; then
  ok "index.cortexdev.lan /laravel.html -> 200"
else
  bad "index.cortexdev.lan /laravel.html -> $c"
fi

c="$(code ca.cortexdev.lan /cortexdev-lan-ca.crt)"
if [ "$c" = "200" ]; then
  ok "ca.cortexdev.lan /cortexdev-lan-ca.crt -> 200"
else
  bad "ca.cortexdev.lan /cortexdev-lan-ca.crt -> $c"
fi

info "DNS (Pi-hole local)"
if command -v dig >/dev/null; then
  for h in index ca pihole proxmox backups pbs uptime kuma netdata-services netdata-backups netdata-proxmox netdata-docker; do
    r="$(dig +short "$h.cortexdev.lan" @127.0.0.1 2>/dev/null || true)"
    if [ "$r" = "192.168.0.49" ]; then
      ok "$h.cortexdev.lan -> 192.168.0.49"
    else
      bad "$h.cortexdev.lan -> ${r:-sin respuesta} (falta el override en misc.dnsmasq_lines)"
    fi
  done

  r="$(dig +short app-admin.cortexdev.lan @127.0.0.1 2>/dev/null || true)"
  if [ "$r" = "192.168.0.87" ]; then
    ok "app-admin.cortexdev.lan -> 192.168.0.87 (wildcard apps)"
  else
    bad "app-admin.cortexdev.lan -> ${r:-sin respuesta}"
  fi
else
  bad "dig no instalado; no se pudo verificar DNS"
fi

info "Puertos"
if command -v ss >/dev/null; then
  for p in 80 443 8080 8443; do
    if ss -ltn 2>/dev/null | grep -q ":$p "; then
      ok "puerto $p escuchando"
    else
      bad "nada escuchando en $p"
    fi
  done
  echo "     contenedores y puertos publicados:"
  docker ps --format '       {{.Names}} -> {{.Ports}}' 2>/dev/null || true
fi

echo
if [ "$FAIL" = "0" ]; then
  printf '\033[1;32mTodo OK\033[0m\n'
else
  printf '\033[1;31mHay fallos\033[0m\n'
  exit 1
fi
