# Mover el dashboard UPS de `.87` a `.49` (repo `cortexdev-access`)

## Objetivo

Ejecutar la UPS desde **ubuntu-services (192.168.0.49)**, en el repo `cortexdev-access`, y
**retirarla por completo de ubuntu-docker (.87)**. La capa de acceso está siempre encendida, así que
el monitoreo de la UPS sobrevive a los reinicios de `.87`. Se conserva el histórico SQLite.

## Decisiones confirmadas

| Decisión | Valor |
|---|---|
| Alcance | **Mover** (no espejo): `.49` es la única instancia; se retira de `.87` |
| Fuente de verdad del código | **Solo** en `cortexdev-access` (`~/cortexdev-access/ups/`); se elimina `ups/` del repo `dev` |
| Dominios | Solo `ups.cortexdev.win` (sin `.lan`, sin enlace en el portal) |
| Histórico | **Migrar** el `ups.db` (volumen `dev_ups_data` de `.87`) |
| Transferencia | El usuario la ejecuta: no hay SSH `.87 → .49`; sí funciona `.49 → .87` |
| Edición | Documentada aquí; la aplica el usuario en `.49` |

## Arquitectura resultante

```
Cliente LAN
  └─ ups.cortexdev.win → DNS Pi-hole (.49) → access_nginx (.49, host 80/443)
                                              ├─ /            → http://127.0.0.1:8484 (ups_app)
                                              └─ /cgi-bin/nut/ → http://192.168.0.224:80 (CGI clásico)

ups_app (.49, Docker, red bridge, publica 127.0.0.1:8484)
  ├─ colector: upsc → si falla, HTTP fallback a 192.168.0.224/cgi-bin/nut/upsstats.cgi
  ├─ SQLite ./ups/data/ups.db (histórico migrado)
  └─ sirve el frontend estático
```

`ups_app` corre en la red bridge del compose de acceso y publica **solo** `127.0.0.1:8484`; el nginx
de acceso (host network, igual que hoy llega a Pi-hole en `127.0.0.1:8443`) llega a `127.0.0.1:8484`
sin exponer nada a la LAN.

## Payload a transferir (versión del working tree, NO un git clone)

El rediseño de la página está **staged pero sin commit** en `.87`. Un `git clone` del repo `dev`
traería la versión vieja (`9d092d9`). Transferir el directorio tal cual:

```
ups/Dockerfile
ups/requirements.txt
ups/main.py
ups/collector.py
ups/db.py
ups/web/index.html
ups/web/app.js
ups/web/styles.css
ups/web/favicon.png          # opcional (1 MB, hoy sin uso: index.html usa SVG inline)
ups/web/vendor/chart.umd.min.js
```

**Excluir** `ups/__pycache__/` y opcionalmente `ups/plan_mejora*.md` (notas de diseño).

---

## Fase A — Transferir desde `.49` (recomendado)

Sin SSH `.87 → .49`; desde `.49` se tira de `.87`. Comparar el árbol (`-c`) para copiar exacto:

```bash
# en .49
rsync -avc -e ssh \
  --exclude '__pycache__' \
  --exclude 'plan_mejora*.md' \
  christian@192.168.0.87:/home/christian/dev/ups/ \
  ~/cortexdev-access/ups/

# si no hay rsync:
scp -r christian@192.168.0.87:/home/christian/dev/ups ~/cortexdev-access/
rm -rf ~/cortexdev-access/ups/__pycache__
```

Verificar que `~/cortexdev-access/ups/Dockerfile` y `ups/web/index.html` existen y que `index.html`
contiene el rediseño (busca `hero-value` o `Tiempo restante`).

---

## Fase B — Aplicar en `.49` (`~/cortexdev-access`)

### B1. Servicio en `docker-compose.yml`

Añadir el servicio (dejar el resto del archivo intacto; el nombre de red lo resuelve el compose):

```yaml
  ups_app:
    container_name: ups_app
    mem_limit: 128m
    build:
      context: ./ups
      dockerfile: Dockerfile
    environment:
      UPS_HOST: "192.168.0.224"
      UPS_NAME: "apc"
      POLL_INTERVAL: "30"
      DB_PATH: "/data/ups.db"
      SIMULATE: "0"
      HTTP_FALLBACK: "1"
    volumes:
      - ./ups/data:/data
    ports:
      - "127.0.0.1:8484:8484"
    healthcheck:
      test:
        - "CMD"
        - "python"
        - "-c"
        - "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8484/healthz', timeout=3).status == 200 else 1)"
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    restart: unless-stopped
```

Notas:
- Si el compose de acceso usa `network_mode: host` a nivel de archivo (`network_mode:` global), revisar
  cómo está montado; el objetivo es que `access_nginx` alcance `127.0.0.1:8484`. Con nginx host-network
  y este `ports:` en bridge, funciona.
