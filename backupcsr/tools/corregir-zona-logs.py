#!/usr/bin/env python3
"""Corrige la zona horaria de los logs de backupcsr escritos en UTC.

Contexto: mientras el host estuvo en `Etc/UTC`, `date` escribió los timestamps de
`/var/log/backupcsr/*.log` en UTC. Tras pasar el host a `America/Bogota`, los logs quedan
mezclados (tramo viejo en UTC, tramo nuevo en Bogotá) y el portal avisa
"los logs van N h por delante del reloj del portal" (api._clock_skew), y las duraciones /
estados salen mal.

Este corrector resta el desplazamiento de la zona destino (5 h en Bogotá) a las líneas con
timestamp del tramo UTC. Si detecta el salto hacia atrás (~5 h) que marca el cambio de
zona, convierte **solo** las líneas anteriores a ese salto, de modo que es seguro aunque ya
existan líneas nuevas en Bogotá. Si no hay salto, considera que todo el fichero es del
tramo viejo y lo convierte entero.

Es de un solo uso: deja una marca por fichero en `<dir>/tz-fixed/` y no vuelve a tocarlo.

Uso (root, desde el checkout):
    sudo python3 backupcsr/tools/corregir-zona-logs.py            # dry-run (no escribe)
    sudo python3 backupcsr/tools/corregir-zona-logs.py --apply    # aplica, con respaldo

Opciones:
    --dir DIR       directorio de logs (def. /var/log/backupcsr)
    --target TZ     zona destino (def. America/Bogota)
    --apply         escribe los cambios (sin esto solo muestra qué haría)

Tras aplicarlo, re-deriva el historial del portal (runs/run_files salen de los logs):
    cd /opt/backupcsr/web && venv/bin/python -m app.cli resync-runs --dry-run
    cd /opt/backupcsr/web && venv/bin/python -m app.cli resync-runs
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
FMT = "%Y-%m-%d %H:%M:%S"
BACKWARD = timedelta(hours=3)


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, FMT).replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dir", default="/var/log/backupcsr")
    parser.add_argument("--target", default="America/Bogota")
    parser.add_argument("--apply", action="store_true", help="escribe (def. dry-run)")
    args = parser.parse_args()

    target = ZoneInfo(args.target)
    root = Path(args.dir)
    if not root.is_dir():
        print(f"no existe el directorio {root}", file=sys.stderr)
        return 2
    state_dir = root / "tz-fixed"
    backup_dir = root / "utc-backup"
    logs = sorted(p for p in root.glob("*.log") if p.is_file())
    if not logs:
        print(f"no hay *.log en {root}", file=sys.stderr)
        return 2

    total = 0
    for path in logs:
        if (state_dir / path.name).exists():
            print(f"{path.name}: ya marcado como corregido, se omite")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        stamps = []
        for index, line in enumerate(lines):
            match = TS_RE.match(line)
            if match:
                stamps.append((index, parse_utc(match.group(1)), match.group(1)))
        if not stamps:
            print(f"{path.name}: sin líneas con timestamp, se omite")
            continue

        # El cambio de zona aparece como un salto hacia atrás de ~5 h en el log.
        cut = len(stamps)
        for pos in range(1, len(stamps)):
            if stamps[pos][1] < stamps[pos - 1][1] - BACKWARD:
                cut = pos
                break
        converted = stamps[:cut]
        skipped = stamps[cut:]
        example = converted[0][1]
        print(
            f"{path.name}: convertir {len(converted)} líneas"
            + (f", respetar {len(skipped)} ya en {args.target}" if skipped else "")
            + f"  (p.ej. {example.strftime(FMT)} UTC -> "
            f"{example.astimezone(target).strftime(FMT)} {args.target})"
        )
        if not args.apply:
            total += len(converted)
            continue

        state_dir.mkdir(exist_ok=True)
        backup_dir.mkdir(exist_ok=True)
        shutil.copy2(path, backup_dir / path.name)
        for index, ts, old in converted:
            new = ts.astimezone(target).strftime(FMT)
            lines[index] = lines[index].replace(old, new, 1)
        tmp = root / (path.name + ".tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        shutil.copystat(path, tmp)
        os.replace(tmp, path)
        (state_dir / path.name).touch()
        print(f"    aplicado; respaldo en {backup_dir / path.name}")
        total += len(converted)

    if not args.apply:
        print(f"\nDRY-RUN: se convertirían {total} líneas. Repite con --apply para escribir.")
    else:
        print(f"\nListo: {total} líneas convertidas a {args.target}.")
        print("Ahora re-deriva el historial del portal: app.cli resync-runs (ver cabecera).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
