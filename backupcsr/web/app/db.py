"""Acceso a MySQL (PyMySQL). Conexión por operación, sin pool: el portal es de bajo tráfico.

Si MySQL no está disponible (ubuntu-docker apagado o 3306 bloqueado) las funciones de
lectura devuelven vacío/False y los endpoints de escritura responden 503. La fuente de
verdad operativa (logs/archivos/cron) vive en el sistema de archivos.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from . import config

log = logging.getLogger("backupcsr-web")

_last_error: str | None = None


def _connect():
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=config.DB_CONNECT_TIMEOUT,
        read_timeout=15,
        write_timeout=15,
    )


@contextmanager
def cursor():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def available() -> bool:
    global _last_error
    try:
        with cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        _last_error = None
        return True
    except Exception as exc:  # noqa: BLE001 - degradación controlada
        _last_error = f"{type(exc).__name__}: {exc}"[:300]
        return False


def last_error() -> str | None:
    return _last_error


def init_schema() -> None:
    sql = config.SCHEMA_PATH.read_text(encoding="utf-8")
    # Quita comentarios de línea ANTES de separar por ';': si un comentario
    # contiene un ';', separar primero generaría fragmentos inválidos.
    sql = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    statements = [chunk.strip() for chunk in sql.split(";") if chunk.strip()]
    with cursor() as cur:
        for statement in statements:
            cur.execute(statement)


def query(sql: str, params=None, one: bool = False):
    with cursor() as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql: str, params=None) -> int:
    with cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def executemany(sql: str, seq) -> None:
    with cursor() as cur:
        cur.executemany(sql, seq)


def insert(sql: str, params=None) -> int:
    with cursor() as cur:
        cur.execute(sql, params or ())
        return cur.lastrowid
