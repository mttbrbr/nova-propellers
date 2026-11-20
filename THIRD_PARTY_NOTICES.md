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
| Matplotlib and Pillow | Local validation plots and PNG rendering | Matplotlib license / MIT-CMU |
| Trimesh | Mesh generation and STL export | MIT |
| React and React DOM | User interface | MIT |
| Three.js and React Three Fiber | 3D rendering | MIT |
| Lucide React | Interface icons | ISC |
| Vite, Tailwind CSS, PostCSS and Autoprefixer | Frontend build | MIT |
| Tauri, Wry and Tauri shell plugin | Linux desktop shell and sidecar lifecycle | Apache-2.0 / MIT |
| PyInstaller | Standalone Python application bundler | GPL-2.0-or-later with bootloader exception |

The exact transitive inventory is generated from the committed Python and npm
lockfiles. Notable transitive notices include `caniuse-lite` under CC-BY-4.0.
NumPy/SciPy binary wheels may contain OpenBLAS/LAPACK under BSD-style licenses,
GCC runtime libraries under GPL-3.0-with-GCC-exception, and `libquadmath` under
LGPL-2.1-or-later. Those notices do not relicense Nova source code, but must be
preserved by anyone redistributing the corresponding binaries.

Desktop binary packages include the PyInstaller bootloader and the resolved
Python environment. PyInstaller's bootloader exception permits distribution of
the resulting application under Nova's license; bundled dependency license and
native-library notices still apply. GTK and WebKitGTK are system dependencies
of the Arch and Debian packages and remain under their respective licenses.

## Optional external programs and published coefficients

These programs are installed by the user, configured in Settings → Integrations and driven only
through their input and output files. They are not bundled, linked or redistributed.

| Program | Use in Nova | License |
| --- | --- | --- |
| OpenFAST | Time-domain cases and structural linearisation | Apache-2.0 |
| PyWake | Wind-farm wake model (NOJ) | MIT |
| CalculiX (ccx) | Shell finite-element modes of the blade | GPL-2.0 |
| DUST | Lifting-line / vortex-particle rotor check | MIT |
| FMPy (optional Python package) | FMI 2.0 co-simulation FMUs | BSD-2-Clause |

The turbine cost block uses the equations and coefficients of the NREL Cost and Scaling Model as
published in NREL WISDEM (`wisdem/nrelcsm`, `wisdem/plant_financese`, Apache-2.0); no WISDEM source
code is included.

The release process must refresh this file whenever a runtime dependency or
locked version changes. Package metadata marked `UNKNOWN` must be verified
against the dependency's official license file before release.

## Brand artwork

The NOVA wordmark (`docs/media/brand/nova-wordmark.svg` and the header logo
data in `frontend/src/shell/brand.js`) contains the letters N, V and A
outlined from **Outfit** Bold, © 2021 The Outfit Project Authors
(https://github.com/Outfitio/Outfit-Fonts), licensed under the SIL Open Font
License 1.1. The font software is not included; only the resulting artwork.
