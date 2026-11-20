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
- Planform shaping beyond chord and twist: user-defined sweep (scimitar
  blades) and canted or swept tips (winglet-like). Today the STL mesh applies
  only a fixed cosmetic offset of 0.035·R·sin(π·span) and no solver accounts
  for sweep, so this needs geometry parameters, mesh support and solver
  treatment (or an explicit "not modelled" warning) together.

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

## Engineering extensions (block-based)

Every capability below is delivered as workflow blocks; when a block needs new inputs, dedicated
input blocks are added (as `point_mass` and `spring_damper` were for structural dynamics).

### Phase 1 — Structural dynamics (done)

- 3-D coupled Timoshenko beam (spectral elements); clamped and rotating blade modes, tower modes, Campbell
  diagram with MAC tracking, margins and crossings, point masses, springs and dampers, template
  `structural_campbell`. See `docs/technical/structural-dynamics.md`.
- Rotor–tower coupled Campbell diagram in multi-blade coordinates (MBC3, collective/BW/FW), template
  `coupled_campbell`.
- OpenFAST linearisation block (ElastoDyn, aerodynamics off, MBC3) with a mode-by-mode comparison; on the
  AOC 15/50 example the first five coupled modes agree within 2.5 %, the second flap within about 7 %.
- Campbell chart, animated mode shapes and participation in the block result panel.
- Open: refreshed README screenshots; mode shapes in the 3-D viewport (today a 2-D animated side view).

### Phase 2 — Performance curves and operating strategy (done)

- *Performance map*: progressive grid refinement around the optimum and a thin-plate RBF response surface
  whose optimum is verified.
- *Cp–λ flexible & sheared*: power-law shear (azimuthal BEMT) and steady flap deflection of the rotating
  3-D beam (cos³β coning). *Operating strategy*: rotor speed from λ and wind speed, limits, rated power,
  schedule. See `docs/technical/performance-strategy.md`.

### Phase 3 — Cost models and multidisciplinary optimisation (done)

- NREL Cost and Scaling Model (2015 mass–cost update, WISDEM coefficients), annual energy, LCOE.
- *Design optimiser* (SLSQP/COBYLA), *Pareto optimiser* (NSGA-II) and *Multi-fidelity optimiser* over any
  quantity computed downstream: every candidate re-runs the downstream blocks. See
  `docs/technical/economics-optimisation.md`.
- Not implemented: Sandia blade cost model (no published model with a licence found) and INNWIND.EU cost
  model (public deliverables without a reuse licence). Decision for the owner.

### Phase 4 — Sections and CalculiX (done, CalculiX run not qualified)

- *Blade layup*: thin-walled sections (NACA or circular root, shell, spar caps, webs; multi-cell torsion)
  producing the blade structure record.
- CalculiX adapter and *Blade shell modes* block (S4 shell model). Tested with a stand-in executable; a
  real-solver test runs with `NOVA_CCX`. See `docs/technical/blade-sections-fem.md`.

### Phase 5 — Aerodynamic integrations (done, DUST run not qualified)

- Wind-farm blocks: farm turbine, layout, Weibull climate, farm AEP with native NOJ or PyWake.
- DUST adapter and *DUST rotor* block (lifting-line rotor, vortex-particle wake, integral loads). Case
  syntax from the DUST examples; not yet run against a real DUST build. See
  `docs/technical/wind-farm-dust.md`.

### Phase 6 — Control and co-simulation (done, FMU run not qualified)

- Control blocks on named signals: sources, PI/PID with gain scheduling and anti-windup, kω² torque law,
  schedules, transfer function, state space, rotor–drivetrain plant, simulation. Templates
  `turbine_control`, `lcoe_optimization`, `wind_farm_aep`, `rotor_economics_chain`.
- FMI 2.0 co-simulation FMUs through optional FMPy (replaces a dedicated OpenModelica integration);
  tested with a stand-in FMPy module. See `docs/technical/control.md`.

### Next

- Qualify the external runs: CalculiX shell modes against the beam, DUST against BEMT/OpenFAST, a real
  OpenModelica FMU.
- Mode shapes in the 3-D viewport; dedicated result views for wind farms and control time series.

### To decide

- Hosting of the Sphinx documentation (GitHub Pages or Read the Docs) and removal of
  `docs/esempio documentazione/`.
