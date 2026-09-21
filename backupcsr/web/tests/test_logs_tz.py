"""Regresión: la zona del host no debe cachearse al importar `app.logs`.

Escenario real (ubuntu-services, 2026-09-21): el host pasó de `Etc/UTC` a
`America/Bogota` mientras `backupcsr-web` seguía corriendo. Si `logs.py` captura la zona
al importar, los logs nuevos (escritos en hora Bogotá) se interpretan con el offset viejo
(UTC): el portal resta 5 h y produce duraciones negativas (= "sin dato"), horas y estados
(`TARDE`) incorrectos hasta reiniciar el servicio.

Este test simula el cambio de zona **sin reimportar** el módulo y comprueba que
`parse_log_time` usa la zona vigente en cada llamada.

Corre con el python del venv del portal y no toca NAS, MySQL, /etc ni /run/lock:

    /opt/backupcsr/web/venv/bin/python backupcsr/web/tests/test_logs_tz.py
"""
import os
import sys
import time
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB_DIR))

os.environ["BACKUP_TZ"] = "America/Bogota"

# El módulo se importa con el host en UTC (como estaba el servicio al arrancar).
os.environ["TZ"] = "UTC"
time.tzset()

from app import logs  # noqa: E402

checks = 0
failures = 0


def check(name, ok, extra=""):
    global checks, failures
    checks += 1
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(extra)) if extra else ""))


# Con el host en UTC, 18:20 del log son las 13:20 en Bogotá.
utc = logs.parse_log_time("2026-09-21 18:20:00")
check("host UTC: 18:20 se convierte a 13:20 Bogotá", utc.strftime("%H:%M") == "13:20", utc)

# Cambia la zona del host sin reiniciar el proceso (equivale a `timedatectl set-timezone`).
os.environ["TZ"] = "America/Bogota"
time.tzset()
bogota = logs.parse_log_time("2026-09-21 18:20:00")
check("host Bogotá: 18:20 se interpreta como 18:20 (sin reimportar)",
      bogota.strftime("%H:%M") == "18:20", bogota)

# Y a la inversa: volver a UTC debe reflejarse de inmediato.
os.environ["TZ"] = "UTC"
time.tzset()
utc2 = logs.parse_log_time("2026-09-21 18:20:00")
check("host UTC otra vez: vuelve a 13:20", utc2.strftime("%H:%M") == "13:20", utc2)

print()
print(f"{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
