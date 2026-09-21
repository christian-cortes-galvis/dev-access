"""Parser de /var/log/backupcsr/*.log y cálculo de estado/frescura.

Reimplementa en Python las reglas de backupcsr/tools/validar-copias.sh (no lo invoca):
un job está OK si su log cierra con "=== fin <job> ===" en o después de la última
ejecución que le corresponde según el horario, interpretado en America/Bogota.
"""
from __future__ import annotations

import gzip
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, db

log = logging.getLogger("backupcsr-web")

TZ = ZoneInfo(config.TIMEZONE)
# Los jobs escriben sus logs con la hora local del host (no con CRON_TZ). Se
# interpretan en esa zona y se convierten a TIMEZONE antes de comparar.
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[([^\]]+)\] (.*)$")


def host_tz():
    """Zona local del host, evaluada en cada llamada.

    No cachear en una constante de módulo: el portal corre como servicio y un cambio
    de zona (`timedatectl set-timezone`, o un host que arranca en otra zona) no reinicia
    el proceso. Una captura al importar dejaría los logs nuevos mal interpretados
    (offset viejo) hasta reiniciar `backupcsr-web`, con horas/duraciones y `TARDE`
    incorrectos.
    """
    return datetime.now().astimezone().tzinfo

TRANSFER_RE = re.compile(r"^Transferring file `(.+)'$")
REMOVE_RE = re.compile(r"^Removing old file `(.+)'$")
ERROR_HINT_RE = re.compile(r"fatal|error|failed|refused|denied|no such|timeout|retries", re.I)


def now() -> datetime:
    return datetime.now(TZ)


def parse_log_time(timestamp: str) -> datetime:
    """Hora de un log (zona del host) expresada en la zona configurada."""
    naive = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=host_tz()).astimezone(TZ)


def to_naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def from_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def _fmt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def log_files(slug: str) -> list[Path]:
    directory = config.LOG_DIR
    if not directory.exists():
        return []
    found = list(directory.glob(f"{slug}.log*"))
    found.sort(key=lambda p: p.stat().st_mtime)
    return found


def _iter_lines(files: list[Path]):
    for path in files:
        try:
            if path.suffix == ".gz":
                with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        yield path, line.rstrip("\n")
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        yield path, line.rstrip("\n")
        except OSError as exc:
            log.warning("no se pudo leer %s: %s", path, exc)


def parse_slug(slug: str) -> list[dict]:
    """Devuelve la lista de corridas encontradas en los logs (más antigua primero)."""
    runs: list[dict] = []
    current: dict | None = None

    def close(status: str | None = None) -> None:
        nonlocal current
        if current is None:
            return
        if status:
            current["status"] = status
        runs.append(current)
        current = None

    for path, line in _iter_lines(log_files(slug)):
        match = TS_RE.match(line)
        if match:
            timestamp, _job, message = match.groups()
            started = parse_log_time(timestamp)
            if message.startswith("=== inicio "):
                close("INCIERTO")
                current = {
                    "started_at": started,
                    "finished_at": None,
                    "status": "EN_CURSO",
                    "dry_run": 1 if "(dry_run=1)" in message else 0,
                    "files_transferred": 0,
                    "files_removed": 0,
                    "error_text": None,
                    "truncated": False,
                    "log_path": str(path),
                    "_files": [],
                    "_finished": False,
                }
            elif current is None:
                continue
            elif message.startswith("=== fin "):
                current["finished_at"] = started
                current["_finished"] = True
                close("OK")
            elif message.startswith("FALLO:") or message.startswith("ERROR:"):
                current["status"] = "FALLO"
                if not current["error_text"]:
                    current["error_text"] = message[:1000]
            continue

        if current is None:
            continue
        transfer = TRANSFER_RE.match(line)
        if transfer:
            current["files_transferred"] += 1
            if len(current["_files"]) < config.MAX_RUN_FILES:
                current["_files"].append((transfer.group(1)[:512], "transfer"))
            else:
                current["truncated"] = True
            continue
        remove = REMOVE_RE.match(line)
        if remove:
            current["files_removed"] += 1
            if len(current["_files"]) < config.MAX_RUN_FILES:
                current["_files"].append((remove.group(1)[:512], "remove"))
            else:
                current["truncated"] = True
            continue
        if not current["error_text"] and ERROR_HINT_RE.search(line):
            current["error_text"] = line.strip()[:1000]

    close(None)
    return runs


def latest_run(slug: str) -> dict | None:
    runs = parse_slug(slug)
    return runs[-1] if runs else None


def _expand_field(spec: str, lo: int, hi: int) -> list[int]:
    values: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            values.update(range(lo, hi + 1))
            continue
        step = 1
        base = part
        if "/" in part:
            base, _, raw_step = part.partition("/")
            try:
                step = max(1, int(raw_step))
            except ValueError:
                step = 1
        if base in ("", "*"):
            start, end = lo, hi
        elif "-" in base:
            raw_a, _, raw_b = base.partition("-")
            try:
                start, end = int(raw_a), int(raw_b)
            except ValueError:
                continue
        else:
            try:
                start = end = int(base)
            except ValueError:
                continue
        start = max(lo, start)
        end = min(hi, end)
        for value in range(start, end + 1, step):
            values.add(value)
    return sorted(values)


def _candidates(schedule: dict, day) -> list[datetime]:
    minutes = _expand_field(schedule.get("minute", "0"), 0, 59)
    hours = _expand_field(schedule.get("hour", "0"), 0, 23)
    return [
        datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)
        for hour in hours
        for minute in minutes
    ]


