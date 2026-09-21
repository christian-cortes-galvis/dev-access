"""Utilidades de línea de comandos del portal de copias.

Uso (dentro del venv, en /opt/backupcsr/web):
  venv/bin/python -m app.cli create-admin [--username admin] [--password ...]
  venv/bin/python -m app.cli apply-schema
  venv/bin/python -m app.cli sync-jobs
  venv/bin/python -m app.cli render-cron [--apply]
  venv/bin/python -m app.cli status
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import auth, catalog, config, cronfile, db


def cmd_create_admin(args: argparse.Namespace) -> int:
    if not db.available():
        print(f"ERROR: MySQL no disponible ({db.last_error()})", file=sys.stderr)
        return 2
    password = args.password or getpass.getpass("Contraseña del admin: ")
    if len(password) < 8:
        print("ERROR: la contraseña debe tener al menos 8 caracteres", file=sys.stderr)
        return 2
    auth.create_user(args.username, password, "admin")
    print(f"usuario '{args.username}' creado/actualizado como admin")
    return 0


def cmd_apply_schema(_args: argparse.Namespace) -> int:
    if not db.available():
        print(f"ERROR: MySQL no disponible ({db.last_error()})", file=sys.stderr)
        return 2
    db.init_schema()
    print("esquema aplicado (idempotente)")
    return 0


def cmd_sync_jobs(_args: argparse.Namespace) -> int:
    if not db.available():
        print(f"ERROR: MySQL no disponible ({db.last_error()})", file=sys.stderr)
        return 2
    db.init_schema()
    count = catalog.sync_jobs()
    print(f"catálogo sincronizado: {count} jobs")
    return 0


def cmd_render_cron(args: argparse.Namespace) -> int:
    jobs = catalog.catalog_jobs()
    if db.available():
        from . import api

        jobs = api.effective_jobs()
    if args.apply:
        if not config.MANAGE_CRON:
            print("ERROR: BACKUP_MANAGE_CRON=0; no se escribe el cron", file=sys.stderr)
            return 2
        cronfile.write(jobs)
        print(f"cron reescrito en {config.CRON_FILE}")
        return 0
    diff = cronfile.diff(jobs)
    if diff["igual"]:
        print("el cron actual coincide con el render")
        return 0
    print("el cron actual DIFIERE del render:")
    for item in diff["diferencias"]:
        print(f"  {item['slug']}: actual={item['actual']} deseado={item['deseado']}")
    return 1


def cmd_status(_args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "db": db.available(),
                "db_error": db.last_error(),
                "manage_cron": config.MANAGE_CRON,
                "cron_path": str(config.CRON_FILE),
                "nas": config.NAS_MOUNT.exists(),
                "logs": str(config.LOG_DIR),
                "jobs": [job["slug"] for job in catalog.catalog_jobs()],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Utilidades de backupcsr-web")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-admin", help="crea/actualiza un usuario admin")
    create.add_argument("--username", default=config.ADMIN_USER)
    create.add_argument("--password", default="")
    create.set_defaults(func=cmd_create_admin)

    sub.add_parser("apply-schema", help="aplica schema.sql").set_defaults(func=cmd_apply_schema)
    sub.add_parser("sync-jobs", help="sincroniza jobs.yml con la BD").set_defaults(
        func=cmd_sync_jobs
    )

    render = sub.add_parser("render-cron", help="compara/reescribe /etc/cron.d/backupcsr")
    render.add_argument("--apply", action="store_true", help="escribe el cron (si MANAGE_CRON=1)")
    render.set_defaults(func=cmd_render_cron)

    sub.add_parser("status", help="estado de conexión/rutas").set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
