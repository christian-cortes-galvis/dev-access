"""Pruebas de la cola serializada de acciones masivas (app/batch.py).

El anfitrión ejecuta una sola copia a la vez (MIRROR_GATE), así que la cola debe
lanzar de a una y esperar el fin de cada corrida. Aquí se sustituyen
`runner.start_direct`
e `runner.is_running` por dobles: **no** se ejecuta ningún job real ni se toca
/mnt/nas, /etc, /run/lock ni MySQL.

    /opt/backupcsr/web/venv/bin/python backupcsr/web/tests/test_batch_queue.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB_DIR))

TMP = Path(tempfile.mkdtemp(prefix="batch-"))
for name, value in {
    "BACKUP_NAS": TMP / "nas",
    "BACKUP_OPT": TMP / "opt",
    "BACKUP_LOG": TMP / "log",
    "BACKUP_ETC": TMP / "etc",
    "BACKUP_CRON": TMP / "cron" / "backupcsr",
    "BACKUP_CATALOG": TMP / "jobs.yml",
}.items():
    os.environ[name] = str(value)
Path(os.environ["BACKUP_NAS"]).mkdir(parents=True, exist_ok=True)

from app import api, batch  # noqa: E402

USER = {"username": "tester", "role": "admin"}

checks = 0
failures = 0


def check(name, ok, extra=""):
    global checks, failures
    checks += 1
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(extra)) if extra else ""))


def reset():
    with batch._guard:
        batch._queue.clear()
        batch._done.clear()
        batch._running = None
        batch._batch_id = None
        batch._batch_action = None
    batch._wake.clear()


def wait_done(timeout=10):
    deadline = time.time() + timeout
    while batch.status()["active"] and time.time() < deadline:
        time.sleep(0.05)
    return batch.status()


# ---------------------------------------------- worker serializado
running = set()
events = []
lock = threading.Lock()


def fake_start(job, dry_run=False):
    slug = job["slug"]
    with lock:
        if running:
            # El worker no debe lanzar mientras otra tarea corre.
            events.append(("OVERLAP", slug))
            return False, "otro job corriendo"
        running.add(slug)
        events.append((slug, bool(dry_run)))
    threading.Timer(0.05, lambda: running.discard(slug)).start()
    return True, "iniciado"


batch.runner.start_direct = fake_start
batch.runner.is_running = lambda job: job["slug"] in running
# `_wait_idle` toma una foto del catálogo y sondea `runner.is_running` por tarea.
api.effective_jobs = lambda: [{"slug": slug} for slug in sorted(running)]
batch._audit = lambda item, action: None
batch._WAIT_IDLE_MAX = 5
batch._WAIT_FINISH_MAX = 5

reset()
info = batch.enqueue("run", [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}], "tester")
check("enqueue encola en orden", info["queued"] == ["a", "b", "c"], info)
state = wait_done()
check("la cola termina", state["active"] is False, state)
check("orden respetado y sin solape", [item for item, _ in events] == ["a", "b", "c"], events)
check("todas OK", [d["result"] for d in state["done"]] == ["ok", "ok", "ok"], state["done"])

# --------------------------------------------------------- dry-run
reset()
events.clear()
batch.enqueue("dry", [{"slug": "d"}], "tester")
wait_done()
check("dry-run se propaga a runner.start_direct", events == [("d", True)], events)

# --------------------------------------------------------- medir tamaño
reset()
calls = []
batch.files.nas_ready = lambda: True
batch.sizes.job_size = lambda job, force=False: (calls.append(job["slug"]) or {"bytes": 10})
batch.sizes.save_snapshot = lambda job_id, size: True
batch.enqueue("size", [{"slug": "e", "id": 1}], "tester")
state = wait_done()
check("size se ejecuta y reporta ok",
      calls == ["e"] and [d["result"] for d in state["done"]] == ["ok"], (calls, state["done"]))

# ----------------------------------------- filtros del endpoint run_batch
catalog_rows = [
    {"slug": "ok1", "status": "OK", "running": False},
    {"slug": "bad1", "status": "FALLO", "running": False},
    {"slug": "run1", "status": "FALLO", "running": True},
]
api.collect_jobs = lambda: list(catalog_rows)
captured = {}


def fake_enqueue(action, jobs, user):
    captured.update(action=action, slugs=[job["slug"] for job in jobs])
    return {"id": 1, "action": action, "queued": captured["slugs"], "pending": []}


api.batch.enqueue = fake_enqueue

res = asyncio.run(api.run_batch(api.BatchIn(action="retry", slugs=["ok1", "bad1", "run1", "nope"]), USER))
check("retry: solo FALLO y detenida", captured.get("slugs") == ["bad1"], captured)
check("retry: reporta 3 omitidas", len(res["skipped"]) == 3, res["skipped"])

captured.clear()
asyncio.run(api.run_batch(api.BatchIn(action="run", slugs=["run1", "ok1"]), USER))
check("run: omite la que ya corre", captured.get("slugs") == ["ok1"], captured)


def code(coro_factory):
    from fastapi import HTTPException
    try:
        asyncio.run(coro_factory())
    except HTTPException as exc:
        return exc.status_code
    return None


check("acción inválida: 400",
      code(lambda: api.run_batch(api.BatchIn(action="nope", slugs=["ok1"]), USER)) == 400)
check("sin tareas: 400",
      code(lambda: api.run_batch(api.BatchIn(action="run", slugs=[]), USER)) == 400)

shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
