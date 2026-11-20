# Performance maps and operating strategy

## In brief

Three blocks extend the performance curve:

- **Performance map** finds the optimum of any rotor output over one or two specification fields —
  typically $C_P$ over tip-speed ratio and pitch — on a grid that is refined around the best point,
  then fits an interpolating response surface and checks its optimum with a direct evaluation.
- **Cp–λ flexible & sheared** gives $C_P(\lambda)$ and $C_T(\lambda)$ of a horizontal-axis turbine in
  power-law wind shear and with the steady flapwise deflection of the connected blade structure,
  next to the rigid, uniform-inflow curve.
- **Operating strategy** turns a tip-speed ratio and a wind speed (or the optimum of a connected
  Cp–λ curve) into a rotor speed, and builds the variable-speed schedule from cut-in to cut-out with
  rotor-speed limits and rated power. It emits the rotor at the chosen operating point.

## In detail

### Progressive refinement and response surface

Level 0 evaluates an $n^d$ grid over the full box ($d$ = 1 or 2 variables). Each following level
centres a box shrunk by the factor `shrink` on the best point so far and evaluates a new grid in it,
within the evaluation budget. A thin-plate radial-basis-function interpolant with a linear trend
(SciPy `RBFInterpolator`) is fitted through every successful evaluation in normalised coordinates;
its maximum (or minimum) is found on a dense grid and polished with L-BFGS-B, then evaluated with the
real model. The reported optimum is the better of the sampled and the verified surface optimum;
`surface_error_pct` is the surface's error at that point. Setting the tip-speed (or advance) ratio
removes the rotor speed (or velocity) it replaces, so a fixed rpm never overrides the map.

On the default 5 m HAWT a 5-point, 4-level map reaches the optimum of a 121-point dense curve in fewer
than 30 evaluations with a surface error below 1 % (`backend/tests/test_performance_blocks.py`).

### Flexibility and shear

Shear uses the azimuthally resolved BEMT with $V(z) = V_\text{hub}(z/z_\text{hub})^\alpha$. For
flexibility, the BEMT distributed thrust and torque force of one blade load the rotating 3-D beam of
the structural blocks (centrifugal stiffening included); its static solution gives the flapwise
deflection $w(s)$ and the local cone angle $\beta(s) = \beta_\text{precone} + \arctan(dw/ds)$. A coned
element sees the normal wind $V\cos\beta$ and moves at $\Omega s\cos\beta$, so its speed ratio is
unchanged, its dynamic pressure scales with $\cos^2\beta$ and its torque arm (and the axial projection
of its normal force) with $\cos\beta$:

$$
C_P^\text{flex}(\lambda) = C_P(\lambda)\,\frac{\int \cos^3\beta \; dQ}{\int dQ},\qquad
C_T^\text{flex}(\lambda) = C_T(\lambda)\,\frac{\int \cos^3\beta \; dT}{\int dT}.
$$

The loads on the deflected blade (scaled with $\cos^2\beta$) are recomputed until the cone angles
settle. Elastic twist, prebend, sweep and the in-plane deflection are not fed back into the
aerodynamics. Checks: a very stiff blade gives the rigid curve, a precone alone gives exactly
$\cos^3\beta$, a soft blade loses power, shear lowers $C_P$; a uniformly loaded cantilever deflects
$qL^4/8EI$.

### Steady aeroelastic model (default)

With `model = "aeroelastic"` (the default) the curve is computed on the deformed blade instead of
scaling rigid loads. At every point of the curve the BEMT and the rotating 3-D beam are iterated
(under-relaxed fixed point, usually 2–10 iterations):

1. the BEMT runs on the deformed geometry: every element has its cone angle
   $\beta(s) = \beta_\text{precone} + \arctan(dw/ds)$, sits at the in-plane radius
   $r(s) = r_\text{hub} + \int_0^s \cos\beta\,ds$, sees the normal wind $V\cos\beta$ and the speed
   $\Omega r$, and its twist is reduced by the elastic nose-up torsion $\theta_e(s)$;
2. the element forces become loads per unit span: normal force $f_n$ (flapwise), tangential force
   $f_t$ (edgewise) and the torque $f_\perp d$ of the force normal to the chord, applied at the quarter
   chord, about the elastic axis a distance $d$ behind it (`elastic_axis_offset_m`, filled by the
   layup block from the section's elastic centre);
3. the beam gives the flapwise deflection (centrifugal stiffening included) and the cantilever torsion
   $\theta_e(s) = \int_0^s T/GJ$ with $T(s) = \int_s^L m_t$.

Thrust is $B\int f_n\cos\beta\,ds$ and torque $B\int f_t\,r\,ds$; the coefficients refer to the
undeformed rotor area. With shear, the sheared rigid coefficients are scaled by the aeroelastic-to-rigid
ratio in uniform inflow. Not modelled: prebend, sweep, the edgewise deflection in the aerodynamics,
bend–twist coupling and the propeller moment in the torsion, gravity and unsteady effects.

Checks (`backend/tests/test_aeroelastic.py`): a very stiff blade reproduces the rigid coefficients; an
elastic axis behind the quarter chord twists the blade nose-up and raises the thrust; against OpenFAST
5.0.0 (AeroDyn + ElastoDyn, prescribed speed, tower locked) on the AOC 15/50 example with the bending
stiffness divided by 10 (ElastoDyn has no blade torsion, so the comparison is flapwise only):

| λ | Tip deflection Nova / OpenFAST | Cp change from flexibility Nova / OpenFAST | Rigid Cp Nova / OpenFAST |
| --- | --- | --- | --- |
| 5 | 377 / 353 mm | −0.65 % / −0.78 % | 0.412 / 0.409 |
| 7 | 271 / 248 mm | −0.38 % / −0.54 % | 0.384 / 0.378 |

The 7–9 % larger deflection is consistent with ElastoDyn's two polynomial assumed modes against the
converged beam. The cos³β model (`model = "cone_factor"`) remains available for quick estimates.

### Operating strategy

Region 2 follows the chosen $\lambda$: $n = \lambda V/R \cdot 60/2\pi$. The speed is clipped to
`rpm_min` (region 1.5) and `rpm_max` (region 2.5); power comes from the connected Cp–λ curve at the
actual tip-speed ratio, and above `rated_power_w` it is held at rating (region 3, pitch regulated —
the pitch angle itself is not computed here; see the control blocks). The schedule is a table with
`wind_speed_m_s`, `rpm`, `power_w` and `CP`, ready for the annual-energy and wind-farm blocks.

### Code

- `backend/nova/blocks/performance.py`, `backend/nova/physics/flexible.py`.
