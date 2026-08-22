# Flood Risk Mapping & Shelter Identification — Kathmandu Valley

AHP (Analytic Hierarchy Process) multi-criteria flood risk mapping and
shelter-identification tool for the Kathmandu Valley.

See [SPEC.md](./SPEC.md) for the data contracts and project-wide
conventions (CRS, grid/resolution, nodata handling) that every phase of
this project follows.

## Quick start

```bash
docker compose up
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend | http://localhost:8000 |
| Postgres/PostGIS | localhost:5432 |

Optionally copy `.env.example` to `.env` first to override the default
(dev-only) database credentials.

## Layout

```
/backend   FastAPI service (Python)
/frontend  React + MapLibre GL client
/schemas   Shared JSON Schema data contracts
```
