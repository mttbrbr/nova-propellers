# Changelog

All notable changes to Nova are documented in this file.

## Unreleased

### Added

- *Structure* workspace: structural data of the open version kept apart from the aerodynamics (blade layup or
  solid section; hub, nacelle and tower for wind turbines), structural run on a chosen aerodynamic run with
  sections, modes, Campbell diagram, deflection, aeroelastic Cp–λ, 3-D turbine and mode view. API under
  `/api/v2/simulations/{id}/structure`.
- Steady aeroelastic Cp–λ: the BEMT runs on the deformed blade (cone, in-plane radius, elastic twist about the
  elastic axis) and is iterated with the rotating 3-D beam; default model of *Cp–λ flexible & sheared*.
  Checked against OpenFAST AeroDyn + ElastoDyn. Blade structures accept `elastic_axis_offset_m`, filled by
  the layup block.
- Mode view: a full-screen view over the Workflow canvas, opened with the *Modes* button on any block with a
  modal result (on the node, in its result card and in the run summary). Mode list and participation, the
  Campbell diagram or the mode table, and an animated 3-D turbine (tower, nacelle, rotor) showing the
  selected mode; coupled modes carry their physical shape, so whirl modes show the phase lag between blades.
- Rotor–tower coupled Campbell diagram (`coupling: mbc`): tower modes and each blade's rotating-frame
  modes coupled through the hub kinematics, multi-blade coordinates and azimuth averaging (MBC3);
  collective, backward- and forward-whirl modes in the fixed frame. Template `coupled_campbell`.
- *OpenFAST linearisation* block: structural linearisation of a flexible ElastoDyn case, `.lin`
  parsing, MBC3 and a mode-by-mode comparison with the coupled Campbell diagram.
- Block results show the Campbell diagram (hover readout, selectable curves, crossings, operating
  speed), animated mode shapes, coupled-mode participation and the OpenFAST comparison table.
- *Performance map* (progressive refinement and response surface), *Cp–λ flexible & sheared* (wind
  shear and steady blade deflection) and *Operating strategy* blocks.
- *Annual energy*, *Turbine cost (NREL CSM)* with LCOE, and the *Design*, *Pareto (NSGA-II)* and
  *Multi-fidelity* optimisers, which re-run the downstream blocks for every candidate so any computed
  quantity can be an objective or a constraint.
- *Blade layup* (thin-walled sections to a blade structure) and *Blade shell modes* through a new
  CalculiX adapter (external, not bundled).
- Wind-farm blocks (*Farm turbine*, *Farm layout*, *Wind climate*, *Wind farm AEP*) with a native NOJ
  model or PyWake, and a DUST adapter with the *DUST rotor* block (external, not bundled).
- Control blocks on named signals (sources, PI/PID, kω² torque law, schedules, transfer function,
  state space, rotor–drivetrain plant, simulation) and FMI 2.0 co-simulation FMUs through optional
  FMPy. Templates `rotor_economics_chain`, `lcoe_optimization`, `wind_farm_aep`, `turbine_control`.
- Structural-dynamics blocks without aerodynamics on a 3-D coupled beam (Timoshenko,
  six degrees of freedom per node, spectral elements as in BeamDyn): *Blade modes
  (clamped)*, *Blade modes (rotating)* with centrifugal stiffening, spin softening,
  Coriolis and propeller-moment terms, *Tower modes* with the nacelle and parked
  rotor as rigid bodies at the top, and *Campbell diagram* with 1P/BP/2BP lines,
  crossings, MAC mode tracking and the smallest excitation margin at the operating
  speed. Flap, edge, torsion and axial modes are coupled through structural twist
  (aerodynamic twist by default) and centre-of-mass offset. *Point mass* and
  *Spring & damper* blocks chain onto them. *Blade structure* and table *Tower*
  accept optional columns (EA, GJ, GA, rotary inertias, twist, offset); tubular
  towers derive them from the material. Template `structural_campbell`.
- BLAS libraries run on one thread in the desktop backend, CLI and Docker image:
  at Nova's matrix sizes extra threads only slow the solution and load every core.
- Flexible OpenFAST models from blocks: *Hub*, *Nacelle & shaft*, *Tower* (tubular
  or table) and *Blade structure* blocks feed *OpenFAST case from rotor*, which
  then writes a full ElastoDyn case at prescribed rotor speed. Mode shapes are
  computed by Nova from the mass and stiffness distributions (finite-element
  beam, checked against analytic frequencies) and fitted to the ElastoDyn
  polynomial form. Missing data are named and block the case; assumptions and
  modal frequencies are reported. Template with the NREL AOC 15/50 structural
  data as an editable example. Station tables accept pasted spreadsheet columns.
