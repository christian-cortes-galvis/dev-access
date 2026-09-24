#!/usr/bin/env bash
# Google Web: centro-apoyo/assets, sapg/assets, historiasclinicas -> OneDrive
# Reemplaza scripts/servidor_google_web.bat + texts/script_google_web.txt
set -euo pipefail
. "${BACKUPCSR_LIB:-/opt/backupcsr/lib/common.sh}"

job_init "google-web"
load_credentials

G_HOST="$GOOGLE_WEB_HOST"
G_PORT="${GOOGLE_WEB_PORT:-22}"
G_USER="$GOOGLE_WEB_USER"
G_KEY="$BACKUPCSR_KEYS/google"

# Centro de apoyo -> Backup CSR/CHEQUEOS
mirror_sftp_pairs "$G_HOST" "$G_PORT" "$G_USER" "$G_KEY" \
	"/var/www/html/centro-apoyo/assets/archivosAdjuntos" "$JOB_STAGING/CHEQUEOS/archivosAdjuntos" \
	"/var/www/html/centro-apoyo/assets/comprobantes_ordenes_compras" "$JOB_STAGING/CHEQUEOS/comprobantes_ordenes_compras" \
	"/var/www/html/centro-apoyo/assets/documentacion_gestion_humana" "$JOB_STAGING/CHEQUEOS/documentacion_gestion_humana" \
	"/var/www/html/centro-apoyo/assets/evidencias" "$JOB_STAGING/CHEQUEOS/evidencias" \
	"/var/www/html/centro-apoyo/assets/evidenciasEventos" "$JOB_STAGING/CHEQUEOS/evidenciasEventos" \
	"/var/www/html/centro-apoyo/assets/firmasColaboradores" "$JOB_STAGING/CHEQUEOS/firmasColaboradores" \
	"/var/www/html/centro-apoyo/assets/ordenesCompras" "$JOB_STAGING/CHEQUEOS/ordenesCompras" \
	"/var/www/html/centro-apoyo/assets/reporte_informes_documentacion_empleados" "$JOB_STAGING/CHEQUEOS/reporte_informes_documentacion_empleados" \
	"/var/www/html/centro-apoyo/assets/reportes_cartera" "$JOB_STAGING/CHEQUEOS/reportes_cartera" \
	"/var/www/html/centro-apoyo/assets/reportes_proveedores_compras" "$JOB_STAGING/CHEQUEOS/reportes_proveedores_compras" \
	"/var/www/html/centro-apoyo/assets/solicitudes_ausencia_gh" "$JOB_STAGING/CHEQUEOS/solicitudes_ausencia_gh" \
	"/var/www/html/centro-apoyo/assets/solicitudes_contrato_gestión_humana" "$JOB_STAGING/CHEQUEOS/solicitudes_contrato_gestión_humana"

# Planes de gestión -> Backup CSR/SAPG
mirror_sftp_pairs "$G_HOST" "$G_PORT" "$G_USER" "$G_KEY" \
	"/var/www/html/sapg/assets/analisis_riesgos" "$JOB_STAGING/SAPG/analisis_riesgos" \
	"/var/www/html/sapg/assets/img" "$JOB_STAGING/SAPG/img" \
	"/var/www/html/sapg/assets/mapas_riesgos" "$JOB_STAGING/SAPG/mapas_riesgos" \
	"/var/www/html/sapg/assets/no_conformidades" "$JOB_STAGING/SAPG/no_conformidades" \
	"/var/www/html/sapg/assets/uploads" "$JOB_STAGING/SAPG/uploads" \
	"/var/www/html/sapg/assets/uploads_consolidados" "$JOB_STAGING/SAPG/uploads_consolidados"

# Historias clínicas -> Backup CSR/historiasClinicas
mirror_sftp_pairs "$G_HOST" "$G_PORT" "$G_USER" "$G_KEY" \
	"/var/www/html/historiasclinicas/files" "$JOB_STAGING/historiasClinicas/files"

publish_onedrive "$JOB_STAGING/CHEQUEOS" "$ONEDRIVE_ROOT/CHEQUEOS"
publish_onedrive "$JOB_STAGING/SAPG" "$ONEDRIVE_ROOT/SAPG"
publish_onedrive "$JOB_STAGING/historiasClinicas" "$ONEDRIVE_ROOT/historiasClinicas"

log "=== fin google-web ==="
