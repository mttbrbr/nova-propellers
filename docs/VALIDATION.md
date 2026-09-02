# Solver verification and validation

## Purpose and claim boundary

This document defines how Nova collects evidence about its numerical results.
It deliberately distinguishes software verification from validation against
physical measurements. Passing the current suite means that a supported build
reproduces the declared baseline and satisfies the implemented consistency
checks. It does **not** mean that a propeller prediction is experimentally
validated, certified, safe to manufacture or suitable for flight.

Nova uses the following evidence levels:

| Level | Question | Evidence | Current BEMT status |
| --- | --- | --- | --- |
| Contract verification | Is a result complete and unambiguous? | Versioned models, units, convergence and warnings | Implemented |
| Numerical regression | Did the implementation change unexpectedly? | Deterministic golden cases with tolerances | Implemented for one baseline |
| Physics consistency | Do related outputs satisfy required identities and trends? | Invariants and parameter sweeps | Initial set implemented |
| Reference validation | Does the solver agree with independent measurements? | Licensed experimental datasets and declared error metrics | Not implemented |
| Qualification | Is accuracy acceptable over a stated operating domain? | Multiple datasets, thresholds and release evidence | Not achieved |

The UI and method registry must continue to label BEMT as `preliminary` until
the reference-validation and qualification requirements are met.

## Process followed by Nova and why

Nova follows a gated verification-and-validation process. The order is
intentional: a comparison with measurements is not meaningful until the
software produces traceable, internally consistent and reproducible results.

```text
Result contract
    -> software regression checks
    -> physics-consistency checks
    -> numerical sensitivity studies
    -> comparison with independent measurements
    -> qualification over a declared operating domain
```

Each gate answers a different question and prevents a different class of
mistake:

1. **Define the result contract.** Inputs, outputs, units, solver version,
   warnings and convergence are made explicit. This comes first because an
   apparently accurate number is unusable when its meaning or provenance is
   ambiguous.
2. **Freeze deterministic regression cases.** Golden cases reveal unintended
   changes in code, dependencies or numerical behavior. They are established
   before experimental tuning so that implementation changes remain visible.
3. **Check physics and accounting invariants.** Conservation between radial
   and global loads, `P = Q omega`, finite values and expected trends expose
   defects that a single measured point can hide through error cancellation.
4. **Study numerical sensitivity.** Station count, iteration tolerance and
   interpolation choices must be varied. This separates discretization and
   convergence error from aerodynamic-model error.
5. **Validate against independent measurements.** Predictions are compared
   with traceable experimental data across an operating sweep, not only at one
   favorable point. This is the first stage that provides evidence about
   physical accuracy.
6. **Qualify a bounded domain.** A solver can be promoted only if predeclared
   metrics pass on more than one geometry and on data not used for tuning. The
   resulting claim applies only to the tested ranges of geometry, Reynolds
   number, RPM and advance ratio.

The process is deliberately cumulative. A later gate does not replace an
earlier one: agreement with one experiment cannot excuse a violated power
identity, and a stable golden case cannot demonstrate agreement with reality.

### Calibration, validation and held-out evidence

If empirical constants or corrections are introduced, available reference
points are divided by purpose:

- **calibration data** may guide model parameters and correction choices;
- **validation data** measure error after the choices are frozen;
- **held-out data** are not inspected during tuning and provide the strongest
  available check against overfitting.

The split, random or deterministic selection rule, and every tuned parameter
must be recorded before final evaluation. Nova will not report an accuracy
claim obtained by tuning and evaluating on the same points without clearly
labelling it as calibration performance.

### Evidence and decision records

Every validation case must retain machine-readable inputs, expected or
measured outputs, units, provenance, transformation notes and tolerances. A
validation report must also record the Nova version, result-schema version,
solver configuration and pass/fail criteria. This makes the conclusion
repeatable and allows a future release to explain why a result changed.

Passing checks never promotes a solver automatically. A maturity change is a
reviewed project decision accompanied by updated documentation, limitations
and release notes.

## Canonical result contract

`backend/validation/contracts.py` defines schema version `1.0`. An analysis
result records:

- solver identity, software version and maturity;
- RPM, angular velocity, density and axial velocity;
- thrust, torque, power and efficiency with declared units;
- convergence state, iteration count, residual, tolerance and termination;
- warnings and radial station results.

The contract validates that a converged result has a residual below its
tolerance. It also checks that the legacy `summary` values agree with the
canonical `performance` block. The legacy block remains temporarily available
for alpha project files and the current frontend.

