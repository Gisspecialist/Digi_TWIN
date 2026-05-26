from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
CACHE_TTL_SECONDS = 300
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

app = FastAPI(
    title="3D Planetary Digital Twin Simulation Interface",
    description="Operational-style planetary environmental digital twin scaffold with safer live data endpoints.",
    version="1.1.0-amended-open-meteo-fallbacks",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def clean_coord(lat: float, lng: float) -> Tuple[float, float]:
    return clamp(float(lat), -90, 90), clamp(float(lng), -180, 180)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def cache_key(lat: float, lng: float) -> str:
    return f"{lat:.4f},{lng:.4f}"


async def fetch_json(client: httpx.AsyncClient, url: str, params: Optional[dict] = None) -> Tuple[Optional[dict], str, Optional[str]]:
    try:
        response = await client.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json(), "online", None
    except Exception as exc:  # noqa: BLE001 - returned in diagnostic payload
        return None, "offline", str(exc)


async def fetch_weather(client: httpx.AsyncClient, lat: float, lng: float) -> Dict[str, Any]:
    """Fetch weather using a robust primary endpoint and a richer fallback.

    Primary endpoint intentionally uses current_weather=true because it is stable in
    browsers, Vercel/serverless fetches, and simple backend adapters. The richer
    current= endpoint is retained as fallback when current_weather is unavailable.
    """
    primary_params = {
        "latitude": lat,
        "longitude": lng,
        "current_weather": "true",
        "timezone": "America/Belize",
    }
    primary_url = "https://api.open-meteo.com/v1/forecast"
    data, status, error = await fetch_json(client, primary_url, primary_params)
    if data and data.get("current_weather"):
        current = data["current_weather"]
        return {
            "status": "online",
            "source_url": str(httpx.URL(primary_url, params=primary_params)),
            "temperature_c": current.get("temperature"),
            "wind_speed_kmh": current.get("windspeed"),
            "wind_direction_deg": current.get("winddirection"),
            "weather_code": current.get("weathercode"),
            "time": current.get("time"),
            "precipitation_mm": None,
            "relative_humidity_pct": None,
            "fallback_used": False,
        }

    fallback_params = {
        "latitude": lat,
        "longitude": lng,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
        "timezone": "America/Belize",
    }
    data2, status2, error2 = await fetch_json(client, primary_url, fallback_params)
    if data2 and data2.get("current"):
        current = data2["current"]
        return {
            "status": "online",
            "source_url": str(httpx.URL(primary_url, params=fallback_params)),
            "temperature_c": current.get("temperature_2m"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "wind_direction_deg": current.get("wind_direction_10m"),
            "weather_code": current.get("weather_code"),
            "time": current.get("time"),
            "precipitation_mm": current.get("precipitation"),
            "relative_humidity_pct": current.get("relative_humidity_2m"),
            "fallback_used": True,
        }

    return {
        "status": "offline",
        "source_url": str(httpx.URL(primary_url, params=primary_params)),
        "error": error2 or error or "No current weather payload returned.",
        "temperature_c": None,
        "wind_speed_kmh": None,
        "precipitation_mm": None,
        "relative_humidity_pct": None,
        "fallback_used": True,
    }


async def fetch_air_quality(client: httpx.AsyncClient, lat: float, lng: float) -> Dict[str, Any]:
    base_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": lat,
        "longitude": lng,
        "current": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,ozone,us_aqi,european_aqi",
        "timezone": "America/Belize",
    }
    data, status, error = await fetch_json(client, base_url, params)
    if data and data.get("current"):
        current = data["current"]
        return {
            "status": "online",
            "source_url": str(httpx.URL(base_url, params=params)),
            "pm2_5": current.get("pm2_5"),
            "pm10": current.get("pm10"),
            "us_aqi": current.get("us_aqi"),
            "european_aqi": current.get("european_aqi"),
            "carbon_monoxide": current.get("carbon_monoxide"),
            "nitrogen_dioxide": current.get("nitrogen_dioxide"),
            "ozone": current.get("ozone"),
            "time": current.get("time"),
            "fallback_used": False,
        }

    fallback_params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,ozone,us_aqi,european_aqi",
        "forecast_hours": 24,
        "timezone": "America/Belize",
    }
    data2, status2, error2 = await fetch_json(client, base_url, fallback_params)
    hourly = data2.get("hourly", {}) if data2 else {}
    if hourly and hourly.get("time"):
        idx = 0
        return {
            "status": "online",
            "source_url": str(httpx.URL(base_url, params=fallback_params)),
            "pm2_5": (hourly.get("pm2_5") or [None])[idx],
            "pm10": (hourly.get("pm10") or [None])[idx],
            "us_aqi": (hourly.get("us_aqi") or [None])[idx],
            "european_aqi": (hourly.get("european_aqi") or [None])[idx],
            "carbon_monoxide": (hourly.get("carbon_monoxide") or [None])[idx],
            "nitrogen_dioxide": (hourly.get("nitrogen_dioxide") or [None])[idx],
            "ozone": (hourly.get("ozone") or [None])[idx],
            "time": hourly.get("time", [None])[idx],
            "fallback_used": True,
        }
    return {"status": "offline", "source_url": str(httpx.URL(base_url, params=params)), "error": error2 or error}


