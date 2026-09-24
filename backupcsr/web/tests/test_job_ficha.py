"""Pruebas de la ficha editable de tareas (campos nuevos, permisos y validación).

Cubre: que `catalog_jobs()` exponga la ficha nueva, que `sync-jobs` no pise los campos
editables, que el PATCH de ficha funcione sin `BACKUP_MANAGE_CRON` y no reescriba el cron,
que el PATCH de programación exija `MANAGE_CRON`, las validaciones y el visor/drift del
script real.

Corre con el python del venv del portal (necesita fastapi + yaml) y usa un directorio
temporal: **no** toca /mnt/nas, /etc, /run/lock ni MySQL.

    /opt/backupcsr/web/venv/bin/python backupcsr/web/tests/test_job_ficha.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from fastapi import HTTPException

WEB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB_DIR))

TMP = Path(tempfile.mkdtemp(prefix="ficha-"))
os.environ["BACKUP_NAS"] = str(TMP / "nas")
os.environ["BACKUP_OPT"] = str(TMP / "opt")
os.environ["BACKUP_LOG"] = str(TMP / "log")
os.environ["BACKUP_ETC"] = str(TMP / "etc")
os.environ["BACKUP_CRON"] = str(TMP / "cron" / "backupcsr")
os.environ["BACKUP_CATALOG"] = str(TMP / "jobs.yml")
os.environ["BACKUP_MANAGE_CRON"] = "1"
Path(os.environ["BACKUP_NAS"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["BACKUP_LOG"]).mkdir(parents=True, exist_ok=True)

REAL_CATALOG = yaml.safe_load((WEB_DIR / "jobs.yml").read_text(encoding="utf-8"))
for item in REAL_CATALOG["jobs"]:
    item["lockfile"] = str(TMP / "locks" / f"backupcsr-{item['slug']}.lock")
Path(os.environ["BACKUP_CATALOG"]).write_text(
    yaml.safe_dump(REAL_CATALOG, allow_unicode=True, sort_keys=False), encoding="utf-8"
)

from app import api, catalog, config, cronfile, db  # noqa: E402

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


def run(coro):
    return asyncio.run(coro)


def code(fn):
    try:
        fn()
    except HTTPException as exc:
        return exc.status_code
    return None


# --------------------------------------------------------------- harness
EXECUTED = []
WRITES = []
LOCK_TAKEN = [False]


def capture_execute(sql, params=None):
    EXECUTED.append((sql, params))
    return 1


def fake_query(sql, params=None, one=False):
    if "lockfile=" in sql:
        return {"slug": "otra-tarea"} if LOCK_TAKEN[0] else None
    return []


api.audit = lambda *args, **kwargs: None
api.db.available = lambda: True
api.db.execute = capture_execute
api.db.query = fake_query
api.cronfile.write = lambda jobs: WRITES.append(jobs)
api.runner.is_running = lambda job: False
api.logs.parse_slug = lambda slug: []
api.sizes.current = lambda job: {"bytes": None, "files": 0}

# ---------------------------------------------------- catálogo: campos nuevos
jobs = {job["slug"]: job for job in catalog.catalog_jobs()}
ruta = jobs["ruta56-bd"]
check("catálogo: criticality por defecto", ruta["criticality"] == "media", ruta.get("criticality"))
check("catálogo: owner/tags/notes vacíos",
      ruta["owner"] == "" and ruta["tags"] == "" and ruta["notes"] == "")
check("catálogo: retention_days vacío", ruta["retention_days"] is None)
check("catálogo: size_exclude es lista", ruta["size_exclude"] == ["storage"], ruta["size_exclude"])

# ---------------------------------------------------- sync: no pisa la ficha
EXECUTED.clear()
catalog.db.execute = capture_execute
catalog.sync_jobs()
sync_sql = EXECUTED[0][0]
check("sync: inserta las columnas nuevas",
      all(col in sync_sql for col in ("criticality", "owner", "retention_days", "tags",
                                      "size_exclude", "notes")))
check("sync: no pisa name/source/dest/sort en duplicado",
      not any(f"{field} = VALUES({field})" in sync_sql
              for field in ("name", "description", "source", "dest_rel", "sort", "lockfile")))
check("sync: siembra size_exclude solo si está vacío",
      "COALESCE(NULLIF(size_exclude" in sync_sql)
check("sync: no toca enabled", "enabled =" not in sync_sql)

# ---------------------------------------------- ficha sin BACKUP_MANAGE_CRON
config.MANAGE_CRON = False
EXECUTED.clear()
WRITES.clear()
patch = api.JobPatch(
    name="Ruta56 BD (ficha)",
    description="Base de datos de Ruta56 (FTP).",
    source="taskManager/ruta56",
    dest_rel="ruta56",
    sort=30,
    criticality="alta",
    owner="Infra",
    retention_days=30,
    tags="db, critico",
    size_exclude="storage, tmp",
    notes="Revisar storage compartido con ruta56-web.",
)
result = run(api.update_job("ruta56-bd", patch, USER))
check("ficha sin MANAGE_CRON: ok", result.get("ok") is True, result)
ficha_sql = EXECUTED[0][0]
check("ficha: UPDATE incluye los campos nuevos",
      all(f"{field}=%s" in ficha_sql for field in
          ("criticality", "owner", "retention_days", "tags", "size_exclude", "notes")))
check("ficha: no reescribe el cron", WRITES == [], WRITES)
check("ficha: no incluye campos de programación",
      "cron_minute" not in ficha_sql and "enabled" not in ficha_sql)

check("cron sin MANAGE_CRON: 409",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(cron_minute="7"), USER))) == 409)
check("enabled sin MANAGE_CRON: 409",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(enabled=False), USER))) == 409)

# ------------------------------------------------ programación con MANAGE_CRON
config.MANAGE_CRON = True
EXECUTED.clear()
WRITES.clear()
result = run(api.update_job(
    "ruta56-bd",
    api.JobPatch(cron_minute="7", lockfile="/run/lock/backupcsr-ruta56-bd.lock"),
    USER,
))
check("programación con MANAGE_CRON: ok", result.get("ok") is True, result)
check("programación: reescribe el cron", len(WRITES) == 1, WRITES)
cron_sql = EXECUTED[0][0]
check("programación: cron_minute y lockfile en el UPDATE",
      "cron_minute=%s" in cron_sql and "lockfile=%s" in cron_sql)

EXECUTED.clear()
WRITES.clear()
run(api.update_job("ruta56-bd", api.JobPatch(name="Solo ficha"), USER))
check("ficha con MANAGE_CRON: no reescribe el cron", WRITES == [], WRITES)

# ------------------------------------------------------------ validaciones
check("origin_type inválido: 400",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(origin_type="rsync"), USER))) == 400)
check("criticality inválida: 400",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(criticality="urgente"), USER))) == 400)
check("dest_rel absoluto: 400",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(dest_rel="/etc"), USER))) == 400)
check("dest_rel con ..: 400",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(dest_rel="a/../b"), USER))) == 400)
check("dest_rel vacío explícito: 400",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(dest_rel=""), USER))) == 400)
check("lockfile fuera de /run/lock: 400",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(lockfile="/tmp/x.lock"), USER))) == 400)
check("lockfile con ..: 400",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(lockfile="/run/lock/../x.lock"), USER))) == 400)
check("lockfile con componente vacío: 400",
      code(lambda: run(api.update_job("ruta56-bd", api.JobPatch(lockfile="/run/lock/a//b.lock"), USER))) == 400)
LOCK_TAKEN[0] = True
check("lockfile duplicado: 409",
      code(lambda: run(api.update_job(
          "ruta56-bd", api.JobPatch(lockfile="/run/lock/duplicado.lock"), USER))) == 409)
LOCK_TAKEN[0] = False

# Tareas sin destino (deshabilitadas, dest_rel ""): la ficha se puede guardar.
ficha_tarea = run(api.update_job("ticware-bd", api.JobPatch(notes="revisar origen"), USER))
check("ficha: tarea sin dest_rel se puede editar", ficha_tarea.get("ok") is True, ficha_tarea)

# ------------------------------------------------------------------ esquema
schema_text = (WEB_DIR / "schema.sql").read_text(encoding="utf-8")
check("esquema: columnas de _JOB_COLUMNS presentes en schema.sql",
      all(name in schema_text for name, _ in db._JOB_COLUMNS))

# -------------------------------------------------- script real y drift
script = config.JOBS_DIR / "ruta56-bd.sh"
script.parent.mkdir(parents=True, exist_ok=True)
script.write_text(
    'mirror_ftp "$RUTA56_HOST" "$RUTA56_USER" "$RUTA56_PASS" \\\n'
    '  "taskManager/ruta56" "$BACKUPCSR_NAS_ROOT/ruta56" "storage"\n',
    encoding="utf-8",
)
data = run(api.job_script("ruta56-bd", USER))
check("script: existe y devuelve texto", data["exists"] and "mirror_ftp" in data["text"])
check("script: ficha actual coincide (sin drift)", data["drift"] is False, data.get("drift"))
check("drift: token ausente se detecta",
      api._script_drift({"source": "/otro/lado", "dest_rel": "ruta56"}, data["text"]) is True)
check("drift: sin script no avisa",
      api._script_drift({"source": "/otro/lado", "dest_rel": "ruta56"}, None) is False)
check("drift: ignora las rutas citadas solo en comentarios",
      api._script_drift(
          {"source": "ruta56/storage", "dest_rel": "ruta56/storage/app"},
          "# Ruta56 Web: ruta56/storage -> NAS (ruta56/storage/app)\n"
          'mirror_ftp "$H" "$U" "$P" "/otro" "$BACKUPCSR_NAS_ROOT/otro"\n',
      ) is True)

shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
