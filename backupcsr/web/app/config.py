"""Configuración del portal de copias (env + rutas).

Todas las variables se leen de /etc/backupcsr/web.env (lo carga systemd vía
EnvironmentFile) o del entorno del proceso.
"""
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("backupcsr-web")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip() == "1"


# --- Runtime de backupcsr (mismas rutas que install.sh del subsistema) ---
ETC_DIR = Path(os.environ.get("BACKUP_ETC", "/etc/backupcsr"))
OPT_DIR = Path(os.environ.get("BACKUP_OPT", "/opt/backupcsr"))
LOG_DIR = Path(os.environ.get("BACKUP_LOG", "/var/log/backupcsr"))
NAS_MOUNT = Path(os.environ.get("BACKUP_NAS", "/mnt/nas"))
CRON_FILE = Path(os.environ.get("BACKUP_CRON", "/etc/cron.d/backupcsr"))
JOBS_DIR = OPT_DIR / "jobs"

# --- Directorio del proyecto (app/..) ---
WEB_DIR = Path(os.environ.get("BACKUP_WEB_DIR", str(Path(__file__).resolve().parent.parent)))
CATALOG_PATH = Path(os.environ.get("BACKUP_CATALOG", str(WEB_DIR / "jobs.yml")))
SCHEMA_PATH = Path(os.environ.get("BACKUP_SCHEMA", str(WEB_DIR / "schema.sql")))

# --- Base de datos MySQL ---
DB_HOST = os.environ.get("BACKUP_DB_HOST", "127.0.0.1")
DB_PORT = _int("BACKUP_DB_PORT", 3306)
DB_NAME = os.environ.get("BACKUP_DB_NAME", "backupcsr")
DB_USER = os.environ.get("BACKUP_DB_USER", "backupcsr_web")
DB_PASSWORD = os.environ.get("BACKUP_DB_PASSWORD", "")
DB_CONNECT_TIMEOUT = _int("BACKUP_DB_CONNECT_TIMEOUT", 5)

# --- Sesión ---
SECRET_KEY = os.environ.get("BACKUP_SECRET_KEY", "").strip()
_SECRET_GENERATED = False
if not SECRET_KEY:
    # Sin clave persistente las sesiones no sobreviven reinicios; se avisa fuerte.
    SECRET_KEY = secrets.token_hex(32)
    _SECRET_GENERATED = True
SESSION_COOKIE = "backupcsr_session"
SESSION_MAX_AGE = _int("BACKUP_SESSION_MAX_AGE", 12 * 3600)
# Cookie Secure: 1 por defecto (todo va por https vía nginx). Poner 0 solo para
# pruebas directas contra http://127.0.0.1:8089.
COOKIE_SECURE = _flag("BACKUP_COOKIE_SECURE", "1")

# --- Comportamiento ---
MANAGE_CRON = _flag("BACKUP_MANAGE_CRON")
TIMEZONE = os.environ.get("BACKUP_TZ", "America/Bogota")
POLL_INTERVAL = _int("BACKUP_POLL_INTERVAL", 30)
GRACE_MIN = _int("BACKUP_GRACE_MIN", 90)
MAX_RUN_FILES = _int("BACKUP_MAX_RUN_FILES", 5000)

# --- Tamaños (GB por tarea) ---
SIZE_TTL = _int("BACKUP_SIZE_TTL", 600)
SIZE_MAX_ENTRIES = _int("BACKUP_SIZE_MAX_ENTRIES", 500000)
SIZE_TIMEOUT = _int("BACKUP_SIZE_TIMEOUT", 120)
NAS_MIN_FREE_PCT = _int("BACKUP_NAS_MIN_FREE_PCT", 10)
SIZE_SNAPSHOT = _flag("BACKUP_SIZE_SNAPSHOT", "1")

# --- Admin inicial ---
ADMIN_USER = os.environ.get("BACKUP_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("BACKUP_ADMIN_PASSWORD", "")


def warn_if_insecure() -> None:
    if _SECRET_GENERATED:
        log.warning(
            "BACKUP_SECRET_KEY no está definida: se generó una efímera. "
            "Las sesiones se invalidarán al reiniciar. Definirla en /etc/backupcsr/web.env."
        )
