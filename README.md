# cortexdev-access

Capa de acceso de la infraestructura `*.cortexdev.lan`: portal/índice, CA local y dashboards
de infraestructura. Vive en **ubuntu-services** (192.168.0.49), que está siempre encendida, para
que reiniciar `ubuntu-docker` (192.168.0.87, donde corren las apps) no deje sin portal ni DNS.

## Contenido

```
docker-compose.yml                 # nginx:stable + portal-api, network_mode host
nginx/conf.d/
  index.conf                       # index.cortexdev.lan  → portal/ + /api/
  ca.conf                          # ca.cortexdev.lan     → ca.pem
  infra.conf                       # pihole, proxmox, backups/pbs, uptime/kuma, netdata-*
portal/                            # portal (shells HTML + render.js, favicons, iconos)
backend/                           # portal-api: FastAPI + SQLite (catalogo y estado)
backend/catalog.yml                # catalogo de servicios (fuente de verdad, se edita aqui)
certs/                             # gitignored; wildcard *.cortexdev.lan + CA (install-certs.sh)
systemd/access-ingress.service.template
scripts/install-certs.sh
scripts/dns-overrides.sh           # overrides DNS de la capa de acceso en Pi-hole (idempotente)
scripts/deploy.sh
scripts/check.sh
scripts/setup-services.sh
```

## Requisitos en ubuntu-services

- Docker + Docker Compose v2, con el servicio habilitado al arranque (`systemctl is-enabled docker`).
- Pi-hole (nativo o Docker) debe soltar 80/443 para dejárselos a este nginx:
  - **nativo (v6)**: `sudo pihole-FTL --config webserver.port '8080o,8443s'` y `sudo systemctl restart pihole-FTL`.
  - **Docker**: publicar `8080:80` y `8443:443` en su compose y recrear con `docker compose up -d`
    (no `restart`), con `restart: unless-stopped`.
  `infra.conf` proxifica `pihole.cortexdev.lan` a `127.0.0.1:8443`.
- Los certificados (no están en git).

## Puesta en marcha

```bash
# 1. Clonar
git clone <REMOTE_URL> ~/cortexdev-access
cd ~/cortexdev-access

# 2. Instalar certificados (scp desde ubuntu-docker, una vez)
scripts/install-certs.sh
#    o: scripts/install-certs.sh usuario@otro-host:/ruta/certs
```

`install-certs.sh` se ejecuta **sin `sudo`**: así usa tus claves y tu `known_hosts`. Acepta el
host nuevo automáticamente (`StrictHostKeyChecking=accept-new`). Si `ubuntu-services` aún no tiene
acceso SSH a `ubuntu-docker`, autoriza su clave primero (o usa un origen local
`scripts/install-certs.sh /ruta/local`).

```bash
# 3. Levantar nginx de acceso (requiere 80/443 libres)
docker compose up -d

# 4. Autostart (opcional, recomendado)
INSTALL_SYSTEMD=1 scripts/deploy.sh
```

## Actualizar

```bash
scripts/deploy.sh                 # git pull + docker compose up -d --build
```

## Validar

En `ubuntu-services`:

```bash
scripts/check.sh
```

Comprueba certificados, que `access_nginx` esté corriendo, respuestas `200` de `index`/`ca` por HTTP
local (con `Host`, sin depender del DNS), los overrides DNS en Pi-hole y los puertos 80/443.
Equivalente manual:

```bash
curl -sk -o /dev/null -w '%{http_code}\n' -H 'Host: index.cortexdev.lan' https://127.0.0.1/  # 200
curl -sk -o /dev/null -w '%{http_code}\n' -H 'Host: ca.cortexdev.lan' https://127.0.0.1/cortexdev-lan-ca.crt  # 200
dig +short index.cortexdev.lan @127.0.0.1      # 192.168.0.49
dig +short app-admin.cortexdev.lan @127.0.0.1  # 192.168.0.87
```

Desde cualquier equipo de la LAN: `https://index.cortexdev.lan` (sin `-k` si ya confía en la CA).
Si `index` devuelve `403`, Pi-hole sigue ocupando el 443: remapea su UI a `8080/8443`.

