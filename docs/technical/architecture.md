# Architecture

## In brief

NOVA is a *local-first* application: a web interface (React) and a scientific engine in Python
(FastAPI). In the desktop build, Tauri only manages the application lifecycle and starts the same
engine Docker uses; the numerical code does **not** move to Rust.

## In detail

### Structure

```text
Desktop
  React / React Three Fiber
       | HTTP requests
  FastAPI on a dynamic 127.0.0.1 port
       | Python calls
  geometry, inverse design, aerodynamic solvers, SQLite
       ^
  Tauri starts, monitors and stops the Python engine

Docker / browser
  React -> Vite proxy (/api) -> FastAPI:8000 -> the same Python modules
```

This separation keeps the scientific code usable without the interface, for automation, external
solvers and, later, remote execution. FastAPI is a transport boundary, not the scientific engine.

:::{table} Responsibilities of the layers
:name: tab-layers

| Layer | Role |
|---|---|
| `frontend/src/backend.js` | Selects the API endpoint: asks Tauri on desktop, uses `/api` in the browser |
| `src-tauri/src/lib.rs` | Starts the engine, checks `/api/health`, stops it on exit |
| `backend/desktop_launcher.py` | Picks a free port, sets the data folder, starts Uvicorn |
| `backend/nova/` | Physics, blocks, workflows, adapters, application layer, HTTP transport |
:::

### Programming interface

Request validation is part of the boundary: for example `GeometryRequest` limits diameter, rpm,
blade count and geometry methods before values reach the engine. Responses carry method metadata,
units, warnings and convergence information, not only scalar values. The OpenAPI schema is at
`/openapi.json` and the interactive documentation at `/docs`.

```{warning}
The API is still alpha: consumers must pin a NOVA version and cannot rely on backward
compatibility until an explicit versioning policy exists.
```

### Automation

For repeatable scripts, start the engine on a known port (Docker exposes 8000; from source use
`uvicorn main:app --host 127.0.0.1 --port 8000`) instead of looking for the private port of an
installed desktop instance. A client should set explicit connection and computation timeouts.

**[TO COMPLETE]** List the current endpoints once the ongoing reorganisation of the code
(`backend/nova/transport/`) settles; it is replacing some of the paths described in the older
documents.
