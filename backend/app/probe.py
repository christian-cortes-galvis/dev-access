import asyncio
import os
import time

import httpx

CA_PATH = os.environ.get("CA_PATH", "/certs/ca.pem")
PROBE_TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "5"))
PROBE_CONCURRENCY = int(os.environ.get("PROBE_CONCURRENCY", "10"))
USER_AGENT = "cortexdev-portal-check/1.0"


def classify(code, accept):
    if code is None:
        return "offline"
    if code in accept:
        return "online" if 200 <= code < 300 else "auth"
    return "offline"


def _verify():
    return CA_PATH if os.path.isfile(CA_PATH) else False


async def probe_one(client, service):
    url = service.get("probe_url") or service["url"]
    method = (service.get("method") or "GET").upper()
    started = time.perf_counter()
    try:
        request = client.build_request(method, url)
        response = await client.send(request, stream=True)
        await response.aclose()
        latency = int((time.perf_counter() - started) * 1000)
        state = classify(response.status_code, service["accept_set"])
        return {
            "ok": 1 if state in ("online", "auth") else 0,
            "state": state,
            "code": response.status_code,
            "latency_ms": latency,
            "error": None,
        }
    except Exception as exc:  # timeouts, DNS, TLS, connection refused...
        latency = int((time.perf_counter() - started) * 1000)
        return {
            "ok": 0,
            "state": "offline",
            "code": None,
            "latency_ms": latency,
            "error": f"{type(exc).__name__}: {exc}"[:200],
        }


async def probe_all(services):
    timeout = httpx.Timeout(PROBE_TIMEOUT)
    limits = httpx.Limits(max_connections=PROBE_CONCURRENCY + 5)
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)

    async with httpx.AsyncClient(
        verify=_verify(),
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        limits=limits,
    ) as client:

        async def run(service):
            async with semaphore:
                return await probe_one(client, service)

        return await asyncio.gather(*(run(service) for service in services))