### Puesta en marcha todo-en-uno

Si prefieres un solo paso (idempotente), en `ubuntu-services`:

```bash
scripts/setup-services.sh
```

Instala certs si faltan, detecta Pi-hole y libera 80/443 (modo host o bridge), levanta el compose,
aplica los overrides DNS con `scripts/dns-overrides.sh` y valida con `scripts/check.sh`.

## DNS en Pi-hole (192.168.0.49)

En `misc.dnsmasq_lines` el wildcard manda las apps a ubuntu-docker; estos overrides mandan la
capa de acceso a ubuntu-services (dnsmasq usa la coincidencia más específica).
`scripts/dns-overrides.sh` los aplica automáticamente (backup de `pihole.toml`, escritura vía
`pihole-FTL --config`, `reloaddns` y verificación con `dig`; idempotente):

```
address=/index.cortexdev.lan/192.168.0.49
address=/ca.cortexdev.lan/192.168.0.49
address=/pihole.cortexdev.lan/192.168.0.49
address=/proxmox.cortexdev.lan/192.168.0.49
address=/backups.cortexdev.lan/192.168.0.49
address=/pbs.cortexdev.lan/192.168.0.49
address=/uptime.cortexdev.lan/192.168.0.49
address=/kuma.cortexdev.lan/192.168.0.49
address=/netdata-services.cortexdev.lan/192.168.0.49
address=/netdata-backups.cortexdev.lan/192.168.0.49
address=/netdata-proxmox.cortexdev.lan/192.168.0.49
address=/netdata-docker.cortexdev.lan/192.168.0.49
```

Y mantener el wildcard a las apps:

```
address=/cortexdev.lan/192.168.0.87
```

## Portal dinámico (catálogo + estado)

El portal ya no lleva las listas hardcodeadas: `portal-api` (contenedor `portal_api`, FastAPI +
SQLite) guarda el catálogo de servicios y comprueba su estado.

- Catálogo: `backend/catalog.yml` es la fuente de verdad. Al arrancar (y en cada
  `scripts/deploy.sh`) se sincroniza por `slug` con `/data/portal.db`; los servicios que se
  quitan del YAML se desactivan (no se borra el histórico).
- Sondeos: cada `POLL_INTERVAL` (30s) `portal_api` hace GET contra la URL pública de cada
  servicio (`probe_url` opcional), sin seguir redirecciones, con timeout de `PROBE_TIMEOUT`.
  Un código en `accept` es online (2xx) o login (3xx/401/403); timeout, error o 5xx = offline.
  Los Netdata usan `/api/v1/info` para no cargar el dashboard.
- API (bajo `index.cortexdev.lan/api/`, bind local `127.0.0.1:8088`):
  - `GET /api/health` → estado de la BD.
  - `GET /api/portal` → catálogo + categorías + estado + `uptime_24h`.
  - `GET /api/status[?refresh=1]` → solo estados, para el refresco del navegador (cada 20s).
- Histórico: tabla `checks` con retención de 7 días (`RETENTION_DAYS`); el portal muestra el %
  de disponibilidad 24h.
- Frontend: `portal/render.js` pinta tablas, tarjetas y contadores desde `/api/portal` y
  refresca los pills desde `/api/status`. Si `portal_api` cae, las páginas cargan con un aviso.
- Añadir/editar servicios: editar `backend/catalog.yml` y ejecutar `scripts/deploy.sh`
  (idempotente). No hay que tocar los HTML.

Variables de `portal_api` (compose): `DB_PATH`, `CATALOG_PATH`, `CA_PATH` (CA local para
verificar TLS), `POLL_INTERVAL`, `PROBE_TIMEOUT`, `RETENTION_DAYS`.

## Seguridad

- `certs/` está en `.gitignore`: **nunca** subir `.pem`/llaves privadas, ni siquiera en un repo
  privado. Si la llave se filtra, regenerar el wildcard con `mkcert` y volver a instalar la CA
  en los equipos.
- El repo debe ser **privado**.
