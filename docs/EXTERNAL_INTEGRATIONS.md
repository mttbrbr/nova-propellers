# PyWake and OpenFAST integrations

NOVA includes integration code, not the external scientific programs. Neither
PyWake nor OpenFAST is a dependency of NOVA's bundled Python runtime. Configure
independently installed software in **Integrations**. The propeller workflow and
its aerodynamic implementations remain unchanged.

## PyWake

1. Create a separate Python environment and install PyWake there. The tested
   release is `py-wake==2.6.20`; the adapter checks the 2.6.x public APIs.
2. Select **PyWake**, enter the environment's `bin/python` path, detect it and
   save the configuration. Preserve this interpreter path, including its venv
   symlink; selecting the base interpreter loses that environment.
3. Enter turbine diameter/height, layout coordinates in metres, and a shared
   wind-speed/power/Ct curve. Power is in **W**, not kW. The provided UI curve
   is explicitly synthetic demonstration data.
   Use local Cartesian coordinates with x east and y north. Wind directions
   follow PyWake's meteorological convention: the direction the wind comes
   from, clockwise from north (270° blows towards positive x).
4. Enter wind directions, wind speeds, turbulence intensity and a matrix of
   joint probabilities: rows follow entered directions, columns follow speeds.
   Probabilities must sum to one; NOVA never silently normalizes them.
5. Run the case, inspect powers/effective wind speeds and per-turbine AEP,
   export CSV or reopen the persisted result.

The first adapter uses NOJ with `k=0.1`, flat terrain, no shear and a single
turbine type. Conditions are evaluated separately to preserve input ordering.
AEP is the sum of condition powers multiplied by the joint probabilities and
8760 hours/year. With/without-wake AEP uses the same distribution. Relative
wake loss is undefined (`null`) when the reference production is zero.
Power/Ct interpolation uses the selected PyWake implementation; conditions
outside the supplied curve coverage are rejected. No Weibull resource,
terrain import or farm-layout optimization is implied.

### Reusable case inputs

Select PyWake to use **Saved wind farm cases** even when PyWake is not installed.
Enter a name and notes, retain the demonstration-data label where appropriate,
and use **Save case copy**. Each save creates an immutable asset containing the
actual turbine curve, layout, discrete wind conditions and timeout, with a case
hash. The earlier saved copy remains unchanged. **Load saved case (replace
inputs)** explicitly restores those inputs without changing local software.

The preview uses equal scales on both axes, with x east/y north in metres;
turbine markers are schematic. Empty coordinates require completion and are not
silently converted to zero. In-session drafts, including selected local software,
survive workspace changes. Save a case copy before closing NOVA to retain its
scientific inputs; executable configurations remain separately managed.

`POST /api/v1/external-cases` accepts `{name, case, notes, demonstration}`;
`GET /api/v1/external-cases` lists saved PyWake cases and `GET .../{id}` restores
one. Saving validates the existing PyWake case contract without probing or
executing software. Cases contain no executable/environment configuration and
are not yet attached to a propeller project or automatically packaged with a
standalone result archive.

Limits: 128 turbines, 512 curve points, 8192 turbine-condition evaluations and
a configurable execution timeout of at most 3600 seconds.

