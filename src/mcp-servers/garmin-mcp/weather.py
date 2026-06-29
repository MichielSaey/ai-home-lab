"""Daily weather lookup via the Open-Meteo API (free, no API key).

The forecast endpoint serves both recent past days and a short forecast window
in a single call (start_date / end_date within roughly -92 .. +16 days), which
covers the training plan's lookback weeks plus the upcoming week.

All network failures degrade gracefully to an empty result so weather is purely
additive — the training plan still works when no location is configured or the
API is unreachable.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from typing import Any, Callable, Dict, Optional

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes → short human-readable descriptions.
WMO_DESCRIPTIONS: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Light snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def describe_weather_code(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    return WMO_DESCRIPTIONS.get(int(code), "Unknown")


# A fetcher takes a fully-formed URL and returns the decoded JSON payload.
Fetcher = Callable[[str], Dict[str, Any]]


def _default_fetcher(url: str) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 (trusted host)
        return json.loads(response.read().decode("utf-8"))


def _build_url(lat: float, lon: float, start_date: str, end_date: str) -> str:
    query = (
        f"latitude={lat}&longitude={lon}"
        "&daily=temperature_2m_mean,weather_code"
        "&timezone=auto"
        f"&start_date={start_date}&end_date={end_date}"
    )
    return f"{FORECAST_URL}?{query}"


def fetch_daily_weather(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    *,
    fetcher: Optional[Fetcher] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return {iso_date: {"temp_c": float|None, "weather_code": int|None,
    "description": str}} for the inclusive date range. Empty dict on any error.
    """
    fetch = fetcher or _default_fetcher
    try:
        payload = fetch(_build_url(lat, lon, start_date, end_date))
    except Exception:
        return {}

    daily = payload.get("daily") if isinstance(payload, dict) else None
    if not isinstance(daily, dict):
        return {}

    times = daily.get("time") or []
    temps = daily.get("temperature_2m_mean") or []
    codes = daily.get("weather_code") or []

    result: Dict[str, Dict[str, Any]] = {}
    for index, day in enumerate(times):
        temp = temps[index] if index < len(temps) else None
        code = codes[index] if index < len(codes) else None
        result[str(day)] = {
            "temp_c": round(float(temp), 1) if temp is not None else None,
            "weather_code": int(code) if code is not None else None,
            "description": describe_weather_code(code),
        }
    return result


def average_temp(
    daily_weather: Dict[str, Dict[str, Any]],
    start: date,
    end: date,
) -> Optional[float]:
    """Mean of available daily mean temperatures within [start, end] inclusive."""
    temps = [
        entry["temp_c"]
        for iso, entry in daily_weather.items()
        if entry.get("temp_c") is not None and start <= _parse(iso) <= end
    ]
    if not temps:
        return None
    return round(sum(temps) / len(temps), 1)


def days_in_range(
    daily_weather: Dict[str, Dict[str, Any]],
    start: date,
    end: date,
) -> list[Dict[str, Any]]:
    """Per-day weather blocks (date, temp, description) within [start, end]."""
    days: list[Dict[str, Any]] = []
    current = start
    while current <= end:
        iso = current.isoformat()
        entry = daily_weather.get(iso)
        days.append(
            {
                "date": iso,
                "avg_temp_c": entry["temp_c"] if entry else None,
                "weather": entry["description"] if entry else "Unknown",
            }
        )
        current = current.fromordinal(current.toordinal() + 1)
    return days


def _parse(iso: str) -> date:
    return date.fromisoformat(iso[:10])
