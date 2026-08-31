# Architecture and integration paths

Nova is a local-first application with a web frontend and a Python scientific
backend. The desktop build does not move numerical code into Rust: Tauri owns
the application lifecycle and runs the same FastAPI application used by the
Docker workflow as a bundled sidecar.

This boundary keeps the scientific implementation usable without the desktop
UI and provides a stable place for automation, external solvers and, if
required later, remote execution. This document separates implemented
capabilities from possible extensions: OpenFOAM execution, remote jobs and a
public compatibility guarantee for the API are not currently implemented.

## Current structure

```text
Desktop
  React / React Three Fiber
       | HTTP requests
  FastAPI on a dynamic 127.0.0.1 port
       | Python calls
  geometry, inverse design, aerodynamic solvers and SQLite
       ^
       |
  Tauri starts, monitors and stops the bundled Python sidecar

Docker / browser
  React -> Vite proxy (/api) -> FastAPI:8000 -> the same Python modules
```

The layers have the following responsibilities:

- `frontend/src/backend.js` selects the API endpoint. In desktop mode it asks
  Tauri for the dynamically selected sidecar endpoint; in browser mode it uses
  `VITE_API_BASE_URL` or `/api`.
- `src-tauri/src/lib.rs` starts `nova-backend`, reads the announced endpoint,
  checks `/api/health`, exposes its status to React and terminates it when the
  application exits.
- `backend/desktop_launcher.py` selects a free loopback port, configures the
  application data directory and starts Uvicorn.
- `backend/main.py` defines the HTTP contract and Pydantic request models. It
  delegates geometry to `build_canonical_geometry()`, mesh creation to
  `generate_mesh_from_geometry()`, solver selection to `create_solver()` and
  persistence to functions in `backend/database.py`.
- `backend/inverse_design/`, `backend/geometry_engine.py` and
  `backend/airfoil_management/` contain numerical and geometric code that does
  not depend on Tauri.
- `backend/database.py` owns the current SQLite persistence layer.

FastAPI is therefore a transport boundary, not the scientific engine itself.
Some orchestration still lives directly in `backend/main.py`; as the project
grows, it should be extracted into application-service functions callable by
HTTP routes, tests and Python scripts without duplicated logic.

## API surface

The current API groups operations around these workflows:

| Workflow | Endpoint | Main implementation |
| --- | --- | --- |
| Initial sizing | `POST /api/sizing/actuator-disk` | `size_with_actuator_disk()` |
| Geometry generation | `POST /api/geometries` | `build_canonical_geometry()` |
| STL generation | `POST /api/geometries/stl` | `generate_mesh_from_geometry()` |
| Aerodynamic analysis | `POST /api/analyses` | `create_solver()` and `evaluate_detailed()` |
| Inverse design | `POST /api/inverse-design` | `InverseDesignOptimizer.optimize()` |
| Airfoils and polars | `/api/airfoils...` | `AirfoilManager`, `AirfoilLoft` and database functions |
| Project storage | `/api/projects`, `/api/propellers...` | functions in `database.py` |

Request validation is part of this boundary. For example,
`GeometryRequest` constrains diameter, RPM, blade count and supported geometry
methods before values reach the geometry engine. Analysis responses record
method metadata, units, warnings and convergence information rather than only
scalar results.

The OpenAPI schema and interactive documentation are available at
`/openapi.json` and `/docs` while the backend is running. The API is still an
alpha interface: consumers should pin a Nova version and must not assume
backward compatibility before an explicit versioning policy is introduced.

## Scientific automation

For repeatable scripts, start the backend on a known port instead of trying to
discover the private dynamic port of an installed desktop instance. Docker
exposes port 8000. A source checkout can run the backend directly:

```bash
cd backend
NOVA_DB_PATH=/tmp/nova-automation.db \
  uvicorn main:app --host 127.0.0.1 --port 8000
```

A minimal sizing sweep can use the standard HTTP interface:

```python
import requests

results = []
for disk_loading in [200.0, 300.0, 400.0]:
    response = requests.post(
        "http://127.0.0.1:8000/api/sizing/actuator-disk",
        json={"thrust_target": 12.0, "disk_loading": disk_loading},
        timeout=30,
    )
    response.raise_for_status()
    results.append(response.json())

for result in results:
    print(result["diameter_m"], result["ideal_power_w"])
```

