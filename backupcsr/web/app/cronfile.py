"""Lectura/escritura de /etc/cron.d/backupcsr.

El portal solo reescribe el archivo cuando BACKUP_MANAGE_CRON=1. El formato generado
es idéntico al que ya entiende tools/validar-copias.sh (una línea por job habilitado,
con flock y la ruta /opt/backupcsr/jobs/<slug>.sh), para no romper el validador.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime

from . import config

log = logging.getLogger("backupcsr-web")

JOB_RE = re.compile(r"/jobs/([A-Za-z0-9_.-]+)\.sh")

HEADER = [
    "# Copias de seguridad (backupcsr) - ubuntu-services.",
    "# Generado por backupcsr-web. No editar a mano: se sobrescribe.",
    "# El cron NO honra CRON_TZ: los horarios se evaluan en la zona del host, que debe ser",
    "# __TZ__ (validar-copias.sh lo verifica). La linea CRON_TZ solo exporta el env.",
    "SHELL=/bin/bash",
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG=C.UTF-8",
    "CRON_TZ=__TZ__",
    'MAILTO=""',
    "",
]


def header() -> list[str]:
    return [line.replace("__TZ__", config.TIMEZONE) for line in HEADER]


def parse(text: str | None = None) -> dict:
    """Devuelve {slug: {minute,hour,dom,month,dow}} leído del cron instalado."""
    if text is None:
        if not config.CRON_FILE.exists():
            return {}
        text = config.CRON_FILE.read_text(encoding="utf-8")
    jobs: dict[str, dict] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "/jobs/" not in line:
            continue
        match = JOB_RE.search(line)
        if not match:
            continue
        fields = line.split()
        if len(fields) < 7:
            continue
        jobs[match.group(1)] = {
            "minute": fields[0],
            "hour": fields[1],
            "dom": fields[2],
            "month": fields[3],
            "dow": fields[4],
        }
    return jobs


def command_for(slug: str, lockfile: str | None = None) -> str:
    lock = lockfile or f"/run/lock/backupcsr-{slug}.lock"
    return f"flock -n {lock} {config.JOBS_DIR}/{slug}.sh"


def render(jobs: list[dict]) -> str:
    lines = list(header())
    for job in sorted(jobs, key=lambda item: item.get("sort", 100)):
        if not job.get("enabled"):
            continue
        command = command_for(job["slug"], job.get("lockfile"))
        lines.append(
            f'{job["cron_minute"]} {job["cron_hour"]} {job["cron_dom"]} '
            f'{job["cron_month"]} {job["cron_dow"]}  root  {command}'
        )
    lines.append("")
    return "\n".join(lines)


def validate(text: str, expected_slugs: set[str] | None = None) -> None:
    parsed = parse(text)
    if expected_slugs is not None and set(parsed) != set(expected_slugs):
        raise ValueError(
            f"cron inválido: esperados {sorted(expected_slugs)}, obtenidos {sorted(parsed)}"
        )
    if "\r" in text:
        raise ValueError("el cron generado contiene CRLF")


def current_text() -> str:
    if not config.CRON_FILE.exists():
        return ""
    return config.CRON_FILE.read_text(encoding="utf-8")


def diff(jobs: list[dict]) -> dict:
    from_file = parse()
    rendered = render(jobs)
    rendered_parsed = parse(rendered)
    enabled = {job["slug"] for job in jobs if job.get("enabled")}
    differences = []
    for slug in sorted(enabled | set(from_file)):
        actual = from_file.get(slug)
        desired = rendered_parsed.get(slug)
        if actual != desired:
            differences.append({"slug": slug, "actual": actual, "deseado": desired})
    return {
        "igual": not differences and current_text() == rendered,
        "diferencias": differences,
        "render": rendered,
        "actual": current_text(),
    }


def write(jobs: list[dict]) -> str:
    """Escribe el cron de forma atómica, con backup previo, y recarga cron.

    El backup y el temporal se escriben FUERA de /etc/cron.d: cron lee todos los
    archivos de ese directorio y ejecutaría un `.bak.<ts>` o un `.tmp` como si fuera
    un crontab. Se escribe el temporal en /etc/backupcsr y se hace rename atómico
    (mismo sistema de archivos) sobre /etc/cron.d/backupcsr.
    """
    text = render(jobs)
    enabled = {job["slug"] for job in jobs if job.get("enabled")}
    validate(text, expected_slugs=enabled)
    if "\r" in text:
        raise ValueError("el cron generado contiene CRLF")

    target = config.CRON_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_dir = config.ETC_DIR / "cron-backups"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(backup_dir, 0o700)
        if target.exists():
            backup = backup_dir / f"backupcsr.{stamp}"
            backup.write_text(current_text(), encoding="utf-8")
            os.chmod(backup, 0o600)
    except OSError as exc:
        log.warning("no se pudo respaldar el cron actual: %s", exc)

    tmp = config.ETC_DIR / f".backupcsr.cron.{stamp}.tmp"
    config.ETC_DIR.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, target)
    log.info("cron reescrito: %s jobs habilitados", len(enabled))
    reload_cron()
    return text


def reload_cron() -> bool:
    try:
        subprocess.run(["systemctl", "reload", "cron"], timeout=10, check=False)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("no se pudo recargar cron: %s", exc)
        return False
