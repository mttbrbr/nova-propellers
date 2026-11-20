# Structural dynamics

## In brief

NOVA computes natural frequencies, damping ratios and coupled mode shapes of the blade and the
tower **without aerodynamics**, on a three-dimensional beam model of the same kind as OpenFAST
BeamDyn. Four blocks cover the usual design questions: the clamped blade, the rotating blade, the
tower, and the Campbell diagram against rotor speed. Two input blocks, *point mass* and *spring &
damper*, add concentrated masses, inertias, springs and dampers anywhere along the blade or the
tower.

The more section data you give, the more of the physics the model includes. With only mass and
the two bending stiffnesses it reduces exactly to an Euler–Bernoulli beam. Shear, axial and
torsional stiffness, rotary inertias, structural twist and the centre-of-mass offset add shear
deformation, torsion and the couplings between them.

## In detail

### Beam model

Each component is a geometrically linear Timoshenko beam with six degrees of freedom per node:
axial displacement $u_1$, in-plane and out-of-plane displacements $u_2, u_3$, torsion $\theta_1$
and the two section rotations $\theta_2, \theta_3$. The generalised strains are

$$
\boldsymbol\varepsilon = \begin{bmatrix} u_1' & u_2' - \theta_3 & u_3' + \theta_2 & \theta_1' & \theta_2' & \theta_3' \end{bmatrix}^\mathsf{T},
$$

related to the section forces and moments by a 6×6 stiffness matrix
$\mathbf C = \mathbf Q\,\operatorname{diag}(EA, GA_\text{in}, GA_\text{out}, GJ, EI_\text{out}, EI_\text{in})\,\mathbf Q^\mathsf{T}$,
where $\mathbf Q$ rotates the principal axes by the local structural twist. The 6×6 section mass
matrix is that of a rigid slice with mass $m$, centre of mass offset $\boldsymbol\xi$ and inertia
$\mathbf J$ about its centre of mass:

$$
\mathbf M_s = \begin{bmatrix} m\mathbf I & -m\tilde{\boldsymbol\xi} \\ m\tilde{\boldsymbol\xi} & \mathbf J + m\tilde{\boldsymbol\xi}^\mathsf{T}\tilde{\boldsymbol\xi} \end{bmatrix}.
$$

Through the twist, flap and edge bending are coupled. Through the offset, bending is coupled with
torsion (and edge with axial motion).

Frames: for a blade $x$ runs along the span, $y$ lies in the rotor plane (edgewise) and $z$ along
the rotor axis (flapwise). For the tower $x$ points up, $y$ is side-to-side and $z$ fore-aft
(downwind).

### Discretisation

The beam is split into spectral finite elements: Lagrange polynomials up to order 6 on
Gauss–Lobatto–Legendre nodes. Element boundaries sit on the user's stations, so the linearly
varying properties are integrated exactly inside each element. Stiffness uses reduced Gauss
quadrature, which avoids shear locking, while mass and rotation terms use full quadrature. With
more than 40 stations the elements are evenly spaced. The order is lowered as the number of
elements grows, keeping the model near 120 nodes (about 700 degrees of freedom).

### Missing data

NOVA does not invent section properties:

| Not given | Treatment |
| --- | --- |
| Axial stiffness $EA$ | axially rigid (penalty about $10^6\,EI/L^2$); no axial modes reported |
| Shear stiffness $GA$ | shear-rigid (same penalty): Euler–Bernoulli bending |
| Torsional stiffness $GJ$ | torsionally rigid; no torsion modes reported |
| Rotary or torsional inertia | zero; the motions without inertia are condensed statically |
| Structural twist | aerodynamic twist plus pitch from the connected rotor (setting `use_aerodynamic_twist`), otherwise none |
| Centre-of-mass offset | zero |

Static condensation acts on the null space of the mass matrix, so it is exact for every motion
without inertia, including combined ones: a section rotation whose only inertia comes from an
offset centre of mass, for example. With mass and bending stiffness only, the first three flap
frequencies of a uniform cantilever match $(\beta L)^2 = 3.516, 22.03, 61.70$ to within $2\times10^{-4}$.

On a tubular tower NOVA derives every property from the material: $EA$, $GJ = G\,2I$,
$GA = 0.5\,G A$ (thin circular tube), $\rho I$ and $\rho\,2I$, with Poisson ratio 0.3.

### Rotating blade

Rotation at $\Omega$ about the rotor axis $z$ adds, in the rotating frame:

