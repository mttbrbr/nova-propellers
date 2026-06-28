# Nova

Nova is an alpha-stage propeller design tool. It combines a React interface with a FastAPI backend to analyze propellers, manage airfoil polar data, save design runs, and export STL geometry.

> **Alpha software:** `0.1.0-alpha.1` is intended for testing and validation. Generated designs must not be treated as production-ready engineering output without independent verification.

## Quick start with Docker

### Requirements

- Docker Engine or Docker Desktop
- Docker Compose v2 (`docker compose`)

No local Node.js or Python installation is required.

### Start

From the repository root, run:

```bash
docker compose up --build -d
```

Wait for the containers to become healthy, then open:

- Application: <http://localhost:5173>
- API documentation: <http://localhost:8000/docs>
- API health check: <http://localhost:8000/api/health>

Follow startup logs with:

```bash
docker compose logs -f
```

### Stop

```bash
docker compose down
```

The SQLite database is stored in the Docker volume `nova_backend_data`, so designs and airfoil data survive normal restarts and `docker compose down`.

To also delete all persisted Nova data and start from an empty database:

```bash
docker compose down --volumes
```

## Port configuration

The defaults are `5173` for the application and `8000` for the API. If either port is already in use, create a `.env` file from the provided example and change the values:

```bash
cp .env.example .env
docker compose up --build -d
```

For example:

```dotenv
NOVA_FRONTEND_PORT=3000
NOVA_BACKEND_PORT=8080
```

With these values, the application is available at <http://localhost:3000> and the API documentation at <http://localhost:8080/docs>.

## Development workflow

The Compose setup mounts `frontend/` and `backend/` into their containers. Vite and Uvicorn reload automatically when source files change.

Useful commands:

```bash
# Show service status and health
docker compose ps

# Rebuild after changing dependencies or a Dockerfile
docker compose up --build -d

# Open a shell in a running service
docker compose exec frontend sh
docker compose exec backend sh
```

## Architecture

| Service | Technology | Container port | Purpose |
| --- | --- | ---: | --- |
| `frontend` | React, Vite, Three.js | `5173` | User interface and 3D preview |
| `backend` | FastAPI, NumPy, SciPy, Trimesh | `8000` | Analysis, persistence, and STL generation |

The frontend sends `/api` requests through the Vite proxy to the backend. SQLite data is written to `/data/nova.db` inside the persistent `backend_data` volume.

### Inverse design

The inverse-design engine is split into independent geometry, solver and
optimizer blocks under `backend/inverse_design`. Run the standalone example
inside the backend container with:

```bash
docker compose exec backend python -m inverse_design.example
```

`InverseDesignOptimizer` depends only on the common geometry-parameterization
and `BaseSolver` interfaces. BEMT and the preliminary horseshoe-lattice VLM can
therefore be selected without changing the optimization loop.

Every computational method has its own module under
`backend/inverse_design/solvers` and is exposed through the central registry.
Run the deterministic comparison harness with:

```bash
docker compose exec backend python -m inverse_design.benchmark
```

The harness checks software consistency and expected trends. It does not replace
validation against wind-tunnel or published propeller data.

### Airfoil coordinates and spanwise loft

`backend/airfoil_management` imports UIUC/XFOIL `.dat` files, normalizes them
to 100 spline-resampled points and blends corresponding coordinates along the
blade span. The complete import, loft and optimizer-safety example runs with:

```bash
docker compose exec backend python -m airfoil_management.example
```

## Alpha release

The release identifier is `v0.1.0-alpha.1`. After reviewing and committing the release files, create and publish the tag with:

```bash
git tag -a v0.1.0-alpha.1 -m "Nova 0.1.0 alpha 1"
git push origin main v0.1.0-alpha.1
```

Release notes are available in [CHANGELOG.md](CHANGELOG.md).

## Troubleshooting

If startup fails, inspect the service status and logs:

```bash
docker compose ps
docker compose logs backend frontend
```

If dependencies appear stale after changing `requirements.txt` or `package.json`, force a rebuild:

```bash
docker compose build --no-cache
docker compose up -d
```