- `./ups/data` es bind mount para que el `.db` sea visible y fácil de migrar; debe quedar gitignored.
- Verificar que `8484` está libre en `.49`: `ss -ltnp | grep :8484` (no debe salir nada antes de levantar).

### B2. `.gitignore` del repo de acceso

Añadir:

```
ups/data/
ups/__pycache__/
```

### B3. Vhost `nginx/conf.d/ups.conf`

Crear el archivo. **Adaptar la ruta de certificados**: copiar las dos líneas `ssl_certificate` /
`ssl_certificate_key` tal como estén en el vhost `.win` existente (`index.conf`) del repo de acceso.

```nginx
server {
    listen 80;
    server_name ups.cortexdev.win;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name ups.cortexdev.win;

    ssl_certificate     /etc/nginx/certs/cortexdev.win/cortexdev.win.pem;      # ADAPTAR
    ssl_certificate_key /etc/nginx/certs/cortexdev.win/cortexdev.win-key.pem;  # ADAPTAR

    # upsset.cgi (escritura) bloqueado, incluidas variantes con PATH_INFO
    location ~ ^/cgi-bin/nut/upsset\.cgi {
        return 403;
    }

    # NUT clásico (Apache/upsstats.cgi en la PVE)
    location /cgi-bin/nut/ {
        proxy_pass http://192.168.0.224:80;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    # Dashboard propio (mismo origen → /api y /api/ws relativos funcionan igual)
    location / {
        proxy_pass http://127.0.0.1:8484;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket (/api/ws)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

No hace falta `resolver` de Docker: el upstream es `127.0.0.1`.

### B4. Levantar y validar en local (antes de tocar DNS)

```bash
# en .49, ~/cortexdev-access
docker compose config -q
docker compose build ups_app
docker compose up -d ups_app
docker compose exec access_nginx nginx -t      # o el nombre real del contenedor nginx de acceso
docker compose exec access_nginx nginx -s reload

curl -s http://127.0.0.1:8484/healthz
curl -s http://127.0.0.1:8484/api/summary
curl -sk -H 'Host: ups.cortexdev.win' https://127.0.0.1/healthz
curl -sk -o /dev/null -w '%{http_code}\n' -H 'Host: ups.cortexdev.win' https://127.0.0.1/
```

Debe responder `{"status":"ok",...,"source":"http"}` (o `nut` si más adelante se expone `upsd`).
Probar también el CGI clásico: `curl -sk -H 'Host: ups.cortexdev.win' https://127.0.0.1/cgi-bin/nut/upsstats.cgi` → 200, y
`.../upsset.cgi` → 403, `.../upsset.cgi/x` → 403.

### B5. DNS en Pi-hole (`.49`)

Añadir el override conservando los existentes en `misc.dnsmasq_lines`:

```
address=/ups.cortexdev.win/192.168.0.49
```

- Si el repo de acceso ya tiene `scripts/dns-overrides.sh`, agregar `ups.cortexdev.win` a su lista y
  volver a ejecutarlo (idempotente).
- Manual (Pi-hole v6 nativo): leer el array actual, añadir la línea y reescribirlo con
  `sudo pihole-FTL --config misc.dnsmasq_lines '[ ...existentes..., "address=/ups.cortexdev.win/192.168.0.49" ]'`,
  luego `sudo pihole reloaddns`.

Verificar:

```bash
dig +short ups.cortexdev.win @192.168.0.49      # → 192.168.0.49
dig +short app-admin.cortexdev.win @192.168.0.49  # → 192.168.0.87 (no romper el resto)
```

### B6. Validación end-to-end (navegador)

- `https://ups.cortexdev.win` carga el dashboard rediseñado.
- `/healthz` → `stale:false`; el WS conecta (indicador LIVE se actualiza).
- `/api/history?metric=battery_charge&range=7d` devuelve puntos (histórico migrado).
- `/upsset.cgi` sigue bloqueado.

---

## Fase C — Retirar de `.87` (solo tras validar `.49`)

Orden importante: **primero** verificar que `.49` sirve y tiene el histórico; **después** limpiar `.87`.

```bash
# en .87, /home/christian/dev
docker compose stop ups_app
docker compose rm -f ups_app
```

1. `docker-compose.yml`: eliminar el servicio `ups_app` y la entrada `ups_data` de `volumes:`.
2. `nginx/conf.d/ups.conf`: eliminar (ya no se sirve la UPS desde `.87`).
3. Recargar nginx de apps: `docker exec nginx_web nginx -t && docker exec nginx_web nginx -s reload`.
4. Borrar el volumen ya migrado: `docker volume rm dev_ups_data`.
5. Eliminar el código del repo (fuente única en `cortexdev-access`): `git rm -r ups`
   (esto descarta también los cambios staged del rediseño, que ya viven en `.49`).
