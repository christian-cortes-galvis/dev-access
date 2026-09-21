"""Navegador de solo lectura de /mnt/nas, confinado a la raíz del NAS.

Cualquier ruta se resuelve con realpath y debe quedar dentro del ancla (por defecto la
raíz del NAS; para un job, su carpeta de destino). Los enlaces simbólicos que escapen se
rechazan. No se permite borrar ni escribir.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from . import config


def nas_ready() -> bool:
    mount = config.NAS_MOUNT
    return mount.exists() and os.path.ismount(mount) and os.access(mount, os.R_OK)


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _resolve(rel: str | None, anchor: Path | None) -> tuple[Path, Path, Path]:
    base = config.NAS_MOUNT.resolve()
    root = (anchor or base).resolve()
    if not _within(root, base):
        raise HTTPException(status_code=400, detail="ancla fuera del NAS")
    target = (root / (rel or "")).resolve()
    if not _within(target, root):
        raise HTTPException(status_code=400, detail="ruta fuera del ancla")
    return base, root, target


def _rel_to(path: Path, root: Path) -> str:
    return "" if path == root else str(path.relative_to(root))


def _entry(path: Path, root: Path) -> dict | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {
        "name": path.name,
        "path": _rel_to(path, root),
        "type": "dir" if path.is_dir() else "file",
        "size": int(stat.st_size),
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def list_dir(rel: str | None = None, anchor: Path | None = None, limit: int = 2000) -> dict:
    if not nas_ready():
        raise HTTPException(status_code=503, detail=f"el NAS no está montado en {config.NAS_MOUNT}")
    _base, root, target = _resolve(rel, anchor)
    if not target.exists():
        raise HTTPException(status_code=404, detail="la ruta no existe")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="la ruta no es un directorio")

    entries: list[dict] = []
    truncated = False
    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"no se pudo leer: {exc}") from exc
    for index, child in enumerate(children):
        if index >= limit:
            truncated = True
            break
        item = _entry(child, root)
        if item:
            entries.append(item)

    rel_path = _rel_to(target, root)
    parent = ""
    if rel_path:
        parent_rel = str(PurePosixPath(rel_path).parent)
        parent = "" if parent_rel == "." else parent_rel

    return {
        "base": str(config.NAS_MOUNT),
        "anchor": _rel_to(root, _base),
        "path": rel_path,
        "parent": parent,
        "entries": entries,
        "truncated": truncated,
    }
