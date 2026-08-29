# Third-party notices

Nova Propellers source code is licensed under Apache-2.0. Dependencies are
separate works and remain subject to their own licenses. They are downloaded
when users build or develop the application and are not included in the
source-only release archive.

## Declared runtime dependencies

| Dependency | Role | License family |
| --- | --- | --- |
| FastAPI and Pydantic | HTTP API and validation | MIT |
| Uvicorn and Starlette | ASGI runtime | BSD-3-Clause |
| NumPy and SciPy | Numerical computing | BSD-style; binary wheels contain additional notices |
| Trimesh | Mesh generation and STL export | MIT |
| React and React DOM | User interface | MIT |
| Three.js and React Three Fiber | 3D rendering | MIT |
| Lucide React | Interface icons | ISC |
| Vite, Tailwind CSS, PostCSS and Autoprefixer | Frontend build | MIT |

The exact transitive inventory is generated from the committed Python and npm
lockfiles. Notable transitive notices include `caniuse-lite` under CC-BY-4.0.
NumPy/SciPy binary wheels may contain OpenBLAS/LAPACK under BSD-style licenses,
GCC runtime libraries under GPL-3.0-with-GCC-exception, and `libquadmath` under
LGPL-2.1-or-later. Those notices do not relicense Nova source code, but must be
preserved by anyone redistributing the corresponding binaries.

The release process must refresh this file whenever a runtime dependency or
locked version changes. Package metadata marked `UNKNOWN` must be verified
against the dependency's official license file before release.
