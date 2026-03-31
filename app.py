from __future__ import annotations

import json
import os
from datetime import date
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


FORECAST_API_URL = os.getenv("OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast")
GEOCODING_API_URL = os.getenv(
    "OPEN_METEO_GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"
)
REQUEST_TIMEOUT_SECONDS = float(os.getenv("OPEN_METEO_TIMEOUT", "10"))


class CityCatalogItem(TypedDict):
    name: str
    country: str
    latitude: float
    longitude: float


SUPPORTED_CITIES: list[CityCatalogItem] = [
    {"name": "Барнаул", "country": "Россия", "latitude": 53.3474, "longitude": 83.7784},
    {"name": "Москва", "country": "Россия", "latitude": 55.7558, "longitude": 37.6176},
    {"name": "Сочи", "country": "Россия", "latitude": 43.5855, "longitude": 39.7231},
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


class ForecastResponse(BaseModel):
    day: str
    condition: str
    min_temp_c: float
    max_temp_c: float
    precipitation_chance: int


class CitySummary(BaseModel):
    name: str
    country: str
    condition: str
    temperature_c: float


class WeatherResponse(BaseModel):
    city: str
    country: str
    updated_at: str
    condition: str
    temperature_c: float
    feels_like_c: float
    humidity: int
    wind_speed: float
    pressure_mmhg: int
    visibility_km: float
    forecast: list[ForecastResponse]


def fetch_json(base_url: str, params: dict[str, object]) -> dict:
    request_url = f"{base_url}?{urlencode(params, doseq=True)}"

    try:
        with urlopen(request_url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
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


def format_day_label(index: int, iso_date: str) -> str:
    if index == 0:
        return "Сегодня"
    if index == 1:
        return "Завтра"

    weekday_index = date.fromisoformat(iso_date).weekday()
    return DAY_NAMES[weekday_index]


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


def fetch_weather_for_city(city: CityCatalogItem) -> WeatherResponse:
    payload = fetch_json(
        FORECAST_API_URL,
        {
            "latitude": city["latitude"],
            "longitude": city["longitude"],
            "timezone": "auto",
            "forecast_days": 5,
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
        },
    )

    current = payload.get("current", {})
    daily = payload.get("daily", {})
    daily_times = daily.get("time", [])
    daily_codes = daily.get("weather_code", [])
    daily_min_temps = daily.get("temperature_2m_min", [])
    daily_max_temps = daily.get("temperature_2m_max", [])
    daily_precip = daily.get("precipitation_probability_max", [])

    forecast = [
        ForecastResponse(
            day=format_day_label(index, day_value),
            condition=weather_code_to_text(daily_codes[index] if index < len(daily_codes) else None),
            min_temp_c=round(float(daily_min_temps[index]), 1),
            max_temp_c=round(float(daily_max_temps[index]), 1),
            precipitation_chance=int(daily_precip[index] or 0),
        )
        for index, day_value in enumerate(daily_times[:5])
    ]

    return WeatherResponse(
        city=city["name"],
        country=city["country"],
        updated_at=current.get("time", ""),
        condition=weather_code_to_text(current.get("weather_code")),
        temperature_c=round(float(current.get("temperature_2m", 0)), 1),
        feels_like_c=round(float(current.get("apparent_temperature", 0)), 1),
        humidity=int(current.get("relative_humidity_2m", 0)),
        wind_speed=kmh_to_ms(float(current.get("wind_speed_10m", 0))),
        pressure_mmhg=hpa_to_mmhg(float(current.get("pressure_msl", 0))),
        visibility_km=round(float(current.get("visibility", 0)) / 1000, 1),
        forecast=forecast,
    )


app = FastAPI(
    title="Weather Service API",
    description="FastAPI-прослойка над Open-Meteo для погодного сервиса.",
    version="2.0.0",
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
            )
        )

    return city_summaries


@app.get("/api/weather", response_model=WeatherResponse)
def get_weather(city: str = Query(..., description="Название города")) -> WeatherResponse:
    resolved_city = resolve_city(city)
    return fetch_weather_for_city(resolved_city)
@app.get("/api/overview")
def overview() -> dict[str, object]:
    city_weather = [fetch_weather_for_city(city) for city in SUPPORTED_CITIES]
    warmest = max(city_weather, key=lambda item: item.temperature_c)

    return {
        "title": "Погода в выбранном городе",
        "description": "Данные о погоде и прогнозы для нескольких городов взяты через Open-Meteo API",
        "cities_count": len(city_weather),
        "highlight": {
            "city": warmest.city,
            "temperature_c": warmest.temperature_c,
            "condition": warmest.condition,
        },
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)