### Saved convergence diagnostics

BEMT analysis results include a compact diagnostic record inside
`convergence.diagnostics`. It contains the classification, relaxation factor,
initial and final residuals, reduction ratios and a sampled residual history.
The history retains the first iteration, every fifth iteration and the final
iteration. Each sample separates axial and tangential induction residuals and
identifies the radial position of the limiting component.

Each retained sample also records the limiting station's angle of attack,
Reynolds number, inflow angle, Prandtl loss factor, section coefficients and
polar-grid context. The context identifies the active angle and Reynolds
interpolation segments and whether either input was clipped to the available
polar domain. This supports diagnosis without treating interpolation bounds as
the cause before evidence is collected.

The classification is diagnostic rather than a new convergence criterion:

- `converged`: the declared residual tolerance was reached;
- `stagnation`: the recent residual window changes by less than 2%;
- `oscillation`: the recent residual repeatedly changes direction;
- `slow_convergence`: the residual falls overall but misses the tolerance;
- `divergence`: no overall reduction is observed.

Diagnostics also retain whether relaxation was `fixed` or `adaptive` and its
initial, final, minimum and maximum factors. Adaptive relaxation remains an
experimental validation option and is not used by normal analyses.

These fields are returned by the analysis API and therefore saved with the
analysis inside a project bundle. The report workspace exposes them under
**Advanced diagnostics**, including a logarithmic residual chart and the
sample table. Older saved analyses remain readable and show a legacy or
unavailable diagnostic state.

Sampling keeps project files reasonably small. The full internal iteration
state is not retained because it contains radial vectors for every iteration;
that level of tracing should be enabled only in a dedicated developer run.

Schema versioning describes the result representation, not solver accuracy.
Any incompatible field or unit change requires a new schema version and a
migration policy for stored projects.

## Current BEMT verification case

The case `bemt-baseline-001` is stored as data in
`backend/validation/cases/bemt_baseline.json`. It uses:

- a 0.25 m, two-blade Bézier geometry with 18 radial stations;
- 5000 RPM, zero axial inflow and density 1.225 kg/m³;
- Nova's synthetic section-polar model;
- an internal result generated with Nova `0.1.0-alpha.2`.

Its purpose is `deterministic_regression`. Its expected thrust, torque and
efficiency are not experimental observations. The JSON file includes the
reference origin and tolerances so the evidence remains machine-readable.

The validation runner currently checks:

1. all global performance values are finite;
2. BEMT declares convergence and residual is below tolerance;
3. radial thrust contributions sum to total thrust;
4. radial power and global torque satisfy `P = Q omega`;
5. thrust increases between the declared low- and nominal-RPM points;
6. nominal results remain within the case's absolute and relative tolerances.

The golden values use a relative tolerance of 0.1% and an absolute tolerance
of `1e-5`. These are regression tolerances, chosen to detect implementation
changes while allowing insignificant floating-point variation. They are not
accuracy limits relative to reality.

## Numerical-sensitivity study

The declared study matrix is stored in
`backend/validation/cases/bemt_sensitivity.json` and executed by
`backend/validation/sensitivity.py`. It covers two geometries, three RPM
values, five radial discretizations and the supported tolerance range from
`1e-3` through `1e-5`. For each geometry and RPM, a separately declared
72-station, `1e-5` reference is used to measure numerical change. This
reference is a refined numerical result, not a physical truth value.

The current gate contains 90 matrix evaluations and six references. Its
acceptance conditions are:

- every matrix and reference evaluation declares convergence;
- thrust, torque and power on the 48-station grid differ by no more than 1%
  from the corresponding refined reference.

The current production configuration passes: all 96 evaluations and
references converge, and the maximum finest-grid relative difference is
`0.300291%`. Earlier diagnostic matrices that included `1e-6` remain useful
evidence, but that tolerance is outside the supported numerical domain. Three
36-station baseline cases settled near a residual of `4.32e-6` and did not
reach `1e-6`; increasing their iteration budget did not change that conclusion.
Nova therefore documents `1e-5` as the tightest supported BEMT tolerance rather
than claiming convergence below the observed numerical floor.

### Relaxation-strategy comparison

`backend/validation/cases/bemt_relaxation_study.json` defines a separate
comparison so relaxation behavior is not mixed with the grid-sensitivity
claim. It exercises 24 common cases for each candidate and requires both full
convergence and a maximum 0.5% performance change relative to the existing
fixed `0.08` behavior.

