# Block workflows

## In brief

A block workflow is a **directed acyclic graph** with typed ports: only ports of the same type
connect. It expresses a design problem, for example "find the diameter that meets these
constraints", without writing code.

## In detail

### Port types

The types are `record` (named scalars), `rotor_spec`, `rotor_result`, `table` and `report`, plus
the structural types `hub`, `nacelle`, `tower`, `blade`, `attachment` and `modal`.

### Blocks

- **General blocks** are domain-free and work on named quantities: parameter and parameter set
  (with min/max limits that fail the run when exceeded), expression (safe arithmetic, for example
  `power_w / 1000`), merge, constraints, sweep, feasible filter, select best, optimiser (grid,
  Nelder–Mead with penalty, COBYLA with constraints as inequalities) and report.
- **Specific blocks** define the engineering problem: HAWT, VAWT, propeller and marine rotors,
  operating point, hull and immersion, corrections, rotor solver, performance curve and design
  checks.
- **Structural-dynamics blocks** compute blade, tower and Campbell-diagram modes without
  aerodynamics; see [Structural dynamics](structural-dynamics.md).

Rotor and operating-point blocks accept **bindings** (for example `geometry.radius_m = D / 2`), so
requirements drive the specification.

### Constraints and checks

A constraint has the form "quantity operator limit", with *hard* or *soft* severity and a
normalised margin. Design checks come with presets: Betz, rated power, tip speed, tip Mach, thrust,
Keller, Burrill, local cavitation, torque ripple, peak incidence, solidity.

With `on_violation: "stop"` a violated hard limit blocks every downstream block. Failed blocks also
block their dependants, and the run ends as `succeeded`, `stopped` or `failed`, with the overall
feasibility.

### Templates

HAWT rated design, VAWT DMST with corrections, marine cavitation check, HAWT constrained
optimisation, propeller diameter sweep.
