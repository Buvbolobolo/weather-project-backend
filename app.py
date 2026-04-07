from __future__ import annotations

import json
import math
import os
import time
from copy import deepcopy
from datetime import date, datetime
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


FORECAST_API_URL = os.getenv("OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast")
GEOCODING_API_URL = os.getenv(
    "OPEN_METEO_GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"
)
REVERSE_GEOCODING_URL = os.getenv(
    "REVERSE_GEOCODING_URL", "https://nominatim.openstreetmap.org/reverse"
)
REQUEST_TIMEOUT_SECONDS = float(os.getenv("OPEN_METEO_TIMEOUT", "10"))
CACHE_TTL_SECONDS = int(os.getenv("WEATHER_CACHE_TTL", "300"))


class CityCatalogItem(TypedDict):
    name: str
    country: str
    latitude: float
    longitude: float


class CacheEntry(TypedDict):
    expires_at: float
    payload: dict


SUPPORTED_CITIES: list[CityCatalogItem] = [
    {"name": "Барнаул", "country": "Россия", "latitude": 53.3474, "longitude": 83.7784},
]

WEATHER_CODE_MAP = {
    0: "Ясно",
    1: "Преимущественно ясно",
    2: "Переменная облачность",
    3: "Пасмурно",
    45: "Туман",
    48: "Изморозь",
    51: "Слабая морось",
    53: "Морось",
    55: "Сильная морось",
    56: "Ледяная морось",
    57: "Сильная ледяная морось",
    61: "Небольшой дождь",
    63: "Дождь",
    65: "Сильный дождь",
    66: "Ледяной дождь",
    67: "Сильный ледяной дождь",
    71: "Небольшой снег",
    73: "Снег",
    75: "Сильный снег",
    77: "Снежные зерна",
    80: "Кратковременный дождь",
    81: "Ливень",
    82: "Сильный ливень",
    85: "Снежный заряд",
    86: "Сильный снежный заряд",
    95: "Гроза",
    96: "Гроза с градом",
    99: "Сильная гроза с градом",
}

DAY_NAMES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

WEATHER_CACHE: dict[str, CacheEntry] = {}


class ForecastResponse(BaseModel):
    day: str
    condition: str
    min_temp_c: float
    max_temp_c: float
    precipitation_chance: int


class HourlyForecastResponse(BaseModel):
    time: str
    condition: str
    temperature_c: float
    precipitation_chance: int


class CitySummary(BaseModel):
    name: str
    country: str
    condition: str
    temperature_c: float
    latitude: float
    longitude: float


class WeatherResponse(BaseModel):
    city: str
    country: str
    latitude: float
    longitude: float
    updated_at: str
    condition: str
    temperature_c: float
    feels_like_c: float
    humidity: int
    wind_speed: float
    pressure_mmhg: int
    visibility_km: float
    forecast: list[ForecastResponse]
    hourly_forecast: list[HourlyForecastResponse]


def get_cached_payload(cache_key: str) -> dict | None:
    cached_entry = WEATHER_CACHE.get(cache_key)
    if cached_entry is None:
        return None

    if cached_entry["expires_at"] <= time.time():
        WEATHER_CACHE.pop(cache_key, None)
        return None

    return deepcopy(cached_entry["payload"])


def set_cached_payload(cache_key: str, payload: dict) -> None:
    WEATHER_CACHE[cache_key] = {
        "expires_at": time.time() + CACHE_TTL_SECONDS,
        "payload": deepcopy(payload),
    }


