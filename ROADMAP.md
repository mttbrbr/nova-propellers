# Roadmap

Nova is maintained as a solo, part-time portfolio project. Milestones are
release gates, not promises of engineering qualification.

## v0.1.0-alpha.2 — Public Portfolio Alpha

- Apache-2.0 licensing, provenance and dependency review.
- Reproducible Docker startup and dependency locks.
- Backend, frontend, compliance and Compose CI checks.
- Truthful solver roles, maturity labels and limitations.
- Public documentation and original portfolio captures.

## v0.2 — Validation Foundation

- Canonical solver result and unit contract. Initial schema `1.0` implemented.
- Versioned API boundary.
- Open reference datasets with provenance and reusable licenses.
- BEMT convergence, polar interpolation and correction qualification. Initial
  convergence contract and supported numerical domain implemented; experimental
  reference qualification remains open.
- Physics invariants, golden cases and acceptance thresholds. Initial internal
  BEMT regression case implemented; experimental thresholds remain open.

Only a solver that passes the declared reference thresholds may move from
`preliminary` to `qualified`.

## v0.3 — Engineering Workflow

- Portable versioned project format.
- Operating-envelope sweeps and performance maps.
- Traceable reports and CSV exports.
- Design comparison, manufacturability checks and constrained optimization.

## v1.0 and later

- Observable long-running jobs and release qualification.
- Supported local or self-hosted distribution and recovery.
- Accessibility and complete user documentation.
- Authentication and multi-user hosting only if a hosted edition becomes a
  real project goal.

## NOVA architecture implementation

Implemented application foundations:

- Transport-independent geometry/analysis services and shared result contracts.
- Explicit imported polar assets, source retention and sparse-safe interpolation.
- Scientific input validation and convergence-aware optimization.
- Typed DAG validation/execution, immutable template cloning and headless CLI.
- Isolated local workers, cancellation, persisted run history and interruption.
- Stable project revisions, immutable assets/results and transactional `.nova`
  archive transfer including historical assets.
- Guided and editable workflow execution over the same engine; run-specific
  results, diagnostics, CSV/STL export and visible stale-state feedback.
- Desktop API session authentication, bounded startup/logs and graceful shutdown.

Verification completed on the development host: backend scientific/integration
suite, Rust tests/build, frontend lint/build, Chromium journey and frozen-sidecar
workflow smoke test. See `docs/NOVA_IMPLEMENTATION.md` for commands and limits.

Clean Arch and Ubuntu 24.04 package installation and actual desktop-launcher
lifecycle qualification now pass. The repeatable process is documented in
`docs/LINUX_QUALIFICATION.md`; physical graphics/Wayland testing and bit
reproducibility remain separate release concerns. Subsequent phases remain gated:
DUST, broader OpenFAST case qualification, richer validated external cases
and profiling-driven C++ acceleration.
External solver software is independently installed; no implementation is bundled.

### Studies and adapter framework increment

Implemented: bounded one-axis sweeps with case checkpoints, retained failures,
comparisons/CSV/case inspection, queued inverse design using canonical geometry,
and an independent adapter SDK with sequential stages and environment isolation.
The framework-only increment registered no production scientific adapter;
the subsequent user-requested PyWake/OpenFAST work is recorded below.

## PyWake and OpenFAST adapter increment

Implemented optional PyWake NOJ execution with explicit joint probabilities,
OpenFAST ASCII/binary import and execution of self-contained supplied cases.
Both use typed default graphs, isolated jobs, retained artifacts and the
Integrations UI. Real PyWake 2.6.20 and an official OpenFAST binary output were
checked. On 2026-10-21, independently installed OpenFAST 5.0.0 also completed
a shortened official AOC case through source and frozen backends: 101 samples × 30
channels exactly matched direct execution. This verifies one execution path;
controller-dependent cases and physical validation remain separate work.

Next bounded tasks: qualify additional OpenFAST configurations as needed;
extend saved wind-farm cases to portable exchange and suitable project types; evaluate
additional PyWake models/resource datasets only against validated use cases.
Cross-tool coupling, DUST, new native algorithms and C++ migration remain later
work. See `docs/EXTERNAL_INTEGRATIONS.md`.

## Project and simulation coherence increment

Implemented: persistent project/draft/model context, multiple named native
configurations per project, independent revision/save/clone controls, and frozen
execution lineage for analyses, studies and optimization. Project archives retain
configurations and historical references; legacy archives remain importable.
External integrations remain explicitly standalone. See
`docs/PROJECT_SIMULATIONS.md` for scope and verification.

Verification: 75 backend tests, both browser journeys, frontend lint/build and
updated Arch package installation/desktop/runtime checks passed. Ubuntu remains
at the earlier integration increment. Next coherence work can extend project
types and external-case persistence before connecting those cases to projects.

### Shared geometry and command simplification

Shared project geometry has immutable revisions and explicit adoption by selected
simulation configurations. Solver/operating variants reuse the same baseline;
historical results keep their earlier geometry. Legacy configurations/archives
remain compatible, and derived sizing/study/optimization outputs remain distinct
from the baseline reference.

One persistent Save/Run simulation/Cancel control set replaces duplicate native
commands. Project actions groups archive/new/close operations; New and Duplicate
simulation have distinct behavior, dirty transitions are protected, and workflow
customization/block addition/validation/log controls are more compact. External
integrations and the legacy propeller library retain their existing capabilities.

### Project explorer, solver comparisons and portable results

Implemented: searchable native project explorer; strict comparisons of 2–8 saved
solver configurations with frozen source revisions and explicit reference
differences; optional two-axis studies with bounded Cartesian cases, discrete
result matrices and exact-case inspection; `.nova-run` external result archives
with preserved scientific artifacts; persistent external job monitoring and
global cancellation across navigation. Scientific solver algorithms are unchanged.

Saved immutable PyWake cases now retain turbine curves, layout and wind inputs
independently of software, with explicit demonstration metadata, an equal-scale
layout preview and in-session draft retention across workspace changes.

Next: portable external-case exchange and suitable project types, broader OpenFAST case
qualification, optimization-history candidate inspection, then validated resource
models. General multiphysics coupling and native-language migration stay gated
by numerical baselines, profiling and demonstrated user needs.
