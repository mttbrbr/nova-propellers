# Interface

## In brief

The interface is designed for 16:9 desktop screens and adapts down to phone width. Every
engineering control stays available, but only what the current task needs is shown.

## In detail

### The design sheet

There is no stage bar: the design reads top to bottom as a **sheet** with four sections,
**Sizing**, **Geometry**, **Analysis** and **Results**. A closed section keeps a one-line summary
and a status dot:

- green: up to date;
- amber: needs attention, or changed since the last run;
- grey: not run yet.

The centre shows the active view (charts, formulas); the right shows the latest run and the 3D
render. The **selected station** along the blade (0 at the root, 1 at the tip) is the same
everywhere: clicking a chart or a row, or pressing ←/→, moves the dashed line, the labels and the
ring on the render together.

### Workspaces

:::{table} Workspaces
:name: tab-workspaces

| Workspace | Contents |
|---|---|
| Library | Projects (search, filters, compare, export), airfoils and polars, physical models with maturity and warnings |
| Comparisons | Runs from any project overlaid, with a table against a baseline |
| Studies | Solver comparison, design comparison, parameter sweep |
| Workflow | Project graph or block workflows with constraints |
| Integrations | External programs (PyWake, OpenFAST) and result import |
:::

### Keyboard

:::{table} Keyboard shortcuts
:name: tab-keys

| Action | Keys |
|---|---|
| Run (opens the model chooser; Enter starts) | Ctrl+Enter |
| Open project | Ctrl+P |
| Save | Ctrl+S |
| Open design-sheet section 1–4 | Alt+1 … Alt+4 |
| Previous / next station | ← / → |
| Fit render to view | F |
| Close a menu | Esc |
:::

```{note}
**Run** is the only orange button. While a calculation, study or external job is active it becomes
**Cancel** and shows its state and progress.
```

### Protecting your edits

Switching to another project or configuration with unsaved changes offers *Save*, *Discard* or
*Keep editing*. The `.nova` export always uses the **saved** project: unsaved edits are not part
of it.
