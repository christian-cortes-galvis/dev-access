"""Endpoints HTTP del portal de copias (prefijo /api)."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from . import auth, catalog, config, cronfile, db, files, logs, runner

log = logging.getLogger("backupcsr-web")

router = APIRouter(prefix="/api")

CRON_FIELD_RE = re.compile(r"^[0-9*/,\-]+$")
JOB_FIELDS = (
    "slug",
    "name",
    "description",
    "origin_type",
    "source",
    "dest_rel",
    "enabled",
    "cron_minute",
    "cron_hour",
    "cron_dom",
    "cron_month",
    "cron_dow",
    "sort",
)


class LoginIn(BaseModel):
    username: str
    password: str


class RunIn(BaseModel):
    dry_run: bool = False


class JobPatch(BaseModel):
    enabled: bool | None = None
    cron_minute: str | None = None
    cron_hour: str | None = None
    cron_dom: str | None = None
    cron_month: str | None = None
    cron_dow: str | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _schedule(job: dict) -> dict:
    return {
        "minute": job.get("cron_minute", "0"),
        "hour": job.get("cron_hour", "0"),
        "dom": job.get("cron_dom", "*"),
        "month": job.get("cron_month", "*"),
        "dow": job.get("cron_dow", "*"),
    }


def _cron_valid_field(value: str) -> bool:
    return bool(CRON_FIELD_RE.match(value.strip()))


def effective_jobs() -> list[dict]:
    """Catálogo + overrides de la BD; si no hay BD, usa el cron instalado."""
    jobs = catalog.catalog_jobs()
    db_rows = {}
    if db.available():
        try:
            for row in db.query("SELECT * FROM jobs"):
                db_rows[row["slug"]] = row
        except Exception:  # noqa: BLE001
            log.exception("no se pudieron leer los jobs de la BD")
    cron_map = cronfile.parse()
    merged = []
    for job in jobs:
        slug = job["slug"]
        row = db_rows.get(slug)
        if row:
            for field in JOB_FIELDS:
                if field in row and row[field] is not None:
                    job[field] = row[field]
            job["id"] = row.get("id")
        elif slug in cron_map:
            cron = cron_map[slug]
            job["cron_minute"] = cron["minute"]
            job["cron_hour"] = cron["hour"]
            job["cron_dom"] = cron["dom"]
            job["cron_month"] = cron["month"]
            job["cron_dow"] = cron["dow"]
        merged.append(job)
    merged.sort(key=lambda item: item.get("sort", 100))
    return merged


def find_job(slug: str) -> dict | None:
    for job in effective_jobs():
        if job["slug"] == slug:
            return job
    return None


def collect_jobs() -> list[dict]:
    reference = logs.now()
    result = []
    for job in effective_jobs():
        runs = logs.parse_slug(job["slug"])
        latest = runs[-1] if runs else None
        running = runner.is_running(job)
        status, detail = logs.evaluate(latest, _schedule(job), reference, running)
        result.append(
            {
                **{field: job.get(field) for field in JOB_FIELDS},
                "status": status,
                "status_detail": detail,
                "running": running,
                "last_run": logs.run_to_dict(latest) if latest else None,
                "next_run": _iso(logs.next_run(_schedule(job), reference)),
                "runs_total": len(runs),
            }
        )
    return result


def audit(username: str, action: str, slug: str | None = None, detail: dict | None = None) -> None:
    if not db.available():
        return
    try:
        db.execute(
            "INSERT INTO audit_log (username, action, job_slug, detail_json) VALUES (%s, %s, %s, %s)",
            (username, action, slug, json.dumps(detail or {}, ensure_ascii=False)),
        )
    except Exception:  # noqa: BLE001
        log.exception("no se pudo registrar auditoría")


def _require_db() -> None:
    if not db.available():
        raise HTTPException(status_code=503, detail="base de datos no disponible")


# ------------------------------- auth -------------------------------------


@router.post("/auth/login")
async def login(payload: LoginIn, response: Response):
    _require_db()
    user = auth.get_user(payload.username)
    if not user or not user.get("active") or not auth.verify_password(
        payload.password, user["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="usuario o contraseña inválidos")
    token = auth.make_session(user["username"], user["role"])
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return {"username": user["username"], "role": user["role"]}


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
async def me(user: dict = Depends(auth.current_user)):
    return user


# ------------------------------ health ------------------------------------


@router.get("/health")
async def health():
    db_ok = db.available()
    cron_ok = config.CRON_FILE.exists()
    nas_ok = files.nas_ready()
    status = "ok" if db_ok and cron_ok else "degraded"
    return {
        "status": status,
        "db": db_ok,
        "db_error": db.last_error(),
        "cron": cron_ok,
        "cron_path": str(config.CRON_FILE),
        "nas": nas_ok,
        "nas_path": str(config.NAS_MOUNT),
        "manage_cron": config.MANAGE_CRON,
        "time": _iso(logs.now()),
    }


# ------------------------------- jobs -------------------------------------


@router.get("/summary")
async def summary(user: dict = Depends(auth.current_user)):
    jobs = collect_jobs()
    counts = {"total": len(jobs), "OK": 0, "EN_CURSO": 0, "TARDE": 0, "FALLO": 0, "NUNCA": 0}
    for job in jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    counts["habilitados"] = sum(1 for job in jobs if job.get("enabled"))
    return {
        "counts": counts,
        "manage_cron": config.MANAGE_CRON,
        "db": db.available(),
        "nas": files.nas_ready(),
        "generated_at": _iso(logs.now()),
    }


@router.get("/jobs")
async def list_jobs(user: dict = Depends(auth.current_user)):
    return {
        "jobs": collect_jobs(),
        "manage_cron": config.MANAGE_CRON,
        "db": db.available(),
        "nas": files.nas_ready(),
        "generated_at": _iso(logs.now()),
    }


@router.get("/jobs/{slug}")
async def job_detail(slug: str, tail: int = 200, user: dict = Depends(auth.current_user)):
    job = find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="job no encontrado")
    runs = logs.parse_slug(slug)
    latest = runs[-1] if runs else None
    running = runner.is_running(job)
    status, detail = logs.evaluate(latest, _schedule(job), logs.now(), running)
    return {
        "job": {
            **{field: job.get(field) for field in JOB_FIELDS},
            "status": status,
            "status_detail": detail,
            "running": running,
            "next_run": _iso(logs.next_run(_schedule(job), logs.now())),
        },
        "runs": [logs.run_to_dict(run) for run in runs[-20:]][::-1],
        "log": logs.tail_log(slug, tail),
    }


@router.post("/jobs/{slug}/run")
async def run_job(slug: str, payload: RunIn, user: dict = Depends(auth.require_admin)):
    job = find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="job no encontrado")
    ok, message = runner.start(job, dry_run=payload.dry_run)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    audit(user["username"], "run-dry" if payload.dry_run else "run", slug)
    return {"ok": True, "message": message, "dry_run": payload.dry_run}


@router.patch("/jobs/{slug}")
async def update_job(slug: str, patch: JobPatch, user: dict = Depends(auth.require_admin)):
    _require_db()
    if not config.MANAGE_CRON:
        raise HTTPException(
            status_code=409,
            detail="gestión de cron deshabilitada (BACKUP_MANAGE_CRON=0)",
        )
    if not find_job(slug):
        raise HTTPException(status_code=404, detail="job no encontrado")

    updates: dict = {}
    for field in ("cron_minute", "cron_hour", "cron_dom", "cron_month", "cron_dow"):
        value = getattr(patch, field)
        if value is None:
            continue
        if not _cron_valid_field(value):
            raise HTTPException(status_code=400, detail=f"{field} inválido: {value}")
        updates[field] = value.strip()
    if patch.enabled is not None:
        updates["enabled"] = 1 if patch.enabled else 0
    if not updates:
        raise HTTPException(status_code=400, detail="nada que actualizar")

    assignments = ", ".join(f"{field}=%s" for field in updates)
    db.execute(f"UPDATE jobs SET {assignments} WHERE slug=%s", (*updates.values(), slug))

    cronfile.write(effective_jobs())
    audit(user["username"], "update-job", slug, updates)
    return {"ok": True, "job": next(j for j in collect_jobs() if j["slug"] == slug)}


@router.post("/jobs/{slug}/reset-schedule")
async def reset_schedule(slug: str, user: dict = Depends(auth.require_admin)):
    _require_db()
    if not config.MANAGE_CRON:
        raise HTTPException(
            status_code=409,
            detail="gestión de cron deshabilitada (BACKUP_MANAGE_CRON=0)",
        )
    try:
        catalog.reset_schedule(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="job no encontrado") from None
    cronfile.write(effective_jobs())
    audit(user["username"], "reset-schedule", slug)
    return {"ok": True, "job": next(j for j in collect_jobs() if j["slug"] == slug)}


@router.get("/jobs/{slug}/files")
async def job_files(slug: str, path: str = "", user: dict = Depends(auth.current_user)):
    job = find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="job no encontrado")
    dest = (job.get("dest_rel") or "").strip("/")
    anchor = config.NAS_MOUNT / dest if dest else config.NAS_MOUNT
    return {"job": slug, **files.list_dir(path, anchor=anchor)}


# ------------------------------ cron --------------------------------------


@router.get("/cron")
async def cron_status(user: dict = Depends(auth.current_user)):
    jobs = effective_jobs()
    return {
        "manage_cron": config.MANAGE_CRON,
        "path": str(config.CRON_FILE),
        "diff": cronfile.diff(jobs),
    }


# ------------------------------- runs -------------------------------------


@router.get("/runs")
async def list_runs(
    job: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(auth.current_user),
):
    if db.available():
        where = []
        params: list = []
        if job:
            where.append("j.slug = %s")
            params.append(job)
        if status:
            where.append("r.status = %s")
            params.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = db.query(
            f"""
            SELECT r.*, j.slug AS job_slug
            FROM runs r JOIN jobs j ON j.id = r.job_id
            {clause}
            ORDER BY r.started_at DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        return {"runs": [_run_row(row) for row in rows], "source": "db"}

    collected = []
    for item in effective_jobs():
        if job and item["slug"] != job:
            continue
        for run in logs.parse_slug(item["slug"]):
            data = logs.run_to_dict(run)
            data["job_slug"] = item["slug"]
            if status and data["status"] != status:
                continue
            collected.append(data)
    collected.sort(key=lambda run: run.get("started_at") or "", reverse=True)
    return {"runs": collected[offset : offset + limit], "source": "logs"}


