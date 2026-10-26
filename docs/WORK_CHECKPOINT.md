# NOVA work checkpoint — 2026-10-22


## Mixed project increment (source, not yet packaged)

- `/api/v2` adds neutral projects and typed propeller, OpenFAST and PyWake
  simulations. Existing native APIs remain available. External cases are
  immutable assets; changing a saved case creates a new asset revision identity.
  Local executable/environment selection remains outside portable project data.
- Mixed `.nova` archives preserve scientific case inputs, simulation references
  and historical execution lineage. Import remaps identities transactionally;
  existing v1 project archives remain supported. Source OpenFAST directories may
  be removed after saving a case without preventing execution or restoration.
- Fixed external duplication to copy the edited draft without saving over the
  original. Restored legacy project configuration fallback and guarded asynchronous
  project activation. Explorer labels distinguish external cases and limit native
  solver comparison to compatible simulation kinds.
- Verified 13 mixed API/archive tests; frontend lint/build; browser mixed-project
  persistence, dirty-switch protection and duplication of an edited draft while
  preserving the original. Added `npm run test:mixed-projects` to CI.
- Existing guided browser journey also passed (workflow, studies, comparison,
  integrations and exports). Full backend discovery: 99 passed, two optional
  real-PyWake skips, one module import error because Matplotlib is absent from
  this test runtime (`test_validation`). Scientific validation suite is therefore
  not qualified by this run. Log: `/tmp/nova-mixed-review/backend-tests.log`.
- Repeated real OpenFAST source qualification with `--project-mode`: direct vs
  project run, deleted private source copy, project export/import, historical
  simulation revision/name and actual imported-case rerun. 101 samples, 30
  channels, 0–5 s, maximum absolute difference 0. Report:
  `/tmp/nova-mixed-qualification/source-project-reviewed.json`.
  This is software qualification of the declared demonstration case, not physical
  validation. No external solver or official case is redistributed.
- Remaining: dedicated external case/results workspaces and central external DAG
  editor; broader cross-kind history navigation; version-aware OpenFAST file
  editor, turbine authoring and specialist-tool workflows in
  `NOVA_OPENFAST_PLAN.md`. Current external forms/results still occupy Workflow.
  These later phases are not complete. No new desktop package was built for this
  increment; the qualified revision -3 below remains the previous delivery.

## OpenFAST execution increment

- Added a solver-independent case inspection API and Integrations panel:
  contained relative inputs, bytes, SHA256 inventory and case fingerprint.
  Editing paths/output/timeout invalidates the display; stale responses are
  ignored. Execution independently validates and snapshots the inputs again.
- OpenFAST 5.0.0 was built from the official pinned source and installed
  independently at `~/.local/share/nova-external/openfast/5.0.0/`. No solver,
  source checkout, official case, generated output or controller was copied
  into NOVA's source or package. No host system package was installed.
- A shortened official `AOC_WSt` case passed direct execution and the actual
  API → DAG → worker → adapter path with both source and rebuilt frozen desktop
  backends: 101 samples × 30 channels, 0–5 s,
  maximum absolute difference 0. Queued input hashes, portable `.nova-run`
  restoration and original raw output bytes also matched; backend stopped.
  `tools/qualify_openfast.py` repeats this test with external paths and an
  isolated library, optionally using a frozen backend.
- Source/report provenance: OpenFAST commit
  `2895884d2be01862173c88d70f86b358d2f1a50a`, r-test commit
  `dd5feaaaa500ba7283140107806300d551cff0a7`; prepared `TMax=5`, `TStart=0`,
  `OutFileFmt=3`, `Echo=False`, with originals preserved externally.
  The official case declares fictional parameters and startup low-TSR BEM
  warnings: this verifies software execution, not turbine physics or all cases.
  External evidence: installation `qualification/` and
  `/tmp/nova-openfast-qualification/nova-{source,frozen}-qualification.json`.
- Backend release gate: **105 completed, 103 passed, two optional real-PyWake
  tests skipped**. Corrected only a `/proc` test race where a terminated child
  vanishes between existence/read checks. Logs retain the initial failure and
  passing repeat under `.desktop-tools/qualification/openfast-source-tests*.log`.
  Frontend lint/build and the new browser inspection journey passed, including
  failed input validation, field invalidation, delayed responses and zero solver
  probe/execution calls during inspection. CI includes this journey.
- Source-distribution checks now also reject executable signatures and compiled
  libraries/binary solver outputs. External cases and software stay outside
  NOVA; package qualification continues to use original process fixtures.
