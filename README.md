# cortexdev-access

Capa de acceso de la infraestructura `*.cortexdev.lan`: portal/índice, CA local y dashboards
de infraestructura. Vive en **ubuntu-services** (192.168.0.49), que está siempre encendida, para
que reiniciar `ubuntu-docker` (192.168.0.87, donde corren las apps) no deje sin portal ni DNS.

## Contenido

```
docker-compose.yml                 # nginx:stable, network_mode host, 80/443
nginx/conf.d/
  index.conf                       # index.cortexdev.lan  → portal/
  ca.conf                          # ca.cortexdev.lan     → ca.pem
  infra.conf                       # pihole, proxmox, backups/pbs, uptime/kuma, netdata-*
portal/                            # índice estático (HTML/CSS/JS, favicons, iconos)
certs/                             # gitignored; wildcard *.cortexdev.lan + CA (install-certs.sh)
systemd/access-ingress.service.template
scripts/install-certs.sh
scripts/deploy.sh
```

## Requisitos en ubuntu-services

- Docker + Docker Compose v2, con el servicio habilitado al arranque (`systemctl is-enabled docker`).
- Pi-hole en Docker: su UI web debe salir de 80/443 para dejar esos puertos a este nginx.
  En su compose, publicar `8080:80` y `8443:443` (los puertos internos del contenedor no cambian)
  y `restart: unless-stopped`. `infra.conf` proxifica `pihole.cortexdev.lan` a `127.0.0.1:8443`.
- Los certificados (no están en git).

## Puesta en marcha

```bash
# 1. Clonar
git clone <REMOTE_URL> ~/cortexdev-access
cd ~/cortexdev-access

# 2. Instalar certificados (scp desde ubuntu-docker, una vez)
scripts/install-certs.sh
#    o: scripts/install-certs.sh usuario@otro-host:/ruta/certs

# 3. Levantar nginx de acceso (requiere 80/443 libres)
docker compose up -d

# 4. Autostart (opcional, recomendado)
INSTALL_SYSTEMD=1 scripts/deploy.sh
```

## Actualizar

```bash
scripts/deploy.sh                 # git pull + docker compose up -d
```

## DNS en Pi-hole (192.168.0.49)

En `misc.dnsmasq_lines` el wildcard manda las apps a ubuntu-docker; estos overrides mandan la
capa de acceso a ubuntu-services (dnsmasq usa la coincidencia más específica):

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

## Seguridad

- `certs/` está en `.gitignore`: **nunca** subir `.pem`/llaves privadas, ni siquiera en un repo
  privado. Si la llave se filtra, regenerar el wildcard con `mkcert` y volver a instalar la CA
  en los equipos.
- El repo debe ser **privado**.
