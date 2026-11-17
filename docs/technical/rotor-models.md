# Rotor models

## In brief

For every rotor family NOVA produces a **performance curve**. The core of horizontal-axis rotors
and propellers is **BEMT** (blade-element momentum theory); vertical-axis turbines use the
**streamtube** family.

```{note}
Status: **preliminary**. The models reproduce textbook behaviour and pass the physics invariants of
the automated tests, but none has been compared with measured data on real rotors.
```

## In detail

### One sheet for every rotor type

:::{table} How the sections adapt to the rotor type
:name: tab-sections

| Section | Air propeller | Marine propeller | HAWT | VAWT |
|---|---|---|---|---|
| Sizing | thrust and disk loading → D | thrust, $V_s$, $w$, $t$, rpm, $J$ → D; Keller → $A_E/A_0$ | power, wind, $C_p$, $\eta$ → R | power, wind, $C_p$, $\eta$, H/D, $\sigma$ → R, H, c |
| Geometry | Bézier/Laguerre blade, airfoils | B-series, Z, $A_E/A_0$, P/D | Burton optimum or explicit blade | H- or Φ-rotor, struts, shaft |
| Analysis | BEMT, LLT, VLM, BEM | BEMT, hull and immersion | BEMT | SST, DS, MST, DMST |
| Results | native performance | open-water diagram, cavitation | $C_p$–$\lambda$, $C_T$, $C_Q$ | $C_p$–$\lambda$, azimuthal loads |
:::

Every family produces a performance curve: $C_p$–$\lambda$ at fixed wind speed for turbines
(varying the rotation), $K_T$, $10K_Q$, $\eta$–$J$ at fixed rpm for propellers.

:::{table} Families and main outputs
:name: tab-families

| Family | Model | Main outputs |
|---|---|---|
| HAWT (wind/tidal) | Axial BEMT, turbine mode | P, Q, T, $C_p$, $C_T$, $C_Q$, $\lambda$ |
| VAWT | Streamtube family | P, Q, force, $C_p$, azimuthal incidence, induction |
| Air propeller | Axial BEMT, propeller mode | T, Q, P, $K_T$, $K_Q$, $J$, $\eta$, figure of merit |
| Marine propeller | BEMT + marine theory | $K_T$, $10K_Q$, $\eta_0$, $\eta_H$, $\eta_D$, cavitation |
:::

### Dimensionless quantities

The tip-speed ratio of turbines and the advance ratio of propellers are

$$
\lambda = \frac{\Omega R}{V}, \qquad J = \frac{V}{n D}
$$ (eq-lambda-j)

where $\Omega$ is the angular velocity, $R$ the radius, $V$ the free-stream speed, $n$ the
revolutions per second and $D$ the diameter. For a propeller, with $\rho$ the fluid density, the
thrust and torque coefficients and the open-water efficiency are

$$
K_T = \frac{T}{\rho\, n^2 D^4}, \qquad
K_Q = \frac{Q}{\rho\, n^2 D^5}, \qquad
\eta_0 = \frac{J\,K_T}{2\pi\,K_Q}
$$ (eq-kt-kq)

and power is always tied to torque by $P = Q\,\Omega$, one of the identities checked by the tests
(see [Verification and validation](verification-validation.md)).

### Axial BEMT

At each blade station the inflow angle $\varphi$ is solved with Ning's (2014) one-dimensional
residual, bracketed by a vectorised scan and refined by bisection, so there is **no relaxation
factor to tune**. The physical root is the rising zero crossing. In the momentum region
$1/(1-a)$ is evaluated as $1 + k$ to avoid the spurious pole at $k = -1$. Turbine and propeller
modes use the usual sign conventions ($\alpha = \varphi - \theta$ for the turbine,
$\alpha = \theta - \varphi$ for the propeller). The propeller residual,

$$
f(\varphi) = \Omega r \sin\varphi\,(1 - k) - V \cos\varphi\,(1 + k')
$$ (eq-propeller-residual)

remains valid at $V = 0$, that is for static thrust.

```{algorithm} Solving the inflow angle at one station
:name: algorithm-bemt

input: station radius $r$, chord and twist, airfoil polar, $V$ and $\Omega$
scan $\varphi$ over an interval and compute the residual $f(\varphi)$
find the zero crossings and keep the rising ones
for each interval containing a crossing:
  refine by bisection down to the required tolerance
select the physical root
compute incidence, lift and drag coefficients, and the station loads
output: inflow angle $\varphi$ and station loads
```

{numref}`algorithm-bemt` summarises the procedure; **[TO COMPLETE]** add the bracketing details
and tolerances read from `backend/nova/physics/axial.py`.

```{note}
Check invariant: a drag-free Glauert rotor without tip loss at $\lambda = 7$ reaches
$C_p \approx 0.55$–$0.57$ with $a \approx 1/3$ along the span (theoretical value 0.570).
```

### Corrections

:::{table} Available corrections
:name: tab-corrections

| Correction | Axial rotors | VAWT |
|---|---|---|
| Tip loss | Prandtl; Shen et al. (2005) | Finite aspect ratio (Lanchester–Prandtl) with induced drag |
| Hub loss | Prandtl | Velocity deficit in the shaft wake |
| High induction | Glauert, Buhl, Spera | Glauert, Buhl, Spera on each disk |
| 3-D rotation | Snel (inboard of 0.8 R) | — |
| Compressibility | Prandtl–Glauert (M ≤ 0.7) | — |
| Flow curvature | — | Virtual incidence at 3/4 chord (Migliore) |
| Dynamic stall | — | Gormont with Berg blending |
| Parasitic | — | Strut drag |
:::

All polars are extended to ±180° with Viterna–Corrigan and a flat-plate mirror for reversed flow.

```{note}
**[TO COMPLETE]** Recent commits add the Du–Selig stall delay, the upstream rotor/body wake and
configurable tip/hub loss. Describe them here once the work on the code is stable.
```
