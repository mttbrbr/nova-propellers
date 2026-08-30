# Changelog

All notable changes to Nova are documented in this file.

## Unreleased

### Added

- Tauri 2 Linux desktop shell with automatic FastAPI sidecar lifecycle,
  dynamic loopback endpoint discovery and readiness/error reporting.
- PyInstaller backend build and standalone smoke test.
- Arch Linux `PKGBUILD`, Ubuntu/Debian bundling and clean package CI.
- Arch-first desktop development, packaging and debugging guide.

### Changed

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