Public interfaces and assumptions were checked against the
[PyWake turbine documentation](https://topfarm.pages.windenergy.dtu.dk/PyWake/notebooks/WindTurbines.html)
and [site documentation](https://topfarm.pages.windenergy.dtu.dk/pywake/api/Site.html).
PyWake is an optional MIT-licensed external program;
[its license](https://gitlab.windenergy.dtu.dk/TOPFARM/PyWake/-/blob/v2.6.19/LICENSE)
is separate from NOVA's integration code.

## OpenFAST output import

Import `.out` or `.outb` in Integrations without configuring or installing
OpenFAST. NOVA preserves raw bytes, SHA256, description, channel names and
original units. It supports ASCII output and little-endian binary IDs 1–4,
including packed time, compressed channels, uncompressed values and extended
channel names. Time must explicitly be in seconds and increase strictly.
The parser rejects malformed, truncated and nonfinite data.

Select a channel to inspect its actual time history and extrema. Plot sampling
is reduced for display; exported CSV preserves every sample. Unknown reference
frames and sign conventions remain explicitly unspecified. Import does not
infer the solver version or convert kW, degrees or other channel units to SI.

The HTTP import limit is 20 MiB. The parser's bounded limits are 100 MiB,
one million samples, 4096 channels and two million non-time values.

Binary decoding follows the
[official OpenFAST writer](https://github.com/OpenFAST/openfast/blob/main/modules/nwtc-library/src/NWTC_IO.f90).
An [official binary sample](https://raw.githubusercontent.com/OpenFAST/openfast_toolbox/main/openfast_toolbox/io/tests/example_files/FASTOutBin.outb)
was compared with the unmodified official reader: 201 samples × 10 channels,
zero difference across all time and channel values, matching names. Its
SHA256 is `d787c2cbdd31a98abb2d475c85a41a86220550f752eed7b399a97db9558f4a8f`.
The sample and reader are validation resources, not bundled solver code.

## OpenFAST case execution

Before running, **Inspect OpenFAST case** lists the selected input files, byte
counts and SHA256 fingerprint without requiring an executable. Changing case
paths, expected output or timeout clears the displayed inspection; a delayed
response cannot validate newer inputs. This is a bounded filesystem inspection,
not an OpenFAST syntax checker or numerical qualification. Submission validates
and snapshots the files again, so an earlier inspection cannot authorize changed
files implicitly.

Select a local executable, detect its version with the documented `-v` flag,
and save the configuration. Follow the
[official installation guide](https://openfast.readthedocs.io/en/main/source/install/index.html)
for the independent software installation.

Supply a complete case directory, a relative `.fst` input and expected relative
`.out`/`.outb` output. NOVA snapshots input files before queueing, verifies their
hashes, prepares an isolated execution directory and invokes the executable
without a shell. Editing original files after submission does not alter that
run. Existing `.out/.outb` files are excluded so stale results cannot satisfy a
successful execution. NOVA does not generate, upgrade or patch OpenFAST cases.

Cases must be self-contained: no symlinks, absolute/outside file references or
special files; at most 1000 files and 100 MiB. Relative paths within the selected
case are preserved. External controller/library dependencies must already be
available to the installed solver; NOVA does not bundle them. Timeout is at
most 3600 seconds. OpenFAST is licensed Apache-2.0 independently of NOVA.

Version detection establishes executable availability, not compatibility of
every OpenFAST module/case. On 2026-10-21, an independently built OpenFAST
**5.0.0** completed the shortened official `AOC_WSt` case through both NOVA's
source and rebuilt frozen desktop backend. In each check, a separate direct
execution of the same inspected inputs produced
identical time vectors, channel metadata and all values: **101 samples × 30
channels**, 0–5 seconds, maximum absolute difference **0**. The input hashes and
portable result export/import, including original output bytes, also matched.
This qualifies that execution path, not other cases or turbine physics. The
official case explicitly describes many parameters as fictional; startup also
reports low tip-speed ratio with BEM temporarily disabled. File-format
compatibility has separately been checked against the official reader/sample
described above.

### Local installation used for qualification

The independently installed workstation executable is
`~/.local/share/nova-external/openfast/5.0.0/bin/openfast`. Enter its expanded
absolute path in **Integrations → OpenFAST**, detect it and save the local
configuration. The prepared case directory is
`~/.local/share/nova-external/openfast/5.0.0/cases/aoc-steady`, with relative
input `AOC_WSt/AOC_WSt.fst` and output `AOC_WSt/AOC_WSt.outb`.
Select the `aoc-steady` directory rather than its `AOC_WSt` child: the sibling
`AOC` directory contains referenced model data. Inspect the case before running.

The source tag is `v5.0.0` (commit
`2895884d2be01862173c88d70f86b358d2f1a50a`), with matching official r-test
commit `dd5feaaaa500ba7283140107806300d551cff0a7`. Only `TMax=5`, `TStart=0`,
`OutFileFmt=3` and `Echo=False` were changed in the prepared input; untouched
originals, hashes, compiler settings, shared-library inspection and logs are
preserved under the external installation's `qualification/` and `reference/`
directories. The executable depends on this host's Fortran/BLAS/LAPACK runtime;
it is a local test installation, not a portable NOVA artifact. NOVA's package
installer neither downloads nor installs this program or its cases.

## Workflow and persistence

Each execution uses a typed two-node default workflow (case → adapter) through
the same DAG validator, executor and isolated job coordinator as native
propeller analyses. Wind-farm cases, OpenFAST cases and rotor results have
distinct ports and cannot be connected by silently reinterpreting quantities.
This increment supports one external case and one matching adapter per graph;
cross-tool coupling and arbitrary graph composition remain later work.

Local configurations are separate from immutable run inputs/results. Files live
under `external-runs/` beside the SQLite library. Retained artifacts include
raw/generated inputs, outputs, logs, result JSON, execution manifest and workflow
JSON for executed cases. Failures/cancellation retain diagnostics and inputs,
including when a worker exits before sending its final protocol message.
Cancellation stops the external process group and its descendants.

External runs reopen from Integrations. They are not included in propeller
`.nova` archives or static rotor comparisons. Dedicated wind-farm project editors,
portable editable case exchange, live OpenFAST progress interpretation and
coupled model execution remain subsequent work.

### Portable external results

Export a completed run with **Export external archive** and restore it with
**Open external archive**. The `.nova-run` ZIP preserves normalized results,
original scientific artifacts, versions, provenance and historical run state.
It omits local executable/environment configurations and known credentials;
raw scientific source files remain intact. Treat source files as the original
engineering data they contain, including any user-authored descriptions.

Import verifies the manifest, hashes, scientific shape/metadata, relative paths
and limits before committing a new run ID and private, nonexecutable artifacts.
Failure rolls back staged files and database writes. An imported archive is a
historical result: importing never launches software and does not restore an
executable configuration or promise that a case can be rerun on another machine.
Limits are 128 MiB ZIP, 100 MiB expanded content, 20 MiB per JSON document and
2048 files. Native propeller projects continue to use `.nova`.

APIs: `GET /api/v1/external-runs/{id}/archive` and
`POST /api/v1/external-runs/import` with `{content_base64}`. Restored source,
CSV and raw artifacts use the same endpoints as locally produced results.

The application monitors external jobs across workspace changes. The single
global **Cancel** remains available; opening an older result does not replace
the active job tracker. Returning to Integrations restores the tracked job.

Headless interfaces:

```sh
cd backend
python -m nova.cli import-openfast turbine.outb > time-series.json
python -m nova.cli run external-job.json > external-result.json
```

The execution document contains `workflow`, `inputs` (the external case) and
`external_job: {adapter_id, configuration: {executable, environment_kind,
options: {}}, artifact_root}`. Obtain the default graph from
`nova.workflow.engine.external_template('pywake' or 'openfast')`. The numerical
services do not import FastAPI or require Tauri.

API: `/api/v1/adapters`, `/integrations`, `/external-runs`, `/openfast/import`,
`POST /api/v1/openfast/inspect` with `{case: {...}}`,
`/runs/{id}` and `/runs/{id}/cancel`; external CSV/artifacts are below
`/external-runs/{id}`.

## Verification

### Independently installed OpenFAST

Keep OpenFAST executables, source checkouts, official cases and generated outputs
outside the NOVA repository and packages. NOVA's adapter does not redistribute
OpenFAST. The source-release checker rejects compiled executables/libraries and
binary simulation outputs accidentally added to source files.

With NOVA's Python dependencies available, qualify a local installation:

```sh
python tools/qualify_openfast.py \
  --executable "$HOME/.local/share/nova-external/openfast/5.0.0/bin/openfast" \
  --case-directory "$HOME/.local/share/nova-external/openfast/5.0.0/cases/aoc-steady" \
  --input-file AOC_WSt/AOC_WSt.fst \
  --output-file AOC_WSt/AOC_WSt.outb \
  --report /tmp/nova-openfast-qualification/source-qualification.json
```

The tool requires external paths and a new report filename. It independently
copies inspected inputs for a direct OpenFAST run, configures an isolated NOVA
library, runs the same case through the API/job engine, compares sampled values,
checks the queued input hashes and restores a portable result archive including
the original output bytes. It preserves reports, source/output files and logs
outside the repository. At least two time samples are required; inspect `TStart`,
`TMax` and `DT_Out` when preparing a short case. Input changes must be recorded
against their untouched originals. A direct-versus-adapter comparison tests the
execution path; both outputs use NOVA's importer, so it is not an independent
verification of that importer or of turbine physics.

Pass `--backend /path/to/nova-backend` to repeat against a rebuilt frozen NOVA
backend. No OpenFAST download or installation is performed by this tool, the app
or the NOVA package installer. Use the
[official installation documentation](https://openfast.readthedocs.io/en/main/source/install/index.html)
for an independently managed installation.

```sh
cd backend
NOVA_PYWAKE_PYTHON=/path/to/pywake-environment/bin/python \
  python -m unittest discover -s tests
```

Real PyWake tests additionally check isolated-turbine zero loss, downstream
NOJ loss and analytic no-wake AEP. Without the optional interpreter these real
tests are explicitly skipped; protocol/import tests still run. The browser
journey uses the same environment variable for real configuration, execution,
CSV and reopen checks. Packaging smoke tests distinguish execution fixtures
from scientific validation and verify that OpenFAST import needs no system
Python or OpenFAST installation.
The exact separately managed PyWake validation environment is recorded locally
in `.desktop-tools/qualification/integrations/pywake-2.6.20-requirements.txt`.
