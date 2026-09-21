"""Navegador y gestor de /mnt/nas, confinado a la raíz del NAS.

Cada ruta se resuelve por partes: el directorio padre debe quedar dentro del ancla (por
defecto la raíz del NAS; para un job, su carpeta de destino) y el último segmento se trata
como hoja **sin seguir enlaces simbólicos**, de modo que borrar o renombrar un enlace nunca
actúe sobre su destino. Los enlaces que apunten fuera del ancla se rechazan.

Las operaciones de escritura (borrar, renombrar, mover, crear carpeta, subir) validan el
nombre, no pisan nada existente y se niegan a tocar la raíz del ancla.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from . import config

log = logging.getLogger("backupcsr-web")

MAX_NAME = 200
TREE_MAX_ENTRIES = 20000
# SMB/Windows: prohibidos en un nombre y reservados por el sistema.
BAD_CHARS = set('/\\:*?"<>|')
RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


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
    if (rel or "").startswith("/"):
        raise HTTPException(status_code=400, detail="usa una ruta relativa al ancla")
    target = (root / (rel or "")).resolve()
    if not _within(target, root):
        raise HTTPException(status_code=400, detail="ruta fuera del ancla")
    return base, root, target


def _leaf(rel: str | None, anchor: Path | None) -> tuple[Path, Path, Path]:
    """(base, root, hoja): resuelve el padre y deja el último segmento sin resolver.

    Así un enlace simbólico se trata como lo que es (una entrada más) y nunca se
    borra/renombra el archivo al que apunta.
    """
    base = config.NAS_MOUNT.resolve()
    root = (anchor or base).resolve()
    if not _within(root, base):
        raise HTTPException(status_code=400, detail="ancla fuera del NAS")
    if (rel or "").startswith("/"):
        raise HTTPException(status_code=400, detail="usa una ruta relativa al ancla")
    parts = [part for part in PurePosixPath((rel or "").strip("/")).parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="ruta fuera del ancla")
    if not parts:
        raise HTTPException(status_code=400, detail="no se puede operar sobre la raíz del ancla")
    parent = (root / PurePosixPath(*parts[:-1])).resolve() if len(parts) > 1 else root
    if not _within(parent, root):
        raise HTTPException(status_code=400, detail="ruta fuera del ancla")
    target = parent / parts[-1]
    if target == root or target == base:
        raise HTTPException(status_code=400, detail="no se puede operar sobre la raíz")
    return base, root, target


def _dir(rel: str | None, anchor: Path | None) -> tuple[Path, Path, Path]:
    """(base, root, directorio) siguiendo enlaces y validando el ancla."""
    base, root, target = _resolve(rel or "", anchor)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="la ruta no es un directorio")
    return base, root, target


def clean_name(name: str) -> str:
    """Valida un nombre de una sola pieza para crear, renombrar o subir."""
    value = name if isinstance(name, str) else ""
    if not value or value in (".", ".."):
        raise HTTPException(status_code=400, detail="nombre inválido")
    if value != value.strip() or value.endswith("."):
        raise HTTPException(
            status_code=400,
            detail="el nombre no puede empezar/terminar en espacio ni terminar en punto",
        )
    if len(value) > MAX_NAME or len(value.encode("utf-8")) > 255:
        raise HTTPException(status_code=400, detail=f"nombre demasiado largo (máx. {MAX_NAME})")
    for char in value:
        if char in BAD_CHARS or ord(char) < 32:
            raise HTTPException(
                status_code=400,
                detail='el nombre no puede contener / \\ : * ? " < > | ni caracteres de control',
            )
    if value.split(".")[0].upper() in RESERVED_NAMES:
        raise HTTPException(status_code=400, detail=f"'{value}' es un nombre reservado")
    return value


def _rel_to(path: Path, root: Path) -> str:
    return "" if path == root else str(path.relative_to(root))


def _same(first: Path, second: Path) -> bool:
    """¿Son la misma entrada? (para permitir cambiar solo mayúsculas en CIFS)."""
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _entry(path: Path, root: Path) -> dict | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {
        "name": path.name,
        "path": _rel_to(path, root),
        "type": "dir" if path.is_dir() else "file",
        "link": path.is_symlink(),
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


def tree_info(path: Path, max_entries: int = TREE_MAX_ENTRIES) -> dict:
    """Cuenta entradas y bytes bajo `path` sin seguir enlaces; acota el recorrido."""
    entries = 0
    total = 0
    partial = False
    pending = [path]
    while pending and not partial:
        current = pending.pop()
        try:
            with os.scandir(current) as items:
                for item in items:
                    entries += 1
                    if entries > max_entries:
                        partial = True
                        break
                    try:
                        info = item.stat(follow_symlinks=False)
                    except OSError:
                        partial = True
                        continue
                    if item.is_symlink():
                        continue
                    if item.is_dir(follow_symlinks=False):
                        pending.append(Path(item.path))
                    else:
                        total += int(info.st_size)
        except OSError:
            partial = True
    return {"entries": entries, "bytes": total, "partial": partial}


def entry_info(rel: str, anchor: Path | None = None) -> dict:
    """Datos de una entrada (con conteo de una carpeta) para confirmar operaciones."""
    _base, root, target = _leaf(rel, anchor)
    if not os.path.lexists(target):
        raise HTTPException(status_code=404, detail="la ruta no existe")
    stat = target.lstat()
    link = target.is_symlink()
    is_dir = target.is_dir() and not link
    info = {
        "name": target.name,
        "path": _rel_to(target, root),
        "type": "dir" if is_dir else ("link" if link else "file"),
        "link": link,
        "size": int(stat.st_size),
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "entries": 1,
        "bytes": int(stat.st_size),
        "partial": False,
    }
    if is_dir:
        tree = tree_info(target)
        info.update(entries=tree["entries"], bytes=tree["bytes"], partial=tree["partial"])
    elif link:
        # A dónde apunta (solo informativo): borrar/renombrar actúa sobre el enlace.
        resolved = target.resolve()
        info["target"] = _rel_to(resolved, root) if _within(resolved, root) else None
    return info


def delete(rel: str, anchor: Path | None = None, confirm: str = "") -> dict:
    """Elimina una entrada. Exige `confirm` igual al nombre (defensa en profundidad)."""
    _base, root, target = _leaf(rel, anchor)
    info = entry_info(rel, anchor)
    if confirm != info["name"]:
        raise HTTPException(
            status_code=400,
            detail=f"escribe el nombre «{info['name']}» para confirmar la eliminación",
        )
    try:
        if info["type"] == "dir":
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"no se pudo eliminar: {exc}") from exc
    return {
        "entries": info["entries"],
        "bytes": info["bytes"],
        "type": info["type"],
        "path": info["path"],
        "partial": info["partial"],
    }


def rename(rel: str, anchor: Path | None, name: str) -> dict:
    _base, root, target = _leaf(rel, anchor)
    if not os.path.lexists(target):
        raise HTTPException(status_code=404, detail="la ruta no existe")
    new_name = clean_name(name)
    if new_name == target.name:
        return {"path": _rel_to(target, root), "name": new_name, "unchanged": True}
    destination = target.parent / new_name
    if os.path.lexists(destination) and not _same(target, destination):
        raise HTTPException(status_code=409, detail=f"ya existe «{new_name}» en esa carpeta")
    try:
        os.rename(target, destination)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"no se pudo renombrar: {exc}") from exc
    return {"path": _rel_to(destination, root), "name": new_name}


def make_dir(rel_dir: str | None, anchor: Path | None, name: str) -> dict:
    _base, root, parent = _dir(rel_dir, anchor)
    new_name = clean_name(name)
    destination = parent / new_name
    if os.path.lexists(destination):
        raise HTTPException(status_code=409, detail=f"ya existe «{new_name}» en esa carpeta")
    try:
        destination.mkdir()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"no se pudo crear la carpeta: {exc}") from exc
    return {"path": _rel_to(destination, root), "name": new_name}


def move(rel: str, anchor: Path | None, dest_rel: str | None = None) -> dict:
    _base, root, source = _leaf(rel, anchor)
    if not os.path.lexists(source):
        raise HTTPException(status_code=404, detail="la ruta no existe")
    _dest_base, _dest_root, destination = _dir(dest_rel, anchor)
    if source == destination:
        raise HTTPException(status_code=400, detail="el origen y el destino son la misma carpeta")
    real_source = source.resolve()
    real_dest = destination.resolve()
    if real_source == real_dest or real_source in real_dest.parents:
        raise HTTPException(status_code=400, detail="no se puede mover una carpeta dentro de sí misma")
    if source.parent == destination:
        raise HTTPException(status_code=400, detail="el origen ya está en esa carpeta")
    target = destination / source.name
    if os.path.lexists(target):
        raise HTTPException(
            status_code=409,
            detail=f"ya existe «{source.name}» en {dest_rel or 'la raíz del job'}",
        )
    try:
        os.rename(source, target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"no se pudo mover: {exc}") from exc
    return {"from": _rel_to(source, root), "path": _rel_to(target, root), "name": source.name}


async def save_upload(rel_dir: str | None, anchor: Path | None, filename: str,
                      stream, overwrite: bool = False) -> dict:
    """Guarda una subida (iterador async de bytes) en un temporal del mismo directorio.

    El temporal + `os.replace` evita dejar el archivo a medias si se corta la subida.
    """
    _base, root, parent = _dir(rel_dir, anchor)
    name = clean_name((filename or "").replace("\\", "/").rsplit("/", 1)[-1])
    destination = parent / name
    if os.path.lexists(destination) and not overwrite:
        raise HTTPException(
            status_code=409, detail=f"ya existe «{name}» (marca «sobrescribir» para reemplazarlo)"
        )
    limit = max(1, config.FILES_MAX_UPLOAD_MB) * 1024 * 1024
    temp = parent / f".{name}.subida-{os.getpid()}-{int(time.time())}"
    written = 0
    try:
        with open(temp, "wb") as handle:
            async for chunk in stream:
                if not chunk:
                    continue
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"el archivo supera el máximo de {config.FILES_MAX_UPLOAD_MB} MB",
                    )
                handle.write(chunk)
        os.replace(temp, destination)
    except HTTPException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise
    except OSError as exc:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise HTTPException(status_code=500, detail=f"no se pudo subir: {exc}") from exc
    return {"path": _rel_to(destination, root), "name": name, "bytes": written}


def download(rel: str, anchor: Path | None = None) -> dict:
    _base, root, target = _leaf(rel, anchor)
    if not os.path.lexists(target):
        raise HTTPException(status_code=404, detail="la ruta no existe")
    resolved = target.resolve()
    if not _within(resolved, root):
        raise HTTPException(status_code=400, detail="el enlace apunta fuera del ancla")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="la ruta no es un archivo")
    return {
        "path": resolved,
        "name": target.name,
        "rel": _rel_to(target, root),
        "bytes": int(resolved.stat().st_size),
    }
