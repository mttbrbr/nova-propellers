# Energy, cost and design optimisation

## In brief

- **Annual energy** integrates a power curve over a Weibull wind distribution, with availability and
  losses, and reports the capacity factor.
- **Turbine cost (NREL CSM)** estimates component masses and costs of a land-based geared turbine
  from the NREL Cost and Scaling Model and, with the energy and the site's balance-of-station and
  operating costs, the levelised cost of energy.
- **Design optimiser**, **Pareto optimiser (NSGA-II)** and **Multi-fidelity optimiser** vary
  specification fields and, for every candidate, **re-run the blocks downstream of themselves**. The
  objectives and constraints can therefore be any quantity any later block computes: mass, power,
  thrust, frequencies, cost, LCOE.

## In detail

### Annual energy

With the Weibull scale $c = \bar V/\Gamma(1 + 1/k)$,

$$
\text{AEP} = 8760\,h \cdot a\,(1 - \ell) \int_0^{V_\text{max}} P(V)\,\frac{k}{c}\Bigl(\frac{V}{c}\Bigr)^{k-1} e^{-(V/c)^k}\, dV ,
$$

with the power curve interpolated from the connected table and zero outside it. A step power curve
reproduces the closed form $P\,(e^{-(V_1/c)^k} - e^{-(V_2/c)^k})$ in the tests.

### Cost model

Component masses and costs follow the NREL Cost and Scaling Model (Fingersh, Hand & Laxson 2006,
NREL/TP-500-40566) in its 2015 mass–cost update, with the coefficients of NREL's open-source WISDEM
(`wisdem.nrelcsm`, Apache-2.0): blade mass $0.5\,(D/2)^{b}$ with $b$ from the turbine class and carbon
spar caps (or the blade mass computed by the structural blocks), hub, pitch system, spinner,
low-speed shaft, main bearings, gearbox (torque density 200 N·m/kg and 50 USD/kN·m, WISDEM 2024),
brake, high-speed shaft, generator, bedplate, yaw system, hydraulics and cooling, nacelle cover,
platforms and crane, transformer, electrical connections, controls and tower; each cost is a mass (or
rating) multiplier. The rated torque is $P/(\eta\,\Omega_\text{max})$ with
$\Omega_\text{max} = V_\text{tip}/(D/2)$. Costs are in the coefficients' dollars (mostly 2015) and serve
to compare designs, not to quote prices. The fits come from 0.5–5 MW turbines: below about 40 m and
500 kW fixed intercepts dominate and the block says so.

The LCOE uses WISDEM's plant-finance form,

$$
\text{LCOE} = \frac{\text{FCR}\cdot(\text{TCC}/P + \text{BOS}_{/kW}) + \text{OpEx}_{/kW}}{\text{AEP}\,(1 - \ell_\text{wake})/P},
$$

and needs `bos_per_kw` and `opex_per_kw_yr`: they are site inputs and are never assumed.

The roadmap also listed the Sandia blade cost model and the INNWIND.EU cost model. The INNWIND.EU
deliverables (D1.21 cost-model spreadsheet, D1.23) are publicly downloadable (dissemination level
PU) but carry no licence that would allow reimplementing or redistributing them; no published Sandia
blade cost model with a stated licence was found. Neither is implemented.

### Optimisation over the downstream workflow

The engine runs an optimiser after every other block that is ready, then gives it an evaluator of
its downstream chain: for a candidate specification the evaluator runs, in topological order, every
block reachable from the optimiser and collects every numeric `values` output; downstream constraint
blocks with hard checks act as constraints. After the optimisation the downstream blocks run once
more with the optimum. Optimisers cannot be nested.

- **Design optimiser**: one objective (or a weighted sum of several), SciPy SLSQP with finite
  differences on the normalised box, or COBYLA; hard checks are inequality constraints on their
  margins.
- **Pareto optimiser**: NSGA-II (Deb et al. 2002) with a Latin-hypercube start, simulated binary
  crossover ($\eta = 15$), polynomial mutation ($\eta = 20$), non-dominated sorting, crowding distance
  and constrained domination. It emits the final front and the knee point (closest to the ideal point
  in normalised objectives).
- **Multi-fidelity optimiser**: levels in sequence, each with its specification overrides (e.g. fewer
  BEMT stations), evaluation budget, trust region around the previous optimum, optional own objective
  and a switch for the downstream chain — cheap models far from the optimum, the full chain (finite
  elements, costs) only at the end.

Checks (`backend/tests/test_economics_optimization.py`): component equations, AEP and LCOE against
hand calculations; a radius optimisation minimising the LCOE through Cp–λ, strategy, energy and cost;
a non-dominated Pareto front; the multi-fidelity optimum equal to the full-model optimum.

### Code

- `backend/nova/physics/costs.py`, `backend/nova/blocks/economics.py`, `backend/nova/blocks/optimization.py`,
  scheduling and the downstream evaluator in `backend/nova/blocks/engine.py`.

### References

- Fingersh, L., Hand, M., Laxson, A. (2006). *Wind Turbine Design Cost and Scaling Model*.
  NREL/TP-500-40566.
- NREL WISDEM, `wisdem/nrelcsm` and `wisdem/plant_financese` (Apache-2.0).
- Deb, K., Pratap, A., Agarwal, S., Meyarivan, T. (2002). *A fast and elitist multiobjective genetic
  algorithm: NSGA-II*. IEEE Transactions on Evolutionary Computation 6(2), 182–197.
