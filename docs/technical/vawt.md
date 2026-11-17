# Vertical-axis turbines

## In brief

Vertical-axis turbines (H-rotor and Φ-rotor) are computed with the **streamtube family**: four
methods of increasing complexity, from a single disk to the double-multiple streamtube model.

## In detail

### The four methods

:::{table} The streamtube family
:name: tab-streamtubes

| Method | Momentum balance |
|---|---|
| Single streamtube (Templin) | One actuator disk for the whole rotor |
| Double streamtube | One disk upwind and one downwind, in tandem |
| Multiple streamtube (Strickland) | One disk per streamtube, for both blade passages |
| Double-multiple streamtube (Paraschivoiu) | Two disks per streamtube; downwind the speed is $V_e = V(1 - 2a_u)$ |
:::

### Conventions

The blade sits at $r(-\cos\theta, \sin\theta)$ with the wind along $+x$; reported azimuths are
shifted so that 0–180° is the upwind side. The equilibrium velocity is floored at $0.2\,V$ when the
upwind disk enters the turbulent-wake state, and the iteration uses adaptive relaxation.

```{warning}
Streamtubes next to $\theta = \pm 90^\circ$ have vanishing width, so the induction there is
ill-conditioned. This is a known property of the DMST method; their contribution to power is small.
```

Troposkien blades use a parabolic shape, with the height levels solved independently. The specific
corrections (finite aspect ratio, curvature, dynamic stall, struts, shaft) are listed in
[Rotor models](rotor-models.md).

**[TO COMPLETE]** Add a worked numerical example of an H-rotor with the expected results.
