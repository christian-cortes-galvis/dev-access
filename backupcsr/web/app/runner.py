"""Ejecución de jobs: planificador (backupcsr-scheduler) o directo como respaldo.

Con `BACKUP_SCHEDULER=1`, `start()` encola en el planificador (app/scheduler.py), que
controla la concurrencia. Si el daemon no responde, cae a `start_direct()`: el mismo
`flock -n <lockfile>` que usa cron, para no solapar corridas (degradación serial).

cron ejecuta `flock -n <lockfile> /opt/backupcsr/jobs/<slug>.sh`. Aquí se adquiere el
mismo lockfile con fcntl (no bloqueante) y se lanza el script; si cron ya lo tiene
tomado (o al revés) la segunda ejecución se rechaza. El job escribe su propio log.
"""
from __future__ import annotations

import fcntl
import logging
import os
import subprocess
import threading
from pathlib import Path

from . import config

log = logging.getLogger("backupcsr-web")

_locks: dict[str, tuple] = {}
# slug -> (lock_file, process)


def lock_path(job: dict) -> Path:
    return Path(job.get("lockfile") or f"/run/lock/backupcsr-{job['slug']}.lock")


def _try_lock(path: Path) -> tuple:
    """Devuelve (handle, busy). handle None indica que no se pudo usar el lock."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+")
    except OSError as exc:
        log.warning("no se pudo abrir el lock %s: %s", path, exc)
        return None, False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle, False
    except OSError:
        handle.close()
        return None, True


def is_running(job: dict) -> bool:
    if job["slug"] in _locks:
        return True
    handle, busy = _try_lock(lock_path(job))
    if handle is None:
        # Sin acceso al lockfile no podemos afirmar que esté corriendo: no rompemos
        # el panel por un problema de permisos.
        return busy
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()
    return False


def submit(job: dict, action: str = "run", trigger: str = "manual",
           dry_run: bool = False) -> dict | None:
    """Encola en el planificador; None si está apagado, caído o rechaza la tarea.

    Con `BACKUP_SCHEDULER=0` el portal sigue lanzando directo (comportamiento previo).
    Un timeout puede ocurrir DESPUÉS de que el daemon encoló: se reintenta una vez
    (el daemon deduplica por slug) antes de caer a ejecución directa, para no duplicar.
    """
    if not config.SCHEDULER:
        return None
    try:
        from . import scheduler_client
    except Exception:  # noqa: BLE001
        return None
    result = None
    for _ in (1, 2):
        try:
            result = scheduler_client.submit(
                job["slug"], action=action, trigger=trigger, dry_run=dry_run,
            )
        except scheduler_client.SchedulerUnavailable as exc:
            log.warning("planificador sin respuesta, reintento único: %s", exc)
            continue
        except Exception as exc:  # noqa: BLE001
            log.warning("planificador no disponible, se usa ejecución directa: %s", exc)
            return None
        break
    if isinstance(result, dict) and result.get("ok"):
        return result
    log.info("el planificador rechazó %s: %s", job.get("slug"), result)
    return None


def start(job: dict, dry_run: bool = False, trigger: str = "manual") -> tuple[bool, str]:
    """Intenta encolar en el planificador y, si no está, lanza el script directo.

    La ejecución directa conserva el `MIRROR_GATE` serial: es la degradación segura.
    """
    action = "dry" if dry_run else "run"
    queued = submit(job, action=action, trigger=trigger, dry_run=dry_run)
    if queued is not None:
        return True, "encolado"
    return start_direct(job, dry_run=dry_run)


def start_direct(job: dict, dry_run: bool = False) -> tuple[bool, str]:
    slug = job["slug"]
    if slug in _locks:
        return False, "ya hay una ejecución en curso"
    script = config.JOBS_DIR / f"{slug}.sh"
    if not script.exists():
        return False, f"no existe el job {script}"

    handle, busy = _try_lock(lock_path(job))
    if handle is None:
        if busy:
            return False, "el job ya está corriendo (flock ocupado)"
        return False, "no se pudo acceder al lockfile (revisa permisos de /run/lock)"

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DRY_RUN"] = "1" if dry_run else "0"
    # El job lo registra en su línea "=== inicio ... trigger=manual ===" y el portal
    # lo persiste en runs.triggered_by (el cron usa el valor por defecto, cron).
    env["BACKUP_TRIGGERED_BY"] = "manual"
    try:
        process = subprocess.Popen(
            ["/bin/bash", str(script)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
        return False, f"no se pudo lanzar: {exc}"

    _locks[slug] = (handle, process)
    threading.Thread(target=_reap, args=(slug,), daemon=True).start()
    log.info("job %s lanzado (dry_run=%s pid=%s)", slug, dry_run, process.pid)
    return True, "iniciado"


def _reap(slug: str) -> None:
    entry = _locks.get(slug)
    if not entry:
        return
    handle, process = entry
    process.wait()
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
    except OSError:
        pass
    _locks.pop(slug, None)
    log.info("job %s terminó con código %s", slug, process.returncode)