- Arch `0.1.0.alpha.2-3` build and exact-package installed qualification passed:
  three frozen backend smokes, five Rust tests, native workflows and external
  inspection/import/archive fixtures, ELF resolution, desktop launcher and
  clean shutdown. The disposable runtime had no Python, compiler or OpenFAST.
  Initial harness attempts lacked `jq`/`cmp`; logs are retained and the final
  attempt installed only test prerequisites in the disposable container.
  Evidence: `.desktop-tools/qualification/openfast-integration-report.json`,
  `OPENFAST_INTEGRATION_SHA256SUMS` and
  `arch-openfast-integration-installed-final.log`.
  Package SHA256:
  `746f3ff9e681a4b730307abb5e566f6ce3473d2a7d216dadc69c075b6e0d60a4`.
- Generated local NOVA sidecar refreshed only after qualification, SHA256
  `479a0969de06742ccbe4fbeff053cf5f4f922de78fd3c8a192afb1b5c65b2562`.
  Previous `-2` artifacts remain under
  `archives/workflow-expansion-5575294749d6/`. Ubuntu remains at the earlier
  integration increment. Owned temporary browser/API servers stopped cleanly.

## Preserved workflow-expansion increment (2026-10-16)

Project exploration, strict solver comparisons, two-axis studies and reusable
external case/result data extend the existing shared-geometry workflow.
Changes remain in the working tree; pre-existing user changes have
been preserved. No numerical solver algorithms were changed in this increment.

### Delivered changes

- Project explorer: searchable saved simulations, immutable geometry revisions,
  referenced data/source inspection and native project executions. Study and
  comparison history opens its frozen results rather than the edited source.
- Guided solver comparison: 2–8 saved configurations, explicit reference,
  evaluated geometry/condition/polar compatibility checks, revision conflicts,
  queued immutable batches, retained failures, backend-computed differences,
  CSV and exact-case STL/report inspection. Initial scope is one-analysis guided
  graphs with manual geometry; arbitrary coupled comparisons are not implied.
- Optional two-axis Cartesian studies: at most 32 cases / 128 analysis evaluations,
  normalized rows/units, a discrete result matrix, actual case conditions and
  both-axis report context. Legacy one-axis serialization remains compatible.
- Portable `.nova-run` archives: original external scientific files, normalized
  results, provenance and historical states; no executable configuration or
  automatic execution on import. Limits, relative paths, checksums, array shapes,
  energy consistency and atomic rollback are checked.
- Saved immutable PyWake input cases: turbine curve/layout/wind data, notes,
  demonstration flag and hashes independent of installed software. Explicit load
  replaces inputs; Save creates another copy. Equal-scale layout preview and
  in-session integration draft retention prevent loss during workspace changes.
- One application monitor tracks external jobs across navigation; the global
  Cancel remains reachable, including while an older result is open. Optional
  software remains independently installed and external cases remain standalone.
- Native execution/optimization polling now retries transient connection/server
  errors against the same submitted ID, with visible recovery feedback.
- Final backend release gate: 104 tests completed, 102 passed and two optional
  real-PyWake tests skipped because the separate environment is absent. Log:
  `.desktop-tools/qualification/workflow-expansion-source-tests.log`.
- Browser checks cover guided/advanced workflows, project/simulation history,
  actual BEMT/LLT comparison, actual LLT 2×2 cases, portable external archives,
  navigation/cancellation and reusable case inputs without optional software.
  Frontend lint/build and all seven browser journeys passed, including visible
  HTTP 503 recovery against one submitted native execution. CI includes the
  corresponding commands in `frontend/package.json`.
- Arch `0.1.0.alpha.2-2` qualification passed: three frozen backend smoke tests,
  five Rust tests, clean installed native/integration workflows without system
  Python, desktop launcher, ELF dependencies and clean shutdown. Package:
  `.desktop-tools/qualification/arch/packaging/arch/nova-propellers-0.1.0.alpha.2-2-x86_64.pkg.tar.zst`.
  SHA256 `5575294749d6e1acb51599e0445e78d1a9c57f62cc0f1a1467dd9487ac556eb1`.
  Evidence: `.desktop-tools/qualification/workflow-expansion-report.json` and
  `WORKFLOW_EXPANSION_SHA256SUMS`. All 113 production source hashes matched the
  build snapshot. No host package installation was performed.
