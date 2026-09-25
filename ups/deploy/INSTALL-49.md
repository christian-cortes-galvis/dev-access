# Instalar el dashboard UPS en ubuntu-services (.49) — `cortexdev-access`

Guía operativa para mover la UPS desde ubuntu-docker (.87) a la capa de acceso (.49).
El diseño y el detalle completo están en `deploy/PLAN.md`.

Decisión de esta migración:

- `.49` es la **única** instancia; se retira de `.87`.
- Código fuente **solo** en `~/cortexdev-access/ups/`.
- Se sirve **solo** `ups.cortexdev.win` (sin `.lan`, sin portal).
- Se **migra** el histórico SQLite.

Contenido de `ups/` al transferir:

```
ups/
  Dockerfile  requirements.txt  main.py  collector.py  db.py  .dockerignore
  web/{index.html,app.js,styles.css,favicon.png,vendor/chart.umd.min.js}
  deploy/
    PLAN.md                 # plan completo
    INSTALL-49.md           # este archivo
    ups.conf                # vhost nginx (va a nginx/conf.d/)
    compose.ups_app.yml     # bloque de servicio a pegar en docker-compose.yml
    gitignore.append        # lineas a anadir al .gitignore del repo
    export-db-87.sh         # (se corre en .87)
    import-db-49.sh         # (se corre en .49)
```

---

## 0. Transferir `ups/` de .87 a .49

Desde **.49** (sí hay SSH `.49 -> .87`):

```bash
rsync -avc -e ssh --exclude '__pycache__' --exclude 'plan_mejora*.md' \
  christian@192.168.0.87:/home/christian/dev/ups/ \
  ~/cortexdev-access/ups/
```

Verificar que `~/cortexdev-access/ups/Dockerfile` y `ups/web/index.html` existen, y que
`index.html` contiene el rediseño (`grep -c hero-value ups/web/index.html`).

---

## 1. Servicio en el compose

En `~/cortexdev-access/docker-compose.yml`, dentro de `services:`, pegar el bloque de
`ups/deploy/compose.ups_app.yml` (sin reemplazar el resto del archivo).

Confirmar que `8484` está libre antes de levantar:

```bash
ss -ltnp | grep :8484 || echo "8484 libre"
```

## 2. .gitignore

Añadir a `~/cortexdev-access/.gitignore` las líneas de `ups/deploy/gitignore.append`:

```
ups/data/
ups/__pycache__/
```

## 3. Vhost nginx

Copiar el vhost y **adaptar las rutas de certificado** a las que usa el `.win` existente
(comparar con `nginx/conf.d/index.conf`):

```bash
cp ups/deploy/ups.conf nginx/conf.d/ups.conf
$EDITOR nginx/conf.d/ups.conf   # ajustar ssl_certificate / ssl_certificate_key
```

## 4. Levantar y validar en local (aún sin tocar DNS)

```bash
cd ~/cortexdev-access
docker compose config -q
docker compose build ups_app
docker compose up -d ups_app

# nombre real del contenedor nginx de acceso (ajustar si difiere):
docker compose exec access_nginx nginx -t
docker compose exec access_nginx nginx -s reload

curl -s http://127.0.0.1:8484/healthz
curl -s http://127.0.0.1:8484/api/summary
curl -sk -H 'Host: ups.cortexdev.win' https://127.0.0.1/healthz
curl -sk -o /dev/null -w '%{http_code}\n' -H 'Host: ups.cortexdev.win' https://127.0.0.1/
curl -sk -o /dev/null -w '%{http_code}\n' -H 'Host: ups.cortexdev.win' https://127.0.0.1/cgi-bin/nut/upsset.cgi
```

Esperado: `status:ok` con `stale:false`, `200` en `/` y `403` en `upsset.cgi`.
El `source` será `http` mientras no se exponga `upsd` en la PVE (igual que en .87).

## 5. Migrar el histórico

En **.87**:

```bash
bash /home/christian/dev/ups/deploy/export-db-87.sh
```

En **.49**:

```bash
cd ~/cortexdev-access
bash ups/deploy/import-db-49.sh
docker compose restart ups_app
curl -s 'http://127.0.0.1:8484/api/history?metric=battery_charge&range=30d' | head -c 300
```

## 6. DNS en Pi-hole (.49)

Añadir el override conservando los existentes en `misc.dnsmasq_lines`:

```
address=/ups.cortexdev.win/192.168.0.49
```

- Si existe `scripts/dns-overrides.sh`, agregar `ups.cortexdev.win` a su lista y reejecutarlo.
- Manual (Pi-hole v6): reescribir el array completo con
  `sudo pihole-FTL --config misc.dnsmasq_lines '[ ...existentes..., "address=/ups.cortexdev.win/192.168.0.49" ]'`
  y luego `sudo pihole reloaddns`.

Verificar:

```bash
dig +short ups.cortexdev.win @192.168.0.49        # -> 192.168.0.49
dig +short app-admin.cortexdev.win @192.168.0.49  # -> 192.168.0.87 (intacto)
```

## 7. Validar en navegador

- `https://ups.cortexdev.win` carga el dashboard rediseñado.
- LIVE se actualiza (WebSocket), `/healthz` con `stale:false`.
- El histórico muestra datos anteriores al corte.
- `upsset.cgi` sigue en 403.

---

## 8. Retirar de .87 (solo tras validar .49)

En **.87** (`/home/christian/dev`):

```bash
docker compose stop ups_app
docker compose rm -f ups_app
```

Luego:

1. `docker-compose.yml`: borrar el servicio `ups_app` y la entrada `ups_data` de `volumes:`.
2. Borrar `nginx/conf.d/ups.conf`.
3. `docker exec nginx_web nginx -t` y `docker exec nginx_web nginx -s reload`.
4. `docker volume rm dev_ups_data` (ya migrado).
5. `git rm -r ups` (la fuente vive solo en `cortexdev-access`).
6. `docker compose up -d nginx` y confirmar que el resto de apps sigue `Up`.

> No hacer este paso hasta que el paso 7 esté validado y el histórico confirmado.

## Rollback

- DNS: quitar `address=/ups.cortexdev.win/192.168.0.49` y `sudo pihole reloaddns`.
- App: `docker compose stop ups_app` en `.49` (no toca el resto de la capa de acceso).
- .87: restaurar desde `9d092d9` (`git checkout 9d092d9 -- ups` + servicio + `ups.conf`).
- Histórico: `ups_data.tgz` queda en `.87:/tmp/ups-migrate` y en `.49`.

## Riesgos / a confirmar

- `access_nginx` debe ser `network_mode: host` para que `127.0.0.1:8484` funcione. Verificar:
  `docker inspect access_nginx --format '{{.HostConfig.NetworkMode}}'`.
  Si fuera bridge, publicar `ups_app` en el host y usar `host.docker.internal:8484`.
- Ruta real de los certificados `.win` (paso 3).
- Nombre real del contenedor nginx de acceso (paso 4).
