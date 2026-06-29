from datetime import date

from weather import (
    average_temp,
    days_in_range,
    describe_weather_code,
    fetch_daily_weather,
)


def _fake_payload() -> dict:
    return {
        "daily": {
            "time": ["2026-06-27", "2026-06-28", "2026-06-29"],
            "temperature_2m_mean": [31.4, 33.0, None],
            "weather_code": [0, 95, 3],
        }
    }


def test_describe_weather_code_maps_known_and_unknown() -> None:
    assert describe_weather_code(0) == "Clear sky"
    assert describe_weather_code(95) == "Thunderstorm"
    assert describe_weather_code(123456) == "Unknown"
    assert describe_weather_code(None) == "Unknown"


def test_fetch_daily_weather_parses_payload() -> None:
    captured = {}

    def fetcher(url: str) -> dict:
        captured["url"] = url
        return _fake_payload()

    result = fetch_daily_weather(
        51.2, 4.4, "2026-06-27", "2026-06-29", fetcher=fetcher
    )

    assert "latitude=51.2" in captured["url"]
    assert "start_date=2026-06-27" in captured["url"]
    assert result["2026-06-27"] == {
        "temp_c": 31.4,
        "weather_code": 0,
        "description": "Clear sky",
    }
    assert result["2026-06-28"]["description"] == "Thunderstorm"
    assert result["2026-06-29"]["temp_c"] is None


def test_fetch_daily_weather_degrades_to_empty_on_error() -> None:
    def boom(_url: str) -> dict:
        raise RuntimeError("network down")

    assert fetch_daily_weather(0.0, 0.0, "2026-06-27", "2026-06-29", fetcher=boom) == {}


def test_average_temp_ignores_missing_values() -> None:
    daily = fetch_daily_weather(
        0.0, 0.0, "2026-06-27", "2026-06-29", fetcher=lambda _u: _fake_payload()
    )
    avg = average_temp(daily, date(2026, 6, 27), date(2026, 6, 29))
    assert avg == 32.2  # mean of 31.4 and 33.0; None ignored


def test_days_in_range_fills_every_date() -> None:
    daily = fetch_daily_weather(
        0.0, 0.0, "2026-06-27", "2026-06-29", fetcher=lambda _u: _fake_payload()
    )
    days = days_in_range(daily, date(2026, 6, 27), date(2026, 6, 30))

    assert [d["date"] for d in days] == [
        "2026-06-27",
        "2026-06-28",
        "2026-06-29",
        "2026-06-30",
    ]
    # Date past the fetched range still produces a block with unknown weather.
    assert days[-1] == {"date": "2026-06-30", "avg_temp_c": None, "weather": "Unknown"}
