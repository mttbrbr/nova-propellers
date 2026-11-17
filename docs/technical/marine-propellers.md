# Marine propellers

## In brief

For the marine propeller NOVA computes open-water coefficients, hull interaction, cavitation risk
and the minimum expanded area. The blade outline follows the Wageningen B-series chord
distribution.

## In detail

### Hull interaction

The advance speed at the propeller depends on the wake fraction $w$, and the overall efficiency on
the thrust-deduction factor $t$:

$$
V_A = V_s\,(1 - w), \qquad
\eta_H = \frac{1 - t}{1 - w}, \qquad
\eta_D = \eta_0\,\eta_H\,\eta_R
$$ (eq-hull)

with $V_s$ the ship speed, $\eta_H$ the hull efficiency, $\eta_R$ the relative-rotative efficiency
and $\eta_D$ the propulsive efficiency.

### Cavitation and expanded area

NOVA computes the cavitation number at $0.7R$, Burrill's thrust loading $\tau_c$ with
$A_P/A_D \approx 1.067 - 0.229\,P/D$, Keller's minimum expanded area ratio and the local section
$\sigma$ at top dead centre.

```{warning}
Burrill acceptance lines are **not** hard-coded: published curve fits disagree. Read the limit for
the computed $\sigma_{0.7R}$ from your reference chart and enter it as a `burrill` constraint.
```

**[TO COMPLETE]** Describe the required inputs and a complete cavitation-check example.
