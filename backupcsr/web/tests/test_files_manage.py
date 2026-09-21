"""Pruebas de la gestión de archivos: app/files.py (sistema de archivos) y los
handlers de app/api.py.

Se ejecutan con el python del venv del portal (necesita fastapi) y usan un NAS
temporal: **no** tocan /mnt/nas, ni MySQL, ni /run/lock.

    /opt/backupcsr/web/venv/bin/python backupcsr/web/tests/test_files_manage.py

Cubren lo que protege a las copias: confinamiento al ancla del job, nombres
válidos, no pisar existentes, borrado con confirmación, enlaces simbólicos (se
borra/renombra el enlace, jamás el destino), límites de subida y bloqueos (job
corriendo, sin MySQL, gestión desactivada).
"""
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException

WEB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB_DIR))

NAS = Path(tempfile.mkdtemp(prefix="nas-"))
os.environ["BACKUP_NAS"] = str(NAS)
os.environ["BACKUP_FILES_MAX_UPLOAD_MB"] = "1"

from app import api, config, files, sizes  # noqa: E402

files.nas_ready = lambda: True
ANCHOR = NAS / "google"
ANCHOR.mkdir(parents=True)
OTHER = NAS / "latino"
OTHER.mkdir()

checks = 0
failures = 0


def check(name, ok, extra=""):
    global checks, failures
    checks += 1
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(extra)) if extra else ""))


