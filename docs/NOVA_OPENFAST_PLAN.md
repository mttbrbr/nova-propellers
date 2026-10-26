# Multidisciplinary projects and OpenFAST development plan

Accepted direction: 2026-10-22. Implementation lead: Astra.

NOVA will support propeller, OpenFAST and PyWake simulations inside one project.
The first delivery is a working mixed project, followed by the turbine editor
and creation of a terrestrial turbine from scratch. Tauri, FastAPI, the SQLite
library, existing DAG engine and isolated execution coordinator remain the base.

## Data and interaction contracts

- A project is a named multidisciplinary container and can exist without rotor
  geometry. Simulations identify their scientific kind and retain independent
  revisions, workflows and references to immutable assets.
- An execution retains its actual input snapshot, configuration revision,
  software identity, results and provenance. Attaching a historical standalone
  execution uses an association; it does not rewrite the execution.
- OpenFAST case assets own inspected, contained input snapshots. Editing the
  original directory after saving cannot change a saved simulation.
- Additive v2 project/simulation APIs share application services and job
  execution with v1. Existing propeller configurations remain readable.
- A new mixed project archive version carries scientific assets and results,
  imports previous native archives, remaps identities, and excludes executable
  installations and controller binaries. Missing data/configuration is explicit.
- One persistent project/simulation/model context and Save/Run/Cancel command
  set applies across scientific kinds. Workflow keeps the central graph editor;
  guided forms and the graph configure the same executable document.
- Integrations manages local software and environments. Existing standalone
  cases/results stay accessible while project analysis moves into its context.

## Ordered deliveries

| Phase | Deliverable | Acceptance | Size |
| --- | --- | --- | --- |
| 1 | Neutral projects, typed simulations and saved OpenFAST cases | One project holds native, OpenFAST and PyWake configurations; revisions and clones are independent | L |
| 2 | Shared UI context, execution, results and portable mixed archives | Create, save, run, reopen and export a mixed project from the desktop | L |
| 3 | Version-aware OpenFAST editor over imported cases | Supported forms/tables create a new revision; untouched files and source cases stay intact | XL |
| 4 | Terrestrial turbine creation from scratch | Generate complete OpenFAST 5.0.0 inputs from an explicitly complete three-bladed turbine model | XL |
| 5 | Advanced external preparation and execution | Qualified BeamDyn, turbulent wind, composite/modal preparation and ROSCO tuning paths with provenance | XL |
| 6 | OpenFAST comparisons and bounded studies | Reproducible multichannel plots, interval statistics, configuration comparisons and parameter studies | L |

Each phase depends on the previous phase and is split into runnable increments.
Implementation status must be recorded against verified acceptance checks;
planned capabilities must not be presented as available controls.

## Turbine editor and external tools

The editor will describe geometry, aerodynamic data, structure, materials,
laminates, operating conditions and outputs. Initial native file generation
targets OpenFAST 5.0.0 onshore horizontal-axis, three-bladed turbines with
ElastoDyn, AeroDyn, InflowWind and ServoDyn. Advanced support adds BeamDyn,
turbulent inflow and independently installed controllers.

Readers/writers are specific to supported formats and versions. Unknown sections
are preserved and explicitly unavailable to guided editing. Missing engineering
data blocks generation rather than receiving invented physical properties.

The user explicitly chose existing specialist tools for scientific preparation.
NOVA provides forms/tables, launches configured tools, captures diagnostics and
explicitly acquires their outputs as new revisions. Tools retain their native
connections and formats: OpenFAST loads its controller through ServoDyn; ROSCO
Toolbox prepares tuning from the model and required rotor-performance tables;
compatible specialist preprocessing supplies composite properties and modes.
SONATA/ANBA4 is the planned composite preparation path, not a bundled solver or
a new NOVA scientific stack. Each external path requires its own compatibility
qualification before being marked supported.

Local executable and controller paths are separate from portable scientific
configuration. Execution resolves declared dependencies in a private working
directory, records their hashes and preserves originals. Export does not include
OpenFAST, other scientific programs or controller libraries.

## Verification and release gates

- Native v1 project/simulation/archive compatibility, including historical runs.
- Mixed project save/clone/revision conflicts, input snapshot isolation and
  immutable historical-run associations.
- Archive limits, references, hashes, rollback, original scientific artifacts,
  installation exclusion and explicit missing-data handling.
- UI context, dirty transitions, asynchronous response isolation and cancellation.
- OpenFAST read/write preservation and module input completeness; no unsupported
  version conversion or silent quantity reinterpretation.
- Real OpenFAST direct-versus-NOVA execution for each supported configuration,
  independently from physical model validation.
- Separate qualification for ElastoDyn, BeamDyn, turbulent inflow and ROSCO.
- Arch build, frozen backend, installed desktop launch and shutdown.

The existing local OpenFAST 5.0.0 AOC qualification (101 samples by 30 channels,
zero direct-versus-NOVA difference) is an execution baseline. It is not physical
validation of the model or evidence for untested OpenFAST modules.

Before persistence changes, preserve the existing library/package for rollback.
No destructive conversion, scientific algorithm migration or host application
installation is implicit in a development check.

Offshore models, automatic OpenFAST–PyWake coupling, CFD and C++ migration remain
outside this cycle. Shared project membership does not imply compatible physics.
