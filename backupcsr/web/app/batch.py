"""Cola de acciones masivas sobre tareas (Panel).

Con el planificador activo (`BACKUP_SCHEDULER=1`) cada acción se encola en
`app/scheduler.py`, que es quien ordena y limita la concurrencia (global y por host).
Sin planificador se conserva el camino anterior: una FIFO con un único hilo worker
que espera a que no haya ninguna tarea corriendo antes de lanzar la siguiente.

La cola es en memoria: un reinicio del portal la descarta (no se reanudan acciones
destructivas solas).
"""
from __future__ import annotations

import logging
import threading
import time
from itertools import count

from . import files, runner, sizes

log = logging.getLogger("backupcsr-web")

ACTIONS = ("run", "dry", "retry", "size")

# Espera máxima antes de rendirse esperando el turno o el fin de una corrida.
_WAIT_IDLE_MAX = 30 * 60      # 30 min esperando que ninguna tarea esté corriendo
_WAIT_FINISH_MAX = 12 * 3600  # 12 h de tope por corrida (los backups pueden tardar)

_guard = threading.Lock()
_wake = threading.Event()
_worker: threading.Thread | None = None

_queue: list[dict] = []
_running: str | None = None
_done: list[dict] = []
_batch_id: int | None = None
_batch_action: str | None = None
_ids = count(1)


def _ensure_worker() -> None:
    global _worker
    with _guard:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="backupcsr-batch", daemon=True)
            _worker.start()


def enqueue(action: str, jobs: list[dict], username: str) -> dict:
    """Agrega tareas a la cola y devuelve el resumen del lote actual."""
    global _batch_id, _batch_action
    if action not in ACTIONS:
        raise ValueError(f"acción inválida: {action}")
    items = [{"action": action, "job": job, "username": username, "slug": job.get("slug")}
             for job in jobs]
    with _guard:
        if not _queue and _running is None:
            _batch_id = next(_ids)
            _batch_action = action
            _done.clear()
        _queue.extend(items)
        pending = [item["slug"] for item in _queue]
        batch_id, batch_action = _batch_id, _batch_action
    _ensure_worker()
    _wake.set()
    return {"id": batch_id, "action": batch_action,
            "queued": [item["slug"] for item in items], "pending": pending}


def status() -> dict:
    with _guard:
        return {
            "id": _batch_id,
            "action": _batch_action,
            "running": _running,
            "pending": [item["slug"] for item in _queue],
            "done": list(_done),
            "active": bool(_running or _queue),
        }


def queued_slugs() -> set[str]:
    """Slugs que ya esperan turno (para no encolar la misma tarea dos veces)."""
    with _guard:
        return {item["slug"] for item in _queue}


def _run() -> None:
    global _running
    while True:
        _wake.wait()
        while True:
            with _guard:
                if not _queue:
                    _running = None
                    _wake.clear()
                    break
                item = _queue.pop(0)
                _running = item["slug"]
            try:
                result = _process(item)
            except Exception:  # noqa: BLE001
                log.exception("lote: falló %s", item.get("slug"))
                result = "error"
            with _guard:
                _running = None
                _done.append({"slug": item["slug"], "result": result})


def _process(item: dict) -> str:
    action = item["action"]
    job = item["job"]
    if action == "size":
        queued = runner.submit(job, action="size", trigger="manual")
        if queued is not None:
            _audit(item, "size-refresh")
            return "queued"
        if not _wait_idle():
            return "timeout"
        if not files.nas_ready():
            return "error"
        size = sizes.job_size(job, force=True)
        job_id = job.get("id")
        if job_id and size.get("bytes") is not None:
            sizes.save_snapshot(job_id, size)
        _audit(item, "size-refresh")
        return "ok"

    dry = action == "dry"
    # Con el planificador activo, el lote se encola y el daemon ordena y limita la
    # concurrencia; sin él, se conserva el camino serializado de siempre.
    queued = runner.submit(job, action=action, trigger="manual", dry_run=dry)
    if queued is not None:
        effective = queued.get("action") or action
        eff_dry = bool(queued.get("dry_run"))
        _audit(item, "run-dry" if eff_dry else ("run-retry" if effective == "retry" else "run"))
        return "queued"
    audit_action = "run-dry" if dry else ("run-retry" if action == "retry" else "run")
    if not _wait_idle():
        return "timeout"
    ok, message = runner.start_direct(job, dry_run=dry)
    if not ok:
        log.info("lote: no se pudo lanzar %s: %s", item.get("slug"), message)
        return "skipped"
    _audit(item, audit_action)
    _wait_finish(job)
    return "ok"


def _wait_idle() -> bool:
    """Espera a que ninguna tarea corra (portal o cron) antes de lanzar la siguiente.

    Se toma una foto del catálogo una vez: `effective_jobs()` lee jobs.yml, la BD y
    el cron, así que no conviene reconstruirlo en cada sondeo. El lockfile de cada
    tarea sigue siendo la comprobación real y cubre también las corridas de cron.
    """
    from . import api
    try:
        jobs = api.effective_jobs()
    except Exception:  # noqa: BLE001
        log.exception("lote: no se pudo listar las tareas para esperar el turno")
        jobs = []
    deadline = time.monotonic() + _WAIT_IDLE_MAX
    while any(runner.is_running(job) for job in jobs):
        if time.monotonic() > deadline:
            return False
        time.sleep(3)
    return True


def _wait_finish(job: dict) -> None:
    deadline = time.monotonic() + _WAIT_FINISH_MAX
    while runner.is_running(job):
        if time.monotonic() > deadline:
            log.warning("lote: %s no terminó dentro del tope; se continúa", job.get("slug"))
            return
        time.sleep(3)


def _audit(item: dict, action: str) -> None:
    from . import api
    try:
        api.audit(item["username"], action, item["slug"])
    except Exception:  # noqa: BLE001
        log.exception("lote: no se pudo auditar %s", item.get("slug"))
