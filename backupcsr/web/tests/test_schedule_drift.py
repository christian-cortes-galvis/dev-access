"""Regresión: el estado se evalúa con el cron instalado, no con el horario de la BD.

Escenario real (ubuntu-services, 2026-09-21): `install.sh` copia a
`/etc/cron.d/backupcsr` el cron escalonado (`02/14/20/26/38/50`), pero la tabla `jobs`
conserva horarios viejos (`:20`, `gastro 0 6`), porque `catalog.sync_jobs()` nunca pisa los
campos de cron de las filas existentes. El portal evaluaba con el horario de la BD y marcaba
`TARDE` a jobs que sí habían corrido en su minuto (p. ej. google-bd 19:02 vs 19:20 esperado).

Este test fija una BD con `20 6-19` y un cron instalado con `2 6-19`, y comprueba que
`collect_jobs()` da `OK`, marca el desvío y que `build_alerts()` emite **una** alerta
agregada. También cubre `app.cli adopt-cron`.

Corre con el python del venv del portal (usa fastapi + yaml) y un directorio temporal: **no**
toca /mnt/nas, /etc, /run/lock ni MySQL.

    /opt/backupcsr/web/venv/bin/python backupcsr/web/tests/test_schedule_drift.py
"""
import argparse
import contextlib
import io
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import yaml

WEB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB_DIR))

# Los logs se interpretan con la zona del host; el test asume Bogotá.
os.environ["TZ"] = "America/Bogota"
time.tzset()

TMP = Path(tempfile.mkdtemp(prefix="sched-"))
os.environ["BACKUP_NAS"] = str(TMP / "nas")
os.environ["BACKUP_OPT"] = str(TMP / "opt")
os.environ["BACKUP_LOG"] = str(TMP / "log")
os.environ["BACKUP_ETC"] = str(TMP / "etc")
os.environ["BACKUP_CRON"] = str(TMP / "cron" / "backupcsr")
os.environ["BACKUP_CATALOG"] = str(TMP / "jobs.yml")
os.environ["BACKUP_MANAGE_CRON"] = "1"
Path(os.environ["BACKUP_NAS"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["BACKUP_LOG"]).mkdir(parents=True, exist_ok=True)

# Copia del catálogo real con los lockfiles movidos al temporal (no tocar /run/lock).
REAL_CATALOG = yaml.safe_load((WEB_DIR / "jobs.yml").read_text(encoding="utf-8"))
for item in REAL_CATALOG["jobs"]:
    item["lockfile"] = str(TMP / "locks" / f"backupcsr-{item['slug']}.lock")
Path(os.environ["BACKUP_CATALOG"]).write_text(
    yaml.safe_dump(REAL_CATALOG, allow_unicode=True, sort_keys=False), encoding="utf-8"
)

# Cron instalado (escalonado): google-bd :02 y latino-bd :14; ruta56-web coincide con la BD.
CRON_FILE = Path(os.environ["BACKUP_CRON"])
CRON_FILE.parent.mkdir(parents=True, exist_ok=True)
CRON_LINES = [
    "2 6-19 * * *   root  flock -n /tmp/g.lock /opt/backupcsr/jobs/google-bd.sh",
    "14 6-19 * * *  root  flock -n /tmp/l.lock /opt/backupcsr/jobs/latino-bd.sh",
    "26 6-19 * * *  root  flock -n /tmp/r.lock /opt/backupcsr/jobs/ruta56-bd.sh",
    "20 6,13,19 * * *  root  flock -n /tmp/w.lock /opt/backupcsr/jobs/ruta56-web.sh",
    "38 6-19 * * *  root  flock -n /tmp/ga.lock /opt/backupcsr/jobs/gastro-bd.sh",
    "50 6-19 * * *  root  flock -n /tmp/e.lock /opt/backupcsr/jobs/enter-bd.sh",
]
CRON_FILE.write_text("\n".join(CRON_LINES) + "\n", encoding="utf-8")

# Log de google-bd: cerró 19:03 en Bogotá (con la BD decía 19:20 → TARDE; con el cron :02 → OK).
(Path(os.environ["BACKUP_LOG"]) / "google-bd.log").write_text(
    "2026-09-21 19:02:01 [google-bd] === inicio google-bd (dry_run=0 nice=15) ===\n"
    "2026-09-21 19:03:34 [google-bd] === fin google-bd ===\n",
    encoding="utf-8",
)

from app import api, cli, config, cronfile, db, logs  # noqa: E402

REFERENCE = datetime(2026, 9, 21, 19, 30, tzinfo=logs.TZ)

# BD "vieja": horarios de la tabla `jobs` (los que el portal usaba para evaluar).
DB_ROWS = [
    ("google-bd", "20", "6-19"),
    ("latino-bd", "20", "6-19"),
    ("ruta56-bd", "20", "6-19"),
    ("ruta56-web", "20", "6,13,19"),
    ("gastro-bd", "0", "6"),
    ("enter-bd", "20", "6-19"),
]
ROWS = [
    {
        "id": index + 1,
        "slug": slug,
        "enabled": 1,
        "cron_minute": minute,
        "cron_hour": hour,
        "cron_dom": "*",
        "cron_month": "*",
        "cron_dow": "*",
    }
    for index, (slug, minute, hour) in enumerate(DB_ROWS)
]
DRIFTED = ["enter-bd", "gastro-bd", "google-bd", "latino-bd", "ruta56-bd"]

EXECUTED = []


def fake_query(sql, params=None, one=False):
    if "SELECT * FROM jobs" in sql:
        rows = [dict(row) for row in ROWS]
    else:
        rows = []
    return (rows[0] if rows else None) if one else rows


def fake_execute(sql, params=None):
    EXECUTED.append((sql, params))
    return 1


db.available = lambda: True
db.query = fake_query
db.execute = fake_execute
api.logs.now = lambda: REFERENCE
cronfile.reload_cron = lambda: True

USER = {"username": "tester", "role": "admin"}

checks = 0
failures = 0


def check(name, ok, extra=""):
    global checks, failures
    checks += 1
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(extra)) if extra else ""))


