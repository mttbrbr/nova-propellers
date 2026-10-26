# Project, simulation and execution context

NOVA distinguishes four objects:

| Object | Purpose | Persistence |
| --- | --- | --- |
| Project | Named container for configurations, assets and executions | Stable ID and revision |
| Geometry | Shared baseline rotor definition within a project | Immutable, explicitly selected revisions |
| Simulation | Named native configuration: geometry inputs, workflow/models, polars and operating conditions | Separate ID and revision within its project |
| Execution | One evaluation of a saved configuration | Immutable inputs, results, model and configuration revision |

A propeller project can contain, for example, a BEMT baseline at 5000 rpm and
an LLT comparison at 6500 rpm. Editing either configuration does not overwrite
the other. Repeating an unchanged simulation creates another execution without
incrementing its configuration revision. Changing and saving its configuration
creates a new revision; earlier results retain their original snapshot.

## Shared geometry and comparison semantics

Solver variants can reference the same geometry revision. RPM, thrust target,
fluid properties, polar selection and solver settings belong to the analysis;
diameter, blade count, airfoil, geometry method, curve parameters and frozen loft
coordinates define the baseline rotor geometry. Editing that definition creates
a new immutable revision. Adoption by other simulations is an explicit operation
on selected configurations, with revision-conflict checks; past executions stay
unchanged.

The reference identifies **baseline input geometry**. An advanced actuator-disk
sizing node can derive a different diameter, a diameter sweep evaluates variants,
and optimization produces candidate geometry. Their evaluated geometry and hashes
remain in results; those operations do not silently replace the shared baseline.

## Interface

The persistent context bar identifies the open project, selected simulation,
saved/draft/modified status and models configured in the actual graph. With no
saved project selected, it explicitly says **No project open** and identifies
the unsaved propeller draft. Project and simulation selectors remain available
when the contextual panel is hidden.

The persistent header provides **Save** and **Run simulation**, changing to
**Cancel** while a native execution is active. Save stores the current simulation
and creates/renames its project when necessary. Project actions groups New/Close,
Open `.nova` and Export **saved** project `.nova`; exporting does not imply that
unsaved edits were committed. Native controls are hidden in standalone Integrations.

New simulation keeps the selected published geometry and resets analysis settings
to defaults. Duplicate simulation copies the current draft into a separate
configuration without overwriting its source. Switching projects/configurations,
creating a fresh simulation and closing a project protect unsaved edits with
Save changes / Discard changes / Keep editing. The first execution saves its
initial project/configuration; running a configuration does not silently replace
the project's default geometry/workflow.

In Geometry, Publish geometry revision creates an immutable baseline definition.
Apply revision to saved simulations lists explicit checkbox targets. A geometry
revision selector lets each configuration use the desired saved revision.
Save and Run simulation publish edited linked geometry as a new immutable
revision for the current configuration only. Other configurations adopt it only
through explicit selection. Publish geometry revision also supports preparing
a revision independently of saving the current simulation.

Workflow retains the central canvas and contextual inspector. Customize workflow
enables editing the default graph, Add block is a compact menu, graph validity
and execution order/errors are visible, and logs are collapsible. Execution uses
the persistent header rather than a duplicate graph toolbar command. The old
propeller database remains available as a clearly identified legacy library.

Opening a project selects its most recently saved simulation when one exists;
older projects with no simulations open their existing configuration as a draft.
Close project returns to an unsaved draft while preserving stored configurations
and results. Model selection in guided analysis updates the graph that executes;
custom multi-model graphs are configured through their node inspector.

Executions in this project lists named analyses, model/RPM, status, timestamp
and execution ID. Viewing a stored result identifies the simulation/revision and
actual model used, independently of the configuration currently being edited.
The geometry footer uses the displayed geometry's dimensions. Late geometry,
configuration and study responses are guarded against project/view changes.

Studies and optimization execute from saved simulation configurations and retain
the same lineage. Study case inspection forwards its simulation context. An
optimizer's explicitly selected solver is recorded independently of the graph's
analysis model. Imported/legacy results do not inherit a previous execution's
caption.

External integrations remain standalone operations and are explicitly labeled
as not linked to the active propeller project. Wind-farm project containers
remain subsequent work; portable standalone `.nova-run` result archives are
described in `EXTERNAL_INTEGRATIONS.md`. This increment does not attach
incompatible physical cases to a rotor project implicitly.

## Storage and APIs

The additive SQLite record kinds `simulation` and `geometry` use the existing
library. No destructive migration or numerical solver changes are required.
Geometry records have a project-scoped family ID and immutable revision number,
definition, content hash and canonical geometry snapshot/hash. Configurations
retain complete input snapshots plus explicit geometry references. Saving older
configurations without references links their geometry additively; changing the
project default does not rewrite saved cases.

- `GET /api/v1/projects/{id}/simulations`
- `GET /api/v1/simulations/{id}`
- `POST /api/v1/simulations`: configuration, `project_id`, optional `id` and expected revision.
- `POST /api/v1/simulations/{id}/clone`
- `POST /api/v1/simulations/{id}/run`
- `POST /api/v1/simulations/{id}/study`
- `POST /api/v1/simulations/{id}/optimize`
- `GET /api/v1/projects/{id}/geometries`
- `POST /api/v1/projects/{id}/geometries`: name, full inputs, optional geometry family ID and expected latest revision.
- `POST /api/v1/projects/{id}/geometries/{geometry_id}/adopt`: geometry revision and selected simulation IDs with expected configuration revisions.

Execution endpoints accept an expected simulation revision. Conflicting edits
return 409. Configurations cannot be moved to another project through an update.
Executions store `simulation_id`, `simulation_name`, `simulation_revision` and
`project_revision`, alongside their frozen scientific inputs/results.

`.nova` archives include optional `simulations` and `geometries` arrays,
configurations' assets and historical run links. Import validates all records
before an atomic write, remaps project/asset/simulation/geometry IDs, and retains
configuration and geometry revisions. Older archives without these records
remain importable. Named configurations
require this updated application to retain their complete functionality.

The project explorer exposes saved configurations, geometry revisions, referenced
data and native execution history from these same records. Strict solver
comparisons now snapshot 2–8 saved configurations into one batch; matching
geometry/conditions and expected revisions are checked before submission.
Comparison rows, nested frozen source records and case inspection survive
archive remapping. One/two-axis studies retain actual case conditions separately
from their baseline configuration. See `STUDIES_AND_ADAPTERS.md` for limits.

## Verification

Backend tests cover two models in one project, repeated runs, clone/edit
isolation, conflicts/ownership, historical assets, archive round trips, legacy
archives and saved-configuration study/optimization lineage. The complete suite
passed 80 tests (78 passed, two optional real-PyWake tests skipped because the
separate temporary environment was no longer available). Earlier real PyWake
2.6.20 tests and its browser journey passed before that environment reset;
external adapter algorithms are unchanged. Shared-geometry checks additionally
cover immutable snapshots, selected adoption/conflicts, loft source remapping,
derived sizing/study provenance and arbitrary-diameter station serialization.

Frontend verification:

```sh
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend run test:simulations
npm --prefix frontend run test:comparison
npm --prefix frontend run test:studies2d
npm --prefix frontend run test:external-archives
```

The simulation journey verifies independent configurations, unchanged baseline
revision, repeated executions, restored models, historical result captions,
close/reopen, selected geometry adoption, automatic publication through Save,
duplication of edited geometry, responsive unique commands and delayed study
responses/cancellation across workspace/project switches. Frozen backend smoke
additionally checks shared revisions, named model variants and archive ID remapping.
