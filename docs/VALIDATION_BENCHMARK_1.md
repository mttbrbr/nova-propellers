# Benchmark 1 selection: UIUC APC Thin Electric 10×5

## Audit and selection

The initial shortlist used UIUC Volume 1 APC Thin Electric 9×4.5, 9×6, 10×5,
10×7 and 11×5.5. Each is a conventional two-blade propeller with static data
and forward-flight CT, CP and efficiency sweeps at several nominal speeds.

| candidate | dynamic RPM coverage | online digitized geometry | assessment |
| --- | --- | --- | --- |
| APC Thin Electric 9×4.5 | about 4000–6900 | yes | complete, smaller chord and lower Re |
| APC Thin Electric 9×6 | about 4000–6700 | yes | complete, higher pitch |
| **APC Thin Electric 10×5** | **4005–6710, seven runs** | **yes, 18 stations** | **best first case** |
| APC Thin Electric 10×7 | 4007–6531, seven runs | yes | complete, broader high-J operation |
| APC Thin Electric 11×5.5 | about 3000–6000 | yes | complete, larger diameter |

APC 10×5 was selected because it combines a moderate pitch, complete static
and dynamic measurements, multiple RPM/Reynolds regimes, direct CT/CP/eta
columns, and a simple two-blade geometry. UIUC also uses APC 10×5E and 10×7E
in its comparison with Ohio State data, adding independent usefulness for a
later cross-facility check. Benchmark 1 evaluates all seven published dynamic
runs (4005, 4993, 5000, 6005, 6018, 6707 and 6710 rpm). Results include both
overall metrics and an RPM breakdown so Reynolds/RPM trends cannot be hidden
by one aggregate.

The selection is scientific, not licensing-driven. UIUC's downloadable file
and approximate geometry have no explicit redistribution license identified,
so neither is committed. APC manufacturer geometry is a distinct source with
separate, likewise unspecified redistribution terms.

## Measurement conventions

UIUC Volume 1 defines `n` as revolutions per second and `D` as diameter:

- `J = V_inf / (n D)`
- `CT = T / (rho n² D⁴)`
- `CP = P / (rho n³ D⁵)`
- `eta = J CT / CP`

The adapter preserves the tabulated nondimensional values. At the solver
boundary it converts `RPM / 60` to `n` and reconstructs `V_inf = J n D` in SI.
It compares power coefficient, not torque coefficient. Static `J=0` data uses
a separate three-column format and is not silently mixed into this dynamic
case.

## Known limitations

- UIUC labels the published geometry as approximate digitization.
- Exact per-run atmospheric values are not encoded in the coefficient file;
  the declared density/viscosity are explicit assumptions for dimensional
  solver execution, while both sides are compared nondimensionally.
- Nova currently uses its built-in synthetic NACA 4412 polar assumption. This
  is not claimed to be the APC section and is expected to be a major source of
  model discrepancy.
- No solver coefficient, loss model or polar is calibrated to this benchmark.
- The online data include UIUC's later mounting-fixture drag correction and
  supersede the older thesis tables.