- Generated local sidecar refreshed from that qualified build, SHA256
  `abd045cd9250e73e70604f95187c738bff9e67a1a9b06a6cd1b989c20a2580b8`.
  Prior `-1` package is retained in `archives/shared-geometry-e9fec3c98e8c/`.
  Ubuntu remains at the earlier integration increment. Temporary browser/API
  servers were stopped cleanly.
- Screenshots: `.desktop-tools/ui-navigation/comparison-explorer/`,
  `.desktop-tools/ui-navigation/external-cases/`, with copies retained beside
  qualification evidence. Physical Wayland/GPU behavior, byte-identical builds,
  real OpenFAST solver execution and a fresh real-PyWake environment remain
  separate qualification work. Makepkg reports embedded build-source references;
  installed execution passed without the builder source directory.

## Preserved shared-geometry increment (2026-10-11)

- One persistent Save / Run simulation / Cancel control set, with secondary project/archive actions. New simulation keeps geometry and resets analysis defaults; Duplicate preserves the current configuration.
- Save/Run publish edited geometry for the current simulation only. Immutable geometry revisions can be adopted explicitly by selected saved configurations, with transactional revision checks. Historical results remain frozen.
- Dirty transitions offer Save/Discard/Keep editing. The graph uses Customize workflow, compact block addition, validation details and collapsible logs. Studies remain cancellable across workspace/project changes.
- Geometry baseline identity excludes solver/RPM/thrust/fluids; actual derived sizing/study/optimization geometry remains in execution results. Canonical geometry snapshots and loft source references survive archive remapping.
- Corrected canonical station serialization so rounding never places the tip outside the true rotor radius; arbitrary-diameter regression added, without changing solver algorithms.
- Verification: full backend suite passed 80 tests (78 passed, two optional real-PyWake tests skipped after the temporary environment reset). Final simulation browser journey passed geometry edits/duplication, selected adoption/history, responsive commands and persistent study cancellation. Frontend lint/build passed. Updated Arch package passed three frozen backend smoke tests, five Rust tests and full installed native/integration/desktop-launch/shutdown qualification.
- Current previews: `.desktop-tools/ui-navigation/shared-geometry/`. Current qualification evidence: `.desktop-tools/qualification/shared-geometry-report.json`; previous package evidence below applies to earlier increments.
- Current checksum: `.desktop-tools/qualification/SHARED_GEOMETRY_SHA256SUMS`; package SHA256 `e9fec3c98e8c963e23cc21514811a8830bf5c9c4da414f90b0e0263ecdec4857`. Generated host sidecar was refreshed from the same qualified build. Prior package remains preserved in `archives/project-simulations-6802d9d25b7f/`. No host package installation was performed; Ubuntu remains at the earlier integration increment.

## Preserved project/simulation increment

- Persistent project, simulation, saved/draft/modified status and actual graph-model context. Selectors remain available with the contextual panel hidden.
- Multiple named native configurations per project, each with geometry/conditions/workflow snapshots and independent revisions. New/clone/save/run controls preserve the original configuration.
- Analyses, studies and optimization retain simulation lineage. Stored results show their frozen model/RPM/revision independently of current edits. Delayed responses cannot populate another project/view.
- Additive simulation records and validated `.nova` archive remapping preserve legacy archives. External integrations remain explicitly standalone.
- Verification: 75 backend tests with real separately managed PyWake, both Chromium journeys, frontend lint/build, Ruff and diff checks passed. New Arch build and full installed runtime/desktop qualification passed; refreshed host sidecar smoke passed.
- Evidence: `docs/PROJECT_SIMULATIONS.md`, `.desktop-tools/ui-navigation/project-simulations.png`, `.desktop-tools/qualification/project-simulations-report.json` and `PROJECT_SIMULATIONS_SHA256SUMS`. Ubuntu remains at the preceding integration increment.

## Preserved navigation increment

- Workflow now renders the block editor in the central workspace instead of the geometry viewport. Graph toolbar and block palette are central; selected-node solver, project/data controls and job logs remain in the sidebar. Existing controller/state is shared through a React portal.
- Frontend lint/build, full browser journey and central-canvas/node-inspector checks at 1440 and 1024 px passed. Updated Arch package passed targeted install/ELF/launcher/shutdown checks; sidecar is unchanged. Evidence: `.desktop-tools/qualification/workflow-editor-report.json` and `WORKFLOW_EDITOR_SHA256SUMS`.