The first comparison produced:

| Strategy | Converged | Median iterations | Max performance delta | Eligible |
| --- | ---: | ---: | ---: | --- |
| Fixed 0.08 | 18/24 | 356.0 | 0.000% | No |
| Fixed 0.12 | 18/24 | 338.0 | 0.003% | No |
| Fixed 0.16 | 12/24 | 518.5 | 0.000% | No |
| Fixed 0.20 | 12/24 | 506.5 | 0.001% | No |
| Adaptive, initial 0.08 | 9/24 | 800.0 | 0.001% | No |

No relaxation strategy was recommended and the production relaxation remains
fixed `0.08`.
The experiment shows that simply increasing relaxation or reacting to the
global residual does not resolve the difficult cases. The small performance
deltas suggest the candidates approach similar states, but failed convergence
still prevents acceptance. The next diagnosis must examine which radial
station and polar interpolation segment limits the residual.

The radial/polar diagnostic pass localizes all six failures of the production
`0.08` strategy at the first interior station, `r/R = 0.1583`. All six use a
Reynolds number below the minimum polar-grid value and are therefore clipped;
their limiting residual is tangential induction. Higher fixed relaxation keeps
the failures at the same station, while the rejected adaptive strategy spreads
some failures to the next station. This is strong correlation, not yet proof
that clipping causes the convergence rate. The next controlled experiment must
compare the current clipped polar evaluation with a smooth, explicitly
documented low-Reynolds extrapolation while leaving geometry and convergence
criteria unchanged.

### Controlled low-Reynolds polar experiment

`backend/validation/cases/bemt_low_re_study.json` compares three treatments
while keeping geometry, fixed relaxation, iteration budget and tolerances
unchanged:

- `clip`, the production behavior;
- bounded linear extrapolation from the first two Reynolds levels;
- a bounded C1-smooth transition to a constant value below `Re = 15,000`.

The extended diagnostic criteria require 36/36 converged cases, less than 0.5% change
from `clip`, and bounded finite section coefficients. Results were:

| Treatment | Converged | Median iterations | Max performance delta | Coefficients valid |
| --- | ---: | ---: | ---: | --- |
| Clip | 33/36 | 314.5 | 0.000% | Yes |
| Linear extrapolation | 33/36 | 314.5 | 0.281% | Yes |
| Smooth transition | 33/36 | 314.5 | 0.192% | Yes |

Neither alternative improves the number of converged cases. After applying
the accepted tangential bound, the remaining strict-tolerance diagnostic
failures are axial-induction limited near `r/R = 0.1642`; their Reynolds
numbers remain far below the lowest polar level of 30,000 and outside a
credible aerodynamic-data domain. The experiment therefore rejects polar
clipping as the primary convergence cause and recommends no polar-production
change. The low-Reynolds alternatives remain study-only options.

The experiment did not justify changing the polar treatment. It led instead
to a controlled study of the tangential-induction bound near the hub.

### Root tangential-induction bound

The previous implementation allowed tangential induction to reach 95% of the
local rotational velocity. At the first interior annulus this collapsed the
relative tangential velocity, produced Reynolds numbers of roughly
1,100--2,500 and controlled the global residual.

`backend/validation/cases/bemt_root_induction_study.json` compares explicit
bounds while retaining the original 0.95 result as the performance baseline.
In the supported-domain gate, which includes 18, 48 and 72 stations, a bound
of 0.75 achieved 18/18 convergence, reduced median iterations from 353 to 312
and changed global performance by at most 0.054%. Bounds of 0.70 and 0.65 also
passed but were slower and changed results more; 0.50 exceeded the 0.5%
performance-change criterion. The 0.75 bound was therefore adopted.

An extended 72-station diagnostic revealed three axial-induction cases below
the unsupported `1e-6` tolerance, but all cases pass at the declared `1e-5`
limit. The production defaults are consequently:

- fixed relaxation factor `0.08`;
- maximum tangential-induction ratio `0.75`;
- clipped low-Reynolds polar behavior;
- supported convergence tolerance no tighter than `1e-5`.

This is a numerical robustness result, not physical validation of the
root-flow model. Root-region predictions still carry the low-Reynolds and
synthetic-polar limitations stated below.

Run the root-bound study with:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps \
  --user 1000:1000 backend python -m validation.root_induction_study \
  --output-dir /app/reports/bemt-root-induction
