# Main navigation organization

The interface now has one primary navigation instead of overlapping workspace
tabs and numbered phase toggles. Destinations are grouped by purpose:

| Group | Destinations |
| --- | --- |
| Propeller workflow | Initial sizing → Geometry → Force analysis → Results |
| Analysis tools | Models, Workflow, Studies |
| Library & software | Database, Integrations |

Each destination has one navigation entry and an explicit active state. The
header identifies the current workspace and its purpose; New project is a
separate action and returns to Initial sizing. Existing projects, archives and
simulation selection remains in the persistent context bar. The header has one
Save and Run simulation/Cancel action; New/Close project and `.nova` import/export
are grouped under Project actions. Export explicitly uses the saved project.
Standalone Integrations keeps software-specific submission controls and shares
the global job cancellation/monitoring control across workspace changes.

Sizing shows targets/dimensions immediately. Polar import and fluid properties
appear in Force analysis and Workflow; hiding these controls does not reset
their values or unmount the project controller. Geometry/Results retain a
summary of the selected polar asset. Models, Studies and Integrations use the
available central width without unrelated propeller controls. Workflow uses
the full central region for its block editor, with Customize workflow, validity
details and a compact Add block menu in its toolbar. Project/data settings,
selected-node solver and collapsible job logs remain in the sidebar. The existing
graph state and numerical implementations
are preserved; no geometry viewport is rendered in Workflow.

Custom graphs that cannot be represented safely by guided forms disable the
three guided setup destinations and direct users to Workflow. On narrow
windows, a grouped Workspace selector replaces the desktop navigation rail.
Surface/Mesh controls remain local to the 3D viewport.

New simulation retains the selected shared geometry and resets analysis settings;
Duplicate simulation preserves the current draft as a new configuration. Dirty
project/configuration transitions offer Save changes, Discard changes and Keep
editing. Shared geometry revisions are selected independently of solver/RPM;
publishing and applying to explicit simulation targets happens in Geometry.
Older propeller records remain in the identified legacy library. See
[Project and simulation context](PROJECT_SIMULATIONS.md).

## Project explorer and study navigation

The contextual panel contains a project explorer with searchable saved
simulations, geometry families/revisions, referenced datasets and all native
project executions. Sections collapse independently; execution history initially
shows the latest ten entries and can expand. Source inspection shows units/data
identity, synthetic-data flags and the original source download. Using a polar
or geometry is an explicit edit, protected by the existing dirty-state controls.

Opening a historical study/comparison routes to Studies and preserves its frozen
sources; opening a native analysis retains its original simulation caption.
The comparison shortcut opens the guided selection of saved configurations.
Studies adds an optional second-axis grid, with exact-case inspection and CSV;
single-axis controls remain the default. Read-only history can be opened while
another job is active, without changing which job the global Cancel targets.
Optimization candidate restoration from the explorer remains later work.

Current verification: seven browser journeys, frontend lint/build and clean
installed Arch qualification passed. Screenshots for the explorer, solver
comparison and responsive result grids are under
`.desktop-tools/ui-navigation/comparison-explorer/`; reusable wind-farm inputs
and equal-scale layout preview are under `.desktop-tools/ui-navigation/external-cases/`.
Evidence: `.desktop-tools/qualification/workflow-expansion-report.json`.

Verified with frontend lint/build, the complete Chromium project/study/import
journey, and visual/layout checks at 1440×1000, 1024×768 and 390×844. Checks
include active navigation, retained project state, contextual controls and no
horizontal page overflow. Local previews are under
`.desktop-tools/ui-navigation/`; package evidence is in
`.desktop-tools/qualification/UI-navigation-report.json`.
The expanded workflow canvas was additionally checked at 1440×1000 and
1024×768, including node selection and the complete save/reopen/study journey.
Current package evidence: `.desktop-tools/qualification/workflow-editor-report.json`.
Preview: `.desktop-tools/ui-navigation/workflow.png`.

The current shared-geometry/unified-command increment additionally passed the
simulation journey at widths 1440, 1024 and 390 px (viewport height 1000 px),
including unique/reachable commands, Save publication, duplication of edited
geometry, selective revision adoption and persistent study cancellation.
Current previews: `.desktop-tools/ui-navigation/shared-geometry/`.
Current Arch package evidence: `.desktop-tools/qualification/shared-geometry-report.json`
and `SHARED_GEOMETRY_SHA256SUMS`. Ubuntu remains at the preceding integration
increment; earlier evidence above describes the earlier navigation steps.
