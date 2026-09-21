"""Aplicación FastAPI del portal de copias (se ejecuta con uvicorn vía systemd)."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI

from . import api, auth, catalog, config, db, logs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backupcsr-web")


async def _poll() -> None:
    while True:
        try:
            if db.available():
                for job in api.effective_jobs():
                    logs.store_runs(job, logs.parse_slug(job["slug"]))
        except Exception:  # noqa: BLE001
            log.exception("falló el ciclo de sondeo")
        await asyncio.sleep(config.POLL_INTERVAL)


def _bootstrap() -> None:
    config.warn_if_insecure()
    if not db.available():
        log.warning(
            "MySQL no disponible al arrancar (%s); el portal queda en modo lectura "
            "desde el filesystem hasta que vuelva la BD",
            db.last_error(),
        )
        return
    try:
        db.init_schema()
        catalog.sync_jobs()
    except Exception:  # noqa: BLE001
        log.exception("no se pudo inicializar el esquema/catálogo")
        return
    try:
        if auth.user_count() == 0:
            if config.ADMIN_PASSWORD:
                auth.create_user(config.ADMIN_USER, config.ADMIN_PASSWORD, "admin")
                log.info("usuario admin '%s' creado", config.ADMIN_USER)
            else:
                log.warning(
                    "no hay usuarios y BACKUP_ADMIN_PASSWORD no está definida; "
                    "crea uno con: venv/bin/python -m app.cli create-admin"
                )
    except Exception:  # noqa: BLE001
        log.exception("no se pudo verificar/crear el usuario admin")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    _bootstrap()
    task = asyncio.create_task(_poll())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="CortexDev Backup API", lifespan=lifespan)
app.include_router(api.router)
