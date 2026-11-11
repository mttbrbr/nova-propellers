# Changelog

All notable changes to Nova are documented in this file.

## Unreleased

### Added

- Design sheet replaces the stage bar: Sizing, Geometry, Analysis and Results
  are stacked sections (several open at once, summaries and status dots when
  closed), with view tabs in the centre and an always-visible latest-run card.
- Open projects as tabs in the header.
- Run opens a model chooser every time (several models for the air propeller,
  one streamtube model for VAWT, BEMT for HAWT and marine).
- Comparisons workspace: runs from any project overlaid, baseline deltas,
  input differences with an attribution warning, saved comparisons.
- Sweep lens for rotor-engine designs with limits, VAWT refinement with a more
  complete model, adopt-into-design and open-as-block-workflow;
  `POST /api/v1/rotors/sweep`.
- New NOVA logo and app icon (dashed-O wordmark), orange primary colour.

- Rotor type chosen at the start of the Design flow (air propeller, marine
  propeller, HAWT, VAWT). Sizing, Geometry, Analysis and Results adapt to it:
  turbine sizing from rated power, marine sizing from thrust/J with Keller,
  only the corrections that apply to the chosen type, Cp–λ or K_T/10K_Q/η–J
  curves, run-to-run comparison and a requirement check. Non-propeller types
  are saved as `rotor` simulations in v2 projects and archives.
  `/api/v1/rotors/*` exposes the models. See `docs/ROTOR_MODELS.md`.
- VAWT single, double, multiple and double-multiple streamtube models with
  finite-aspect-ratio, flow-curvature, Gormont–Berg dynamic-stall, strut-drag
  and shaft-wake corrections; straight and troposkien blades.
- Axial BEMT (Ning's 1-D residual) for propellers and turbines with Prandtl or
  Shen tip loss, hub loss, Glauert/Buhl/Spera high induction, Snel rotational
  augmentation and Prandtl–Glauert compressibility.
- Marine propeller theory: B-series outline, hull interaction, σ₀.₇R, Burrill
  τc, Keller minimum area ratio and local cavitation number.
- Block workflows (Workflow → Block workflows, `/api/v1/blocks/*`): typed DAG
  of general blocks (parameters with limits, expressions, constraints, sweep,
  filter, select, optimizer, report) and rotor-specific blocks (rotors,
  operating point, hull, corrections, solver, performance curve, design
  checks). Hard/soft constraints report margins; "stop" blocks downstream
  work. Templates and saved workflows included.

- `POST /api/v1/simulations/{id}/solver-comparison` runs one saved simulation
  with 2–4 solvers as a frozen comparison without creating simulations.
- `GET /api/v2/project-index` returns lightweight project summaries;
  `DELETE /api/v2/projects/{id}` removes a project with its simulations,
  geometry revisions and runs (rejected while a job is active).
- Tauri 2 Linux desktop shell with automatic FastAPI sidecar lifecycle,
  dynamic loopback endpoint discovery and readiness/error reporting.
- PyInstaller backend build and standalone smoke test.
- Arch Linux `PKGBUILD`, Ubuntu/Debian bundling and clean package CI.
- Arch-first desktop development, packaging and debugging guide.

### Changed

- Redesigned interface for 16:9 screens: one header with project and
  simulation selectors, stage stepper, Save, More actions and Run; an icon
  rail for workspaces; each stage laid out as inputs, data and a square 3D
  render. Geometry previews update automatically, curves gained axes, hover
  values and a shared station selection, Results colours the blade by a chosen
  quantity, and out-of-date runs say what changed. Models and the legacy
  archive moved into Library. See `docs/UI_NAVIGATION.md`.
- Studies offers three explicit study types: solver comparison of one saved
  simulation (also launched from Analysis with "Also compare with"), design
  comparison across projects with like-for-like checks and planform overlay,
  and parameter sweeps. Library lists saved projects with search, filters,
  comparison, export and confirmed deletion; a searchable project picker
  (Ctrl+P) replaces the project drop-down.
- Local non-Docker persistence follows XDG data directory conventions.
- The frontend discovers its desktop backend while retaining `/api` for the
  existing web and Docker workflow.

## [0.1.0-alpha.2] - 2026-08-30

### Added

- Apache-2.0 licensing, provenance records and dependency license checks.
- Reproducible Python and npm dependency locks.
- Backend, frontend, compliance and Compose CI workflows.
- Multi-architecture frontend and backend images published through GitHub
  Container Registry for tagged releases.
- Explicit solver roles, warnings, units and convergence metadata.
- Public-facing project documentation and an original interface screenshot.

### Changed

- Docker Compose supports both published GHCR images and reproducible local
  builds; reload mounts live in `docker-compose.dev.yml`.
- Built-in polar data are explicitly identified as synthetic demonstration data.
- Actuator disk is a sizing reference rather than a selectable blade analysis.

### Fixed

- Toroidal geometry is consistently rejected until implemented.
- Experimental VLM/BEM methods no longer advertise unsupported toroidal geometry.
- Non-converged BEMT runs return explicit metadata and warnings instead of an
  opaque API failure.

## [0.1.0-alpha.1] - 2026-06-19

### Added

- First alpha release of the propeller design interface.
- FastAPI analysis and STL generation API.
- Airfoil polar database and persistent propeller runs.
- Docker Compose development environment for one-command startup.

[0.1.0-alpha.1]: https://github.com/mttbrbr/nova-propellers/releases/tag/v0.1.0-alpha.1
[0.1.0-alpha.2]: https://github.com/mttbrbr/nova-propellers/releases/tag/v0.1.0-alpha.2