The same pattern supports a geometry-analysis pipeline: submit a
`GeometryRequest` to `POST /api/geometries`, then pass the returned canonical
geometry and the original inputs to `POST /api/analyses`.

```python
geometry_response = requests.post(
    f"{base_url}/api/geometries", json=geometry_request, timeout=60
)
geometry_response.raise_for_status()

analysis = requests.post(
    f"{base_url}/api/analyses",
    json={
        "model": "bemt",
        "inputs": geometry_request,
        "geometry": geometry_response.json()["geometry"],
    },
    timeout=120,
)
analysis.raise_for_status()
print(analysis.json()["summary"])
```

Here `geometry_request` must follow the `GeometryRequest` schema published in
`/openapi.json`. Generated schemas or clients are preferable to separately
maintained client models for larger integrations.

Automation clients should:

- set explicit connection and computation timeouts;
- retain structured error bodies and call `raise_for_status()`;
- record Nova version, solver identifier, inputs, warnings and convergence
  data with every result;
- use an isolated `NOVA_DB_PATH` for independent experiments;
- limit concurrency until database access and solver thread-safety have been
  validated for the workload.

For Python code in the same environment, a future application-service layer
should also provide a direct library API. HTTP is useful across process and
machine boundaries, but should not be mandatory for an in-process notebook or
test.

## Remote solver execution

The HTTP contract allows the UI and numerical process to live on different
machines, but the packaged desktop application does not yet support this
topology. Tauri currently accepts only a loopback `NOVA_BACKEND_ENDPOINT`; this
prevents an environment variable from silently redirecting the desktop UI to
an arbitrary host.

A remote-capable design should preserve that default and add an explicit,
user-configured connection mode:

```text
Nova desktop
  -> authenticated HTTPS API
     -> job service on a compute workstation
        -> Python low-order solver or OpenFOAM executor
        -> result and artifact storage
```

Remote execution requires more than changing a URL: TLS, authentication, API
version negotiation, request limits, cancellation, timeouts and policies for
uploading geometry and downloading artifacts are required. A local gateway
managed by Tauri is another valid design: React continues to talk only to
loopback, while the gateway owns remote credentials and forwards approved
jobs.

Long calculations should use jobs instead of keeping one request open:

```http
POST   /api/jobs                    create a calculation
GET    /api/jobs/{id}               read state and progress
POST   /api/jobs/{id}/cancel        request cancellation
GET    /api/jobs/{id}/artifacts     list result files
```

Each job should retain immutable inputs, solver and Nova versions, timestamps,
execution environment, logs, convergence state and artifact checksums. These
fields support reproducibility in both local and remote execution.

## OpenFOAM integration path

OpenFOAM should be an execution adapter, not something called directly from
React or embedded in the low-order solver interfaces.

```text
Analysis application service
  -> LowOrderExecutor (BEMT, LLT, VLM, BEM)
  -> OpenFOAMExecutor
       -> local Docker engine
       -> later: remote job service
```

An `OpenFOAMExecutor` would:

1. validate the case and resource limits;
2. convert canonical geometry into case input and mesh artifacts;
3. start a pinned container image with controlled mounts;
4. capture progress, logs, exit status and cancellation;
5. parse forces, moments and fields into a versioned result model;
6. preserve enough provenance to reproduce the run.

The job contract can remain unchanged when the executor moves from local
Docker to a Linux workstation. Only execution and artifact transport change.
Docker daemon access must remain in the trusted backend: the WebView must not
be allowed to supply arbitrary images, command arguments or host paths.

## Evolution rules

To preserve these options without over-engineering the alpha:

- keep numerical functions independent from FastAPI, Tauri and Docker;
- keep routes thin and move multi-step workflows into application services;
- treat canonical geometry and result models as versioned contracts;
- add job semantics when the first genuinely long-running executor is built;
- retain loopback-only desktop operation by default;
- add authentication before allowing non-loopback API access;
- avoid exposing SQLite-specific details through application services;
- benchmark serialization before introducing a binary protocol.

This structure does not commit Nova to a hosted service. It keeps a standalone
desktop path while allowing the same scientific core to support scripts,
notebooks, CI studies, compute workstations and future CFD executors.
