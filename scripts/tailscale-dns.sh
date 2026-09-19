#!/usr/bin/env bash
#
# Verifica que los dominios *.cortexdev.lan funcionen desde la VPN Tailscale.
# Se ejecuta EN ubuntu-services: scripts/tailscale-dns.sh
#
# No modifica nada. Comprueba:
#   1. tailscale activo y con la subred 192.168.0.0/24 anunciada/aprobada
#   2. split DNS (restricted nameserver): cortexdev.lan -> 192.168.0.49
#   3. Pi-hole con dns.listeningMode = ALL (responde consultas del tailnet)
#   4. resolucion de index/app-admin via MagicDNS (100.100.100.100)
#
# Variables:
#   ACCESS_IP   IP de la capa de acceso (default 192.168.0.49)
#   APPS_IP     IP de las apps (default 192.168.0.87)
#   DNS_DOMAIN  dominio del tailnet a comprobar (default cortexdev.lan)
#
set -uo pipefail

ACCESS_IP="${ACCESS_IP:-192.168.0.49}"
APPS_IP="${APPS_IP:-192.168.0.87}"
DNS_DOMAIN="${DNS_DOMAIN:-cortexdev.lan}"
MAGICDNS_IP="100.100.100.100"

FAIL=0

info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m %s\n' "$*"; FAIL=1; }
warn() { printf '  \033[1;33mWARN\033[0m %s\n' "$*"; }

if ! command -v tailscale >/dev/null 2>&1; then
  warn "tailscale no instalado en esta maquina; omito la verificacion de acceso remoto"
  exit 0
fi

info "1/4 Estado de Tailscale"
if ! tailscale status >/dev/null 2>&1; then
  bad "tailscale no responde (demonio caido o sin login)"
  tailscale status 2>&1 | head -n 5 || true
  exit 1
fi

node_ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
ok "nodo local: ${node_ip:-?}"

routes="$(tailscale status --json 2>/dev/null | tr -d '\n ' | grep -o '"PrimaryRoutes":\[[^]]*\]' || true)"
if printf '%s' "$routes" | grep -q "192\.168\.0\.0/24"; then
  ok "subred 192.168.0.0/24 anunciada y aprobada"
else
  bad "este nodo no anuncia/aprueba 192.168.0.0/24"
  printf '       Revisa: tailscale status --json | grep PrimaryRoutes\n'
  printf '       Aprueba la ruta en https://console.tailscale.com/admin/machines\n'
fi

info "2/4 Split DNS de Tailscale (${DNS_DOMAIN})"
dns_status="$(tailscale dns status 2>/dev/null || true)"
if [ -z "$dns_status" ]; then
  warn "no pude leer 'tailscale dns status'"
else
  split_line="$(printf '%s\n' "$dns_status" | grep -E "^[[:space:]]*-[[:space:]]*${DNS_DOMAIN}\.?" | head -n 1 || true)"
  if [ -z "$split_line" ]; then
    bad "no hay restricted nameserver (split DNS) para ${DNS_DOMAIN}"
    printf '       Consola: https://console.tailscale.com/admin/dns\n'
    printf '       Add nameserver -> Custom -> %s, restrict to domain %s\n' "$ACCESS_IP" "$DNS_DOMAIN"
    printf '       No actives "Override DNS servers".\n'
  elif printf '%s' "$split_line" | grep -q "$ACCESS_IP"; then
    ok "split DNS ${DNS_DOMAIN} -> $ACCESS_IP"
  else
    bad "el split DNS de ${DNS_DOMAIN} no apunta a $ACCESS_IP"
    printf '       linea actual: %s\n' "$split_line"
  fi
fi

info "3/4 Pi-hole (escucha de consultas del tailnet)"
if ! command -v pihole-FTL >/dev/null 2>&1; then
  warn "pihole-FTL no disponible en este host; no verifico dns.listeningMode"
else
  mode="$(sudo -n pihole-FTL --config dns.listeningMode 2>/dev/null || true)"
  if [ -z "$mode" ]; then
    warn "no pude leer dns.listeningMode sin contrasena; ejecuta: sudo pihole-FTL --config dns.listeningMode"
  elif printf '%s' "$mode" | grep -qiE '"?ALL"?'; then
    ok "dns.listeningMode = $mode"
  else
    bad "dns.listeningMode = $mode (debe ser ALL para consultas del tailnet 100.64.0.0/10)"
    printf '       sudo pihole-FTL --config dns.listeningMode ALL\n'
    printf '       sudo systemctl restart pihole-FTL\n'
  fi
fi

info "4/4 Resolucion via MagicDNS (${MAGICDNS_IP})"
dig_answer() {
  local name="$1" out=""
  for _ in 1 2 3 4; do
    out="$(dig +short "$name" @"$MAGICDNS_IP" +time=2 +tries=1 2>/dev/null || true)"
    [ -n "$out" ] && break
    sleep 1
  done
  printf '%s' "$out"
}

if ! command -v dig >/dev/null; then
  warn "dig no instalado; no verifico la resolucion"
else
  for pair in "index.${DNS_DOMAIN}:${ACCESS_IP}" "app-admin.${DNS_DOMAIN}:${APPS_IP}"; do
    name="${pair%%:*}"
    want="${pair##*:}"
    r="$(dig_answer "$name")"
    if [ "$r" = "$want" ]; then
      ok "$name -> $want"
    else
      bad "$name -> ${r:-sin respuesta} (esperado $want)"
      printf '       Si falla solo aqui, revisa el split DNS y misc.dnsmasq_lines (scripts/dns-overrides.sh)\n'
    fi
  done
fi

echo
if [ "$FAIL" = "0" ]; then
  printf '\033[1;32mAcceso remoto Tailscale OK\033[0m\n'
else
  printf '\033[1;31mHay fallos: los .cortexdev.lan no funcionaran bien por Tailscale\033[0m\n'
  exit 1
fi
