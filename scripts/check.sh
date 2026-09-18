#!/usr/bin/env bash
#
# Valida la capa de acceso en ubuntu-services (192.168.0.49).
# Se ejecuta EN ubuntu-services: scripts/check.sh
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAIL=0

cd "$REPO_DIR"

ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=1; }
info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$*"; }

if ! hostname -I 2>/dev/null | grep -q '192\.168\.0\.49'; then
  warn "esta maquina no tiene la IP 192.168.0.49: check.sh valida ubuntu-services, no ubuntu-docker (.87)"
fi

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
  echo "       Si es 000 estando access_nginx 'running':"
  echo "       --- NetworkMode / mounts ---"
  docker inspect access_nginx --format '  NetworkMode={{.HostConfig.NetworkMode}}' 2>/dev/null || true
  docker inspect access_nginx --format '{{range .Mounts}}  mount {{.Source}} -> {{.Destination}}{{println}}{{end}}' 2>/dev/null || true
  echo "       --- git status (repo) ---"
  git status --short 2>/dev/null || true
  echo "       --- ls -la nginx/conf.d (host) ---"
  ls -la nginx/conf.d 2>/dev/null || true
  echo "       --- docker exec access_nginx ls -la /etc/nginx/conf.d ---"
  docker exec access_nginx ls -la /etc/nginx/conf.d 2>/dev/null || true
  echo "       --- listen/server_name de la config cargada (nginx -T) ---"
  docker exec access_nginx nginx -T 2>&1 | grep -E 'nginx:|listen|server_name' || true
  echo "       --- docker compose logs --tail 15 ingress ---"
  docker compose logs --tail 15 ingress 2>/dev/null || true
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

dig_answer() {
  local name="$1" out=""
  for _ in 1 2 3 4; do
    out="$(dig +short "$name" @127.0.0.1 +time=2 +tries=1 2>/dev/null || true)"
    [ -n "$out" ] && break
    sleep 1
  done
  printf '%s' "$out"
}

info "DNS (Pi-hole local)"
if command -v dig >/dev/null; then
  for h in index ca pihole proxmox backups pbs uptime kuma netdata-services netdata-backups netdata-proxmox netdata-docker; do
    r="$(dig_answer "$h.cortexdev.lan")"
    if [ "$r" = "192.168.0.49" ]; then
      ok "$h.cortexdev.lan -> 192.168.0.49"
    else
      bad "$h.cortexdev.lan -> ${r:-sin respuesta} (falta el override en misc.dnsmasq_lines)"
    fi
  done

  r="$(dig_answer app-admin.cortexdev.lan)"
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