- **centrifugal stiffening**: the tension
  $T(x) = \Omega^2 \int_x^L m(s)(r_\text{hub}+s)\,\mathrm ds$ (plus point masses outboard) gives the
  geometric stiffness $\int T\,(u_2'^2 + u_3'^2)/2$;
- **centrifugal softening** of the in-plane motions, $-m\,\tilde{\boldsymbol\Omega}^\mathsf{T}\tilde{\boldsymbol\Omega}$
  applied to the displacement of the centre of mass ("spin softening" of edgewise modes);
- **Coriolis / gyroscopic coupling** $2m\tilde{\boldsymbol\Omega}$ between axial and edgewise motion,
  and the gyroscopic coupling of the section rotations, $(J_1 + J_2 - J_3)\,\Omega$ as in Euler's
  equations;
- **propeller moment**: the torsional stiffening $(J_3 - J_2)\Omega^2$, so a thin section with its
  chord in the rotor plane follows $\omega_t^2 = \omega_{t0}^2 + \Omega^2$;
- the centrifugal moment of an offset centre of mass.

Precone, prebend, sweep and the tension "trapeze" effect on torsion are not modelled.

### Tower

The tower is clamped at the base. Two rigid bodies sit at its top:

- the nacelle, with its centre-of-mass offset (`cm_up_m`, `cm_lateral_m`, `cm_downwind_m`) and yaw
  inertia;
- the parked rotor (hub plus blades) at the shaft height and overhang, with the polar inertia about
  the shaft and half of it about the other two axes.

The block's `top_mass_kg` and `top_inertia_kg_m2` replace these bodies with a single mass.
Foundation flexibility can be represented with a *spring & damper* block near the base.

### Attachments and damping

*Point mass* and *spring & damper* blocks chain: each appends its item to the list it receives.
Attachments are spread with the element shape functions, so they need not sit on a node.
`direction` chooses the degrees of freedom:

- for springs and dampers: `flap`/`edge`, or `fore_aft`/`side_side`, `both`, `torsion`, `axial`;
- for point masses: the rotations that the inertia acts on.

Point masses contribute to the centrifugal tension and to the rotating-frame terms.

Structural damping ratios from the *Blade structure* block apply by mode family: flap, edge, and
the lower of the two for torsion and axial modes. The *Tower* block applies one ratio to all
modes. When there are gyroscopic terms (rotation) or discrete dampers, NOVA solves the
state-space problem in the basis of the lowest 40 undamped modes. It reports the damped frequency
and damping ratio of each mode.

### Solution and mode identification

The condensed undamped problem is solved densely. With a few hundred degrees of freedom this is
exact and takes milliseconds. Iterative Arnoldi or Lanczos solvers would only pay off for large
three-dimensional finite-element models. NOVA limits BLAS to one thread (environment variables
`OPENBLAS_NUM_THREADS` etc.): at this size, extra threads slow the solution down.

Each mode is classified by its kinetic-energy share among axial, in-plane, out-of-plane and
torsional motion: blade *flap*, *edge*, *torsion*, *axial*; tower *fa*, *ss*, *torsion*, *axial*.
Each mode carries:

- its label and order within the family;
- the shares (`share_*` columns of the table);
- the number of zero crossings;
- every displacement component sampled at 41 points, scaled so that the dominant component peaks
  at +1.

### Campbell diagram

The *Campbell diagram* block sweeps the rotor speed. At each speed it:

- computes the blade modes in the rotating frame;
- keeps the tower modes, which do not depend on rotor speed in this model;
- draws the excitation lines $h\,\Omega/2\pi$ for $1P$, $BP$ and $2BP$ ($B$ blades), or the
  harmonics set in the block;
- tracks every mode from one speed to the next with the complex modal assurance criterion (MAC),
  reporting any mode whose tracking MAC drops below 0.8.

Crossings with the excitation lines are found by linear interpolation. At the operating speed the
block reports each frequency and the smallest relative distance from any excitation line,
`min_excitation_margin_pct`, which a constraint block can check. For rotors with three or more
blades the approximate fixed-frame whirl frequencies $f \pm \Omega/2\pi$ are also returned,
assuming an isotropic rotor.

### Verification

`backend/tests/test_modal.py` checks the model against reference solutions:

