"""FastAPI app: UPS current state + history + WebSocket, and the static frontend."""

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import collector
import db

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
RANGES = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(collector.run())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="UPS Dashboard", lifespan=lifespan)


def _stale(ts):
    now = int(time.time())
    limit = max(3 * collector.POLL_INTERVAL, 90)
    return ts is None or (now - ts) > limit


@app.get("/healthz")
async def healthz():
    summary = collector.latest()
    ts = summary["ts"] if summary else None
    return {
        "status": "ok",
        "last_seen": ts,
        "age_s": (int(time.time()) - ts) if ts else None,
        "stale": _stale(ts),
        "last_error": collector.last_error(),
        "source": collector.source(),
        "simulate": collector.SIMULATE,
    }


@app.get("/api/meta")
async def meta():
    summary = collector.latest() or {}
    return {
        "metrics": [
            {"key": key, **info} for key, info in db.METRICS.items()
        ],
        "ranges": list(RANGES.keys()),
        "thresholds": {
            "charge_warning": summary.get("charge_warning", 50),
            "charge_low": summary.get("charge_low", 10),
            "runtime_low": summary.get("runtime_low", 120),
        },
    }


@app.get("/api/summary")
async def api_summary():
    summary = collector.latest()
    if summary is None:
        return {"stale": True, "last_seen": None, "error": collector.last_error()}
    payload = dict(summary)
    payload["stale"] = _stale(summary["ts"])
    payload["last_seen"] = summary["ts"]
    payload["error"] = collector.last_error()
    return payload


@app.get("/api/history")
async def api_history(metric: str = Query(...), range: str = Query("24h")):
    if metric not in db.METRICS:
        raise HTTPException(status_code=400, detail="metrica invalida")
    if range not in RANGES:
        raise HTTPException(status_code=400, detail="rango invalido")
    until = int(time.time())
    since = until - RANGES[range]
    points = await asyncio.to_thread(db.history, metric, since, until)
    return {
        "metric": metric,
        "range": range,
        "resolution": "hourly" if (until - since) > db.HOURLY_THRESHOLD else "raw",
        "points": points,
    }


@app.get("/api/events")
async def api_events(range: str = Query("7d")):
    if range not in RANGES:
        raise HTTPException(status_code=400, detail="rango invalido")
    since = int(time.time()) - RANGES[range]
    rows = await asyncio.to_thread(db.events, since)
    for row in rows:
        row["to_class"] = collector.status_class(row.get("to_status"))
        row["from_class"] = collector.status_class(row.get("from_status"))
    return {"range": range, "events": rows}


@app.websocket("/api/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    queue = collector.subscribe()
    try:
        summary = collector.latest()
        if summary:
            await websocket.send_json(summary)
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        collector.unsubscribe(queue)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
