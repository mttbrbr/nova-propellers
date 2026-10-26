# Interface organization

The interface is designed for 16:9 desktop screens (1920×1080) and adapts down
to phone width. It keeps every engineering control available but shows only
what the current task needs; optional groups open in place.

## Shell

| Region | Contents |
| --- | --- |
| Header | Project and simulation selectors, save state, configured models, **Simulation options**, stage stepper, Save, **More actions**, Run / Cancel |
| Rail | Design, Studies, Workflow, Library, Integrations (icons with tooltips) |
| Stage area | Inputs on the left, data in the centre, square 3D render with linked data on the right |
| Notices | Confirmations bottom-left (fade after 8 s); errors stay until dismissed |

- **Simulation options** holds the simulation name, New/Duplicate simulation and
  New PyWake/OpenFAST simulation.
- **More actions** holds New/Close project and `.nova` export/import. Export
  uses the saved project.
- Run is the only accent-coloured button. While a run, study or external job is
  active it becomes Cancel and shows the job state and progress. Leaving the
  workspace or changing project keeps that job cancellable.

## Design stages

| Stage | Inputs | Centre | Right |
| --- | --- | --- | --- |
| Sizing | Project, target thrust, diameter (manual or from disk loading) | Ideal actuator-disk trade-off charts, method, presets | Disk schematic and ideal values |
| Geometry | Blade, shape (approach, method, control points or Laguerre coefficients), inverse design, airfoil loft, shared-geometry revision, STL export | Chord and twist curves with draggable points, published revision dashed underneath, point tables | Render with station ring, geometry summary, section at the selected station |
| Analysis | Solver with maturity, rotation speed, airfoil polars and air data | Polar curves the solver will use, solver description and warnings, project explorer | Render, last run (faded with a reason when out of date), current execution and CSV export |
| Results | Runs of the simulation, comparison run, provenance, exports | Performance band, six spanwise distributions, station table, convergence details | Render coloured by dT, α, Re or Cl, residual history, limiting station |

- **Live preview.** The geometry preview regenerates automatically about
  350 ms after an edit, so there is no Generate step. A failed request keeps the
  last valid preview and shows the backend message.
- **Shared station.** The selected station (span 0 at the root section, 1 at the
  tip) is shared everywhere. Clicking a chart or a station row, or pressing
  ←/→, moves the dashed line, value labels, highlighted row and the ring on the
  render together.
- **Custom graphs.** Graphs that the guided forms cannot represent disable the
  first three stages and route to Workflow.

## Other workspaces

| Workspace | Contents |
| --- | --- |
| Workflow | Full-height execution graph; selected block, airfoil data and project explorer in the left column; external case editors (PyWake, OpenFAST) in the centre |
| Studies | Solver comparison, one- and two-axis sweeps, stored runs and comparisons |
| Library | Airfoils and polars (import `.dat`, create, edit, delete), physical models with maturity and warnings, legacy snapshot archive with its report |
| Integrations | External software configuration, OpenFAST import and saved external runs |

## Keyboard

| Action | Keys |
| --- | --- |
| Run simulation | Ctrl+Enter |
| Save | Ctrl+S |
| Go to stage 1–4 | Alt+1 … Alt+4 |
| Previous / next station | ← / → (Geometry, Results) |
| Fit render to view | F |
| Move a focused control point | ↑ / ↓ (Shift for larger steps) |
| Close a menu | Esc |

## Breakpoints

| Width | Layout |
| --- | --- |
| ≥ 1600 px | Inputs 340 px, flexible content, render column 660 px |
| 1280–1600 px | Inputs 300 px, flexible content, render column 500 px |
| 768–1280 px | Inputs beside content; render and linked data move below the content |
| < 768 px | Everything stacks; the rail becomes a top bar |

## Design tokens

Colours live in `frontend/tailwind.config.js` under `nv`:

- surfaces: `canvas`, `chrome`, `panel`, `raised`, `hover`, `active`;
- lines: `line`, `edge`, `edge-strong`;
- text: `muted`, `ink`, `ink-strong`;
- signals: `accent`, `ok`, `warn`, `err`;
- data series: `series2`, `series3`, `reference`.

Numbers use the monospace stack with tabular figures. The minimum text size is
11 px.

Shared components:

| File | Contents |
| --- | --- |
| `src/ui/controls.jsx` | Fields with units, segmented controls, icon buttons with tooltips, click-to-open popovers, disclosures, notices, metrics |
| `src/ui/LineChart.jsx` | Every curve in the app: ticks, hover readout, shared selection, dashed reference series, draggable points |
| `src/ui/SectionView.jsx` | Airfoil section drawn at its pitch angle |

## Project and simulation context

- **New and Duplicate.** New simulation keeps the selected shared geometry and
  resets analysis settings. Duplicate simulation copies the current draft,
  including unsaved geometry edits.
- **Unsaved changes.** Switching away from a project or configuration with
  unsaved changes offers Save changes, Discard changes and Keep editing.
- **Shared geometry revisions.** Revisions are chosen in the Geometry stage's
  Revision section, independently of solver and RPM. Publishing creates an
  immutable revision; applying it changes only the selected simulations.
  Earlier results keep their original geometry.
- **Legacy records.** Older propeller records remain in Library › Archives.
  See [Project and simulation context](PROJECT_SIMULATIONS.md).

## Verification

The nine browser journeys in `frontend/tests` (`npm run test:*`) cover:

- guided execution, auto preview, workflow cloning and validation;
- save/reopen and `.nova` export;
- multiple simulations, geometry adoption and draft protection;
- solver comparisons and one- and two-axis studies;
- external cases, archives and OpenFAST inspection;
- execution monitoring recovery.

The command-reachability and no-horizontal-overflow check runs at 1440, 1024
and 390 px.
