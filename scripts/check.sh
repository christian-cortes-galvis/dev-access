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
for f in fullchain.pem key.pem; do
  if [ -f "$REPO_DIR/certs/cortexdev.win/$f" ]; then
    ok "cortexdev.win/$f"
  else
    bad "falta certs/cortexdev.win/$f (corre scripts/install-win-cert.sh)"
  fi
done
win_cert="$REPO_DIR/certs/cortexdev.win/fullchain.pem"
if [ -f "$win_cert" ]; then
  win_iss="$(openssl x509 -in "$win_cert" -noout -issuer 2>/dev/null | sed 's/^issuer=//')"
  win_sub="$(openssl x509 -in "$win_cert" -noout -subject 2>/dev/null | sed 's/^subject=//')"
  if [ -n "$win_iss" ] && [ "$win_iss" = "$win_sub" ]; then
    warn "cortexdev.win/fullchain.pem es provisional autofirmado; emite con scripts/install-win-cert.sh --issue"
  else
    ok "cortexdev.win/fullchain.pem emitido por CA ($win_iss)"
  fi
fi

info "Contenedores"
for c in access_nginx portal_api; do
  status="$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null || true)"
  if [ "$status" = "running" ]; then
    ok "$c running"
  else
    bad "$c no esta corriendo (docker compose up -d --build)"
  fi
done

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

# Dominio publico: sin -k (valida la cadena real). --resolve evita depender del
# DNS del host durante la puesta en marcha.
code_strict() {
  curl -sS -o /dev/null -w '%{http_code}' --resolve "$1:443:127.0.0.1" "https://$1$2" 2>/dev/null || true
}

c="$(code_strict index.cortexdev.win /)"
if [ "$c" = "200" ]; then
  ok "index.cortexdev.win / -> 200 (cert publico valido)"
else
  bad "index.cortexdev.win / -> ${c:-000} sin -k"
  echo "       Si es 000 con cert provisional: emite con scripts/install-win-cert.sh --issue"
fi

c="$(code_strict ca.cortexdev.win /cortexdev-lan-ca.crt)"
if [ "$c" = "200" ]; then
  ok "ca.cortexdev.win /cortexdev-lan-ca.crt -> 200 (cert publico valido)"
else
  bad "ca.cortexdev.win /cortexdev-lan-ca.crt -> ${c:-000} sin -k"
fi

# Apps de ubuntu-docker (192.168.0.87): el certificado lo sirve nginx_web (.win).
# Se acepta cualquier codigo HTTP != 000 (000 = fallo de TLS/hostname).
info "HTTP apps .win (TLS publico sin -k)"
code_app() {
  curl -sS -o /dev/null -w '%{http_code}' --resolve "$1:443:192.168.0.87" "https://$1/" 2>/dev/null || true
}
for h in apps.cortexdev.win admin-portal-pacientes.cortexdev.win portal-pacientes.cortexdev.win \
         centro-apoyo.cortexdev.win bot-gomedisys.cortexdev.win analisis-datos.cortexdev.win pma.cortexdev.win; do
  c="$(code_app "$h")"
  if [ -n "$c" ] && [ "$c" != "000" ]; then
    ok "$h -> $c (TLS valido)"
  else
    bad "$h -> ${c:-000} (TLS/HTTP)"
  fi
done

info "API del portal (portal-api)"
c="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/api/health || true)"
if [ "$c" = "200" ]; then
  ok "GET /api/health -> 200"
else
  bad "GET /api/health -> ${c:-000} (docker logs --tail 40 portal_api)"
fi

body="$(curl -sk -H 'Host: index.cortexdev.lan' https://127.0.0.1/api/portal 2>/dev/null || true)"
if printf '%s' "$body" | grep -q '"services"'; then
  n="$(printf '%s' "$body" | grep -o '"category"' | wc -l)"
  ok "GET /api/portal -> catalogo ($n servicios)"
else
  bad "GET /api/portal sin catalogo (docker logs --tail 40 portal_api)"
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
  for d in cortexdev.lan cortexdev.win; do
    for h in index ca pihole proxmox backups pbs uptime kuma netdata-services netdata-backups netdata-proxmox netdata-docker; do
      r="$(dig_answer "$h.$d")"
      if [ "$r" = "192.168.0.49" ]; then
        ok "$h.$d -> 192.168.0.49"
      else
        bad "$h.$d -> ${r:-sin respuesta} (falta el override en misc.dnsmasq_lines)"
      fi
    done

    for a in app-admin apps; do
      r="$(dig_answer "$a.$d")"
      if [ "$r" = "192.168.0.87" ]; then
        ok "$a.$d -> 192.168.0.87 (wildcard apps)"
      else
        bad "$a.$d -> ${r:-sin respuesta}"
      fi
    done
  done
else
  bad "dig no instalado; no se pudo verificar DNS"
fi

info "Tailscale (acceso remoto a *.cortexdev.lan y *.cortexdev.win)"
if command -v tailscale >/dev/null; then
  if [ -x "$REPO_DIR/scripts/tailscale-dns.sh" ]; then
    if "$REPO_DIR/scripts/tailscale-dns.sh"; then
      ok "acceso remoto Tailscale OK"
    else
      bad "acceso remoto Tailscale con fallos (detalle arriba)"
    fi
  else
    bad "falta scripts/tailscale-dns.sh (o no es ejecutable)"
  fi
else
  warn "tailscale no instalado; omito la comprobacion de acceso remoto"
fi

info "Puertos"
if command -v ss >/dev/null; then
  for p in 80 443 8080 8443 8088; do
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
