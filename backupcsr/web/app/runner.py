"""Ejecución manual de jobs, respetando el mismo flock que usa cron.

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


def _try_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        return None


def is_running(job: dict) -> bool:
    if job["slug"] in _locks:
        return True
    handle = _try_lock(lock_path(job))
    if handle is None:
        return True
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()
    return False


def start(job: dict, dry_run: bool = False) -> tuple[bool, str]:
    slug = job["slug"]
    if slug in _locks:
        return False, "ya hay una ejecución en curso"
    script = config.JOBS_DIR / f"{slug}.sh"
    if not script.exists():
        return False, f"no existe el job {script}"

    handle = _try_lock(lock_path(job))
    if handle is None:
        return False, "el job ya está corriendo (flock ocupado)"

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DRY_RUN"] = "1" if dry_run else "0"
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
