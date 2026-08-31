from __future__ import annotations

import time
from urllib.error import URLError
from urllib.request import Request, urlopen


class KiwisdrReceiverProbeClient:
    def __init__(self, timeout_s: float = 5.0) -> None:
        self._timeout_s = timeout_s

    def check_health(self, base_url: str) -> dict:
        status_url = base_url.rstrip("/") + "/status"
        request = Request(status_url, headers={"User-Agent": "SpectraEase KiwiSDR health probe/1.0"})
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                body = response.read(32_000).decode("utf-8", errors="replace")
            latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
            return {
                "is_online": True,
                "health_status": "online",
                "latency_ms": latency_ms,
                "status_url": status_url,
                "status": _parse_status(body),
            }
        except (OSError, URLError) as exc:
            return {
                "is_online": False,
                "health_status": "offline",
                "latency_ms": None,
                "status_url": status_url,
                "error": str(exc),
            }


def _parse_status(body: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in body.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed
