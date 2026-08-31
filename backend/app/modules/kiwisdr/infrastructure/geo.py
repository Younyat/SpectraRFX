from __future__ import annotations

import hashlib
import re


COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "ARGENTINA": (-34.0, -64.0),
    "AUSTRALIA": (-25.0, 133.0),
    "AUSTRIA": (47.5, 14.5),
    "BELGIUM": (50.8, 4.5),
    "BRAZIL": (-10.0, -55.0),
    "CANADA": (56.0, -106.0),
    "CHILE": (-30.0, -71.0),
    "CHINA": (35.0, 103.0),
    "CZECH": (49.8, 15.5),
    "DENMARK": (56.0, 10.0),
    "FINLAND": (64.0, 26.0),
    "FRANCE": (46.5, 2.2),
    "GERMANY": (51.2, 10.4),
    "GREECE": (39.0, 22.0),
    "HUNGARY": (47.0, 19.5),
    "INDIA": (22.0, 79.0),
    "IRELAND": (53.2, -8.2),
    "ITALY": (42.5, 12.5),
    "JAPAN": (36.2, 138.2),
    "MEXICO": (23.6, -102.5),
    "NETHERLANDS": (52.1, 5.3),
    "NEW ZEALAND": (-41.0, 174.0),
    "NORWAY": (61.0, 8.0),
    "PARAGUAY": (-23.4, -58.4),
    "POLAND": (52.0, 19.0),
    "PORTUGAL": (39.5, -8.0),
    "ROMANIA": (45.9, 24.9),
    "RUSSIA": (61.5, 105.3),
    "SLOVAKIA": (48.7, 19.7),
    "SLOVENIA": (46.1, 14.9),
    "SOUTH AFRICA": (-30.6, 22.9),
    "SPAIN": (40.4, -3.7),
    "SWEDEN": (62.0, 15.0),
    "SWITZERLAND": (46.8, 8.2),
    "THAILAND": (15.8, 101.0),
    "TURKEY": (39.0, 35.0),
    "UK": (54.0, -2.0),
    "UNITED KINGDOM": (54.0, -2.0),
    "USA": (39.8, -98.6),
    "UNITED STATES": (39.8, -98.6),
}


CITY_HINTS: dict[str, tuple[str, str, float, float]] = {
    "MADRID": ("Madrid", "Spain", 40.4168, -3.7038),
    "BARCELONA": ("Barcelona", "Spain", 41.3874, 2.1686),
    "LONDON": ("London", "United Kingdom", 51.5072, -0.1276),
    "PARIS": ("Paris", "France", 48.8566, 2.3522),
    "BERLIN": ("Berlin", "Germany", 52.52, 13.405),
    "SYDNEY": ("Sydney", "Australia", -33.8688, 151.2093),
    "MELBOURNE": ("Melbourne", "Australia", -37.8136, 144.9631),
    "TOKYO": ("Tokyo", "Japan", 35.6762, 139.6503),
    "OSAKA": ("Osaka", "Japan", 34.6937, 135.5023),
    "TORONTO": ("Toronto", "Canada", 43.6532, -79.3832),
    "VANCOUVER": ("Vancouver", "Canada", 49.2827, -123.1207),
    "NEW YORK": ("New York", "United States", 40.7128, -74.006),
    "CHICAGO": ("Chicago", "United States", 41.8781, -87.6298),
    "LOS ANGELES": ("Los Angeles", "United States", 34.0522, -118.2437),
}


def infer_location(text: str, stable_key: str) -> tuple[float | None, float | None, str, str]:
    upper = text.upper()
    for token, (city, country, lat, lon) in CITY_HINTS.items():
        if token in upper:
            return _jitter(lat, lon, stable_key, 0.8) + (country, city)

    for country_token, (lat, lon) in COUNTRY_CENTROIDS.items():
        if re.search(rf"\b{re.escape(country_token)}\b", upper):
            country = "United States" if country_token == "USA" else country_token.title()
            jittered_lat, jittered_lon = _jitter(lat, lon, stable_key, 6.0)
            return jittered_lat, jittered_lon, country, ""

    return None, None, "", ""


def _jitter(lat: float, lon: float, stable_key: str, scale: float) -> tuple[float, float]:
    digest = hashlib.sha1(stable_key.encode("utf-8")).digest()
    lat_delta = ((digest[0] / 255.0) - 0.5) * scale
    lon_delta = ((digest[1] / 255.0) - 0.5) * scale
    return round(max(-85.0, min(85.0, lat + lat_delta)), 4), round(max(-180.0, min(180.0, lon + lon_delta)), 4)
