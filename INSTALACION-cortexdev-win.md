# Runbook: certificado público comodín `*.cortexdev.win` (capa de acceso)

Todos los comandos de este runbook se ejecutan **EN `ubuntu-services` (192.168.0.49)** salvo
donde se indique el panel web.

- Capa de acceso (este repo): `ubuntu-services` = `192.168.0.49`.
- Apps: `ubuntu-docker` = `192.168.0.87` (Fase 2).
- `access_nginx` corre con `network_mode: host` y bindea 80/443.
- Certificados (gitignored):
  - mkcert: `certs/cortexdev.lan/{cortexdev.lan.pem,cortexdev.lan-key.pem,ca.pem}`
  - Let's Encrypt: `certs/cortexdev.win/{fullchain.pem,key.pem}`
- Dominios internos: `cortexdev.lan` (sigue vigente) y `cortexdev.win` (cert público).
- Emisión: **DNS-01 con Cloudflare** (comodín; no se exponen 80/443).

> Importante: el repo ya tiene el código listo (nginx, scripts, systemd, README). Este runbook
> cubre los pasos que requieren **token de Cloudflare, `sudo` o la consola de Tailscale**.

---

## 0. Comprobaciones previas

```bash
cd ~/cortexdev-access

# Estás en ubuntu-services
hostname -I | grep -q 192.168.0.49 && echo "host OK"

# Servicios vivos
docker ps --format '{{.Names}}\t{{.Status}}'
docker exec access_nginx nginx -t

# El DNS público NO debe tener A/AAAA de servicio (ver sección 1)
dig +short cortexdev.win A @1.1.1.1
dig +short index.cortexdev.win A @1.1.1.1
dig +short aleatorio.cortexdev.win A @1.1.1.1   # si responde, hay wildcard público
dig +short cortexdev.win NS @1.1.1.1
dig +short cortexdev.win CAA @1.1.1.1
```

Estado del certificado `.win`:

```bash
scripts/install-win-cert.sh --status
```

Si no hay cert, `deploy.sh`/`setup-services.sh` generan un **provisional autofirmado** para que
nginx arranque; los navegadores avisarán hasta emitir el real.

---

## 1. Cloudflare: limpiar la zona y crear el token

### 1.1 Borrar registros A/AAAA públicos

En el panel de Cloudflare, zona `cortexdev.win`, **eliminar** cualquier registro de servicio,
en particular el wildcard y el apex:

- `*.cortexdev.win A 192.168.0.87`
- `cortexdev.win A 192.168.0.87`
- cualquier `A`/`AAAA` de hosts internos (`index`, `pihole`, `admin-portal-pacientes`, …)

Debe quedar solo `NS`, `SOA` y, durante la emisión, el `TXT _acme-challenge` temporal.

Por API (necesitas un token con `Zone:DNS:Edit`; el mismo que usarás para ACME):

```bash
export CF_TOKEN='**************************'
ZONE_ID="$(curl -s -H "Authorization: Bearer $CF_TOKEN" \
  'https://api.cloudflare.com/client/v4/zones?name=cortexdev.win' | jq -r '.result[0].id')"
echo "ZONE_ID=$ZONE_ID"

# Listar registros
curl -s -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?per_page=100" \
  | jq -r '.result[] | "\(.id)\t\(.type)\t\(.name)\t\(.content)"'

# Borrar un registro por ID (repetir con cada A/AAAA/CNAME de servicio)
curl -s -X DELETE -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records/<RECORD_ID>" | jq .
```

### 1.2 Crear el API Token

Panel de Cloudflare → **My Profile → API Tokens → Create Token** → template
**Edit zone DNS** → Permissions `Zone / DNS / Edit` → Zone Resources `Include / Specific zone /
cortexdev.win`. Copia el token (se muestra una sola vez).

### 1.3 (Recomendado) Fijar CAA a Let's Encrypt

```bash
curl -s -X POST -H "Authorization: Bearer $CF_TOKEN" -H 'Content-Type: application/json' \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
  --data '{"type":"CAA","name":"cortexdev.win","ttl":1,"data":{"flags":0,"tag":"issue","value":"letsencrypt.org"}}' | jq .
```

Verificar:

```bash
dig +short cortexdev.win CAA @1.1.1.1
dig +short index.cortexdev.win @1.1.1.1   # debe quedar VACIO
dig +short cortexdev.win A @1.1.1.1       # debe quedar VACIO
```