- Different sections along the blade span: Design → Geometry (*Sections along
  the span*), the `sections` setting of the HAWT and propeller blocks and the API.
  Polars are evaluated at the local Reynolds number and blended linearly in r;
  OpenFAST cases carry each station's blended polar.
- Template nodes now carry every setting at its default, so all of them are
  editable; the template auto-layout no longer overlaps wrapped rows.
- *OpenFAST case from rotor* block: writes a rigid-rotor OpenFAST 5 case
  (Simplified ElastoDyn with prescribed speed and pitch, AeroDyn BEMT, steady
  InflowWind) from a Nova horizontal-axis rotor, using Nova's own polars at each
  station's Reynolds number, and feeds *OpenFAST run*. It also emits Nova's BEMT
  result for the same rotor. Template *OpenFAST rigid rotor vs Nova BEMT*. On
  the default 5 m rotor at 8 m/s, TSR 7, OpenFAST 5.0.0 gave power −1.1 %,
  thrust +0.1 % and torque −1.1 % against Nova's BEMT. No structure, tower or
  controller is modelled; other rotor families are rejected.
- Settings replaces the Integrations workspace in the rail (gear at the bottom,
  `Ctrl ,`, header menu): OpenFAST and PyWake paths and detection live in
  Settings → Integrations, plus the shortcut list. Cases, output import and
  external archives stay reachable from there until they move into Workflow.
- F11 toggles full screen (Tauri window or browser Fullscreen API; also in the
  header menu). The desktop capability gains the set/is-fullscreen permissions,
  so a rebuilt desktop package is needed for it.
- Block workflows run in the background (`POST /api/v1/blocks/runs`) with
  progress, OpenFAST log lines and cancellation; Ctrl Enter runs or cancels.
  The OpenFAST run block selects the configured executable, or links to Settings.
- OpenFAST in Workflow: *OpenFAST case* and *OpenFAST run* blocks run a
  self-contained case with the configured executable and expose channel
  statistics to constraints and reports (template *OpenFAST run with limits*).
- Workflow screen is canvas-first: the Project graph and the mode bar are gone;
  blocks are added with a double-click or Ctrl K search, settings open in a
  rounded card beside the block (closed when dragging), and run, validate,
  save, templates, auto-layout, fit and shortcuts float over the canvas.
  Saved workflows can be reused as templates.
- Design sheet replaces the stage bar: Sizing, Geometry, Analysis and Results
  are stacked sections of an accordion (one open at a time; the others compact
  to a title, summary and status dot) with an always-visible latest-run card.
- Nova opens on Library. The header keeps one Project and one Version selector.
- Versions: every simulation has an ID `major.minor.patch`. After a run its
  geometry is locked (speeds, models and conditions stay editable); New version
  copies it as the next patch, editable again
  (`POST /api/v2/simulations/{id}/new-version`, `version` and `locked` fields).
- Air propeller corrections in Analysis: tip and hub loss (Prandtl or none),
  Viterna–Corrigan extension of imported polars beyond their sampled incidence,
  forward speed (advance ratio, propulsive efficiency) and an upstream wake.
- Rotor corrections: Du–Selig stall delay, Øye dynamic stall, and an upstream
  rotor or body wake (Jensen or Gaussian) averaged over the disk.
- Resolved inflow for axial rotors (`inflow` in the rotor specification): the
  BEMT is solved at every blade azimuth with yaw/inclination and Glauert skewed
  wake, wind shear, tower shadow, a partial upstream wake and Øye dynamic stall;
  results add blade and rotor load against azimuth. Uniform inflow reproduces the
  axisymmetric solver exactly.
- Run opens a model chooser every time (several models for the air propeller,
  one streamtube model for VAWT, BEMT for HAWT and marine).
- Comparisons workspace: runs from any project overlaid, baseline deltas,
  input differences with an attribution warning, saved comparisons.
- Sweep lens for rotor-engine designs with limits, VAWT refinement with a more
  complete model, adopt-into-design and open-as-block-workflow;
  `POST /api/v1/rotors/sweep`.
- New NOVA logo and app icon (dashed-O wordmark), orange throughout.

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
