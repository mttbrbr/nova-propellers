# Quick start

## In brief

NOVA opens on the **Library**, the list of saved projects. From there you create a project, choose
the rotor type and work down the **design sheet**: sizing, geometry, analysis, results.

## In detail

### The typical path

1. **Sizing.** Choose the rotor type (air propeller, marine propeller, horizontal-axis or
   vertical-axis turbine) and enter the operating data. For a propeller, for example, thrust, power,
   rpm and conditions; NOVA estimates an initial diameter.
2. **Geometry.** Define chord, twist and airfoil along the blade. The 3D preview refreshes by itself
   shortly after every edit, so there is no "generate" step.
3. **Analysis.** Choose the calculation model, the operating point and the corrections. Only the
   corrections that make sense for the chosen rotor type are shown.
4. **Results.** Start the calculation with **Run** (Ctrl+Enter), read performance and spanwise
   distributions, and export data (CSV) and geometry (STL).
5. **Saving.** The whole project is saved to the local store (Ctrl+S) and can be exported as a
   `.nova` file.

### Versions

Each **version** corresponds to a single geometry and has an identifier of the form `x.y.z`. After
the first run the geometry of that version is **locked**: you can launch further calculations
(other rpm, other models), but to change the geometry you create a **new version**, which copies
the previous one and becomes editable again. This way every result stays tied to the geometry that
produced it.

```{note}
The header keeps a single project selector and a single version selector. The interface is
evolving: if something described here does not match what you see, **[TO VERIFY]** and update this
page.
```

### Where to go next

To understand the terms used here see [Concepts](concepts.md); for commands and screens,
[Interface](interface.md); for studies, comparisons and external programs,
[Studies and integrations](studies-integrations.md).