---

## 2. Guardar la credencial de Cloudflare

```bash
sudo install -d -m 700 /etc/cortexdev
printf 'CF_Token=*************************************\n' | sudo tee /etc/cortexdev/acme.env >/dev/null
# Si la detección automática de zona falla, añade también:
#   CF_Account_ID=<account_id>
sudo chmod 600 /etc/cortexdev/acme.env
sudo ls -l /etc/cortexdev/acme.env      # -rw------- root root
```

El token debe tener `Zone:DNS:Edit` sobre `cortexdev.win`. **Nunca** lo pongas en el repo.

---

## 3. Emitir el certificado (acme.sh, DNS-01)

`scripts/install-win-cert.sh` instala acme.sh en `/root/.acme.sh` (sin cron propio; usamos el
timer de systemd) y emite/instala el comodín.

### 3.1 Ensayo en staging (evita el rate limit de producción)

```bash
sudo scripts/install-win-cert.sh --staging
```

Si sale bien, opcionalmente borra el cert de staging (no es obligatorio:
el paso real usa `--force` y sobrescribe la clave del ensayo):

```bash
sudo /root/.acme.sh/acme.sh --remove -d '*.cortexdev.win' --ecc \
  --server letsencrypt_test --home /root/.acme.sh
```

### 3.2 Emisión real e instalación

```bash
sudo scripts/install-win-cert.sh --issue
```

El script invoca acme.sh con `--force`, por lo que no falla aunque exista la clave de dominio
dejada por el ensayo en staging.
Esto:
1. emite `*.cortexdev.win` (EC-256) contra Let's Encrypt,
2. copia el par a `certs/cortexdev.win/{key.pem,fullchain.pem}` (key en `600`),
3. ejecuta `docker exec access_nginx nginx -s reload`.

Comprobar:

```bash
scripts/install-win-cert.sh --status
openssl x509 -in certs/cortexdev.win/fullchain.pem -noout -issuer -subject -ext subjectAltName
```

Debe mostrar issuer de Let's Encrypt y `DNS:*.cortexdev.win` (ya no autofirmado).

> La `key.pem` del comodín permite suplantar cualquier host de un nivel bajo `cortexdev.win`.
> Mantén `certs/` fuera de git y la key en `600`.

---

## 4. nginx (ya aplicado en el repo)

El repo sirve ambos dominios con **un `server` block por nombre** (nginx no selecciona por SNI
entre dos certs del mismo tipo en un bloque). Para desplegar:

```bash
scripts/deploy.sh
```

Verificación de SNI y respuestas (sin `-k`):

```bash
docker exec access_nginx nginx -t

for sn in index.cortexdev.lan index.cortexdev.win ca.cortexdev.win pihole.cortexdev.win; do
  printf '%-28s ' "$sn"
  echo | openssl s_client -connect 127.0.0.1:443 -servername "$sn" 2>/dev/null \
    | openssl x509 -noout -issuer
done

curl -sSI https://index.cortexdev.win/
curl -sSI https://ca.cortexdev.win/cortexdev-lan-ca.crt
curl -sSI https://pihole.cortexdev.win/admin/
```

---

## 5. Pi-hole: overrides DNS de `.win`

`scripts/dns-overrides.sh` escribe en `misc.dnsmasq_lines` el wildcard de apps y los overrides de
la capa de acceso para ambos dominios (idempotente, con backup de `pihole.toml`):

```
address=/cortexdev.win/192.168.0.87
address=/index.cortexdev.win/192.168.0.49
address=/ca.cortexdev.win/192.168.0.49
... (resto de HOSTS)
```

```bash
scripts/dns-overrides.sh        # pide sudo interactivo para pihole-FTL
```

Verificar:

```bash
dig +short index.cortexdev.win @127.0.0.1      # 192.168.0.49
dig +short app-admin.cortexdev.win @127.0.0.1  # 192.168.0.87 (wildcard apps)
```

---

## 6. Tailscale: split DNS para `.win`

En <https://console.tailscale.com/admin/dns>:

1. **Add nameserver → Custom → `192.168.0.49`**, restringido al dominio `cortexdev.win`
   (además del que ya existe para `cortexdev.lan`).
2. **No** actives "Override DNS servers".
3. Si algún equipo usa **exit node**, activa **"Use with exit node"** en ese nameserver.
4. Opcional: añade `cortexdev.win` a **Search domains**.