def code(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except HTTPException as exc:
        return exc.status_code
    return None


def make(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


async def chunks(data, step=3):
    if len(data) > 65536:
        step = 8192
    for index in range(0, len(data), step):
        yield data[index:index + step]


def upload(rel_dir, anchor, name, data, overwrite=False):
    return asyncio.run(files.save_upload(rel_dir, anchor, name, chunks(data), overwrite=overwrite))


# ---------------------------------------------------------------- nombres
BAD = ["", ".", "..", " a", "a ", "a.", "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b',
       "a<b", "a>b", "a|b", "CON", "con.txt", "NUL", "LPT9.log", "x" * 201, "a\x01b", None]
for value in BAD:
    check(f"nombre inválido: {value!r}", code(files.clean_name, value) == 400)
for value in ["informe.pdf", ".oculto", "a b", "ñandú-2026", "a-b_c.1", "COM10", "copia (1).zip"]:
    check(f"nombre válido: {value!r}", files.clean_name(value) == value)

# --------------------------------------------------------------- listado
make(ANCHOR / "b.txt", b"12345")
make(ANCHOR / "sub" / "c.txt", b"1234567")
os.symlink(ANCHOR / "b.txt", ANCHOR / "enlace")
os.symlink("/etc", ANCHOR / "fuera")
listing = files.list_dir("", anchor=ANCHOR)
links = {item["name"]: item["link"] for item in listing["entries"]}
check("listado con las 4 entradas", sorted(links) == ["b.txt", "enlace", "fuera", "sub"], list(links))
check("listado marca enlaces", links == {"sub": False, "b.txt": False, "enlace": True, "fuera": True}, links)
check("listado: ancla y raíz", listing["anchor"] == "google" and listing["path"] == "" and listing["parent"] == "")
check("listado: padre de subcarpeta", files.list_dir("sub", anchor=ANCHOR)["parent"] == "")
check("listado: no es carpeta", code(files.list_dir, "b.txt", anchor=ANCHOR) == 400)
check("listado: inexistente", code(files.list_dir, "nope", anchor=ANCHOR) == 404)
check("listado: ruta absoluta", code(files.list_dir, "/etc", anchor=ANCHOR) == 400)
check("listado: escape", code(files.list_dir, "../latino", anchor=ANCHOR) == 400)

# ------------------------------------------------------------ entry_info
info = files.entry_info("sub", ANCHOR)
check("entry_info: carpeta", info["type"] == "dir" and info["entries"] == 1 and info["bytes"] == 7, info)
check("entry_info: archivo", files.entry_info("b.txt", ANCHOR)["bytes"] == 5)
check("entry_info: enlace interno apunta dentro", files.entry_info("enlace", ANCHOR)["target"] == "b.txt")
check("entry_info: enlace externo sin destino", files.entry_info("fuera", ANCHOR)["target"] is None)
check("entry_info: raíz prohibida", code(files.entry_info, "", ANCHOR) == 400)
check("entry_info: escape", code(files.entry_info, "../latino", ANCHOR) == 400)
check("entry_info: inexistente", code(files.entry_info, "nope", ANCHOR) == 404)

# ---------------------------------------------------------------- mkdir
made = files.make_dir("", ANCHOR, "nueva")
check("mkdir: crea y devuelve ruta", made["path"] == "nueva" and (ANCHOR / "nueva").is_dir(), made)
check("mkdir: duplicado", code(files.make_dir, "", ANCHOR, "nueva") == 409)
check("mkdir: nombre inválido", code(files.make_dir, "", ANCHOR, "a/b") == 400)
check("mkdir: padre inexistente", code(files.make_dir, "nope", ANCHOR, "x") == 400)
check("mkdir: anidado", files.make_dir("nueva", ANCHOR, "hija")["path"] == "nueva/hija")
check("mkdir: escape", code(files.make_dir, "../latino", ANCHOR, "x") == 400)

# --------------------------------------------------------------- rename
files.make_dir("", ANCHOR, "para-renombrar")
check("rename: carpeta", files.rename("para-renombrar", ANCHOR, "renombrada")["name"] == "renombrada"
      and (ANCHOR / "renombrada").is_dir() and not (ANCHOR / "para-renombrar").exists())
check("rename: archivo", files.rename("b.txt", ANCHOR, "b2.txt")["path"] == "b2.txt")
check("rename: destino ocupado", code(files.rename, "b2.txt", ANCHOR, "renombrada") == 409)
check("rename: mismo nombre", files.rename("b2.txt", ANCHOR, "b2.txt")["unchanged"] is True)
check("rename: inexistente", code(files.rename, "nope", ANCHOR, "x") == 404)
check("rename: nombre inválido", code(files.rename, "b2.txt", ANCHOR, "..") == 400)
check("rename: raíz", code(files.rename, "", ANCHOR, "x") == 400)
check("rename: escape", code(files.rename, "../latino", ANCHOR, "x") == 400)
check("rename: enlace sin tocar el destino",
      files.rename("enlace", ANCHOR, "enlace2")["name"] == "enlace2" and (ANCHOR / "b2.txt").exists())

# ----------------------------------------------------------------- move
make(ANCHOR / "mover.txt", b"abc")
moved = files.move("mover.txt", ANCHOR, "nueva")
check("move: mueve el archivo", moved["path"] == "nueva/mover.txt" and not (ANCHOR / "mover.txt").exists())
check("move: a la misma carpeta", code(files.move, "nueva/mover.txt", ANCHOR, "nueva") == 400)
check("move: la carpeta sobre sí misma", code(files.move, "nueva", ANCHOR, "nueva") == 400)
check("move: carpeta dentro de sí misma", code(files.move, "nueva", ANCHOR, "nueva/hija") == 400)
check("move: destino inexistente", code(files.move, "nueva/mover.txt", ANCHOR, "nope") == 400)
check("move: destino no es carpeta", code(files.move, "nueva/mover.txt", ANCHOR, "b2.txt") == 400)
check("move: fuera del ancla", code(files.move, "nueva/mover.txt", ANCHOR, "../latino") == 400)
make(ANCHOR / "nueva" / "hija" / "dup.txt", b"1")
make(ANCHOR / "nueva" / "dup.txt", b"2")
check("move: destino ocupado", code(files.move, "nueva/hija/dup.txt", ANCHOR, "nueva") == 409)
check("move: carpeta a la raíz", files.move("nueva/hija", ANCHOR, "")["path"] == "hija")

# --------------------------------------------------------------- delete
check("delete: exige confirmación", code(files.delete, "b2.txt", ANCHOR, "") == 400)
check("delete: confirmación distinta", code(files.delete, "b2.txt", ANCHOR, "otro") == 400)
deleted = files.delete("b2.txt", ANCHOR, "b2.txt")
check("delete: archivo", deleted["type"] == "file" and deleted["bytes"] == 5 and not (ANCHOR / "b2.txt").exists(), deleted)
make(ANCHOR / "dir-borrar" / "a.txt", b"123")
make(ANCHOR / "dir-borrar" / "b" / "b.txt", b"1234")
result = files.delete("dir-borrar", ANCHOR, "dir-borrar")
check("delete: carpeta recursiva con recuento",
      not (ANCHOR / "dir-borrar").exists() and result["entries"] == 3 and result["bytes"] == 7, result)
check("delete: raíz prohibida", code(files.delete, "", ANCHOR, "") == 400)
check("delete: escape", code(files.delete, "../latino", ANCHOR, "latino") == 400)
check("delete: inexistente", code(files.delete, "nope", ANCHOR, "nope") == 404)
make(ANCHOR / "real.txt", b"contenido")
os.symlink(ANCHOR / "real.txt", ANCHOR / "link")
files.delete("link", ANCHOR, "link")
check("delete: enlace deja el archivo real", (ANCHOR / "real.txt").read_bytes() == b"contenido")
os.symlink(ANCHOR / "hija", ANCHOR / "link-dir")
removed = files.delete("link-dir", ANCHOR, "link-dir")
check("delete: enlace a carpeta no borra la carpeta",
      (ANCHOR / "hija").is_dir() and not (ANCHOR / "link-dir").exists() and removed["type"] == "link", removed)
files.delete("fuera", ANCHOR, "fuera")
check("delete: enlace externo solo quita el enlace", not (ANCHOR / "fuera").exists())
files.delete("enlace2", ANCHOR, "enlace2")
check("delete: enlace roto", not (ANCHOR / "enlace2").exists())

# ---------------------------------------------------------------- subir
saved = upload("", ANCHOR, "subido.bin", b"hola")
check("upload: guarda y reporta", (ANCHOR / "subido.bin").read_bytes() == b"hola" and saved["bytes"] == 4, saved)
check("upload: sin temporales sueltos", not [p.name for p in ANCHOR.iterdir() if "subida" in p.name])
check("upload: duplicado", code(upload, "", ANCHOR, "subido.bin", b"x") == 409)
check("upload: sobrescribe con la marca",
      upload("", ANCHOR, "subido.bin", b"adios", overwrite=True)["bytes"] == 5
      and (ANCHOR / "subido.bin").read_bytes() == b"adios")
check("upload: nombre inválido", code(upload, "", ANCHOR, "a:b.txt", b"x") == 400)
check("upload: nombre vacío", code(upload, "", ANCHOR, "", b"x") == 400)
check("upload: destino inexistente", code(upload, "nope", ANCHOR, "x.txt", b"x") == 400)
check("upload: recorta la ruta del navegador",
      upload("", ANCHOR, r"C:\temp\win.txt", b"w")["name"] == "win.txt")
check("upload: respeta el límite", code(upload, "", ANCHOR, "grande.bin", b"z" * (2 * 1024 * 1024)) == 413)
check("upload: limpia el temporal tras el 413",
      not [p.name for p in ANCHOR.iterdir() if "grande.bin.subida" in p.name])
check("upload: en subcarpeta", upload("hija", ANCHOR, "dentro.txt", b"d")["path"] == "hija/dentro.txt")

# ------------------------------------------------------------- descargar
item = files.download("real.txt", ANCHOR)
check("download: archivo", item["name"] == "real.txt" and item["bytes"] == 9, item)
os.symlink(ANCHOR / "real.txt", ANCHOR / "enlace-de-prueba")
os.symlink("/etc", ANCHOR / "fuera")
check("download: enlace interno", files.download("enlace-de-prueba", ANCHOR)["name"] == "enlace-de-prueba")
check("download: enlace externo", code(files.download, "fuera", ANCHOR) == 400)
check("download: carpeta", code(files.download, "hija", ANCHOR) == 400)
check("download: inexistente", code(files.download, "nope", ANCHOR) == 404)
check("download: raíz", code(files.download, "", ANCHOR) == 400)

# ------------------------------------------------- confinamiento del ancla
check("ancla fuera del NAS (listar)", code(files.list_dir, "", Path("/etc")) == 400)
check("ancla fuera del NAS (mkdir)", code(files.make_dir, "", Path("/etc"), "x") == 400)
make(OTHER / "latino.txt", b"latino")
check("otra ancla intacta", files.entry_info("latino.txt", OTHER)["path"] == "latino.txt")
check("no se cruza entre anclas", code(files.entry_info, "../latino/latino.txt", ANCHOR) == 400)
os.symlink("/etc", ANCHOR / "escapar")
check("no se navega por un enlace externo", code(files.entry_info, "escapar/passwd", ANCHOR) == 400)
check("no se borra por un enlace externo", code(files.delete, "escapar/passwd", ANCHOR, "passwd") == 400)
check("no se sube por un enlace externo", code(upload, "escapar", ANCHOR, "x.txt", b"x") == 400)

# ----------------------------------------------------- capa API (handlers)
api.find_job = lambda slug: {"slug": "google", "name": "Google", "dest_rel": "google"} if slug == "google" else None
api.db.available = lambda: True
api.db.execute = lambda *args, **kwargs: None
audited = []
api.audit = lambda username, action, slug=None, detail=None: audited.append((action, slug, detail))
invalidated = []
sizes.invalidate = lambda slug: invalidated.append(slug)
running = {"value": False}
api.sizes.job_running = lambda job: running["value"]
USER = {"username": "cdcortes", "role": "admin"}


def run(coro):
    return asyncio.run(coro)


def acode(coro):
    try:
        run(coro)
    except HTTPException as exc:
        return exc.status_code
    return None


class FakeRequest:
    """Request mínima para la subida en crudo."""

    def __init__(self, data, length=None):
        self.headers = {"content-length": str(len(data) if length is None else length)}
        self.data = data

    async def stream(self):
        for index in range(0, len(self.data), 5):
            yield self.data[index:index + 5]


def api_upload(path="", name="x.txt", data=b"x", overwrite=False):
    return run(api.job_file_upload("google", FakeRequest(data), path=path, name=name,
                                   overwrite=overwrite, user=USER))


def api_upload_code(path="", name="x.txt", data=b"x"):
    return acode(api.job_file_upload("google", FakeRequest(data), path=path, name=name,
                                     overwrite=False, user=USER))


listing = run(api.job_files("google", "", USER))
check("api: listado con manage/running/límites",
      listing["manage"] is True and listing["running"] is False and listing["confirm_mb"] == 100
      and listing["max_upload_mb"] == 1, listing)
check("api: job inexistente", acode(api.job_files("nope", "", USER)) == 404)
created = run(api.job_file_mkdir("google", api.FilesMkdirIn(path="", name="2026"), USER))
check("api: mkdir", created["path"] == "2026" and created["ok"] is True, created)
check("api: mkdir audita", audited[-1][0] == "file-mkdir" and audited[-1][1] == "google", audited[-1])
check("api: mkdir invalida el tamaño", invalidated[-1] == "google", invalidated)
written = api_upload(path="2026", name="datos.csv", data=b"a,b\n1,2\n")
check("api: upload", written["path"] == "2026/datos.csv" and written["bytes"] == 8, written)
check("api: upload audita", audited[-1][0] == "file-upload" and audited[-1][2]["bytes"] == 8, audited[-1])
check("api: upload rechaza por content-length",
      acode(api.job_file_upload("google", FakeRequest(b"x" * 10, length=3 * 1024 * 1024),
                                path="", name="grande.bin", overwrite=False, user=USER)) == 413)
check("api: upload nombre inválido", api_upload_code(path="", name="a:b") == 400)
check("api: upload sin temporales",
      not [p.name for p in (NAS / "google" / "2026").iterdir() if "subida" in p.name])
check("api: upload duplicado", api_upload_code(path="2026", name="datos.csv") == 409)
check("api: upload sobrescribe", api_upload(path="2026", name="datos.csv", data=b"nuevo", overwrite=True)["bytes"] == 5)
check("api: contenido sobrescrito", (NAS / "google" / "2026" / "datos.csv").read_bytes() == b"nuevo")
api_upload(path="2026", name="datos.csv", data=b"a,b\n1,2\n", overwrite=True)
renamed = run(api.job_file_rename("google", api.FilesRenameIn(path="2026/datos.csv", name="datos2.csv"), USER))
check("api: rename", renamed["path"] == "2026/datos2.csv" and audited[-1][0] == "file-rename", renamed)
moved = run(api.job_file_move("google", api.FilesMoveIn(path="2026/datos2.csv", dest=""), USER))
check("api: move", moved["path"] == "datos2.csv" and audited[-1][0] == "file-move", moved)
check("api: entry", run(api.job_file_entry("google", "datos2.csv", USER))["entry"]["type"] == "file")
check("api: download", run(api.job_file_download("google", "datos2.csv", USER)).__class__.__name__ == "FileResponse")
check("api: download audita", audited[-1][0] == "file-download", audited[-1])
check("api: delete sin confirmación",
      acode(api.job_file_delete("google", api.FilesDeleteIn(path="datos2.csv", confirm=""), USER)) == 400)
removed = run(api.job_file_delete("google", api.FilesDeleteIn(path="datos2.csv", confirm="datos2.csv"), USER))
check("api: delete de archivo", removed["type"] == "file" and removed["bytes"] == 8
      and audited[-1][2]["entries"] == 1, removed)
check("api: delete de carpeta", run(api.job_file_delete(
    "google", api.FilesDeleteIn(path="2026", confirm="2026"), USER))["type"] == "dir")

running["value"] = True
check("api: bloquea con el job corriendo",
      acode(api.job_file_mkdir("google", api.FilesMkdirIn(path="", name="x"), USER)) == 409)
check("api: el listado avisa que corre", run(api.job_files("google", "", USER))["running"] is True)
running["value"] = False
config.MANAGE_FILES = False
check("api: gestión deshabilitada", acode(api.job_file_mkdir("google", api.FilesMkdirIn(path="", name="x"), USER)) == 409)
check("api: manage=False en el listado", run(api.job_files("google", "", USER))["manage"] is False)
config.MANAGE_FILES = True
api.db.available = lambda: False
check("api: sin BD no se escribe", acode(api.job_file_mkdir("google", api.FilesMkdirIn(path="", name="y"), USER)) == 503)
check("api: sin BD se puede listar", run(api.job_files("google", "", USER))["job"] == "google")
api.db.available = lambda: True
api.find_job = lambda slug: {"slug": "google", "dest_rel": "../../etc"}
check("api: ancla que sale del NAS", acode(api.job_file_mkdir("google", api.FilesMkdirIn(path="", name="x"), USER)) == 400)
api.find_job = lambda slug: {"slug": "google", "dest_rel": ""}
check("api: job sin destino usa la raíz", run(api.job_files("google", "", USER))["anchor"] == "")

print()
print(f"{checks - failures}/{checks} PASS")
shutil.rmtree(NAS, ignore_errors=True)
sys.exit(1 if failures else 0)
