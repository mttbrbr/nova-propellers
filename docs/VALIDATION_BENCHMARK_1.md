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

## Numerical convergence evidence

The full 104-point corpus was evaluated with 18, 36 and 72 radial stations;
all 312 solver calls converged. Relative to the 72-station numerical reference,
the 36-station mean relative changes were 0.291% for CT, 0.553% for CP and
0.279% for efficiency. Maximum relative changes, after the declared near-zero
exclusion, were 0.583%, 1.123% and 1.235% respectively.

The 72-station result is not physical truth. This evidence only shows that the
observed experimental discrepancies are substantially larger than the measured
36-to-72-station sensitivity. It does not validate the aerodynamic model.

The next controlled study compares the already implemented `clip`, bounded
linear-extrapolation and smooth-transition low-Re polar strategies at 36
stations. It is diagnostic: no strategy may be promoted merely because it
fits this same benchmark better.

That study completed with 104/104 converged points for every treatment. CT
MAE was 0.0236292–0.0236319, CP MAE 0.0124026–0.0124060 and efficiency MAE
0.0463229–0.0464239. These differences are negligible relative to the
experimental discrepancy. The evidence does not support changing Nova's
production `clip` default, and suggests that low-Re boundary handling is not
the dominant error source for this corpus. Geometry fidelity and the underlying
section/polar assumptions remain higher-priority uncertainties.

## Radial diagnostic evidence

Four representative conditions were evaluated at 36 stations using the fixed
UIUC planform and twist. At `J=0.149`, where CT is strongly underpredicted,
section angles remain inside the synthetic polar's −8°…16° alpha grid, while
10/36 stations fall below its minimum Reynolds value. The earlier low-Re
treatment study nevertheless showed negligible aggregate response, so merely
changing the boundary extrapolation is not supported as a remedy.

The load does not concentrate at the root: at the low-J diagnostic point,
approximately 4% of thrust comes from `0.15 ≤ r/R < 0.40`, 46% from the middle
region and 50% from `r/R ≥ 0.75`. This weakens the hypothesis that root-only
modeling is the dominant cause. It increases the priority of the assumed
section lift/drag behavior across the middle and outer blade.

At `J=0.549` and near zero thrust around `J=0.671`, some inner stations operate
below the alpha grid. Near zero total thrust, normalized regional percentages
are intentionally not interpreted because positive and negative station loads
cancel. The raw signed loads remain available locally.