```

Run the experiment with:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps \
  --user 1000:1000 backend python -m validation.low_re_study \
  --output-dir /app/reports/bemt-low-re
```

Run the comparison with:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps \
  --user 1000:1000 backend python -m validation.relaxation_study \
  --output-dir /app/reports/bemt-relaxation
```

Run the study and create machine-readable and human-readable reports with:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps \
  --user 1000:1000 backend python -m validation.sensitivity \
  --output-dir /app/reports/bemt-sensitivity
```

The `reports/` directory is intentionally ignored by Git because timestamps
and timings depend on the execution environment. A release-validation report
intended as permanent evidence should instead be reviewed, checksummed and
added as an explicit release artifact.

## Consolidated code-verification report

The final pre-experimental gate is `backend/validation/verification_report.py`.
It executes the deterministic regression case, the supported numerical
sensitivity matrix and the root-induction selection study, then writes a
single JSON evidence record and a human-readable Markdown summary. The report
includes environment versions, configuration SHA-256 hashes, the supported
domain, every decision status and the explicit claim boundary.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps \
  --user 1000:1000 backend python -m validation.verification_report \
  --output-dir /app/reports/bemt-verification
```

The command exits non-zero unless all supported pre-experimental gates pass.
It intentionally excludes experimental accuracy metrics, which belong to the
next validation phase.

The reviewed evidence snapshot produced on 2026-09-02 is available as both
[Markdown](verification/bemt-pre-experimental-verification.md) and
[machine-readable JSON](verification/bemt-pre-experimental-verification.json).

For a specific application run, **Advanced diagnostics** shows separate total,
axial and tangential residual curves on a logarithmic scale. The same panel
can export a JSON record containing solver identity, operating point,
performance, units, warnings and the complete sampled convergence history.
Because analyses are stored inside project bundles, reopening a saved project
restores the same run-specific diagnostic evidence.

## Reproducing the checks

From the repository root, use the development Compose overlay so the checked
out source is mounted into the controlled Python environment:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps \
  backend python -m validation.runner

docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps \
  backend python -m unittest discover -s tests -v
```

A successful runner prints one `PASS` line per case. Any failed invariant or
out-of-tolerance value exits non-zero and must block a release until explained.

To run directly in a prepared Python environment:

```bash
cd backend
python -m validation.runner
python -m unittest discover -s tests -v
```

## Changing an algorithm or golden value

A golden update must never be an automatic response to a failed test. The
change should be reviewed in this order:

1. identify the code, dependency or platform change that altered the result;
2. check units, convergence and station-to-total conservation;
3. compare radial distributions, not only global values;
4. state whether the change fixes a defect, changes a model assumption or only
   affects numerical precision;
5. update the case's expected values and provenance in the same reviewed
   change;
6. record the user-visible or scientific impact in the changelog.

An unexplained baseline shift is a validation failure, even when the new result
looks plausible.

## Experimental-validation plan

The next evidence level requires an independent, reusable dataset. Candidate
data must be accepted only when the following metadata can be retained:

- permanent source identifier and license or reuse terms;
- propeller geometry and airfoil definition;
- dimensional reference conventions;
- RPM, advance ratio or inflow velocity, air density and test conditions;
- measured thrust and torque or power, including uncertainty when published;
- documented transformations from source data to Nova inputs.

Each imported dataset will live separately from internal golden cases and
carry a provenance record. Comparisons should report bias, mean absolute
percentage error and RMSE over a declared operating range. Acceptance limits
will be fixed only after dataset selection and before solver tuning against the
held-out evaluation points.

At least one dataset should be reserved from calibration. Otherwise the
comparison only demonstrates fit to the tuning data, not predictive evidence.

Before modifying BEMT to improve agreement, Nova will first capture the
unmodified solver's results as a baseline report. This prevents the reference
dataset from silently becoming both the target used to design a correction and
the evidence claimed to validate that correction.

## Known limitations

- The current baseline uses synthetic polars, so polar-model error is not
  separated from BEMT error.
- Only static axial operation is covered.
- The RPM trend contains two points and is a sanity check, not a performance
  map.
- Geometry, Reynolds-number and advance-ratio coverage are not yet sufficient
  to define a qualified domain.
- LLT, VLM and BEM are outside this validation increment.
- Floating-point reproducibility has been exercised in the project container;
  cross-platform tolerance evidence is still limited.

These limitations must accompany any technical report derived from the
current solver.