6. `docker compose up -d nginx` (por si el `depends_on`/red cambió) y confirmar que el resto de apps
   sigue `Up`.

> No ejecutar la Fase C hasta que la Fase B esté validada y la migración del histórico confirmada.

---

## Migración del histórico (`ups.db`)

Extraer en `.87` con la app detenida (para copiar WAL/SHM consistentes):

```bash
# en .87
docker compose stop ups_app
mkdir -p /tmp/ups-migrate
docker run --rm -v dev_ups_data:/data -v /tmp/ups-migrate:/backup alpine \
  sh -c "cd /data && tar czf /backup/ups_data.tgz ."
docker compose start ups_app        # opcional, para no dejar .87 caído durante el corte

# en .49
mkdir -p ~/cortexdev-access/ups/data
scp christian@192.168.0.87:/tmp/ups-migrate/ups_data.tgz /tmp/
tar xzf /tmp/ups_migrate.tgz -C ~/cortexdev-access/ups/data
ls -la ~/cortexdev-access/ups/data   # deben estar ups.db (y .db-wal/.db-shm si aplica)
```

Si `/tmp` queda justo, volcar el tar al propio `ups/` del repo (`/home/christian/dev/ups/`), que `.49`
puede traer en el mismo rsync de la Fase A.

Verificar en `.49` que el histórico aparece:
`curl -s 'http://127.0.0.1:8484/api/history?metric=battery_charge&range=30d' | head -c 300`

---

## Validación

| Comprobación | Comando / criterio |
|---|---|
| Compose válido | `docker compose config -q` en `~/cortexdev-access` |
| Nginx válido | `access_nginx nginx -t` |
| App viva | `curl -s http://127.0.0.1:8484/healthz` → `status:ok`, `stale:false` |
| Proxy + TLS | `curl -sk -H 'Host: ups.cortexdev.win' https://127.0.0.1/healthz` |
| DNS | `dig +short ups.cortexdev.win @192.168.0.49` → `.49`; wildcard intacto → `.87` |
| Histórico | `/api/history?...&range=30d` con datos anteriores al corte |
| WebSocket | Indicador LIVE en el navegador; sin errores en consola |
| Seguridad | `upsset.cgi` y `upsset.cgi/x` → 403; `upsstats.cgi` → 200 |
| `.87` limpio | `docker compose ps` sin `ups_app`; resto de apps `Up` |

## Rollback

- **DNS**: quitar `address=/ups.cortexdev.win/192.168.0.49` y `pihole reloaddns` → vuelve al wildcard
  (`.87`). Solo funciona si `.87` todavía no se limpió.
- **App en `.49`**: `docker compose stop ups_app`; el resto de la capa de acceso no se toca.
- **`.87`**: restaurar `ups_app`/`ups.conf` desde el commit `9d092d9` (`git checkout 9d092d9 -- ups`
  + servicio y `ups.conf`), reconstruir y recargar nginx.
- **Histórico**: el `.tgz` original queda en `.87` (`/tmp/ups-migrate`) y en `.49`; restaurar en el
  volumen si hace falta.

## Riesgos y notas

- **Transferencia de la versión correcta**: el rediseño está sin commit; usar rsync/scp del working
  tree, no `git clone`. Si se clona, hacer antes `git add -A && git commit` en `.87`.
- **Red de `access_nginx`**: si NO fuera host-network, `127.0.0.1:8484` apuntaría al propio contenedor
  nginx. Confirmar con `docker inspect access_nginx --format '{{.HostConfig.NetworkMode}}'`; si fuera
  bridge, publicar `ups_app` en el host y usar `host.docker.internal:8484` o la IP del gateway.
- **Ruta de certificados `.win`**: el vhost de B3 hay que ajustarlo a la convención del repo de acceso
  (copiar de `index.conf`); este plan no pudo inspeccionar ese repo.
- **`upsd` no expuesto**: el colector seguirá en `source:"http"` (scrape del CGI) como en `.87`. Exponer
  `upsd` en la PVE es un trabajo aparte y opcional.
- **Alcance de `.win`**: Pi-hole resuelve internamente; clientes que no usen Pi-hole/DNS interno seguirán
  yendo al wildcard. Si `ups` deja de existir en `.87`, esos clientes no verán la página (uso es LAN).
- **`favicon.png`** (1 MB) no se referencia hoy; se puede no copiar.
- **`nut/upsstats.html`** (tema opcional del CGI) queda fuera de alcance.

## Pendiente / adaptar al repo real

- Formato exacto y nombre del contenedor nginx de `cortexdev-access` (para `docker compose exec ...`).
- Rutas de certificado `.win` y si el repo ya tiene `scripts/dns-overrides.sh`.
- Confirmar que `access_nginx` corre con `network_mode: host`.
