# Algorithm provenance and maturity

Nova implements compact, independently written approximations of established
aerodynamic methods. References document the mathematical background; Nova
does not include source code or data copied from those references.

## NACA four-digit geometry

The analytic four-digit coordinate generator follows the public NACA family
definition. A useful primary reference is NASA TM X-3284, *Development of a
computer program to obtain ordinates for NACA 4-digit, 4-digit modified,
5-digit, and 16 series airfoils*. NASA marks the report as a US Government work
with public use permitted:

<https://ntrs.nasa.gov/citations/19760003945>

## Minimum-induced-loss distribution

The design path described as Larrabee-style is a low-order approximation, not
a reproduction of Larrabee's program. The background reference is E. E.
Larrabee, *Propellers of Minimum Induced Loss, and Water Tunnel Tests of Such a
Propeller*. NASA marks this record as public and a US Government work:

<https://ntrs.nasa.gov/citations/19760003930>

Nova currently uses only a simplified radial circulation shape and must not be
described as a complete implementation of the published design procedure.

## BEMT, lifting-line and vortex methods

The BEMT and lifting-line modules implement standard blade-element, annular
momentum, finite-blade-loss and circulation relationships directly in NumPy.
The VLM and boundary-element modules are architecture prototypes built from a
regularized finite-segment Biot-Savart relation; they are not validated
production solvers.

Until reference equations and acceptance cases are documented in the v0.2
validation milestone, maturity labels remain:

- actuator disk: ideal sizing reference;
- BEMT and LLT: preliminary;
- VLM and BEM: experimental.

The first BEMT contract, deterministic regression case and physics-consistency
checks are now implemented. They verify software behavior but do not yet
qualify predictive accuracy. See [Solver verification and validation](VALIDATION.md)
for the evidence levels, acceptance rules, reproducibility procedure and known
limitations.

## Synthetic polars

`backend/polar_database.py` generates demonstration-only values from an
explicit lift-slope, clipping and quadratic-drag formula. The constants are
project parameters, not imported aerodynamic measurements. These values exist
to exercise the software and UI and cannot qualify a design or solver.
