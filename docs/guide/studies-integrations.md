# Studies and integrations

## In brief

Beyond a single calculation, NOVA can **sweep parameters**, **compare solvers** and **import or run
external programs**. Everything stays local and reproducible.

## In detail

### Studies

A parameter sweep works on one or two axes (rpm, diameter, density or viscosity), with 2 to 32
values per axis and at most 32 cases in total. Every case keeps its parameter value, its effective
inputs, and its results or failure diagnostics. Failed cases stay in the table and the CSV but not
in the charts; an interruption keeps the cases already completed.

With two axes the result is a discrete matrix: missing or failed cells keep their status, with no
invented values and no interpolated surfaces.

### Solver comparison

Select 2 to 8 saved simulations in the same project, with one as reference. Before starting, NOVA
checks that geometry, rpm, target thrust, density and viscosity match. Percentage differences are
computed by the engine from the successful results.

```{warning}
This is a comparison between methods of the application, **not** a numerical validation against
measurements.
```

### External programs

NOVA ships the integration code, not the programs: **PyWake** and **OpenFAST** must be installed
separately and configured in *Integrations*.

- **PyWake**: a wind-farm case (turbines, layout, wind conditions), with annual energy production
  (AEP) and wake loss. The example curve is demonstration data, and power is in **W**, not kW.
- **OpenFAST**: import of `.out` / `.outb` files without installing OpenFAST, or execution of a
  complete case with a local executable.

### `.nova` archives

A `.nova` file carries the project, its sources and historical results, and can be imported into
another library without overwriting the original. Older archives remain importable.

**[TO COMPLETE]** Describe the `.nova-run` format for standalone external results once its current
state has been checked.