def fetch_json(base_url: str, params: dict[str, object], *, cache_key: str | None = None) -> dict:
    if cache_key is not None:
        cached_payload = get_cached_payload(cache_key)
        if cached_payload is not None:
            return cached_payload

    request_url = f"{base_url}?{urlencode(params, doseq=True)}"
    request = Request(
        request_url,
        headers={
            "User-Agent": "weather-service-demo/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if cache_key is not None:
                set_cached_payload(cache_key, payload)
            return payload
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Погодный провайдер вернул ошибку: {exc.code}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail="Не удалось связаться с погодным провайдером") from exc


def weather_code_to_text(code: int | None) -> str:
    if code is None:
        return "Нет данных"

    return WEATHER_CODE_MAP.get(code, "Неизвестные погодные условия")


def hpa_to_mmhg(value: float) -> int:
    return round(value * 0.750062)


def kmh_to_ms(value: float) -> float:
    return round(value / 3.6, 1)


def ceil_temperature(value: float) -> float:
    return float(math.ceil(value))


def format_day_label(index: int, iso_date: str) -> str:
    if index == 0:
        return "Сегодня"
    if index == 1:
        return "Завтра"

    weekday_index = date.fromisoformat(iso_date).weekday()
    return DAY_NAMES[weekday_index]


def format_updated_at(value: str) -> str:
    if not value:
        return ""

    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def format_hour_label(iso_datetime: str) -> str:
    if not iso_datetime:
        return ""

    try:
        return datetime.fromisoformat(iso_datetime).strftime("%H:%M")
    except ValueError:
        if "T" in iso_datetime:
            return iso_datetime.split("T", 1)[1][:5]
        return iso_datetime[:5]


def build_hourly_forecast(payload: dict, current_time: str) -> list[HourlyForecastResponse]:
    hourly = payload.get("hourly", {})
    hourly_times = hourly.get("time", [])
    hourly_codes = hourly.get("weather_code", [])
    hourly_temps = hourly.get("temperature_2m", [])
    hourly_precipitation = hourly.get("precipitation_probability", [])

    if not hourly_times or not hourly_temps:
        return []

    start_index = 0
    if current_time and current_time in hourly_times:
        start_index = hourly_times.index(current_time)
    elif current_time:
        for index, hour_value in enumerate(hourly_times):
            if hour_value >= current_time:
                start_index = index
                break

    end_index = min(start_index + 24, len(hourly_times), len(hourly_temps))
    result: list[HourlyForecastResponse] = []

    for index in range(start_index, end_index):
        result.append(
            HourlyForecastResponse(
                time=format_hour_label(hourly_times[index]),
                condition=weather_code_to_text(
                    hourly_codes[index] if index < len(hourly_codes) else None
                ),
                temperature_c=ceil_temperature(float(hourly_temps[index])),
                precipitation_chance=int(
                    hourly_precipitation[index] if index < len(hourly_precipitation) else 0
                ),
            )
        )

    return result


def resolve_city(name: str) -> CityCatalogItem:
    normalized_name = name.strip().lower()

    for city in SUPPORTED_CITIES:
        if city["name"].lower() == normalized_name:
            return city

    payload = fetch_json(
        GEOCODING_API_URL,
        {
            "name": name.strip(),
            "count": 1,
            "language": "ru",
            "format": "json",
        },
        cache_key=f"forward:{normalized_name}",
    )
    results = payload.get("results") or []

    if not results:
        raise HTTPException(status_code=404, detail="Город не найден")

    first_result = results[0]
    return {
        "name": first_result["name"],
        "country": first_result.get("country", ""),
        "latitude": float(first_result["latitude"]),
        "longitude": float(first_result["longitude"]),
    }


def reverse_geocode(latitude: float, longitude: float) -> tuple[str, str]:
    payload = fetch_json(
        REVERSE_GEOCODING_URL,
        {
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "zoom": 10,
            "addressdetails": 1,
        },
        cache_key=f"reverse:{latitude:.4f}:{longitude:.4f}",
    )

    address = payload.get("address", {})
    city_name = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("county")
        or payload.get("name")
        or "Точка на карте"
    )
    country_name = address.get("country") or "Неизвестная страна"
    return str(city_name), str(country_name)


def normalize_coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    if latitude < -90 or latitude > 90:
        raise HTTPException(status_code=400, detail="Широта должна быть в диапазоне от -90 до 90")

    if longitude < -180 or longitude > 180:
        raise HTTPException(status_code=400, detail="Долгота должна быть в диапазоне от -180 до 180")

    return round(latitude, 4), round(longitude, 4)


