# Projects, versions and storage

## In brief

Projects are saved to a local SQLite store. Geometries and simulations have **immutable
revisions**: results stay tied to the exact data that produced them.

## In detail

### Revisions and shared geometry

Several solver variants can refer to the same geometry revision. Rpm, target thrust, fluid
properties, polars and solver settings belong to the analysis; diameter, blade count, airfoil,
geometry method, curve parameters and the frozen loft coordinates define the baseline geometry.
Editing that definition creates a new immutable revision; adoption by other simulations is an
explicit operation, with revision-conflict checks. Past executions never change.

### Versions (`x.y.z`)

Each version has an identifier and a single geometry. After the first run the geometry is locked,
and "New version" creates an editable copy.

```{note}
**[TO COMPLETE]** The rule "one simulation per solver type in each version" is a design decision
not yet enforced by the code: the interface shows the latest run per solver. Update this when it is
enforced.
```

### Conflicts and archives

Execution requests accept an expected simulation revision: a conflicting edit returns 409. `.nova`
archives include simulations, geometries, assets and historical links; import validates every
record before an atomic write and remaps identifiers. Older archives remain importable.

### Verification

The engine tests cover two models in one project, repeated runs, copy/edit isolation, conflicts,
archives and studies from saved configurations. The interface has automated browser journeys
(`npm run test:*`), with a command-reachability check and a no-horizontal-overflow check at 1440,
1024 and 390 px.

```bash
cd backend
python -m unittest discover -s tests -v
ruff check .
npm --prefix frontend run test:e2e
```
