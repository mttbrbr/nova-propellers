# Rotor models and block workflows

Status: `preliminary`. The models below reproduce textbook behaviour and pass
the physics invariants in `backend/tests/test_rotor_physics.py`; none has been
qualified against measured rotor data yet. All built-in section polars are
synthetic demonstration data and every result says so.

Code: `backend/nova/physics/` (models), `backend/nova/blocks/` (workflows),
`backend/nova/transport/rotor_api.py` (HTTP).

## One Design flow for every rotor type

The rotor type is chosen in **Sizing** and the same four stages adapt:

| Stage | Air propeller | Marine propeller | HAWT | VAWT |
|---|---|---|---|---|
| Sizing | thrust + disk loading → D (actuator disk) | effective thrust, V_s, w, t, rpm, J → D; Keller → A_E/A_0 | rated power, rated wind, Cp, η → R | rated power, wind, Cp, η, H/D, σ → R, H, c |
| Geometry | Bézier/Laguerre blade, airfoil loft, 3D | B-series Z, A_E/A_0, P/D | Burton optimum or explicit blade | H- or Φ-rotor, struts, shaft |
| Analysis | native solvers (BEMT, LLT, VLM, BEM) | BEMT, hull & immersion | BEMT | SST, DS, MST, DMST |
| Corrections offered | native BEMT (Prandtl) | tip, hub | tip, hub, high induction, Snel | finite AR, curvature, dynamic stall, high induction, struts, shaft |
| Results | native results | open-water diagram, cavitation, thrust check | Cp–λ, CT, CQ, power check | Cp–λ, azimuthal loads, power check |

Corrections that do not apply to a type are hidden in Analysis, explained
("not applicable") and rejected by the API. Marine, HAWT and VAWT designs are
saved as `rotor` simulations in v2 projects; each run stores the operating
point and the performance curve, and Results can overlay any earlier run of
the same simulation. Changing the rotor type starts a new simulation draft;
saved simulations never change type. The air propeller keeps the native
pipeline; unifying its BEMT with the rotor engine is a later step.

## Rotor families

| Family | Model | Main outputs |
|---|---|---|
| HAWT (wind/tidal) | Axial BEMT, turbine mode | P, Q, T, Cp, CT, CQ, λ |
| VAWT (H-rotor, Φ-rotor) | Streamtube family (below) | P, Q, streamwise force, Cp, CT, CQ, azimuthal α, torque, induction |
| Air propeller | Axial BEMT, propeller mode | T, Q, P, KT, KQ, J, η, figure of merit (static) |
| Marine propeller | Axial BEMT + marine theory | KT, 10KQ, η₀, η_H, η_D, σ₀.₇R, τc, Keller AE/A0, local σ |

Every family produces a performance curve: Cp–λ at fixed free stream for
turbines (rotational speed varied, λ = ΩR/V), KT/10KQ/η–J at fixed rpm for
propellers (J = V/(nD)).

## Axial BEMT

Each station is solved for its inflow angle φ with Ning's (2014) 1-D residual,
bracketed by a vectorized scan and refined by bisection, so there is no
relaxation factor to tune. The physical root is the rising zero crossing; in
the momentum region 1/(1 − a) is evaluated as 1 + k to avoid the spurious pole
at k = −1. Turbine and propeller modes use the usual sign conventions
(α = φ − θ and α = θ − φ). The propeller residual
`Ωr sinφ (1 − k) − V cosφ (1 + k')` remains valid at V = 0 (static thrust).

Validation invariant: a drag-free Glauert-optimum rotor at λ = 7 without tip
loss reaches Cp ≈ 0.55–0.57 with a ≈ 1/3 along the span (theory 0.570).

## VAWT streamtube family

| Method | Momentum balance |
|---|---|
| Single streamtube (Templin) | one actuator disk for the whole rotor |
| Double streamtube | one disk upwind, one downwind, in tandem |
| Multiple streamtube (Strickland) | one disk per streamtube, both blade passages |
| Double-multiple streamtube (Paraschivoiu) | two disks per streamtube; downwind sees V_e = V(1 − 2a_u) |

The blade sits at r(−cos θ, sin θ) with the wind along +x; reported azimuths
are shifted so 0–180° is upwind. The equilibrium velocity is floored at 0.2 V
when the upwind disk enters the turbulent-wake state, and the iteration uses
adaptive relaxation. Streamtubes next to θ = ±90° have vanishing width, so the
induction there is ill-conditioned (a known DMST property); their contribution
to power is small. Troposkien blades use a parabolic shape with height levels
solved independently.

## Corrections

| Correction | Axial rotors | VAWT |
|---|---|---|
| Tip loss | Prandtl; Shen et al. (2005) | Finite aspect ratio (Lanchester–Prandtl lift slope + induced drag) |
| Hub loss | Prandtl | Central-shaft wake velocity deficit |
| High induction | Glauert, Buhl, Spera | Glauert, Buhl, Spera on each disk |
| 3-D rotation | Snel (inboard of 0.8R) | — |
| Compressibility | Prandtl–Glauert (M ≤ 0.7) | — |
| Flow curvature | — | Virtual incidence at 3/4 chord (Migliore) |
| Dynamic stall | — | Gormont with Berg blending (A_M = 6) |
| Parasitic | — | Strut drag torque |

All polars are extended to ±180° with Viterna–Corrigan and a flat-plate
mirror for reversed flow.

## Marine propellers

Open-water coefficients, hull interaction (V_A = V_s(1 − w), η_H = (1 − t)/(1 − w),
η_D = η₀ η_H η_R), cavitation number at 0.7R, Burrill thrust loading τc with
A_P/A_D ≈ 1.067 − 0.229 P/D, Keller's minimum expanded area ratio and the
local section σ at top dead centre. The blade outline follows the Wageningen
B-series chord distribution.

Burrill acceptance lines are **not** hard-coded: published curve fits
disagree, so read the limit for the computed σ₀.₇R from your reference chart
and enter it as a `burrill` constraint.

## Block workflows

Schema 2 workflows are typed DAGs. Port types: `record` (named scalars),
`rotor_spec`, `rotor_result`, `table`, `report`. Only equal types connect.

* **General blocks** work on named quantities and are domain-free:
  parameter / parameter set (with min/max limits that fail the run when
  exceeded), expression (safe arithmetic, e.g. `power_w / 1000`), merge,
  constraints, sweep, feasible filter, select best, optimizer (grid,
  Nelder–Mead with penalty, COBYLA with constraints as inequalities), report.
* **Specific blocks** define the engineering problem: HAWT/VAWT/propeller/
  marine rotors, operating point (fluid, velocity, rpm/λ/J), hull & immersion,
  axial or VAWT corrections, rotor solver, performance curve and design checks.

Rotor and operating blocks accept *bindings* (`geometry.radius_m = D / 2`) so
requirements drive the specification. Constraint checks are
`quantity operator limit` with hard or soft severity and a normalised margin;
design checks provide domain presets (Betz, rated power, tip speed, tip Mach,
thrust, Keller, Burrill, local cavitation, torque ripple, peak incidence,
solidity). With `on_violation: "stop"` a violated hard limit blocks every
downstream block. Failed blocks also block their dependants, and the run
reports `succeeded`, `stopped` or `failed` plus overall feasibility.

Templates: HAWT rated design, VAWT DMST with corrections, marine cavitation
check, HAWT constrained optimisation, propeller diameter sweep.
