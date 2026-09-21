"""Endpoints HTTP del portal de copias (prefijo /api)."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from . import auth, catalog, config, cronfile, db, files, logs, runner, sizes

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
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")
ROLES = ("admin", "viewer")
MIN_PASSWORD = 8


class LoginIn(BaseModel):
    username: str
    password: str


class RunIn(BaseModel):
    dry_run: bool = False
    retry: bool = False


class JobPatch(BaseModel):
    enabled: bool | None = None
    cron_minute: str | None = None
    cron_hour: str | None = None
    cron_dom: str | None = None
    cron_month: str | None = None
    cron_dow: str | None = None


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UserPatch(BaseModel):
    role: str | None = None
    active: bool | None = None


class PasswordIn(BaseModel):
    password: str


class SelfPasswordIn(BaseModel):
    current: str
    new: str


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
        size = sizes.current(job)
        result.append(
            {
                **{field: job.get(field) for field in JOB_FIELDS},
                "status": status,
                "status_detail": detail,
                "running": running,
                "last_run": logs.run_to_dict(latest) if latest else None,
                "next_run": _iso(logs.next_run(_schedule(job), reference)),
                "runs_total": len(runs),
                "size": size,
                "size_bytes": size.get("bytes"),
                "size_exclude": job.get("size_exclude") or [],
            }
        )
    return result


def build_alerts(jobs: list[dict]) -> list[dict]:
    """Avisos para el banner: jobs vencidos/fallidos, NAS lleno o no disponible."""
    alerts: list[dict] = []
    for job in jobs:
        if job["status"] == "FALLO":
            alerts.append({
                "level": "danger", "kind": "job", "slug": job["slug"],
                "text": f"{job['name']}: {job.get('status_detail') or 'falló'}",
            })
        elif job["status"] == "TARDE":
            alerts.append({
                "level": "warning", "kind": "job", "slug": job["slug"],
                "text": f"{job['name']}: ejecución atrasada",
            })
        elif job["status"] == "NUNCA":
            alerts.append({
                "level": "warning", "kind": "job", "slug": job["slug"],
                "text": f"{job['name']}: sin ejecuciones registradas",
            })
    if not files.nas_ready():
        alerts.append({
            "level": "danger", "kind": "nas",
            "text": f"El NAS no está montado en {config.NAS_MOUNT}",
        })
    else:
        stats = sizes.nas_stats()
        if stats and stats["percent"] >= config.NAS_MIN_FREE_PCT:
            alerts.append({
                "level": "warning", "kind": "nas",
                "text": f"NAS al {stats['percent']}% de uso",
            })
    if not db.available():
        alerts.append({
            "level": "warning", "kind": "db",
            "text": "MySQL no disponible: modo lectura (sin edición ni historial)",
        })
    skew = _clock_skew(jobs)
    if skew:
        alerts.append({
            "level": "warning", "kind": "clock",
            "text": f"Los logs van {skew} h por delante del reloj del portal: "
                    "revisa BACKUP_TZ (¿UTC?) o la zona del host",
        })
    return alerts


def _clock_skew(jobs: list[dict]) -> float | None:
    """Desfase en horas si las corridas parecen estar en el futuro (>10 min)."""
    reference = logs.now()
    worst = None
    for job in jobs:
        started = (job.get("last_run") or {}).get("started_at")
        if not started:
            continue
        try:
            when = datetime.fromisoformat(started)
        except ValueError:
            continue
        if when - reference > timedelta(minutes=10):
            worst = when if worst is None or when > worst else worst
    if worst is None:
        return None
    return round((worst - reference).total_seconds() / 3600, 1)


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
        "nas_stats": sizes.nas_stats(),
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
    bytes_total = sum(int(job["size_bytes"] or 0) for job in jobs)
    files_total = sum(int((job.get("size") or {}).get("files") or 0) for job in jobs)
    sizes.warm(effective_jobs())
    durations = [
        job["last_run"]["duration_s"]
        for job in jobs
        if job.get("last_run") and job["last_run"].get("duration_s")
    ]
    return {
        "counts": counts,
        "bytes_total": bytes_total,
        "files_total": files_total,
        "avg_duration_s": int(sum(durations) / len(durations)) if durations else None,
        "manage_cron": config.MANAGE_CRON,
        "db": db.available(),
        "nas": files.nas_ready(),
        "nas_stats": sizes.nas_stats(),
        "growth": sizes.growth(effective_jobs()),
        "alerts": build_alerts(jobs),
        "generated_at": _iso(logs.now()),
    }


@router.get("/jobs")
async def list_jobs(user: dict = Depends(auth.current_user)):
    sizes.warm(effective_jobs())
    return {
        "jobs": collect_jobs(),
        "manage_cron": config.MANAGE_CRON,
        "db": db.available(),
        "nas": files.nas_ready(),
        "nas_stats": sizes.nas_stats(),
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
            "size": sizes.current(job),
        },
        "runs": [logs.run_to_dict(run) for run in runs[-20:]][::-1],
        "log": logs.tail_log(slug, tail),
    }


@router.post("/jobs/{slug}/size/refresh")
def refresh_size(slug: str, user: dict = Depends(auth.require_admin)):
    job = find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="job no encontrado")
    if not files.nas_ready():
        raise HTTPException(status_code=503, detail="el NAS no está montado")
    size = sizes.job_size(job, force=True)
    job_id = job.get("id")
    if job_id and size.get("bytes") is not None:
        sizes.save_snapshot(job_id, size)
    audit(user["username"], "size-refresh", slug)
    return {"ok": True, "size": size}


@router.post("/jobs/{slug}/run")
async def run_job(slug: str, payload: RunIn, user: dict = Depends(auth.require_admin)):
    job = find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="job no encontrado")
    ok, message = runner.start(job, dry_run=payload.dry_run)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    action = "run-dry" if payload.dry_run else ("run-retry" if payload.retry else "run")
    audit(user["username"], action, slug)
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


@router.get("/jobs/{slug}/cron-preview")
async def cron_preview(
    slug: str,
    minute: str | None = None,
    hour: str | None = None,
    dom: str | None = None,
    month: str | None = None,
    dow: str | None = None,
    count: int = Query(5, ge=1, le=20),
    user: dict = Depends(auth.current_user),
):
    """Próximas ejecuciones de un horario propuesto (sin guardarlo)."""
    job = find_job(slug)
    if not job:
        raise HTTPException(status_code=404, detail="job no encontrado")
    schedule = _schedule(job)
    for field, value in (("minute", minute), ("hour", hour), ("dom", dom),
                         ("month", month), ("dow", dow)):
        if value is None:
            continue
        if not _cron_valid_field(value):
            raise HTTPException(status_code=400, detail=f"{field} inválido: {value}")
        schedule[field] = value.strip()
    return {
        "schedule": schedule,
        "next": [_iso(when) for when in logs.next_runs(schedule, count)],
    }


# ------------------------------- runs -------------------------------------


@router.get("/runs")
async def list_runs(
    job: str | None = None,
    status: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(auth.current_user),
):
    source = "db" if db.available() else "logs"
    return {"runs": _collect_runs(job, status, desde, hasta, limit, offset), "source": source}


@router.get("/runs/export")
async def export_runs(
    format: str = Query("csv", pattern="^(csv|json)$"),
    job: str | None = None,
    status: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limit: int = Query(5000, ge=1, le=50000),
    user: dict = Depends(auth.current_user),
):
    runs = _collect_runs(job, status, desde, hasta, limit, 0)
    stamp = logs.now().strftime("%Y%m%d-%H%M")
    if format == "json":
        payload = json.dumps(
            {"generated_at": _iso(logs.now()), "count": len(runs), "runs": runs},
            ensure_ascii=False, indent=2,
        )
        return Response(
            payload, media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="copias-{stamp}.json"'},
        )
    fields = [
        "job_slug", "started_at", "finished_at", "status", "dry_run", "duration_s",
        "size_bytes", "files_transferred", "files_removed", "error_text",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for run in runs:
        writer.writerow({key: run.get(key) for key in fields})
    return Response(
        "\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="copias-{stamp}.csv"'},
    )


def _parse_day(value: str | None, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        day = datetime.strptime(value.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return day + timedelta(days=1) if end else day


def _collect_runs(job: str | None, status: str | None, desde: str | None,
                  hasta: str | None, limit: int, offset: int) -> list[dict]:
    start = _parse_day(desde)
    end = _parse_day(hasta, end=True)
    if db.available():
        where = []
        params: list = []
        if job:
            where.append("j.slug = %s")
            params.append(job)
        if status:
            where.append("r.status = %s")
            params.append(status)
        if start:
            where.append("r.started_at >= %s")
            params.append(start)
        if end:
            where.append("r.started_at < %s")
            params.append(end)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = db.query(
            f"""
            SELECT r.*, j.slug AS job_slug, sz.size_bytes
            FROM runs r
            JOIN jobs j ON j.id = r.job_id
            LEFT JOIN (
                SELECT run_id, MAX(bytes) AS size_bytes
                FROM size_snapshots WHERE run_id IS NOT NULL GROUP BY run_id
            ) sz ON sz.run_id = r.id
            {clause}
            ORDER BY r.started_at DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        return [_run_row(row) for row in rows]

    collected = []
    for item in effective_jobs():
        if job and item["slug"] != job:
            continue
        for run in logs.parse_slug(item["slug"]):
            data = logs.run_to_dict(run)
            data["job_slug"] = item["slug"]
            if status and data["status"] != status:
                continue
            if start and (data.get("started_at") or "") < start.isoformat():
                continue
            if end and (data.get("started_at") or "") >= end.isoformat():
                continue
            collected.append(data)
    collected.sort(key=lambda run: run.get("started_at") or "", reverse=True)
    return collected[offset: offset + limit]


