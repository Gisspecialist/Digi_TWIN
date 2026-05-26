from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "600"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "12"))
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]

app = FastAPI(
    title="3D Planetary Digital Twin Simulation Interface",
    version="1.0.0",
    description="Operational-style planetary environmental digital twin API and WebGL interface.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

_cache: dict[str, tuple[float, Any]] = {}


@dataclass
class NearestFeature:
    title: str
    distance_km: float
    latitude: float
    longitude: float
    source: str


def cache_get(key: str) -> Any | None:
    item = _cache.get(key)
    if not item:
        return None
    saved_at, value = item
    if time.time() - saved_at > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any) -> Any:
    _cache[key] = (time.time(), value)
    return value


def clamp_coordinate(lat: float, lng: float) -> tuple[float, float]:
    lat = max(-90.0, min(90.0, float(lat)))
    lng = max(-180.0, min(180.0, float(lng)))
    return lat, lng


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def classify_risk(pm25: float | None, wind_kmh: float | None, precipitation_mm: float | None, event_km: float | None, quake_km: float | None) -> dict[str, str]:
    pm25_value = pm25 if isinstance(pm25, (int, float)) and math.isfinite(pm25) else None
    wind_value = wind_kmh if isinstance(wind_kmh, (int, float)) and math.isfinite(wind_kmh) else 0
    precip_value = precipitation_mm if isinstance(precipitation_mm, (int, float)) and math.isfinite(precipitation_mm) else 0
    event_value = event_km if isinstance(event_km, (int, float)) and math.isfinite(event_km) else None
    quake_value = quake_km if isinstance(quake_km, (int, float)) and math.isfinite(quake_km) else None

    if pm25_value is None and event_value is None and quake_value is None:
        return {"level": "limited", "message": "Risk cannot be fully classified because live air quality and nearby hazard signals were unavailable."}

    if (pm25_value is not None and pm25_value >= 35) or (quake_value is not None and quake_value <= 150):
        return {"level": "high", "message": "High concern: PM2.5 or nearby seismic activity indicates an elevated environmental stress signal."}

    if (pm25_value is not None and pm25_value >= 12) or wind_value > 35 or precip_value > 2 or (event_value is not None and event_value <= 500) or (quake_value is not None and quake_value <= 500):
        return {"level": "moderate", "message": "Moderate watch: one or more air quality, weather, NASA event, or earthquake indicators crossed the watch threshold."}

    return {"level": "low", "message": "Lower immediate stress signal detected from the currently available live feeds."}


async def fetch_json(client: httpx.AsyncClient, url: str) -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        response = await client.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return True, response.json(), None
    except Exception as exc:  # noqa: BLE001 - deliberate API health capture
        return False, None, str(exc)


def nearest_from_geojson(lat: float, lng: float, features: list[dict[str, Any]], source: str) -> NearestFeature | None:
    nearest: NearestFeature | None = None
    for feature in features:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        coords: list[Any] | None = None
        geometry_type = geometry.get("type")

        if geometry_type == "Point":
            coords = geometry.get("coordinates")
        elif geometry_type == "Polygon":
            coords = (((geometry.get("coordinates") or [[]])[0]) or [[None, None]])[0]
        elif geometry_type == "MultiPolygon":
            coords = (((geometry.get("coordinates") or [[[[]]]])[0][0]) or [[None, None]])[0]

        if not coords or len(coords) < 2:
            continue
        try:
            feature_lng = float(coords[0])
            feature_lat = float(coords[1])
        except (TypeError, ValueError):
            continue

        distance = haversine_distance_km(lat, lng, feature_lat, feature_lng)
        if nearest is None or distance < nearest.distance_km:
            nearest = NearestFeature(
                title=str(feature.get("title") or properties.get("title") or properties.get("place") or "Unnamed event"),
                distance_km=distance,
                latitude=feature_lat,
                longitude=feature_lng,
                source=source,
            )
    return nearest


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "planetary-digital-twin", "cache_items": len(_cache), "cache_ttl_seconds": CACHE_TTL_SECONDS}


