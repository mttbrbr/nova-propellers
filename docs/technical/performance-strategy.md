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

### Operating strategy

Region 2 follows the chosen $\lambda$: $n = \lambda V/R \cdot 60/2\pi$. The speed is clipped to
`rpm_min` (region 1.5) and `rpm_max` (region 2.5); power comes from the connected Cp–λ curve at the
actual tip-speed ratio, and above `rated_power_w` it is held at rating (region 3, pitch regulated —
the pitch angle itself is not computed here; see the control blocks). The schedule is a table with
`wind_speed_m_s`, `rpm`, `power_w` and `CP`, ready for the annual-energy and wind-farm blocks.

### Code

- `backend/nova/blocks/performance.py`, `backend/nova/physics/flexible.py`.
