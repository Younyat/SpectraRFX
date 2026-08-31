from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.modules.kiwisdr.domain.entities import (
    ReceiverCapabilities,
    ReceiverCatalogSnapshot,
    ReceiverLocation,
    ReceiverNode,
    ReceiverStatus,
    utc_now_iso,
)
from app.modules.kiwisdr.infrastructure.geo import infer_location


logger = logging.getLogger(__name__)

PUBLIC_LIST_URLS = (
    "https://kiwisdr.com/public/",
    "http://kiwisdr.com/public/",
)


@dataclass(slots=True)
class CatalogFetchError(Exception):
    attempts: list[str]

    def __str__(self) -> str:
        return "KiwiSDR catalog refresh failed: " + " | ".join(self.attempts)


class KiwisdrPublicCatalogClient:
    def __init__(self, urls: tuple[str, ...] = PUBLIC_LIST_URLS, timeout_s: float = 15.0) -> None:
        self._urls = urls
        self._timeout_s = timeout_s

    def fetch_catalog(self) -> ReceiverCatalogSnapshot:
        attempts: list[str] = []
        raw = ""
        source_url = ""

        for url in self._urls:
            try:
                raw = self._fetch_url(url)
                source_url = url
                if url.startswith("http://"):
                    logger.warning(
                        "KiwiSDR catalog refresh used HTTP fallback because HTTPS was unavailable. "
                        "The backend will normalize and cache the result locally."
                    )
                break
            except Exception as exc:
                message = _describe_fetch_error(url, exc)
                attempts.append(message)
                logger.warning(message)

        if not raw:
            raise CatalogFetchError(attempts)

        receivers = self._parse_public_list(raw)
        return ReceiverCatalogSnapshot(
            receivers=receivers,
            refreshed_at=utc_now_iso(),
            source=source_url,
            notes=(
                "Coordinates are approximate public display coordinates. "
                "Some entries are inferred from public text when exact map metadata is unavailable."
            ),
        )

    def _fetch_url(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": "SpectraEase KiwiSDR catalog refresher/1.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urlopen(request, timeout=self._timeout_s) as response:
            return response.read().decode("utf-8", errors="replace")

    def _parse_public_list(self, raw_html: str) -> list[ReceiverNode]:
        text = _html_to_text(raw_html)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        receivers: list[ReceiverNode] = []
        seen_hosts: set[str] = set()

        for match in re.finditer(r'''href=["'](https?://[^"']+)["']''', raw_html, flags=re.IGNORECASE):
            url = html.unescape(match.group(1).strip())
            parsed = urlparse(url)
            if not parsed.hostname or "kiwisdr.com" in parsed.hostname.lower():
                continue
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 8073)
            dedupe_key = f"{host}:{port}"
            if dedupe_key in seen_hosts:
                continue
            seen_hosts.add(dedupe_key)
            context = _html_to_text(raw_html[max(0, match.start() - 900):match.end() + 900])
            receivers.append(_receiver_from_parts(url, host, port, context, context))

        for index, line in enumerate(lines):
            if not line.startswith(("http://", "https://")):
                continue
            parsed = urlparse(line)
            if not parsed.hostname:
                continue
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 8073)
            dedupe_key = f"{host}:{port}"
            if dedupe_key in seen_hosts:
                continue
            seen_hosts.add(dedupe_key)

            title = _nearest_title(lines, index)
            detail = _nearest_detail(lines, index)
            receivers.append(_receiver_from_parts(line, host, port, title, detail))

        return receivers


def _html_to_text(raw_html: str) -> str:
    value = re.sub(r"(?i)<br\s*/?>", "\n", raw_html)
    value = re.sub(r"(?i)</(div|p|li|tr|h[1-6])>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = value.replace("\u2063", " ").replace("\xa0", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    return "\n".join(line.strip() for line in value.splitlines())


def _nearest_title(lines: list[str], index: int) -> str:
    for candidate in reversed(lines[max(0, index - 5):index]):
        if candidate.lower().startswith(("http://", "https://")):
            continue
        if "KiwiSDR" in candidate:
            continue
        if candidate.lower() == "image":
            continue
        return candidate[:220]
    return ""


def _nearest_detail(lines: list[str], index: int) -> str:
    for candidate in lines[index + 1:index + 5]:
        if "KiwiSDR" in candidate:
            return candidate[:300]
    return ""


def _stable_id(value: str) -> str:
    return "kiwi_" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _receiver_from_parts(url: str, host: str, port: int, title: str, detail: str) -> ReceiverNode:
    dedupe_key = f"{host}:{port}"
    combined = f"{title} {detail}"
    receiver_id = _stable_id(dedupe_key)
    lat, lon, country, city = infer_location(combined, receiver_id)
    current_users, max_users = _parse_users(detail)
    snr = _parse_snr(detail)
    frequency_min_khz, frequency_max_khz = _parse_frequency_range(combined)
    cleaned_title = _clean_title(title, host)

    return ReceiverNode(
        id=receiver_id,
        name=cleaned_title or host,
        host=host,
        port=port,
        url=url,
        location=ReceiverLocation(lat=lat, lon=lon, country=country, city=city, approximate=True),
        status=ReceiverStatus(
            is_online=True,
            is_public=True,
            current_users=current_users,
            max_users=max_users,
            health_status="catalog",
        ),
        capabilities=ReceiverCapabilities(
            frequency_min_khz=frequency_min_khz,
            frequency_max_khz=frequency_max_khz,
            gps_locked="GPS" in detail.upper(),
            tdoa_available="GPS" in detail.upper(),
            drm="DRM" in detail.upper(),
            iq=True,
        ),
        snr=snr,
        source="kiwisdr_public_list",
        notes=detail[:500],
        last_seen=datetime.now(timezone.utc).isoformat(),
    )


def _clean_title(text: str, host: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text.lower() == "image":
        return host
    if len(text) > 120:
        return text[:120].strip()
    return text


def _describe_fetch_error(url: str, exc: Exception) -> str:
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base = f"KiwiSDR catalog source {url} failed: TCP connection to {parsed.hostname}:{port} could not be established"
    reason = str(exc)
    if parsed.scheme == "https":
        return (
            f"{base}. HTTPS is unavailable from the current environment. "
            f"Will try HTTP fallback if configured. Cause: {reason}"
        )
    return f"{base}. HTTP fallback also failed. Cause: {reason}"


def _parse_users(text: str) -> tuple[int | None, int | None]:
    match = re.search(r"\((\d+)\s*/\s*(\d+)\s+users?", text, flags=re.IGNORECASE)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _parse_snr(text: str) -> float | None:
    match = re.search(r"SNR\s+(-?\d+(?:\.\d+)?)(?:\s*/\s*(-?\d+(?:\.\d+)?))?\s*dB", text, flags=re.IGNORECASE)
    if not match:
        return None
    values = [float(item) for item in match.groups() if item is not None]
    return round(sum(values) / len(values), 1) if values else None


def _parse_frequency_range(text: str) -> tuple[float, float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*MHZ", text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1)) * 1000.0, float(match.group(2)) * 1000.0
    return 0.0, 30000.0