# ------------------------------------------------------ helpers de horario
base = {"minute": "20", "hour": "6-19", "dom": "*", "month": "*", "dow": "*"}
installed = {"minute": "2", "hour": "6-19", "dom": "*", "month": "*", "dow": "*"}
check("_same_schedule: iguales", api._same_schedule(base, dict(base)) is True)
check("_same_schedule: distintos", api._same_schedule(base, installed) is False)
check("_effective_schedule: prefiere el cron instalado",
      api._effective_schedule({"installed_cron": installed, **{f"cron_{k}": v for k, v in base.items()}})
      == installed)
check("_effective_schedule: sin cron usa la BD",
      api._effective_schedule({f"cron_{k}": v for k, v in base.items()})["minute"] == "20")

# ------------------------------------------------------------- estado
collected = {job["slug"]: job for job in api.collect_jobs()}
google = collected["google-bd"]
check("estado: google-bd OK con el cron (no TARDE)", google["status"] == "OK", google["status"])
check("estado: google-bd marca desvío", google["schedule_drift"] is True)
check("estado: horario efectivo = cron instalado",
      google["cron_effective"]["minute"] == "2", google["cron_effective"])
check("estado: sigue exponiendo el horario de la BD",
      google["cron_minute"] == "20" and google["cron_hour"] == "6-19")
check("estado: ruta56-web no tiene desvío (BD == cron)",
      collected["ruta56-web"]["schedule_drift"] is False)
check("estado: next_run sale del cron instalado (06:02, no 06:20)",
      "T06:02:00" in str(google["next_run"]), google["next_run"])

# ------------------------------------------------------------- alertas
schedule_alerts = [a for a in api.build_alerts(list(collected.values())) if a["kind"] == "schedule"]
check("alertas: una sola alerta de horario", len(schedule_alerts) == 1, schedule_alerts)
check("alertas: incluye las 5 tareas desviadas",
      sorted(schedule_alerts[0].get("slugs", [])) == DRIFTED,
      schedule_alerts[0].get("slugs") if schedule_alerts else None)
check("alertas: no es crítica", schedule_alerts and schedule_alerts[0]["level"] == "warning")

config.MANAGE_CRON = False
check("alertas: sin MANAGE_CRON no hay alerta de horario",
      not [a for a in api.build_alerts(list(collected.values())) if a["kind"] == "schedule"])
config.MANAGE_CRON = True

# ------------------------------------------------------------- adopt-cron
def run_adopt(dry_run):
    EXECUTED.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.cmd_adopt_cron(argparse.Namespace(dry_run=dry_run))
    return code, out.getvalue()


code, text = run_adopt(dry_run=True)
check("adopt-cron --dry-run: no escribe en la BD", code == 0 and EXECUTED == [], EXECUTED)
check("adopt-cron --dry-run: reporta 5 cambios", "5 horario(s)" in text, text.strip())

code, text = run_adopt(dry_run=False)
check("adopt-cron: actualiza las 5 desviadas", code == 0 and len(EXECUTED) == 5, len(EXECUTED))
check("adopt-cron: no toca enabled",
      all("enabled" not in sql for sql, _ in EXECUTED))
google_params = [params for sql, params in EXECUTED if params and params[-1] == "google-bd"]
check("adopt-cron: google-bd pasa a 2 6-19",
      google_params and google_params[0][:2] == ("2", "6-19"), google_params)

shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