async def fetch_eonet(client: httpx.AsyncClient, lat: float, lng: float) -> Dict[str, Any]:
    # Bounding box around the selected point. EONET bbox order: west,south,east,north.
    pad = 5.0
    bbox = f"{lng-pad},{lat-pad},{lng+pad},{lat+pad}"
    url = "https://eonet.gsfc.nasa.gov/api/v3/events/geojson"
    params = {"bbox": bbox, "status": "open", "limit": 20}
    data, status, error = await fetch_json(client, url, params)
    nearest = None
    if data and data.get("features"):
        for feature in data["features"]:
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates")
            if isinstance(coords, list):
                point = coords
                while isinstance(point, list) and point and isinstance(point[0], list):
                    point = point[0]
                if isinstance(point, list) and len(point) >= 2:
                    dist = haversine_km(lat, lng, float(point[1]), float(point[0]))
                    item = {
                        "title": (feature.get("properties") or {}).get("title"),
                        "distance_km": round(dist, 1),
                        "geometry_type": geom.get("type"),
                    }
                    nearest = item if nearest is None or item["distance_km"] < nearest["distance_km"] else nearest
    return {"status": status, "source_url": str(httpx.URL(url, params=params)), "nearest_event": nearest, "error": error}


async def fetch_quakes(client: httpx.AsyncClient, lat: float, lng: float) -> Dict[str, Any]:
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    params = {"format": "geojson", "latitude": lat, "longitude": lng, "maxradiuskm": 1000, "orderby": "time", "limit": 10}
    data, status, error = await fetch_json(client, url, params)
    nearest = None
    if data and data.get("features"):
        for feature in data["features"]:
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) >= 2:
                dist = haversine_km(lat, lng, float(coords[1]), float(coords[0]))
                props = feature.get("properties") or {}
                item = {"place": props.get("place"), "magnitude": props.get("mag"), "distance_km": round(dist, 1)}
                nearest = item if nearest is None or item["distance_km"] < nearest["distance_km"] else nearest
    return {"status": status, "source_url": str(httpx.URL(url, params=params)), "nearest_quake": nearest, "error": error}


def classify_risk(weather: Dict[str, Any], air: Dict[str, Any], eonet: Dict[str, Any], quakes: Dict[str, Any]) -> Dict[str, Any]:
    pm25 = air.get("pm2_5")
    wind = weather.get("wind_speed_kmh")
    precip = weather.get("precipitation_mm")
    event_distance = (eonet.get("nearest_event") or {}).get("distance_km")
    quake_distance = (quakes.get("nearest_quake") or {}).get("distance_km")
    triggers = []
    level = "low"

    if isinstance(pm25, (int, float)) and pm25 >= 35:
        level = "high"; triggers.append("PM2.5 >= 35 ug/m3")
    if isinstance(quake_distance, (int, float)) and quake_distance <= 150:
        level = "high"; triggers.append("earthquake within 150 km")
    if level != "high":
        if isinstance(pm25, (int, float)) and pm25 >= 12:
            level = "moderate"; triggers.append("PM2.5 >= 12 ug/m3")
        if isinstance(wind, (int, float)) and wind > 35:
            level = "moderate"; triggers.append("wind speed > 35 km/h")
        if isinstance(precip, (int, float)) and precip > 2:
            level = "moderate"; triggers.append("precipitation > 2 mm")
        if isinstance(event_distance, (int, float)) and event_distance <= 500:
            level = "moderate"; triggers.append("NASA EONET event within 500 km")
        if isinstance(quake_distance, (int, float)) and quake_distance <= 500:
            level = "moderate"; triggers.append("earthquake within 500 km")

    if pm25 is None and event_distance is None and quake_distance is None:
        level = "limited"
        triggers.append("insufficient live hazard information")

    return {"level": level, "triggers": triggers or ["No immediate threshold crossed from available feeds."]}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "online", "version": app.version, "cache_entries": len(_cache), "cache_ttl_seconds": CACHE_TTL_SECONDS}


@app.get("/api/digital-twin")
async def digital_twin(lat: float = Query(17.25), lng: float = Query(-88.7667)) -> JSONResponse:
    lat, lng = clean_coord(lat, lng)
    key = cache_key(lat, lng)
    now = time.time()
    if key in _cache and now - _cache[key][0] < CACHE_TTL_SECONDS:
        payload = dict(_cache[key][1])
        payload["cache"] = {"hit": True, "ttl_seconds": CACHE_TTL_SECONDS}
        return JSONResponse(payload)

    async with httpx.AsyncClient(headers={"User-Agent": "planetary-digital-twin/1.1"}) as client:
        weather = await fetch_weather(client, lat, lng)
        air = await fetch_air_quality(client, lat, lng)
        eonet = await fetch_eonet(client, lat, lng)
        quakes = await fetch_quakes(client, lat, lng)

    payload = {
        "coordinate": {"lat": lat, "lng": lng},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "cache": {"hit": False, "ttl_seconds": CACHE_TTL_SECONDS},
        "api_status": {
            "weather": weather.get("status"),
            "air_quality": air.get("status"),
            "nasa_eonet": eonet.get("status"),
            "usgs_quakes": quakes.get("status"),
        },
        "observations": {"weather": weather, "air_quality": air},
        "hazards": {"nasa_eonet": eonet, "usgs_quakes": quakes},
        "risk": classify_risk(weather, air, eonet, quakes),
        "notes": [
            "Weather primary endpoint amended to current_weather=true with America/Belize timezone.",
            "Richer Open-Meteo current= endpoint retained as fallback.",
            "Air-quality current endpoint includes hourly fallback for browser/serverless reliability.",
        ],
    }
    _cache[key] = (now, payload)
    return JSONResponse(payload)
