# Blade sections and shell finite elements

## In brief

The *Blade layup* block turns the connected rotor (chord, twist and airfoil along the span) and a
simple layup — a shell, spar caps and shear webs, each with its modulus, shear modulus, density and
thickness — into a blade structure: mass, axial, bending, torsional and shear stiffness, inertias,
centre-of-mass offset and structural twist at every station. That record feeds every structural
block (modes, Campbell diagram, flexible performance) exactly like a hand-entered table.

The same layup also drives a 3-D shell finite-element model of the blade, solved for its natural
frequencies by **CalculiX** through an external adapter (*Blade shell modes* block). CalculiX is
installed independently (GPL-2.0) and configured in Settings → Integrations; Nova only writes the
input deck and reads the text output.

## In detail

### Section outline

The outline is a NACA four-digit airfoil (the rotor's section when it is a NACA name, otherwise a
44-series of the rotor's thickness, or the code you set), a circle at the root, or a linear blend of
the two over a transition length (`root_cylinder_fraction`, `transition_fraction`,
`root_diameter_m`). Coordinates: $y$ along the chord from the leading edge, $z$ normal to it.

### Thin-wall properties

The wall is split into straight segments of length $ds$, thickness $t$ and smeared isotropic
properties $E, G, \rho$ (the spar cap region is the shell plus the cap, with thickness-weighted
moduli and density). Then

$$
EA = \sum E t\,ds,\qquad (y_c, z_c) = \frac{1}{EA}\sum E t\,ds\,(y, z),
$$

$$
EI_{zz} = \sum E t\,ds\,(z - z_c)^2,\quad EI_{yy} = \sum E t\,ds\,(y - y_c)^2,\quad EI_{yz} = \sum E t\,ds\,(y - y_c)(z - z_c)
$$

(plus each segment's own bending about its mid-line), whose principal values are the flapwise
(smaller) and edgewise stiffnesses; the principal angle is added to the aerodynamic twist to give the
structural twist. Torsion uses the closed multi-cell Bredt–Batho theory: the webs split the section
into cells $k$ of enclosed area $A_k$; with $\delta_{kj} = \oint ds/(Gt)$ along the shared walls,

$$
\sum_j \delta_{kj}\, q_j = 2 A_k\, \theta',\qquad GJ = \sum_k 2 A_k\, q_k \big/ \theta' .
$$

Shear stiffnesses are $\sum G t\,ds \cos^2\alpha$ and $\sum G t\,ds \sin^2\alpha$ ($\alpha$ the wall
angle, no correction factor). Mass, centre of mass and mass moments of inertia per length follow from
$\rho t\,ds$. Laminate couplings, warping and the wall's through-thickness bending are neglected.

Checks (`backend/tests/test_layup_calculix.py`): a thin circular tube reproduces
$EI = \pi r^3 t E$, $GJ = 2\pi r^3 t G$ and $m = 2\pi r t\rho$ to 10⁻⁴, and a web on the diameter of a
tube carries no shear flow (two-cell $GJ$ equal to the single cell's).

### Shell model for CalculiX

The outer surface is lofted through the section outlines (twisted about the pitch axis) and meshed
with four-node shells (S4); each web is a strip of shells between the upper and lower surfaces. Span
bands and regions (shell, spar cap, webs) get their own material and thickness; the spar cap tapers
linearly from root to tip. The root ring is clamped and a `*FREQUENCY` step extracts the requested
modes. The adapter runs `ccx -i` on two threads and reads the eigenvalue table of the `.dat` file. When
the beam modes are connected, each shell mode is paired with the nearest-frequency beam mode.

The adapter and the deck were tested with a stand-in executable; a test against a real CalculiX run is
included and runs when `NOVA_CCX` points to the solver. No CalculiX result was available while
writing this page.

### Code

- `backend/nova/physics/section_properties.py`: outlines and thin-wall properties.
- `backend/nova/physics/blade_shell.py`: CalculiX deck writer and `.dat` parser.
- `backend/nova/adapters/calculix.py`: external adapter.
- `backend/nova/blocks/fem.py`: *Blade layup* and *Blade shell modes* blocks.
