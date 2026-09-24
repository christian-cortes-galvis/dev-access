#!/usr/bin/env bash
# Google Web: centro-apoyo/assets, sapg/assets e historiasclinicas -> NAS
# Reemplaza scripts/servidor_google_web.bat + texts/script_google_web.txt
# Tarea DESHABILITADA en el catálogo: no entra al cron. El destino ya no es OneDrive.
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "google-web"
load_credentials

G_HOST="$GOOGLE_WEB_HOST"
G_PORT="${GOOGLE_WEB_PORT:-22}"
G_USER="$GOOGLE_WEB_USER"
G_KEY="$BACKUPCSR_KEYS/google"

# Espeja <raíz>/<leaf> del VPS a NAS/google-web/<grupo>/<leaf>. El grupo fija la raíz
# remota: cada directorio se declara una sola vez y origen/destino no pueden desviarse.
mirror_google() {
	local group="$1" leaf="$2" root
	case "$group" in
		CHEQUEOS) root="/var/www/html/centro-apoyo/assets" ;;
		SAPG) root="/var/www/html/sapg/assets" ;;
		*) die "google-web: grupo desconocido '$group'" ;;
	esac
	mirror_sftp "$G_HOST" "$G_PORT" "$G_USER" "$G_KEY" \
		"$root/$leaf" "$BACKUPCSR_NAS_ROOT/google-web/$group/$leaf"
}

# Centro de apoyo -> NAS/google-web/CHEQUEOS
for leaf in \
	archivosAdjuntos \
	comprobantes_ordenes_compras \
	documentacion_gestion_humana \
	evidencias \
	evidenciasEventos \
	firmasColaboradores \
	ordenesCompras \
	reporte_informes_documentacion_empleados \
	reportes_cartera \
	reportes_proveedores_compras \
	solicitudes_ausencia_gh \
	"solicitudes_contrato_gestión_humana"; do
	mirror_google CHEQUEOS "$leaf"
done

# Planes de gestión -> NAS/google-web/SAPG
for leaf in \
	analisis_riesgos \
	img \
	mapas_riesgos \
	no_conformidades \
	uploads \
	uploads_consolidados; do
	mirror_google SAPG "$leaf"
done

# Historias clínicas -> NAS/google-web/historiasClinicas/files
mirror_sftp "$G_HOST" "$G_PORT" "$G_USER" "$G_KEY" \
	"/var/www/html/historiasclinicas/files" "$BACKUPCSR_NAS_ROOT/google-web/historiasClinicas/files"

log "=== fin google-web ==="
