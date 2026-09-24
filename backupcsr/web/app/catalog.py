"""Catálogo de jobs: lee jobs.yml y lo sincroniza con la tabla `jobs`.

Regla de sincronización (igual que backend/catalog.yml del portal):
- Los jobs nuevos se insertan con el horario y la ficha por defecto del YAML.
- Los existentes NO se pisan: la BD manda tras el alta (ni `enabled`/cron, ni la ficha).
  Los campos nuevos de la ficha (criticality, owner, retention_days, tags,
  size_exclude, notes) se siembran del YAML solo si están vacíos, para rellenar
  instalaciones que vienen de un esquema anterior sin pisar ediciones.
- Los jobs que ya no están en el YAML se desactivan (enabled=0), sin borrar histórico.
"""
from __future__ import annotations

import logging

import yaml

from . import config, db

log = logging.getLogger("backupcsr-web")

DEFAULT_CRON = {"minute": "20", "hour": "6-19", "dom": "*", "month": "*", "dow": "*"}

CRITICALITIES = ("alta", "media", "baja")
ORIGIN_TYPES = ("ftp", "sftp", "sftp_pass")


def split_list(value) -> list[str]:
    """Normaliza lista de YAML/BD (lista, o texto separado por comas) a lista limpia."""
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.replace(",", " ").split()
    else:
        raw = list(value)
    return [str(item).strip() for item in raw if str(item).strip()]


def join_list(value, limit: int = 512) -> str:
    return ",".join(split_list(value))[:limit]


def load_catalog() -> dict:
    if not config.CATALOG_PATH.exists():
        log.error("no existe el catálogo de jobs en %s", config.CATALOG_PATH)
        return {"settings": {}, "jobs": []}
    with open(config.CATALOG_PATH, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {"settings": {}, "jobs": []}


def _size_exclude(item: dict) -> list[str]:
    """Patrones (nombres de hijo directo del destino) a excluir del cálculo de tamaño."""
    return [value.strip("/") for value in split_list(item.get("size_exclude"))]


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
                "criticality": str(item.get("criticality", "media") or "media"),
                "owner": item.get("owner", "") or "",
                "retention_days": item.get("retention_days"),
                "tags": join_list(item.get("tags"), 255),
                "notes": item.get("notes", "") or "",
            }
        )
    return out


def sync_jobs() -> int:
    jobs = catalog_jobs()
    if not jobs:
        return 0
    slugs = [job["slug"] for job in jobs]
    for job in jobs:
        params = {**job, "size_exclude": join_list(job.get("size_exclude"))}
        db.execute(
            """
            INSERT INTO jobs (
                slug, name, description, origin_type, source, dest_rel, lockfile,
                enabled, cron_minute, cron_hour, cron_dom, cron_month, cron_dow, sort,
                criticality, owner, retention_days, tags, size_exclude, notes
            ) VALUES (
                %(slug)s, %(name)s, %(description)s, %(origin_type)s, %(source)s,
                %(dest_rel)s, %(lockfile)s, %(enabled)s, %(cron_minute)s, %(cron_hour)s,
                %(cron_dom)s, %(cron_month)s, %(cron_dow)s, %(sort)s,
                %(criticality)s, %(owner)s, %(retention_days)s, %(tags)s,
                %(size_exclude)s, %(notes)s
            )
            ON DUPLICATE KEY UPDATE
                criticality = COALESCE(NULLIF(criticality, ''), VALUES(criticality)),
                owner = COALESCE(NULLIF(owner, ''), VALUES(owner)),
                retention_days = COALESCE(retention_days, VALUES(retention_days)),
                tags = COALESCE(NULLIF(tags, ''), VALUES(tags)),
                size_exclude = COALESCE(NULLIF(size_exclude, ''), VALUES(size_exclude)),
                notes = COALESCE(NULLIF(notes, ''), VALUES(notes))
            """,
            params,
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