- Replaced the two overlapping navigation rows with one grouped sidebar: propeller workflow, analysis tools and library/software.
- Header identifies the current workspace; New project returns to Initial sizing. Polar/fluid controls appear in Analysis/Workflow, while their state remains stored when hidden.
- Models, Studies and Integrations use the full content width. Narrow windows use a grouped Workspace selector.
- Frontend lint/build, complete Chromium journey and layout checks at 1440/1024/390 px passed. Updated Arch package passed installation, ELF dependency, desktop launch and shutdown checks; scientific sidecar hash is unchanged.
- UI evidence: `docs/UI_NAVIGATION.md`, `.desktop-tools/ui-navigation/` and `.desktop-tools/qualification/UI-navigation-report.json`. Ubuntu package remains at the preceding integration increment.

## Preserved integration increment

- PyWake NOJ adapter through a separately managed interpreter, structured wind-farm forms, explicit joint probabilities, power/effective-speed/AEP results and CSV.
- OpenFAST standalone ASCII/binary output import and isolated execution of supplied self-contained cases; source bytes, units, channel names and hashes retained.
- Typed case → adapter default graphs use the existing DAG engine, isolated worker and single-job coordinator. External results remain separate from static rotor results.
- Persisted external runs, reopen, logs, cancellation, raw artifacts and workflow JSON.
- Fixed cancellation swallowing by selectors: SIGTERM now raises a distinct exception so subprocess cleanup runs. Regression checks the external PID is no longer alive.
- Interrupted submission preserves referenced input snapshots. Failures/cancellation retain downloadable diagnostics, including incomplete worker protocol exits.

## Verification

- Previous integration backend suite: 71 tests passed with real PyWake 2.6.20 configured. Backend/numerical code is unchanged by the navigation increment.
- Ruff, frontend lint/build and git diff checks passed.
- Full Chromium journey passed: guided propeller workflow, studies/comparison, OpenFAST import/channel plot/CSV/reopen, real PyWake configuration/execution/CSV/reopen.
- Real PyWake tests check isolated-turbine zero loss, downstream wake loss and analytic no-wake AEP.
- Official OpenFAST ID2 sample: 201 samples × 10 channels, all times/values exactly match the unmodified official reader. Source/digest evidence is retained in `.desktop-tools/qualification/integrations/`.
- Host frozen sidecar passed integration smoke with the real separate PyWake environment. Local generated sidecar is updated.
- Final Arch and Ubuntu packages passed three frozen backend smoke tests and installed desktop/runtime checks, including OpenFAST import and an external shell fixture without system Python. Arch also passed five Rust tests.
- Current package report: `.desktop-tools/qualification/integrations-report.json`. Earlier studies and foundation qualification reports remain separate.

## Remaining qualification and next work

The previous Arch package hashes are in
`.desktop-tools/qualification/SHARED_GEOMETRY_SHA256SUMS`. Its original artifact
is preserved in `archives/shared-geometry-e9fec3c98e8c/`. The previous expansion
used Arch package revision `-2`; its passed qualification evidence is
`.desktop-tools/qualification/workflow-expansion-report.json` and
`WORKFLOW_EXPANSION_SHA256SUMS`. Current OpenFAST work uses revision `-3` and
the separate report/checksums recorded above.
Ubuntu remains at the
integration increment recorded in `INTEGRATIONS_SHA256SUMS`. Actual
The older integration increment tested process fixtures and an official output
sample; the current increment above separately qualifies a real local OpenFAST
installation with one declared case. Other modules/cases remain unverified.

Subsequent bounded tasks: broader OpenFAST case qualification, portable input-case
exchange, suitable wind-farm project containers, optimization-history candidate
inspection and validated additional wake/resource models. Cross-tool coupling,
DUST and C++ migration remain later work.
Physical Wayland/GPU behavior and byte-identical builds remain unverified.

## Local resources

- Current test Python: `.desktop-tools/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12`, using existing desktop/cache dependencies. Ruff was unavailable in this session; no package was installed to supply it.
- Earlier `/tmp/nova-test-env` and `/tmp/nova-pywake-env` have been removed. Two real-PyWake tests skip explicitly until an independently managed environment is supplied.
- Isolated package sources/caches: `.desktop-tools/qualification/arch/` and `ubuntu/`.
- Builder images: `localhost/nova-arch-qualification`, `localhost/nova-ubuntu-qualification`; corresponding runtime images are available.
- Integration setup/contracts/limits: `docs/EXTERNAL_INTEGRATIONS.md`.
- Repeatable smoke: `tools/smoke_integrations_backend.py`, optionally `--pywake-python /path/to/environment/bin/python`.

No C++ solver migration or external scientific solver implementation was bundled.
