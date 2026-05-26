# 3D Planetary Digital Twin Simulation Interface

This package upgrades the earlier browser-only planetary eco-assessment prototype into an operational-style production scaffold.

It includes:

- A 3D WebGL planetary interface using Three.js.
- A FastAPI backend that centralizes live data fusion.
- Coordinate-based weather and air-quality feeds from Open-Meteo.
- Near-real-time natural event proximity from NASA EONET.
- Near-real-time earthquake proximity from USGS GeoJSON feeds.
- API health indicators, cache handling, risk classification, and test coverage.
- Docker and Docker Compose deployment files.
- Detailed DOCX and PDF documentation.

## Quick Start

```bash
cd planetary_digital_twin_production
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Docker Start

```bash
docker compose up --build
```

Open:

```text
http://127.0.0.1:8000
```

## API Endpoints

```text
GET /api/health
GET /api/digital-twin?lat=40.71&lng=-74.01
```

## Tests

```bash
pytest
```

## Production Notes

This is now a production-ready scaffold, not just a standalone demo. For a mission-critical fully operational planetary digital twin, connect the visual layers to validated gridded geospatial datasets, add persistent storage, auth, observability, data lineage, model governance, and scheduled ingestion.

## Vector Targeting Correction — Belize Default

The frontend Vector Targeting panel has been corrected to use standard decimal-degree coordinate conventions:

- Latitude: North is positive, South is negative.
- Longitude: East is positive, West is negative.
- Belize approximate geographic center: latitude `17.25`, longitude `-88.7667`.

The application now starts with Belize as the default vector target and includes quick presets for Belize Center and New York City.


## Coordinate Alignment Patch

The frontend now uses a true latitude/longitude-to-sphere-vector conversion instead of the earlier approximate Euler mapping. This keeps the base Earth texture, target marker, overlays, and vector targeting system aligned.

Default Belize coordinate:

```text
Latitude: 17.25
Longitude: -88.7667
```

Coordinate convention:

- North latitude is positive.
- South latitude is negative.
- East longitude is positive.
- West longitude is negative.

The application now displays a yellow target marker and ring on the selected surface coordinate. The same computed 3D vector is used to rotate the globe into camera view, preventing visual mismatch between the base map and selected coordinate.
