"""Regresión de la sincronización de incidentes (`logs._sync_incident`).

Usa un doble de `logs.db` en memoria: no toca MySQL ni el sistema de archivos.

    /opt/backupcsr/web/venv/bin/python backupcsr/web/tests/test_incidents.py
"""
import os
import sys
from datetime import timedelta
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB_DIR))

os.environ.setdefault("BACKUP_TZ", "America/Bogota")

from app import logs  # noqa: E402

checks = 0
failures = 0


def check(name, ok, extra=""):
    global checks, failures
    checks += 1
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(extra)) if extra else ""))


class FakeDB:
    def __init__(self, open_row=None):
        self.open_row = open_row
        self.executes = []

    def query(self, sql, params=None, one=False):
        return self.open_row

    def execute(self, sql, params=None):
        self.executes.append((" ".join(sql.split()), params))
        return 1


def make_run(status, minutes, error_class=None, error_text="x"):
    when = logs.now() - timedelta(minutes=minutes)
    return {
        "status": status,
        "started_at": when,
        "finished_at": when + timedelta(minutes=1),
        "error_class": error_class,
        "error_text": error_text,
    }


# 1) Sin incidente abierto + FALLO -> INSERT con count=1, consecutive=1.
fake = FakeDB(open_row=None)
logs.db = fake
logs._sync_incident(1, [make_run("FALLO", 5, "fatal")])
check("abre incidente en el primer fallo", len(fake.executes) == 1, fake.executes)
check("INSERT con count/consecutive=1", fake.executes and "INSERT INTO incidents" in fake.executes[0][0], fake.executes)

# 2) OMITIDO no abre ni toca incidente.
fake = FakeDB(open_row=None)
logs.db = fake
logs._sync_incident(1, [make_run("OMITIDO", 5, "contencion")])
check("OMITIDO no abre incidente", fake.executes == [], fake.executes)

# 3) Fallo repetido ya contado (mismo last_run_started) -> no duplica.
run = make_run("FALLO", 10, "fatal")
open_row = {"id": 7, "last_run_started": logs.to_naive(run["started_at"])}
fake = FakeDB(open_row=open_row)
logs.db = fake
logs._sync_incident(1, [run])
check("no re-cuenta la misma corrida", fake.executes == [], fake.executes)

# 4) Fallo nuevo con incidente abierto -> UPDATE count+1.
fake = FakeDB(open_row={"id": 7, "last_run_started": logs.to_naive(logs.now() - timedelta(days=1))})
logs.db = fake
logs._sync_incident(1, [make_run("FALLO", 3, "fatal")])
check("actualiza incidente abierto", len(fake.executes) == 1 and "UPDATE incidents" in fake.executes[0][0], fake.executes)

# 5) OK con incidente abierto -> resuelve.
fake = FakeDB(open_row={"id": 7, "last_run_started": logs.to_naive(logs.now() - timedelta(days=1))})
logs.db = fake
logs._sync_incident(1, [make_run("OK", 2)])
check("resuelve el incidente en OK", len(fake.executes) == 1 and "resolved_at" in fake.executes[0][0], fake.executes)

# 5b) OK en la MISMA corrida que antes se vio como FALLO (reintento que tuvo éxito)
#     también resuelve: la resolución es idempotente por `resolved_at IS NULL`.
run = make_run("OK", 5)
fake = FakeDB(open_row={"id": 9, "last_run_started": logs.to_naive(run["started_at"])})
logs.db = fake
logs._sync_incident(1, [run])
check("resuelve en la misma corrida (recuperación)",
      len(fake.executes) == 1 and "resolved_at" in fake.executes[0][0], fake.executes)

# 6) PARCIAL abre incidente warning.
fake = FakeDB(open_row=None)
logs.db = fake
logs._sync_incident(1, [make_run("PARCIAL", 4, "parcial")])
check("PARCIAL abre incidente warning",
      fake.executes and "INSERT INTO incidents" in fake.executes[0][0] and "warning" in fake.executes[0][1],
      fake.executes)

print()
print(f"{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
