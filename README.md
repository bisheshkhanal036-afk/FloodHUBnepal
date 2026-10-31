# Flood Risk Mapping & Shelter Identification — Kathmandu Valley

AHP (Analytic Hierarchy Process) multi-criteria flood risk mapping and
shelter-identification tool for the Kathmandu Valley.

See [SPEC.md](./SPEC.md) for the data contracts and project-wide
conventions (CRS, grid/resolution, nodata handling) that every phase of
this project follows.

## GitHub Pages research demo

The independent [static demo](./pages-demo/README.md) explores precomputed Nepal
district exposure across five weighting schemes, with aggregate downloads and
research figures. It needs no backend. The intended public URL is
[bisheshkhanal036-afk.github.io/FloodHUBnepal](https://bisheshkhanal036-afk.github.io/FloodHUBnepal/).
Live analysis, uploads, Citizen assessments and NBS calculations remain part of
the separate server application below.

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
