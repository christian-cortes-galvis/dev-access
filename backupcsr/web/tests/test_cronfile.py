"""Contrato del formato del cron (app/cronfile.py ↔ tools/validar-copias.sh).

El comando generado encola en el planificador con respaldo serial a nivel de shell.
Aquí se comprueba que el render y ambos parsers (el del portal y el del validador)
coinciden, para que no derive el formato.

    /opt/backupcsr/web/venv/bin/python backupcsr/web/tests/test_cronfile.py
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB_DIR))

TMP = Path(tempfile.mkdtemp(prefix="cron-"))
os.environ["BACKUP_OPT"] = str(TMP / "opt")
os.environ["BACKUP_ETC"] = str(TMP / "etc")
os.environ["BACKUP_CRON"] = str(TMP / "etc" / "backupcsr")

from app import config, cronfile  # noqa: E402

checks = 0
failures = 0


def check(name, ok, extra=""):
    global checks, failures
    checks += 1
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(extra)) if extra else ""))


JOB = {
    "slug": "demo", "cron_minute": "2", "cron_hour": "6-19", "cron_dom": "*",
    "cron_month": "*", "cron_dow": "*", "sort": 10, "enabled": 1,
    "lockfile": "/run/lock/backupcsr-demo.lock",
}
text = cronfile.render([JOB])
line = next((l for l in text.splitlines() if "demo" in l), "")
check("render encola en el planificador", "backupcsr-scheduler submit demo" in line, line)
check("render incluye el fallback serial con flock",
      "flock -n /run/lock/backupcsr-demo.lock" in line, line)
check("render incluye el script real",
      str(config.JOBS_DIR / "demo.sh") in line, line)

parsed = cronfile.parse(text)
check("el parser del portal extrae el slug",
      parsed.get("demo", {}).get("minute") == "2", parsed)

# Réplica de los regex de tools/validar-copias.sh (parse_cron).
JOB_RE = re.compile(r"/jobs/([A-Za-z0-9_.-]+)\.sh")
SUBMIT_RE = re.compile(r"backupcsr-scheduler\s+submit\s+([A-Za-z0-9_.-]+)")
match = JOB_RE.search(line) or SUBMIT_RE.search(line)
check("el parser del validador extrae el mismo slug",
      bool(match) and match.group(1) == "demo", line)
check("sin CRLF", "\r" not in text)

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