def last_expected(schedule: dict, reference: datetime | None = None) -> datetime | None:
    reference = reference or now()
    for back in range(0, 8):
        day = (reference - timedelta(days=back)).date()
        valid = [c for c in _candidates(schedule, day) if c <= reference]
        if valid:
            return max(valid)
    return None


def next_run(schedule: dict, reference: datetime | None = None) -> datetime | None:
    reference = reference or now()
    for forward in range(0, 8):
        day = (reference + timedelta(days=forward)).date()
        valid = [c for c in _candidates(schedule, day) if c > reference]
        if valid:
            return min(valid)
    return None


def next_runs(schedule: dict, count: int = 5, reference: datetime | None = None) -> list[datetime]:
    """Próximas `count` ejecuciones del horario (para previsualizar cambios de cron)."""
    out: list[datetime] = []
    cursor = reference or now()
    for _ in range(max(1, min(int(count), 50))):
        nxt = next_run(schedule, cursor)
        if nxt is None:
            break
        out.append(nxt)
        cursor = nxt + timedelta(seconds=1)
    return out


def evaluate(run: dict | None, schedule: dict, reference: datetime, running: bool,
             grace_min: int | None = None) -> tuple[str, str]:
    """Estado y detalle de un job según su última corrida y el horario."""
    grace = grace_min if grace_min is not None else config.GRACE_MIN
    if run is None:
        return "NUNCA", "sin ejecuciones registradas"

    started = from_naive(run["started_at"]) if run.get("started_at") else None
    finished = run.get("finished_at")
    if isinstance(finished, datetime):
        finished = from_naive(finished)

    if run.get("_finished") and run.get("status") == "OK":
        expected = last_expected(schedule, reference)
        if expected is None:
            return "OK", "cierre correcto; horario no verificable"
        if finished and finished >= expected - timedelta(seconds=60):
            return "OK", "última ejecución al día"
        return "TARDE", "último cierre anterior a la ejecución esperada"

    if run.get("status") == "FALLO":
        return "FALLO", run.get("error_text") or "el log reporta FALLO"

    # inicio sin cierre
    if running:
        detail = f"corriendo desde {started:%Y-%m-%d %H:%M:%S}" if started else "en curso"
        return "EN_CURSO", detail
    if started and (reference - started) <= timedelta(minutes=grace):
        return "EN_CURSO", f"inicio sin cierre, dentro de la gracia ({grace}m)"
    if run.get("error_text"):
        return "FALLO", run["error_text"]
    return "FALLO", "inicio sin cierre y proceso ausente (revisar el log)"


def run_to_dict(run: dict) -> dict:
    return {
        "started_at": _fmt(from_naive(run["started_at"])) if run.get("started_at") else None,
        "finished_at": _fmt(from_naive(run["finished_at"])) if run.get("finished_at") else None,
        "status": run.get("status"),
        "dry_run": bool(run.get("dry_run")),
        "files_transferred": run.get("files_transferred", 0),
        "files_removed": run.get("files_removed", 0),
        "error_text": run.get("error_text"),
        "truncated": bool(run.get("truncated")),
        "log_path": run.get("log_path"),
        "duration_s": _duration(run),
    }


def _duration(run: dict) -> int | None:
    if not run.get("started_at"):
        return None
    end = run.get("finished_at") or now()
    if isinstance(end, datetime) and end.tzinfo is None:
        end = from_naive(end)
    seconds = int((end - from_naive(run["started_at"])).total_seconds())
    # Negativo = el log va por delante del reloj del portal (desfase de TZ):
    # preferimos "sin dato" a mostrar una duración imposible.
    return seconds if seconds >= 0 else None


def _db_status(run: dict) -> str:
    status = run.get("status")
    return status if status in ("OK", "FALLO", "EN_CURSO", "INCIERTO") else "INCIERTO"


def store_runs(job: dict, runs: list[dict]) -> None:
    """Persiste corridas nuevas/abiertas en MySQL (idempotente por started_at)."""
    if not db.available():
        return
    job_id = job.get("id")
    if not job_id:
        row = db.query("SELECT id FROM jobs WHERE slug = %s", (job["slug"],), one=True)
        if not row:
            return
        job_id = row["id"]
    existing = {
        to_naive(row["started_at"])
        for row in db.query("SELECT started_at FROM runs WHERE job_id = %s", (job_id,))
    }
    for run in runs[-200:]:
        started = to_naive(from_naive(run["started_at"]))
        finished = to_naive(run["finished_at"]) if run.get("finished_at") else None
        common = (
            finished,
            _db_status(run),
            int(run["dry_run"]),
            int(run["files_transferred"]),
            int(run["files_removed"]),
            run.get("error_text"),
            1 if run.get("truncated") else 0,
            str(run.get("log_path") or ""),
        )
        if started not in existing:
            run_id = db.insert(
                """
                INSERT INTO runs (
                    job_id, started_at, finished_at, status, dry_run,
                    files_transferred, files_removed, error_text, truncated, log_path
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (job_id, started, *common),
            )
            files = run.get("_files") or []
            if files:
                db.executemany(
                    "INSERT INTO run_files (run_id, path, action) VALUES (%s, %s, %s)",
                    [(run_id, path, action) for path, action in files],
                )
            existing.add(started)
        else:
            db.execute(
                """
                UPDATE runs SET finished_at=%s, status=%s, dry_run=%s,
                    files_transferred=%s, files_removed=%s, error_text=%s,
                    truncated=%s, log_path=%s
                WHERE job_id=%s AND started_at=%s
                """,
                (*common, job_id, started),
            )


def tail_log(slug: str, lines: int = 200) -> str:
    path = config.LOG_DIR / f"{slug}.log"
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.readlines()
    return "".join(content[-max(1, min(lines, 5000)):])
