# Structural dynamics

## In brief

NOVA computes natural frequencies, damping ratios and mode shapes of the blade and the tower
**without aerodynamics**. Four blocks cover the usual design questions: the clamped blade, the
rotating blade, the tower, and the Campbell diagram of the whole turbine against rotor speed. Two
input blocks, *point mass* and *spring & damper*, add concentrated masses, springs and dampers
anywhere along the blade or the tower.

The same solver produces the mode shapes that the OpenFAST case block writes into ElastoDyn, so the
frequencies reported by the modal blocks and those of a generated flexible OpenFAST case agree.

## In detail

### Beam model

Every component is an Euler–Bernoulli beam over its normalised length, clamped at the root (blade)
or base (tower), with mass per length $m(x)$ and bending stiffness $EI(x)$ interpolated linearly from
the station tables of the *Blade structure* and *Tower* blocks. The beam is divided into 80 finite
elements with cubic Hermite shape functions (deflection and slope at each node) and consistent mass
matrices:

$$
K_e = \frac{EI}{h^3}\begin{bmatrix}12 & 6h & -12 & 6h\\ 6h & 4h^2 & -6h & 2h^2\\ -12 & -6h & 12 & -6h\\ 6h & 2h^2 & -6h & 4h^2\end{bmatrix},\qquad
M_e = \frac{m h}{420}\begin{bmatrix}156 & 22h & 54 & -13h\\ 22h & 4h^2 & 13h & -3h^2\\ 54 & 13h & 156 & -22h\\ -13h & -3h^2 & -22h & 4h^2\end{bmatrix}
$$

The undamped modes solve the generalised eigenproblem $K\phi = \omega^2 M\phi$. With about 160
degrees of freedom a dense symmetric solver is exact and takes milliseconds; iterative methods
(Arnoldi, Lanczos) only pay off for large three-dimensional finite-element models.

Flap and edge (blade) and fore-aft and side-to-side (tower) are solved as separate, uncoupled
bending problems. Structural twist, precone, torsion and Coriolis coupling are not modelled.

### Rotating blade

Rotation at $\Omega$ puts the blade in tension,

$$T(x) = \Omega^2 \int_x^L m(s)\,(r_\text{hub} + s)\,\mathrm{d}s \;+\; \text{tip and point masses outboard of } x,$$

which adds the geometric stiffness $\Omega^2 K_G$ with, per element,

$$K_{G,e} = \frac{T}{30h}\begin{bmatrix}36 & 3h & -36 & 3h\\ 3h & 4h^2 & -3h & -h^2\\ -36 & -3h & 36 & -3h\\ 3h & -h^2 & -3h & 4h^2\end{bmatrix}.$$

Flapwise modes solve $(K + \Omega^2 K_G)\phi = \omega^2 M\phi$. Edgewise (in-plane) modes also lose
the centrifugal component along the deflection, $-\Omega^2 M$ (*spin softening*), so for a uniform
blade $\omega_\text{edge}^2 = \omega_\text{flap}^2 - \Omega^2$ at the same speed.

For a uniform cantilever without hub offset the first flap frequency matches the reference values
of Wright et al. (1982) to better than 0.02 % (non-dimensional speed 1–5).

### Tower

The tower is clamped at the base. The nacelle, hub and blade masses are lumped at the top (or the
block's `top_mass_kg` overrides them) together with an optional top rotary inertia. Foundation
flexibility can be represented with a *spring & damper* block at the base region.

### Attachments, damping

*Point mass* and *spring & damper* blocks chain: each appends its item to the list it receives, and
the list enters the modal blocks through one optional input. Attachments are distributed with the
Hermite shape functions, so they need not coincide with a node. Point masses also contribute to the
centrifugal tension of a rotating blade.

The structural damping ratio of the *Blade structure* and *Tower* blocks is applied to every mode.
When a discrete damper is present, NOVA builds the full damping matrix (modal damping plus dampers)
and solves the $2n$ state-space eigenproblem, reporting damped frequency and damping ratio for each
mode.

### Campbell diagram

The *Campbell diagram* block sweeps the rotor speed and, at each speed:

- computes the blade flap and edge modes in the rotating frame;
- keeps the tower modes, which do not depend on rotor speed in this model;
- draws the excitation lines $h\,\Omega/2\pi$ for the harmonics $1P$, $BP$ and $2BP$ ($B$ blades),
  or the harmonics given in the block;
- tracks every mode from one speed to the next with the modal assurance criterion (MAC), so modes
  keep their identity when frequencies come close; a tracking MAC below 0.8 is reported.

Crossings between modes and excitation lines are found by linear interpolation. At the operating
speed the block reports each frequency and the smallest relative distance from any excitation line
(`min_excitation_margin_pct`), which a constraint block can check (the template asks for at least
10 %). For rotors with three or more blades the approximate fixed-frame whirl frequencies
$f \pm \Omega/2\pi$ of the asymmetric blade modes are also returned, assuming an isotropic rotor.

### Mode identification

Every mode carries a label (component, direction and order), the number of zero crossings of its
shape and the shape itself sampled at 41 points, normalised to unit maximum and positive at the free
end.

### Limitations and verification route

The model has no rotor–tower coupling, no aerodynamics (and therefore no aerodynamic damping) and no
gyroscopic effects. The planned verification is OpenFAST linearisation of the same structure
(ElastoDyn, aerodynamics off, multi-blade coordinate transform), overlaid on the NOVA Campbell
diagram.

### Code

- `backend/nova/physics/modal.py`: beam matrices, rotation, attachments, damped solution, MAC
  tracking, Campbell diagram.
- `backend/nova/physics/beam_modes.py`: ElastoDyn polynomial fit of the mode shapes (OpenFAST cases).
- `backend/nova/blocks/structural.py`: block handlers; template `structural_campbell`.
- `backend/tests/test_modal.py`: analytical and literature checks.

### References

- Wright, A. D., Smith, C. E., Thresher, R. W., Wang, J. L. C. (1982). *Vibration modes of
  centrifugally stiffened beams*. Journal of Applied Mechanics 49(1), 197–202.
