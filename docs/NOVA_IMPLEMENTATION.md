# NOVA implementation and verification

The first architectural increment preserves the current guided propeller
workflow and adds a shared headless DAG, project revisions, explicit polar
selection, isolated jobs, a small editable graph, and portable project archives.

## User journey

1. Create/open a project from the project panel.
2. Edit geometry in Design and generate its preview.
3. Import CSV or XFOIL polar data, review the preview, and confirm import.
   Synthetic demonstration data is available through an explicit labeled action.
4. Select the asset and configure static RPM/density/viscosity.
5. Run from guided Analysis or Workflow. Inspect status, logs and diagnostics.
6. Inspect Results, export performance CSV/STL, and save the project.
7. Clone the Workflow before modifying its graph. Connect the geometry output
   to additional analysis nodes; connect results to collect/export nodes.
8. Export `.nova` to move the project, sources and historical results; import it
   into another library without overwriting the original.

CSV import accepts canonical headers `reynolds,alpha_deg,cl,cd` with optional
`mach,ncrit,cm`. The API also accepts a header mapping. Import one Mach/Ncrit
condition at a time. XFOIL headers take precedence over the missing-header
Reynolds fallback. Coordinate DAT import remains separate. Imported values
are not silently replaced with synthetic data or zero-filled missing samples.

The milestone operating envelope is static axial traditional rotors. Models
retain preliminary/experimental maturity. Coordinate lofting is independent
from aerodynamic polar assignment; spanwise polars and forward-flight
qualification remain later work.

## Checks

```sh
cd backend
python -m unittest discover -s tests -v
ruff check .
coverage run -m unittest discover -s tests -v
coverage report
```

Frontend:

```sh
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend run test:simulations
npm --prefix frontend run test:comparison
npm --prefix frontend run test:studies2d
npm --prefix frontend run test:external-archives
npm --prefix frontend run test:external-cases
npm --prefix frontend run test:execution-monitor
```

The browser test expects an isolated frontend at `NOVA_UI_TEST_URL` (default
`http://127.0.0.1:5174`) with its API configured at build time. Use an isolated
`NOVA_DB_PATH`; authorize only that frontend origin through
`NOVA_ALLOWED_ORIGINS`. `NOVA_CHROMIUM_PATH` selects the installed test browser.
The test covers guided execution, graph cloning, validation, save/reopen and
portable archive download. Backend integration tests additionally cover worker
cancellation, immutable assets, malformed graphs, archive rejection, and auth.

Desktop builds must use the locked Python 3.12 environment. The conflicting
standalone packaging pin in desktop requirements has been removed; the runtime
lock is authoritative. Check the rebuilt sidecar with the existing smoke test
and the workflow worker smoke test before desktop packaging.

## Release gates

Clean Arch and Ubuntu 24.04 package builds and runtime installation checks now
pass. Qualification includes ELF dependency resolution, native BEMT without
system Python, STL generation, project save/reopen, archive transfer, launch
through the actual desktop entry under Xvfb, and clean shutdown without an
orphaned backend. Logs, artifacts and SHA256SUMS are retained locally under
`.desktop-tools/qualification/`. See `docs/LINUX_QUALIFICATION.md` for repeatable
commands and headless-test limits. These checks must still run for each release;
physical Wayland/graphics-driver behavior and bit reproducibility are not claimed.
The application identifier, executable name and data location are unchanged;
the visible desktop name is NOVA.

The full audit roadmap remains incremental. The subsequent PyWake/OpenFAST
adapter increment is documented in `EXTERNAL_INTEGRATIONS.md`; external programs
remain independently installed. DUST, C++ migration, high-fidelity CFD and
predictive scientific qualification are not claimed.
