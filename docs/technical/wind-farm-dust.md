# Wind farms and DUST

## In brief

Four blocks build a wind farm from a Nova rotor: **Farm turbine** (power and thrust curves along the
operating strategy, with the hub height), **Farm layout** (a rotated, optionally staggered grid in
rotor diameters, or explicit coordinates), **Wind climate** (direction sectors and Weibull speeds as a
joint probability table) and **Wind farm AEP** (energy with wakes, per turbine and in total). The wake
model is Nova's own NOJ (Jensen) implementation, or PyWake through the existing external adapter.

**DUST rotor** checks the rotor with DUST, the mid-fidelity vortex-particle solver of Politecnico di
Milano (MIT licence, installed independently): Nova writes the case, DUST runs its pre-processor,
solver and post-processor, and Nova compares the mean loads of the last revolution with its BEMT.

## In detail

### NOJ wake model

As in PyWake's `NOJ` defaults: behind turbine $i$ at downstream distance $x$ the deficit is

$$
\Delta U = U_\infty\,\bigl(1 - \sqrt{1 - C_{T,i}}\bigr)\Bigl(\frac{R}{R + kx}\Bigr)^2 ,
$$

with $C_{T,i}$ at turbine $i$'s effective speed; a downstream rotor takes it weighted by the fraction
of its disc inside the wake circle (area overlap), and deficits from several wakes add as a root sum
of squares. Turbines are solved in downstream order. Flat terrain, uniform inflow, one turbine type,
no turbulence or wake-meandering model; wind directions are meteorological (where the wind comes
from, clockwise from north; $x$ east, $y$ north).

The farm turbine's thrust coefficient is the BEMT $C_T$ at each schedule point; above rated power it
is scaled by $C_P/C_{P,\text{available}}$ as an approximation of pitch regulation.

### Wind climate

Each sector's Weibull distribution is integrated over speed bins centred on the requested speeds.
Probability outside the bins (calms below the first bin, storms above the last) is reported as
`excluded_probability`; the table is normalised to sum to one (as PyWake requires) and the energy is
multiplied by one minus the excluded probability.

Checks (`backend/tests/test_farm_dust.py`): overlap fractions against the analytic lens area, a
single aligned wake against the closed form, no wake across the wind, Weibull binning, and a farm
chain from the rotor to the cost model.

### DUST case

Nova writes, after DUST's example cases and its C81 reader:

- `blade.in`: a parametric lifting-line component (`ElType = l`) with sections at evenly spaced radii
  (chord, twist, airfoil table) and regions between them;
- `References.in`: a `Hub` frame with rotor multiplicity (number of blades, rotation about $z$ at the
  operating speed);
- one C81 table per section, tabulated from Nova's polar at that section's Reynolds number (91 angles,
  1° steps within ±30°; two Mach columns with the same data; zero pitching moment);
- `dust_pre.in`, `dust.in` (time step from the requested steps per revolution, vortex-particle wake,
  fast multipole) and `dust_post.in` with an `integral_loads` analysis in the global frame.

The rotor axis is global $z$, the wind blows along $+z$ and a blade at $+y$ moves towards $-x$. DUST's
twist raises the incidence of this inflow, so the turbine twist (which lowers it) is written with the
opposite sign. Thrust is $F_z$, torque $M_z$ and power $M_z\Omega$, averaged over the last revolution.
DUST uses its default air density, so the block accepts air only.

The three-stage adapter was tested with stand-in executables. **The case has not been run with a real
DUST build**: building DUST locally was not possible in this session, so the frame and sign
conventions above are checked against the DUST examples only. Run the block once against a known
rotor before relying on it.

### Code

- `backend/nova/physics/farm.py`, `backend/nova/blocks/farm.py`
- `backend/nova/physics/dust_case.py`, `backend/nova/adapters/dust.py`

### References

- Jensen, N. O. (1983). *A note on wind generator interaction*. Risø-M-2411.
- Katic, I., Højstrup, J., Jensen, N. O. (1986). *A simple model for cluster efficiency*. EWEC 1986.
- DUST — <https://gitlab.com/dust_group/dust> (MIT licence).
