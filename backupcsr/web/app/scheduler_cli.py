"""CLI del planificador: lo llama cron y también el operador.

    backupcsr-scheduler submit <slug> [--action run|dry|retry|size] [--trigger cron|manual]
    backupcsr-scheduler status
    backupcsr-scheduler cancel <slug>

`submit` cae a ejecución directa serial si el daemon no responde (salvo --no-fallback):
así una caída del planificador no deja las copias sin correr, y el script conserva su
`MIRROR_GATE` como protección.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

from . import config, scheduler_client

SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _fallback(slug: str, reason: str) -> int:
    script = config.JOBS_DIR / f"{slug}.sh"
    if not script.is_file():
        print(f"planificador no disponible ({reason}) y no existe {script}", file=sys.stderr)
        return 3
    print(f"AVISO: planificador no disponible ({reason}); ejecución directa serial de {slug}",
          file=sys.stderr)
    lock = f"/run/lock/backupcsr-{slug}.lock"
    flock = shutil.which("flock")
    if flock:
        # Mismo flock por job que usaba el cron anterior: no reejecuta si ya corre.
        os.execv(flock, [flock, "-n", lock, "/bin/bash", str(script)])
    os.execv("/bin/bash", ["/bin/bash", str(script)])
    return 3


def _submit_once(slug, action, trigger, username):
    """Un reintento porque un timeout puede ocurrir tras encolar (el daemon deduplica)."""
    last = None
    for _ in (1, 2):
        try:
            return scheduler_client.submit(
                slug, action=action, trigger=trigger, username=username,
            )
        except scheduler_client.SchedulerUnavailable as exc:
            last = exc
    raise last


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backupcsr-scheduler")
    sub = parser.add_subparsers(dest="cmd", required=True)

    submit = sub.add_parser("submit", help="encola una ronda")
    submit.add_argument("slug")
    submit.add_argument("--action", default="run", choices=("run", "dry", "retry", "size"))
    submit.add_argument("--trigger", default="cron", choices=("cron", "manual"))
    submit.add_argument("--username", default="")
    submit.add_argument("--no-fallback", action="store_true",
                        help="no ejecutar el script si el planificador no responde")

    sub.add_parser("status", help="estado de la cola")
    cancel = sub.add_parser("cancel", help="quita una ronda pendiente")
    cancel.add_argument("slug")

    args = parser.parse_args(argv)
    if args.cmd in ("submit", "cancel") and not SLUG_RE.match(args.slug):
        print(f"slug inválido: {args.slug}", file=sys.stderr)
        return 2
    try:
        if args.cmd == "submit":
            result = _submit_once(args.slug, args.action, args.trigger, args.username)
        elif args.cmd == "status":
            result = scheduler_client.status()
        else:
            result = scheduler_client.cancel(args.slug)
    except scheduler_client.SchedulerUnavailable as exc:
        if args.cmd == "submit" and not args.no_fallback:
            return _fallback(args.slug, str(exc))
        print(f"planificador no disponible: {exc}", file=sys.stderr)
        return 3

    print(json.dumps(result, ensure_ascii=False))
    if args.cmd == "status":
        return 0 if result.get("available") else 2
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
