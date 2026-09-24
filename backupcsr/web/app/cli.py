"""Utilidades de línea de comandos del portal de copias.

Uso (dentro del venv, en /opt/backupcsr/web):
  venv/bin/python -m app.cli create-admin [--username admin] [--password ...]
  venv/bin/python -m app.cli apply-schema
  venv/bin/python -m app.cli sync-jobs
  venv/bin/python -m app.cli render-cron [--apply]
  venv/bin/python -m app.cli adopt-cron [--dry-run]
  venv/bin/python -m app.cli snapshot-sizes
  venv/bin/python -m app.cli resync-runs [--dry-run]
  venv/bin/python -m app.cli status
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import auth, catalog, config, cronfile, db, sizes


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


def cmd_adopt_cron(args: argparse.Namespace) -> int:
    """Adopta el cron instalado como horario en la BD (no reescribe el archivo).

    El cron instalado es la fuente de verdad del disparo; la BD es el horario
    editable del portal. Si se desvían (p. ej. tras copiar un cron nuevo con
    install.sh), el panel evalúa con el cron y avisa del desvío: este comando
    alinea la BD sin tocar `enabled` ni reescribir /etc/cron.d/backupcsr.
    """
    if not db.available():
        print(f"ERROR: MySQL no disponible ({db.last_error()})", file=sys.stderr)
        return 2
    installed = cronfile.parse()
    rows = {row["slug"]: row for row in db.query("SELECT * FROM jobs")}
    cron_only = sorted(set(installed) - set(rows))
    db_only = sorted(slug for slug in rows if slug not in installed)
    # El cron dispara el slug aunque la BD lo tenga enabled=0: el panel lo mostrará
    # DESHABILITADA (sin próxima corrida ni alertas) y, con MANAGE_CRON, la próxima
    # reescritura del cron borraría su línea. Se avisa sin tocar `enabled`.
    disabled_in_cron = sorted(
        slug for slug, row in rows.items() if slug in installed and not row.get("enabled")
    )
    changed = 0
    same = 0
    for slug, cron in sorted(installed.items()):
        row = rows.get(slug)
        if not row:
            continue
        current = {
            "minute": row.get("cron_minute"),
            "hour": row.get("cron_hour"),
            "dom": row.get("cron_dom"),
            "month": row.get("cron_month"),
            "dow": row.get("cron_dow"),
        }
        target = {
            "minute": cron["minute"],
            "hour": cron["hour"],
            "dom": cron["dom"],
            "month": cron["month"],
            "dow": cron["dow"],
        }
        if all(str(current[key]) == str(value) for key, value in target.items()):
            same += 1
            continue
        print(
            f"  {slug}: {current['minute']} {current['hour']} -> "
            f"{target['minute']} {target['hour']}"
        )
        if not args.dry_run:
            db.execute(
                """
                UPDATE jobs SET cron_minute=%s, cron_hour=%s, cron_dom=%s,
                    cron_month=%s, cron_dow=%s
                WHERE slug=%s
                """,
                (
                    target["minute"],
                    target["hour"],
                    target["dom"],
                    target["month"],
                    target["dow"],
                    slug,
                ),
            )
        changed += 1
    if args.dry_run:
        print(f"DRY-RUN: se actualizarían {changed} horario(s); {same} ya coinciden")
    else:
        print(f"horarios adoptados del cron instalado: {changed}; ya coincidían: {same}")
    if cron_only:
        print(f"AVISO: en el cron sin fila en la BD (revisar sync-jobs): {', '.join(cron_only)}")
    if db_only:
        print(f"AVISO: en la BD sin línea en el cron (deshabilitadas o sin script): {', '.join(db_only)}")
    if disabled_in_cron:
        print(
            "AVISO: el cron instalado disparará "
            f"{', '.join(disabled_in_cron)}, pero la BD lo(s) tiene enabled=0: el panel lo(s) "
            "mostrará DESHABILITADA y podría borrar su línea al reescribir el cron. "
            "Habilítalo(s) en el panel o con "
            "UPDATE jobs SET enabled=1 WHERE slug IN (...);",
            file=sys.stderr,
        )
    return 0


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


def cmd_snapshot_sizes(_args: argparse.Namespace) -> int:
    if not db.available():
        print(f"ERROR: MySQL no disponible ({db.last_error()})", file=sys.stderr)
        return 2
    if not config.NAS_MOUNT.exists():
        print(f"ERROR: el NAS no está montado en {config.NAS_MOUNT}", file=sys.stderr)
        return 2
    saved = 0
    for job in catalog.catalog_jobs():
        size = sizes.job_size(job, force=True)
        if size.get("bytes") is None:
            print(f"  {job['slug']}: sin datos ({size.get('error')})")
            continue
        row = db.query("SELECT id FROM jobs WHERE slug = %s", (job["slug"],), one=True)
        if row and sizes.save_snapshot(row["id"], size):
            saved += 1
        print(f"  {job['slug']}: {size['bytes']} bytes en {size['files']} archivos")
    print(f"snapshots guardados: {saved}")
    return 0


def cmd_resync_runs(args: argparse.Namespace) -> int:
    """Re-deriva `runs`/`run_files` desde los logs.

    Necesario tras corregir la zona horaria con que se interpretan los logs: las
    corridas ya guardadas quedan con horas desplazadas y se duplicarían.
    """
    if not db.available():
        print(f"ERROR: MySQL no disponible ({db.last_error()})", file=sys.stderr)
        return 2
    from . import api, logs

    jobs = api.effective_jobs()
    parsed = {job["slug"]: logs.parse_slug(job["slug"]) for job in jobs}
    total = sum(len(runs) for runs in parsed.values())
    if args.dry_run:
        for slug, runs in parsed.items():
            print(f"  {slug}: {len(runs)} corridas en el log")
        print(f"DRY-RUN: se borrarían las corridas de la BD y se re-insertarían {total} desde los logs")
        return 0
    db.execute("DELETE FROM run_files")
    deleted = db.execute("DELETE FROM runs")
    db.execute("UPDATE size_snapshots SET run_id = NULL WHERE run_id IS NOT NULL")
    for job in jobs:
        logs.store_runs(job, parsed[job["slug"]])
    print(f"corridas borradas: {deleted}; re-sincronizadas desde logs: {total}")
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

    adopt = sub.add_parser("adopt-cron", help="adopta el cron instalado como horario en la BD")
    adopt.add_argument("--dry-run", action="store_true", help="solo muestra los cambios")
    adopt.set_defaults(func=cmd_adopt_cron)

    sub.add_parser("status", help="estado de conexión/rutas").set_defaults(func=cmd_status)
    sub.add_parser("snapshot-sizes", help="mide y guarda el tamaño de cada job").set_defaults(
        func=cmd_snapshot_sizes
    )
    resync = sub.add_parser("resync-runs", help="re-deriva las corridas desde los logs")
    resync.add_argument("--dry-run", action="store_true", help="solo muestra lo que haría")
    resync.set_defaults(func=cmd_resync_runs)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
