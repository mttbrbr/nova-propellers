# Studies and external adapter framework

NOVA now runs parameter sweeps and inverse optimization through its existing
isolated job coordinator. Numerical equations remain in the current Python
solvers; studies call the same workflow engine as Guided and Advanced modes.

## Studies

The Studies workspace supports one-axis sweeps of RPM, diameter, density or
viscosity, with 2–32 distinct positive values. An optional distinct second axis
creates a Cartesian grid, bounded to 32 total cases and 128 analysis evaluations.
The default remains a one-axis sweep. Both axes use the same case generator,
workflow engine, checkpoints and cancellation as ordinary analyses.
Geometry defaults are resolved at the baseline and frozen before case generation.
Viscosity sweeps require a BEMT node. LLT, VLM and BEM use constant drag
approximations and are insensitive to viscosity, including in mixed workflows.
Diameter changes keep geometry controls fixed, while existing chord/twist limits
still apply; applied limits are retained in geometry metadata and run warnings.
Ideal sizing must be changed to manual sizing before sweeping diameter, because
otherwise it would overwrite the sweep values.

Each case retains its parameter value, effective inputs/conditions, hash, results
or failure diagnostics. Failed cases remain in tables/CSV and are excluded from
performance curves. Partial failures are explicitly labeled. Completed cases
are checkpointed; cancelling or recovering an interrupted job retains those
cases. Archive import validates counters, completeness, scientific units and
successful analysis outputs before committing records.

The workspace plots thrust against actual parameter coordinates for one axis;
two-axis studies use a discrete result matrix with analysis-node and quantity
selectors. Missing/failed cells retain status without fabricated values or
interpolated surfaces. A cell opens its exact frozen input/condition pair.
`GET /api/v1/runs/{id}/study.rows` supplies normalized rows and axis metadata;
two-axis CSV includes both values and units. Legacy one-axis archives retain
their original representation.

The workspace opens individual
case reports/STL, exports CSV and compares 2–8 stored runs. Comparison rows retain
model fidelity, airfoil/polar source, RPM, density, viscosity and diameter. The
initial comparison scope is static rotor results with compatible native units.
It does not convert different reference frames or imply predictive qualification.

### Compare saved solver configurations

The guided solver-comparison panel selects 2–8 saved simulations in one project,
with an explicit reference configuration. Validation requires the same evaluated
geometry, RPM, target thrust, density and viscosity. BEMT cases require matching
scientific polar content; other native approximations explicitly report that
they do not consume imported polars. Saved revision conflicts return 409 and
require refreshing the selection.

Submission creates one queued batch containing immutable source snapshots.
Each case retains its owner, revision, input hash, outcome and diagnostics.
Percentage differences are computed by the backend from successful retained
results; zero/failed reference values yield null with an explicit reason. This
is an application comparison, not numerical validation against measurements.

Initial scope: guided manual-geometry graphs with one analysis each. Materialize
automatic sizing before comparing; other graphs continue to run normally.
`POST /api/v1/projects/{id}/comparisons/validate` and `/comparisons` accept
`{name, simulations: [{id, expected_revision}, ...]}`. Results export through
`GET /api/v1/runs/{id}/comparison.csv`; cases have individual STL/report inspection.
Project archives preserve and remap nested source references and history.

Queued inverse design retains the existing SciPy optimizer and explicit
apply/discard interaction. Its candidate geometry is now built through the same
canonical geometry service used when applying it. Nonconverged baselines are
withheld; final BEMT candidates must converge. Optimizer convergence is reported
separately from aerodynamic convergence.

Headless studies:

```sh
cd backend
python -m nova.cli study project.json > study-result.json
```

The document contains the ordinary workflow/inputs/conditions/frozen polar asset
and `study: {"parameter": "rpm", "values": [3500, 4250, 5000]}`. An all-failed
study emits its diagnostics JSON and exits unsuccessfully.
For two axes add `"secondary": {"parameter": "air_density_kg_m3",
"values": [1.1, 1.225]}` inside `study`.

## Adapter SDK

`nova.adapters` provides explicit descriptors and registration, configuration,
version probing, validation, preparation, process execution, collection and
normalization. Adapters declare scientific input/output ports and supported
execution environments. They remain independent of FastAPI and the GUI.

A prepared case contains 1–8 sequential process stages, relative input files and
expected outputs. This supports a future preprocessor → solver → postprocessor
adapter without adding numerical coupling to the DAG engine. Each invocation
has an isolated case directory, manifest, generated/raw inputs and outputs,
file hashes, stage commands, exit status, timing and bounded UTF-8 logs.
Failures retain manifests/logs and identify the active stage.

The common runner uses argument arrays with no shell, timeout/cancellation and
process-group cleanup. It preserves a selected virtual-environment interpreter
path, restores host library search paths when launched by PyInstaller, and removes
the private desktop API token and bundled Python environment from child processes.

`/api/v1/adapters` lists registered adapters. Probe/configure endpoints validate a
selected executable/environment and store machine-local configuration separately
from portable projects. The Integrations workspace exposes these capabilities.
PyWake and OpenFAST adapters are now registered; the external programs are not
bundled. See `EXTERNAL_INTEGRATIONS.md` for setup, supported cases and qualification
limits. DUST remains later work. Fixture adapters are never registered in production.

## Verification and limits

Tests compare sweep cases with direct workflow evaluations, retain failures and
cancelled checkpoints, recover interrupted studies through archive round-trips,
and verify that an applied optimization candidate reproduces its prediction.
Process fixtures cover multiple stages, missing outputs, nonzero exits, timeout,
closed-stream cancellation, descendant cleanup, selector setup failure, bounded
UTF-8 logs, literal arguments, token isolation and virtual-environment selection.
The Chromium journey includes study execution, comparison, case inspection,
CSV export and integration availability.

General design-of-experiments beyond two axes, derivatives/sensitivity metrics, arbitrary
scripts in graph nodes, distributed execution, iterative coupling and additional
scientific tool adapters remain subsequent work. An execution fixture is not
an engineering solver.