| Case | Reference |
| --- | --- |
| Uniform cantilever, Euler–Bernoulli limit | $(\beta L)^2$, first three modes |
| Uniform rotating cantilever, first flap | Wright et al. (1982), $\bar\Omega = 1$–$5$ |
| Uniform Timoshenko cantilever with shear and rotary inertia | exact transfer-matrix solution |
| Uniform torsion | $\omega = (2k-1)\,\pi/2\,\sqrt{GJ/I}/L$ |
| Spin softening with rigid axial stretch | $\omega_\text{edge}^2 = \omega_\text{flap}^2 - \Omega^2$ |
| Propeller moment | $\omega_t^2 = \omega_{t0}^2 + \Omega^2$ |
| Constant twist | frequencies invariant |
| Tip mass | characteristic equation of the cantilever with tip mass |
| Stiff tip spring | pinned–clamped beam |
| Discrete damper | first-order modal estimate of the damping ratio |
| AOC 15/50 blade, untwisted | converged Euler–Bernoulli result written into ElastoDyn, within 0.2 % |

Not modelled: rotor–tower coupling (multi-blade coordinates), aerodynamics and aerodynamic
damping, precone and prebend. The planned cross-check is OpenFAST linearisation of the same
structure (ElastoDyn or BeamDyn, aerodynamics off, MBC3).

The ElastoDyn files that the OpenFAST case block writes still use Euler–Bernoulli mode shapes
fitted to ElastoDyn's polynomial, because that is the input ElastoDyn accepts
(`backend/nova/physics/beam_modes.py`).

### Rotor–tower coupling (multi-blade coordinates)

With `coupling = "mbc"` the Campbell block no longer treats the rotor as a rigid body on the tower. The
generalised coordinates are the tower modal coordinates $\boldsymbol\eta$ (clamped tower with the
nacelle at the top, *without* the rotor) and, for each blade $b$, the rotating-frame modal coordinates
$\mathbf q_b$ of the 3-D beam at the current speed (centrifugal stiffening and spin softening included,
Coriolis matrix kept). A point of blade $b$ at radius $r$ is at

$$
\mathbf P = \mathbf p_\text{top} + \mathbf u(\boldsymbol\eta) + \mathbf R(\boldsymbol\theta(\boldsymbol\eta))\,\bigl(\mathbf d + r\,\mathbf e_r(\psi_b) + u_b\,\mathbf e_r + v_b\,\mathbf e_t + w_b\,\mathbf e_z\bigr),
\qquad \mathbf R \approx \mathbf I + [\boldsymbol\theta\times] + \tfrac12[\boldsymbol\theta\times]^2 ,
$$

with $\mathbf u, \boldsymbol\theta$ the tower-top translation and rotation, $\mathbf d$ the hub centre
from the tower top (shaft height, overhang) and $\psi_b = \psi + 2\pi b/B$. Expanding the kinetic energy
to second order gives the mass coupling between tower and blades, the Coriolis and centrifugal terms
and the gyroscopic and centrifugal terms of the tower-top rotations. Every term reduces to five mass
moments of a blade ($\sum m$, $\sum m r$, $\sum m r^2$, $\sum m\mathbf Y$, $\sum m r\mathbf Y$ with
$\mathbf Y$ the modal displacements), so the cost does not grow with the blade resolution. The
blade–blade block is the beam's own rotating-frame model; a hub is a ring of point masses with its
polar inertia. The periodic equations
$\mathbf M(\psi)\ddot{\mathbf x} + \mathbf D(\psi)\dot{\mathbf x} + \mathbf K(\psi)\mathbf x = 0$ are
transformed with $\mathbf q_b = \mathbf q_0 + \sum_h (\mathbf q_{hc}\cos h\psi_b + \mathbf q_{hs}\sin h\psi_b)\,[+\,\mathbf q_d(-1)^b]$
and the first-order system matrix is averaged over 36 azimuths (MBC3, Bir 2008). Modes are labelled by
their largest participation and, for blade modes, by the phase between the cosine and sine
components: collective, backward whirl (BW) or forward whirl (FW). They are tracked from the highest
speed down, where the whirl pairs are well separated.

The coupling needs the tower and nacelle blocks and at least three blades. It ignores gravity,
aerodynamics, shaft tilt, precone and the drivetrain (no generator degree of freedom).

Checks (`backend/tests/test_coupled.py`):

- a tower 10⁵ times stiffer gives the isolated rotating blade for the collective mode and
  $f \mp \Omega/2\pi$ for the backward and forward flap and edge whirl modes (0.1 %);
- at standstill with very stiff blades the tower modes equal those of the tower carrying the rotor as
  a rigid body (0.2 %).

### Mode view