@app.get("/api/digital-twin")
async def digital_twin(lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180)) -> JSONResponse:
    lat, lng = clamp_coordinate(lat, lng)
    key = f"digital-twin:{lat:.3f}:{lng:.3f}"
    cached = cache_get(key)
    if cached:
        cached["cache"] = {"hit": True, "ttl_seconds": CACHE_TTL_SECONDS}
        return JSONResponse(cached)

    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m&timezone=auto"
    air_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lng}&current=pm2_5,carbon_monoxide,us_aqi,european_aqi&timezone=auto"
    eonet_url = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=50"
    usgs_url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"

    async with httpx.AsyncClient(headers={"User-Agent": "planetary-digital-twin/1.0"}) as client:
        weather_ok, weather_data, weather_error = await fetch_json(client, weather_url)
        air_ok, air_data, air_error = await fetch_json(client, air_url)
        eonet_ok, eonet_data, eonet_error = await fetch_json(client, eonet_url)
        usgs_ok, usgs_data, usgs_error = await fetch_json(client, usgs_url)

    weather_current = (weather_data or {}).get("current") or {}
    air_current = (air_data or {}).get("current") or {}

    temp = weather_current.get("temperature_2m")
    humidity = weather_current.get("relative_humidity_2m")
    precipitation = weather_current.get("precipitation")
    wind = weather_current.get("wind_speed_10m")
    pm25 = air_current.get("pm2_5")
    us_aqi = air_current.get("us_aqi")
    eu_aqi = air_current.get("european_aqi")
    carbon_monoxide = air_current.get("carbon_monoxide")

    eonet_features = []
    for event in (eonet_data or {}).get("events", []):
        if event.get("geometry"):
            eonet_features.append({"title": event.get("title"), "geometry": event["geometry"][0], "properties": {"title": event.get("title")}})
    nearest_event = nearest_from_geojson(lat, lng, eonet_features, "NASA EONET")
    nearest_quake = nearest_from_geojson(lat, lng, (usgs_data or {}).get("features", []), "USGS")

    risk = classify_risk(
        pm25=pm25,
        wind_kmh=wind,
        precipitation_mm=precipitation,
        event_km=nearest_event.distance_km if nearest_event else None,
        quake_km=nearest_quake.distance_km if nearest_quake else None,
    )

    payload = {
        "coordinate": {"latitude": lat, "longitude": lng},
        "timestamp_utc": int(time.time()),
        "cache": {"hit": False, "ttl_seconds": CACHE_TTL_SECONDS},
        "api_status": {
            "weather": {"online": weather_ok, "error": weather_error},
            "air_quality": {"online": air_ok, "error": air_error},
            "nasa_eonet": {"online": eonet_ok, "error": eonet_error},
            "usgs_earthquakes": {"online": usgs_ok, "error": usgs_error},
        },
        "observations": {
            "temperature_c": temp,
            "relative_humidity_percent": humidity,
            "precipitation_mm": precipitation,
            "wind_speed_kmh": wind,
            "pm25_ugm3": pm25,
            "us_aqi": us_aqi,
            "european_aqi": eu_aqi,
            "carbon_monoxide_ugm3": carbon_monoxide,
        },
        "hazards": {
            "nearest_nasa_event": nearest_event.__dict__ if nearest_event else None,
            "nearest_usgs_earthquake": nearest_quake.__dict__ if nearest_quake else None,
        },
        "risk": risk,
        "notes": [
            "The globe overlays are visualization layers unless replaced with validated gridded geospatial datasets.",
            "The API fusion panel uses live or near-real-time public feeds and is suitable as an operational prototype baseline.",
        ],
    }
    cache_set(key, payload)
    return JSONResponse(payload)