def _run_row(row: dict) -> dict:
    started = logs.from_naive(row["started_at"]) if row.get("started_at") else None
    finished = logs.from_naive(row["finished_at"]) if row.get("finished_at") else None
    duration = int((finished - started).total_seconds()) if started and finished else None
    return {
        "id": row["id"],
        "job_slug": row.get("job_slug"),
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "status": row["status"],
        "dry_run": bool(row.get("dry_run")),
        "files_transferred": row.get("files_transferred", 0),
        "files_removed": row.get("files_removed", 0),
        "error_text": row.get("error_text"),
        "log_path": row.get("log_path"),
        "duration_s": duration,
    }


@router.get("/runs/{run_id}")
async def run_detail(run_id: int, user: dict = Depends(auth.current_user)):
    _require_db()
    row = db.query(
        """
        SELECT r.*, j.slug AS job_slug
        FROM runs r JOIN jobs j ON j.id = r.job_id
        WHERE r.id = %s
        """,
        (run_id,),
        one=True,
    )
    if not row:
        raise HTTPException(status_code=404, detail="corrida no encontrada")
    files_rows = db.query(
        "SELECT path, action FROM run_files WHERE run_id = %s ORDER BY id", (run_id,)
    )
    return {
        "run": _run_row(row),
        "files": [{"path": item["path"], "action": item["action"]} for item in files_rows],
    }


@router.get("/runs/{run_id}/log")
async def run_log(run_id: int, tail: int = 500, user: dict = Depends(auth.current_user)):
    _require_db()
    row = db.query(
        "SELECT r.log_path, j.slug AS job_slug FROM runs r JOIN jobs j ON j.id=r.job_id WHERE r.id=%s",
        (run_id,),
        one=True,
    )
    if not row:
        raise HTTPException(status_code=404, detail="corrida no encontrada")
    return {"log": _read_log(row.get("job_slug"), row.get("log_path"), tail)}


def _read_log(slug: str | None, log_path: str | None, tail: int) -> str:
    base = config.LOG_DIR.resolve()
    candidates = []
    if log_path:
        candidates.append(Path(log_path))
    if slug:
        candidates.append(config.LOG_DIR / f"{slug}.log")
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if base not in resolved.parents and resolved.parent != base:
            continue
        if resolved.exists() and resolved.is_file():
            with open(resolved, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
            return "".join(lines[-max(1, min(tail, 5000)):])
    return ""


# ------------------------------ files -------------------------------------


@router.get("/files")
async def browse(path: str = "", user: dict = Depends(auth.current_user)):
    return files.list_dir(path)
