# Interface organization

The interface is designed for 16:9 desktop screens (1920×1080) and adapts down
to phone width. It keeps every engineering control available but shows only
what the current task needs; optional groups open in place.

## Shell

| Region | Contents |
| --- | --- |
| Header | NOVA wordmark, **open project tabs** (+ for a new project), project picker (Ctrl+P), simulation selector, save state, configured models, **Simulation options**, Save, **More actions**, Run / Cancel |
| Rail | Design, Comparisons, Studies, Workflow, Library, Integrations (icons with tooltips) |
| Design area | Design sheet on the left, the active view in the centre, latest run and render on the right |
| Notices | Confirmations bottom-left (fade after 8 s); errors stay until dismissed |

- **Project picker** (Ctrl+P) searches every saved project by name, simulation,
  airfoil, solver or id and opens a simulation directly. With an empty search it
  shows pinned and recent projects. Pins and recents are stored in this
  computer's browser storage.
- **Simulation options** holds the simulation name, New/Duplicate simulation and
  New PyWake/OpenFAST simulation.
- **More actions** holds New/Close project and `.nova` export/import. Export
  uses the saved project.
- **Project tabs.** Every opened project becomes a tab showing its rotor type;
  selecting a tab reopens that project (unsaved changes ask save/discard first),
  × closes it. Open tabs are remembered in this computer's browser storage.
- Run is the only accent-coloured (orange) button. It always opens a chooser:
  several models for the air propeller (the first is the main run, the others
  run on the same frozen inputs and are overlaid in Results), one streamtube
  model for a VAWT, BEMT for HAWT and marine propellers. Customised graphs run
  as configured. While a run, study or external job is active the button
  becomes Cancel and shows the job state and progress.

## Design sheet

There is no stage bar. The rotor type is chosen in Sizing and the process reads
top to bottom as sections of a **design sheet**: Sizing, Geometry, Analysis,
Results. Several sections can be open; a closed section keeps a one-line
summary and a status dot (green up to date, amber needs attention or changed
since the last run, grey not run). Clicking a section title makes it the active
view; clicking the active one folds it. View tabs above the centre switch views
directly; rotor-engine designs (marine, HAWT, VAWT) add a **Sweep** lens.

| Section / view | Sheet inputs | Centre | Right |
| --- | --- | --- | --- |
| Sizing | Project, rotor type, target thrust or requirements (rated power, wind, Cp; ship thrust, wake, J) | Sizing trade-off charts and formulas | Rotor schematic and sized values |
| Geometry (Blade / Rotor) | Blade or rotor shape, inverse design, airfoil loft, revisions, STL export | Chord and twist with draggable points, or blade distributions | 3-D render with station ring and section, or rotor proportions |
| Analysis | Solver/model, operating point, only the corrections that apply, polars and air data | Polars or the model ladder and correction notes | Render and last run |
| Results | Runs, comparison, provenance, exports | Performance, spanwise distributions, Cp–λ or open-water curves | Render coloured by a result, convergence, operating point |
| Sweep (rotor engine) | — | Vary one input over a range with a model and limits; chart and table with feasibility | Refine feasible points with a higher-fidelity model (VAWT), adopt a value, open as block workflow |

A **Latest run** card stays on the right in every view except Results and marks
the run out of date when inputs change.

- **Live preview.** The geometry preview regenerates automatically about
  350 ms after an edit, so there is no Generate step. A failed request keeps the
  last valid preview and shows the backend message.
- **Shared station.** The selected station (span 0 at the root section, 1 at the
  tip) is shared everywhere. Clicking a chart or a station row, or pressing
  ←/→, moves the dashed line, value labels, highlighted row and the ring on the
  render together.
- **Custom graphs.** Graphs that the guided forms cannot represent route
  Sizing, Geometry and Analysis to Workflow.

## Other workspaces

| Workspace | Contents |
| --- | --- |
| Comparisons | Runs from any project overlaid (Cp–λ, CT–λ, KT–J, η–J, spanwise thrust and incidence), a table against a baseline with Δ power, the inputs that differ and a warning when a difference has more than one cause; saved comparisons; open any run in a tab |
| Workflow | **Project graph** or **Block workflows** (general and rotor blocks with constraints). Full-height execution graph; selected block, airfoil data and project explorer in the left column; external case editors (PyWake, OpenFAST) in the centre |
| Studies | Three study types with a shared history: **Solver comparison** (one saved simulation, 2–4 solvers, no extra simulations; saved-simulation comparisons remain available underneath), **Design comparison** (2–4 finished runs from this or any project, with a like-for-like check, overlaid chord/twist/loading and a to-scale planform) and **Parameter sweep** (one or two axes) |
| Library | **Projects** (search, filters, sort, multi-select compare/export/delete, detail panel; deleting asks for the project name), airfoils and polars (import `.dat`, create, edit, delete), physical models with maturity and warnings, legacy snapshot archive with its report |
| Integrations | External software configuration, OpenFAST import and saved external runs |

## Keyboard

| Action | Keys |
| --- | --- |
| Run (opens the model chooser; Enter starts) | Ctrl+Enter |
| Open project | Ctrl+P |
| Save | Ctrl+S |
| Open design-sheet section 1–4 | Alt+1 … Alt+4 |
| Previous / next station | ← / → (Geometry, Results) |
| Fit render to view | F |
| Move a focused control point | ↑ / ↓ (Shift for larger steps) |
| Close a menu | Esc |

## Breakpoints

| Width | Layout |
| --- | --- |
| ≥ 1600 px | Design sheet 360 px, flexible content, right column 640 px |
| 1280–1600 px | Design sheet 340 px, flexible content, right column 540 px |
| 768–1280 px | Design sheet beside content; latest run and render move below the content |
| < 768 px | Everything stacks; the rail becomes a top bar |

## Design tokens

Colours live in `frontend/tailwind.config.js` under `nv`:

- surfaces: `canvas`, `chrome`, `panel`, `raised`, `hover`, `active`;
- lines: `line`, `edge`, `edge-strong`;
- text: `muted`, `ink`, `ink-strong`;
- signals: `accent` (orange `#FF8533`), `ok`, `warn`, `err`;
- data series: `series2`, `series3` (cyan), `reference`.

The logo is the NOVA wordmark with a dashed O (three blade-tip paths); the app
icon is that O on a rounded tile. Both are generated by
`tools/brand/make_logo.py` (see `docs/media/PROVENANCE.md`).

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