Las rutas no cambian: `192.168.0.0/24` ya está anunciada/aprobada.

Verificar (en `ubuntu-services` y luego desde un cliente):

```bash
scripts/tailscale-dns.sh
dig +short index.cortexdev.win @100.100.100.100   # 192.168.0.49
```

---

## 7. Renovación automática (systemd timer)

```bash
INSTALL_SYSTEMD=1 scripts/deploy.sh
systemctl list-timers | grep acme
sudo systemctl status acme-renew.timer --no-pager

# Prueba manual de la renovación
sudo scripts/acme-renew.sh
```

El `--reloadcmd` guardado por acme.sh recarga `access_nginx` al renovar.

---

## 8. Verificación final

```bash
scripts/check.sh              # debe terminar en "Todo OK"
scripts/tailscale-dns.sh      # split DNS y MagicDNS de ambos dominios

# Manual
dig +short index.cortexdev.win @127.0.0.1          # 192.168.0.49
curl -sSI https://index.cortexdev.win/             # 200 sin -k
curl -sSI https://ca.cortexdev.win/cortexdev-lan-ca.crt   # 200
openssl s_client -connect 192.168.0.49:443 -servername index.cortexdev.win  # issuer LE, SAN *.cortexdev.win
dig +short index.cortexdev.win @1.1.1.1            # vacio (NXDOMAIN)
dig +short cortexdev.win A @1.1.1.1                # vacio
```

Desde un Android/iOS **sin** la CA de mkcert instalada: abrir `https://index.cortexdev.win`
en la LAN y por Tailscale; no debe aparecer aviso de certificado.

---

## 9. Solución de problemas

| Síntoma | Causa / solución |
| --- | --- |
| `index.cortexdev.win` → `000` sin `-k` | Cert provisional autofirmado. Ejecuta `sudo scripts/install-win-cert.sh --issue`. |
| `.win` resuelve a `192.168.0.87` en la LAN | Faltan overrides de Pi-hole: `scripts/dns-overrides.sh`. |
| `.win` resuelve a `.87` fuera de la LAN | Falta el split DNS `cortexdev.win → 192.168.0.49` en Tailscale. |
| `nginx -t` falla por `/etc/nginx/certs/cortexdev.win/...` | Falta el par: `scripts/install-win-cert.sh` (provisional) o `--issue`. |
| SNI devuelve el cert equivocado | Debe haber un `server` block por dominio (ya en `nginx/conf.d`); no juntes ambos `ssl_certificate` en un bloque. |
| `Domain key exists, do you want to overwrite it?` al emitir | Clave dejada por el ensayo en staging. `scripts/install-win-cert.sh --issue` ya usa `--force`; si lo corres a mano, añade `--force`. |
| Emisión falla con error de Cloudflare | Token sin `Zone:DNS:Edit` sobre `cortexdev.win`, o `CF_Account_ID` necesario en `/etc/cortexdev/acme.env`. |
| `acme.sh --cron` no recarga nginx | `access_nginx` no está corriendo; el cert se instala igual y se recargará en el próximo arranque/deploy. |
| Aviso de certificado en las apps | Fase 2 (nginx de `ubuntu-docker`) aún en `.lan`; fuera de alcance. |

### Rollback

- nginx: revertir a los `server_name`/certs `.lan` (`git checkout` de `nginx/conf.d` + reload).
- DNS: `scripts/dns-overrides.sh` conserva un backup `pihole.toml.bak-<timestamp>` en
  `/etc/pihole/` para restaurar.
- Cert `.win`: borrar `certs/cortexdev.win/` y volver a generar el provisional si hace falta.

---

## 10. Seguridad

- `certs/`, `*.pem` y `*.key` están en `.gitignore`: **nunca** versionar llaves privadas.
- La key del comodín `certs/cortexdev.win/key.pem` (permisos `600`) permite suplantar cualquier
  host de un nivel bajo `cortexdev.win`. Ante filtración: revocar y reemitir con
  `sudo scripts/install-win-cert.sh --issue`.
- La zona pública solo debe tener `NS`/`SOA` (+ CAA) y el `TXT _acme-challenge` temporal.
  El comodín aparece en logs de Certificate Transparency, pero los hosts internos no.
- `.lan` y la CA de mkcert siguen vigentes como respaldo (Fase 2: retirarlos, fuera de alcance).