def build_forecast(city: CityCatalogItem, payload: dict) -> WeatherResponse:
    current = payload.get("current", {})
    daily = payload.get("daily", {})
    daily_times = daily.get("time", [])
    daily_codes = daily.get("weather_code", [])
    daily_min_temps = daily.get("temperature_2m_min", [])
    daily_max_temps = daily.get("temperature_2m_max", [])
    daily_precip = daily.get("precipitation_probability_max", [])
    hourly_forecast = build_hourly_forecast(payload, current.get("time", ""))

    forecast = [
        ForecastResponse(
            day=format_day_label(index, day_value),
            condition=weather_code_to_text(daily_codes[index] if index < len(daily_codes) else None),
            min_temp_c=ceil_temperature(float(daily_min_temps[index])),
            max_temp_c=ceil_temperature(float(daily_max_temps[index])),
            precipitation_chance=int(daily_precip[index] or 0),
        )
        for index, day_value in enumerate(daily_times[:8])
    ]

    return WeatherResponse(
        city=city["name"],
        country=city["country"],
        latitude=city["latitude"],
        longitude=city["longitude"],
        updated_at=format_updated_at(current.get("time", "")),
        condition=weather_code_to_text(current.get("weather_code")),
        temperature_c=ceil_temperature(float(current.get("temperature_2m", 0))),
        feels_like_c=ceil_temperature(float(current.get("apparent_temperature", 0))),
        humidity=int(current.get("relative_humidity_2m", 0)),
        wind_speed=kmh_to_ms(float(current.get("wind_speed_10m", 0))),
        pressure_mmhg=hpa_to_mmhg(float(current.get("pressure_msl", 0))),
        visibility_km=round(float(current.get("visibility", 0)) / 1000, 1),
        forecast=forecast,
        hourly_forecast=hourly_forecast,
    )


def fetch_weather_payload(latitude: float, longitude: float) -> dict:
    return fetch_json(
        FORECAST_API_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
            "forecast_days": 8,
            "current": [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "weather_code",
                "pressure_msl",
                "visibility",
                "wind_speed_10m",
            ],
            "daily": [
                "weather_code",
                "temperature_2m_min",
                "temperature_2m_max",
                "precipitation_probability_max",
            ],
            "hourly": [
                "temperature_2m",
                "weather_code",
                "precipitation_probability",
            ],
        },
        cache_key=f"weather:{latitude:.4f}:{longitude:.4f}",
    )


def fetch_weather_for_city(city: CityCatalogItem) -> WeatherResponse:
    payload = fetch_weather_payload(city["latitude"], city["longitude"])
    return build_forecast(city, payload)


def fetch_weather_for_coordinates(latitude: float, longitude: float) -> WeatherResponse:
    normalized_latitude, normalized_longitude = normalize_coordinates(latitude, longitude)
    payload = fetch_weather_payload(normalized_latitude, normalized_longitude)
    city_name, country_name = reverse_geocode(normalized_latitude, normalized_longitude)

    location = {
        "name": city_name,
        "country": country_name,
        "latitude": normalized_latitude,
        "longitude": normalized_longitude,
    }
    return build_forecast(location, payload)


app = FastAPI(
    title="Weather Service API",
    description="FastAPI-прослойка над Open-Meteo для погодного сервиса.",
    version="3.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "FastAPI backend is running",
        "provider": "Open-Meteo",
        "date": date.today().isoformat(),
    }


@app.get("/api/cities", response_model=list[CitySummary])
def list_cities() -> list[CitySummary]:
    city_summaries: list[CitySummary] = []

    for city in SUPPORTED_CITIES:
        weather = fetch_weather_for_city(city)
        city_summaries.append(
            CitySummary(
                name=weather.city,
                country=weather.country,
                condition=weather.condition,
                temperature_c=weather.temperature_c,
                latitude=weather.latitude,
                longitude=weather.longitude,
            )
        )

    return city_summaries


@app.get("/api/weather", response_model=WeatherResponse)
def get_weather(city: str = Query(..., description="Название города")) -> WeatherResponse:
    resolved_city = resolve_city(city)
    return fetch_weather_for_city(resolved_city)


@app.get("/api/weather/by-coordinates", response_model=WeatherResponse)
def get_weather_by_coordinates(
    latitude: float = Query(..., description="Широта"),
    longitude: float = Query(..., description="Долгота"),
) -> WeatherResponse:
    return fetch_weather_for_coordinates(latitude, longitude)


@app.get("/api/overview")
def overview() -> dict[str, object]:
    city_weather = [fetch_weather_for_city(city) for city in SUPPORTED_CITIES]
    warmest = max(city_weather, key=lambda item: item.temperature_c)

    return {
        "title": "Погодная сводка",
        "description": "Актуальные данные Open-Meteo по нескольким городам и прогноз для любой точки по клику на карте осадков.",
        "cities_count": len(city_weather),
        "highlight": {
            "city": warmest.city,
            "temperature_c": warmest.temperature_c,
            "condition": warmest.condition,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