def _run_row(row: dict) -> dict:
    started = logs.from_naive(row["started_at"]) if row.get("started_at") else None
    finished = logs.from_naive(row["finished_at"]) if row.get("finished_at") else None
    duration = int((finished - started).total_seconds()) if started and finished else None
    if duration is not None and duration < 0:
        duration = None
    return {
        "id": row["id"],
        "job_slug": row.get("job_slug"),
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "status": row["status"],
        "dry_run": bool(row.get("dry_run")),
        "files_transferred": row.get("files_transferred", 0),
        "files_removed": row.get("files_removed", 0),
        "size_bytes": row.get("size_bytes"),
        "error_text": row.get("error_text"),
        "log_path": row.get("log_path"),
        "duration_s": duration,
    }


@router.get("/runs/{run_id}")
async def run_detail(run_id: int, user: dict = Depends(auth.current_user)):
    _require_db()
    row = db.query(
        """
        SELECT r.*, j.slug AS job_slug, sz.size_bytes
        FROM runs r
        JOIN jobs j ON j.id = r.job_id
        LEFT JOIN (
            SELECT run_id, MAX(bytes) AS size_bytes
            FROM size_snapshots WHERE run_id IS NOT NULL GROUP BY run_id
        ) sz ON sz.run_id = r.id
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


# ------------------------------ tamaños -----------------------------------


@router.get("/sizes")
async def size_series(
    days: int = Query(30, ge=1, le=365), user: dict = Depends(auth.current_user)
):
    return {"days": days, "series": sizes.series(days)}


# ------------------------------ usuarios ----------------------------------


def _validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise HTTPException(
            status_code=400,
            detail=f"la contraseña debe tener al menos {MIN_PASSWORD} caracteres",
        )


def _user_row(row: dict) -> dict:
    created = logs.from_naive(row["created_at"]) if row.get("created_at") else None
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "active": bool(row.get("active")),
        "created_at": _iso(created),
    }


@router.get("/users")
async def list_users(user: dict = Depends(auth.require_admin)):
    _require_db()
    return {"users": [_user_row(row) for row in auth.list_users()]}


@router.post("/users")
async def create_user(payload: UserIn, user: dict = Depends(auth.require_admin)):
    _require_db()
    username = payload.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail="usuario inválido (3-64: letras, números, . _ @ -)",
        )
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="rol inválido")
    _validate_password(payload.password)
    if auth.get_user(username):
        raise HTTPException(status_code=409, detail="el usuario ya existe")
    auth.create_user(username, payload.password, payload.role)
    audit(user["username"], "user-create", None, {"username": username, "role": payload.role})
    return {"ok": True}


@router.patch("/users/{username}")
async def update_user(username: str, patch: UserPatch,
                      user: dict = Depends(auth.require_admin)):
    _require_db()
    target = auth.get_user(username)
    if not target:
        raise HTTPException(status_code=404, detail="usuario no encontrado")
    last_admin = target.get("role") == "admin" and target.get("active") and auth.count_active_admins() <= 1
    if patch.role is not None:
        if patch.role not in ROLES:
            raise HTTPException(status_code=400, detail="rol inválido")
        if last_admin and patch.role != "admin":
            raise HTTPException(status_code=409, detail="no se puede degradar al último admin activo")
    if patch.active is not None:
        if not patch.active and username == user["username"]:
            raise HTTPException(status_code=409, detail="no puedes desactivar tu propia cuenta")
        if not patch.active and last_admin:
            raise HTTPException(status_code=409, detail="no se puede desactivar al último admin activo")
    if patch.role is not None:
        auth.set_role(username, patch.role)
    if patch.active is not None:
        auth.set_active(username, patch.active)
    audit(user["username"], "user-update", None, {
        "username": username, "role": patch.role, "active": patch.active,
    })
    return {"ok": True}


@router.post("/users/{username}/password")
async def reset_password(username: str, payload: PasswordIn,
                         user: dict = Depends(auth.require_admin)):
    _require_db()
    if not auth.get_user(username):
        raise HTTPException(status_code=404, detail="usuario no encontrado")
    _validate_password(payload.password)
    auth.set_password(username, payload.password)
    audit(user["username"], "user-password", None, {"username": username})
    return {"ok": True}


@router.post("/auth/password")
async def change_password(payload: SelfPasswordIn, user: dict = Depends(auth.current_user)):
    _require_db()
    row = auth.get_user(user["username"])
    if not row or not auth.verify_password(payload.current, row["password_hash"]):
        raise HTTPException(status_code=401, detail="contraseña actual incorrecta")
    _validate_password(payload.new)
    auth.set_password(user["username"], payload.new)
    audit(user["username"], "self-password")
    return {"ok": True}


# ------------------------------ auditoría ---------------------------------


def _parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


@router.get("/audit")
async def list_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    username: str | None = None,
    action: str | None = None,
    user: dict = Depends(auth.require_admin),
):
    _require_db()
    where = []
    params: list = []
    if username:
        where.append("username = %s")
        params.append(username)
    if action:
        where.append("action = %s")
        params.append(action)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = db.query(
        f"""
        SELECT id, username, action, job_slug, detail_json, created_at
        FROM audit_log
        {clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    )
    return {"entries": [
        {
            "id": row["id"],
            "username": row["username"],
            "action": row["action"],
            "job_slug": row.get("job_slug"),
            "detail": _parse_json(row.get("detail_json")),
            "created_at": _iso(logs.from_naive(row["created_at"])) if row.get("created_at") else None,
        }
        for row in rows
    ]}