Every block with a modal result shows a *Modes* button (on the node, in the result card and in the run
summary). It opens a full-screen view: the modes with their participation, the Campbell diagram (or a
table of all modes) and an animated 3-D turbine built from the connected tower, nacelle and rotor. Coupled
modes carry their physical shape — tower fore-aft and side-side along the height and each blade's flap and
edge with the rotor frozen at $\psi = 0$ — as complex fields, so the displacement is
$\operatorname{Re}(\boldsymbol\phi\,e^{i\varphi})$ and whirl modes show the 120° phase lag between blades.
Shapes are stored at up to nine speeds; the amplitude is a visual scale and the animation rate is fixed.

### Verification against OpenFAST linearisation

The *OpenFAST linearisation* block turns a flexible ElastoDyn case (from *OpenFAST case from rotor*)
into a structural linearisation: aerodynamics, inflow, control and gravity off, prescribed rotor
speed, linearisation times spread over one revolution. It parses the `.lin` state matrices, applies
the same multi-blade transformation and averaging, and pairs the OpenFAST modes with the coupled
Campbell curves by nearest frequency (labels from ElastoDyn state amplitudes are unreliable for the
second tower modes, whose degrees of freedom are normalised at the tower top). A synthetic test writes
`.lin` files from Nova's own periodic system and recovers its MBC frequencies to 0.1 %.

On the AOC 15/50 example structure at 60 rpm (OpenFAST 5.0.0, 12 azimuths):

| Mode | OpenFAST (Hz) | Nova (Hz) | Difference |
| --- | --- | --- | --- |
| Tower fore-aft 1 / side-side 1 | 1.574 / 1.578 | 1.572 / 1.576 | −0.1 % |
| Blade flap BW / collective / FW | 3.37 / 4.48 / 5.36 | 3.28 / 4.40 / 5.28 | −1.6 to −2.5 % |
| Blade edge BW / collective / FW | 7.38 / 7.60 / 9.35 | 7.16 / 7.29 / 9.14 | −2.3 to −4 % |
| Tower fore-aft 2 / side-side 2 | 11.37 / 12.90 | 11.10 / 12.96 | −2.4 / +0.5 % |
| Blade flap 2 (BW / collective / FW) | 14.5 / 15.6 / 16.5 | 13.6 / 14.6 / 15.5 | about −7 % |

ElastoDyn uses two polynomial assumed modes per blade direction (Euler–Bernoulli, fitted at
standstill), Nova the converged 3-D beam: the second flap mode, whose shape changes most with
rotation, differs most. Damping is defined differently (ElastoDyn applies it per assumed mode).

### Code

- `backend/nova/physics/modal.py`: sections, spectral beam elements, rotation terms, condensation,
  damped solution, classification, MAC tracking, Campbell diagram.
- `backend/nova/blocks/structural.py`: block handlers; template `structural_campbell`.
- `backend/nova/adapters/openfast_structure.py`: blade and tower records with the optional columns.

### Optional station columns

| Blade structure | Tower (table) | Meaning |
| --- | --- | --- |
| `structural_twist_deg` | — | orientation of the principal axes |
| `axial_stiffness_n` | `axial_stiffness_n` | $EA$ |
| `torsional_stiffness_nm2` | `torsional_stiffness_nm2` | $GJ$ (needs the torsional inertia) |
| `edge_shear_stiffness_n`, `flap_shear_stiffness_n` | `side_side_shear_stiffness_n`, `fore_aft_shear_stiffness_n` | $\kappa GA$ |
| `torsional_inertia_kg_m` | `torsional_inertia_kg_m` | polar mass moment per length about the centre of mass |
| `flap_inertia_kg_m`, `edge_inertia_kg_m` | `fore_aft_inertia_kg_m`, `side_side_inertia_kg_m` | rotary inertia per length of the bending rotations |
| `cm_offset_m` | — | chordwise offset of the centre of mass from the reference axis |

A column is either given at every station or left out entirely.

### References

- Wright, A. D., Smith, C. E., Thresher, R. W., Wang, J. L. C. (1982). *Vibration modes of
  centrifugally stiffened beams*. Journal of Applied Mechanics 49(1), 197–202.
- Bir, G. (2008). *Multi-blade coordinate transformation and its application to wind turbine
  analysis*. AIAA 2008-1300 (NREL/CP-500-42553).
- Wang, Q., Sprague, M. A., Jonkman, J., Johnson, N., Jonkman, B. (2017). *BeamDyn: a
  high-fidelity wind turbine blade solver in the FAST modular framework*. Wind Energy 20(8),
  1439–1462.
