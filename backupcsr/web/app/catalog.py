"""Catálogo de jobs: lee jobs.yml y lo sincroniza con la tabla `jobs`.

Regla de sincronización (igual que backend/catalog.yml del portal):
- Los jobs nuevos se insertan con el horario por defecto del YAML.
- Los existentes actualizan solo la metadata (nombre, descripción, origen, destino,
  lockfile, orden); NUNCA se pisan `enabled` ni los campos de cron que el usuario editó.
- Los jobs que ya no están en el YAML se desactivan (enabled=0), sin borrar histórico.
"""
from __future__ import annotations

import logging

import yaml

from . import config, db

log = logging.getLogger("backupcsr-web")

DEFAULT_CRON = {"minute": "20", "hour": "6-19", "dom": "*", "month": "*", "dow": "*"}


def load_catalog() -> dict:
    if not config.CATALOG_PATH.exists():
        log.error("no existe el catálogo de jobs en %s", config.CATALOG_PATH)
        return {"settings": {}, "jobs": []}
    with open(config.CATALOG_PATH, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {"settings": {}, "jobs": []}


def _size_exclude(item: dict) -> list[str]:
    """Patrones (nombres de hijo directo del destino) a excluir del cálculo de tamaño."""
    raw = item.get("size_exclude") or []
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    return [str(value).strip().strip("/") for value in raw if str(value).strip()]


def catalog_jobs() -> list[dict]:
    """Jobs del YAML normalizados a la forma de la tabla `jobs` (sin BD)."""
    catalog = load_catalog()
    defaults = catalog.get("settings", {})
    out = []
    for item in catalog.get("jobs", []):
        cron = {**DEFAULT_CRON, **(item.get("cron") or {})}
        out.append(
            {
                "slug": item["slug"],
                "name": item.get("name", item["slug"]),
                "description": item.get("description", "") or "",
                "origin_type": item.get("origin_type", "ftp"),
                "source": item.get("source", "") or "",
                "dest_rel": item.get("dest_rel", "") or "",
                "lockfile": item.get("lockfile", "") or "",
                "enabled": int(item.get("enabled", defaults.get("default_enabled", True))),
                "cron_minute": str(cron["minute"]),
                "cron_hour": str(cron["hour"]),
                "cron_dom": str(cron.get("dom", "*")),
                "cron_month": str(cron.get("month", "*")),
                "cron_dow": str(cron.get("dow", "*")),
                "sort": int(item.get("sort", 100)),
                "size_exclude": _size_exclude(item),
            }
        )
    return out


def sync_jobs() -> int:
    jobs = catalog_jobs()
    if not jobs:
        return 0
    slugs = [job["slug"] for job in jobs]
    for job in jobs:
        db.execute(
            """
            INSERT INTO jobs (
                slug, name, description, origin_type, source, dest_rel, lockfile,
                enabled, cron_minute, cron_hour, cron_dom, cron_month, cron_dow, sort
            ) VALUES (
                %(slug)s, %(name)s, %(description)s, %(origin_type)s, %(source)s,
                %(dest_rel)s, %(lockfile)s, %(enabled)s, %(cron_minute)s, %(cron_hour)s,
                %(cron_dom)s, %(cron_month)s, %(cron_dow)s, %(sort)s
            )
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                description = VALUES(description),
                origin_type = VALUES(origin_type),
                source = VALUES(source),
                dest_rel = VALUES(dest_rel),
                lockfile = VALUES(lockfile),
                sort = VALUES(sort)
            """,
            job,
        )
    placeholders = ",".join(["%s"] * len(slugs))
    db.execute(f"UPDATE jobs SET enabled = 0 WHERE slug NOT IN ({placeholders})", slugs)
    log.info("catálogo sincronizado: %s jobs", len(jobs))
    return len(jobs)


def reset_schedule(slug: str) -> None:
    """Restaura el horario por defecto del YAML para un job."""
    for job in catalog_jobs():
        if job["slug"] == slug:
            db.execute(
                """
                UPDATE jobs SET cron_minute=%(cron_minute)s, cron_hour=%(cron_hour)s,
                    cron_dom=%(cron_dom)s, cron_month=%(cron_month)s, cron_dow=%(cron_dow)s
                WHERE slug=%(slug)s
                """,
                job,
            )
            return
    raise KeyError(slug)
