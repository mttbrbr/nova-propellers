# Concepts

## In brief

Four objects organise the work: **project**, **geometry**, **simulation** and **execution**. Two
more ideas complete the picture: the **rotor family** and the **maturity** of each model.

## In detail

### Project, geometry, simulation, execution

:::{table} The objects of NOVA
:name: tab-objects

| Object | Purpose | How it is kept |
|---|---|---|
| Project | Named container for configurations, assets and executions | Stable ID and revision |
| Geometry | Baseline rotor definition shared within the project | Immutable revisions, explicitly selected |
| Simulation | Named configuration: geometry, models, polars and conditions | Its own ID and revision |
| Execution | One evaluation of a saved simulation | Frozen inputs, results and model |
:::

A project can hold, for example, a BEMT run at 5000 rpm and an LLT run at 6500 rpm on the same
geometry: editing one does not change the other. Repeating a simulation without changing it creates
a new execution; changing and saving it creates a new revision, and earlier results keep their
original snapshot.

### Rotor families

The rotor type is chosen at the start and the same four sections of the design sheet adapt:
**air propeller**, **marine propeller**, **horizontal-axis turbine (HAWT)** and **vertical-axis
turbine (VAWT)**. Corrections that do not apply to the chosen type are hidden, and the API rejects
them.

### Model maturity

Every method carries a maturity label, always shown next to its results:

:::{table} Method status for the air propeller
:name: tab-maturity

| Method | Role | Maturity |
|---|---|---|
| Actuator disk | Sizing reference | Ideal reference |
| BEMT | Analysis and optimisation | Preliminary |
| LLT | Analysis and optimisation | Preliminary |
| VLM | Solver architecture experiments | {tag}`experimental` |
| BEM | Solver architecture experiments | {tag}`experimental` |
:::

"Preliminary" means the model reproduces textbook behaviour and passes the internal physics
checks, but has not been compared with measurements. See
[Verification and validation](../technical/verification-validation.md).

### Synthetic polars

The built-in airfoil polars are **demonstration data** generated from a formula, not measurements.
You can import real polars (CSV or XFOIL-style headers) and airfoil coordinates in UIUC/XFOIL
`.dat` format. Every result states whether it uses synthetic data.
