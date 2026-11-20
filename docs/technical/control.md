# Control and co-simulation

## In brief

Control blocks exchange **named signals**: any block writes and reads signals by name, so a
controller is not tied to a particular plant. Each block appends one element to a chain received on
its `dynamics` port; the **Control simulation** block runs the chain in time and reports, for every
signal, its time series and its final, mean, minimum, maximum and standard deviation.

Elements: **Signal source** (constant, step, ramp, sine, time table), **PI / PID controller** (limits,
anti-windup, derivative filter, gain scheduling), **Torque law kω²**, **Schedule / lookup** (pitch
schedules, gain schedules, any static map), **Transfer function**, **State space**, **FMU** (FMI 2.0
co-simulation, e.g. exported from OpenModelica) and the **Rotor–drivetrain plant** of a Nova rotor.

## In detail

### Simulation

At every step the elements run in chain order. An element that reads a signal written later in the
chain sees its previous value (a one-step delay that breaks algebraic loops); plants publish their
initial outputs before the first step. Linear models are discretised with the bilinear (Tustin)
transform at the simulation step. The plant integrates with a fourth-order Runge–Kutta step,
subdivided, holding its inputs constant over the step.

### PID controller

$u = u_0 + g\,(k_p e + k_i\!\int e\,dt + k_d \dot e_f)$ with $e$ = setpoint − measurement (or the
opposite when `reverse` is set, e.g. pitch increasing with rotor speed), $g$ an optional
gain-scheduling signal, $\dot e_f$ the derivative through a first-order filter, and output limits with
conditional integration (the integrator stops when the output saturates in the direction of the
error).

### Torque law and rotor plant

The generator torque on the low-speed shaft is $T = k\,\omega^2$, capped at rated torque, with
$k = \tfrac12 \rho\pi R^5 C_{P,\max}/\lambda_\text{opt}^3$ from the connected rotor unless given. The
plant is $J\dot\omega = Q_\text{aero}(V, \omega, \beta) - N\,T_\text{gen} - c\,\omega$ with
$Q_\text{aero} = \tfrac12\rho\pi R^2 V^3 C_P(\lambda, \beta)/\omega$ and thrust from $C_T(\lambda, \beta)$;
the tables come from Nova's BEMT over a λ × pitch grid. The inertia is given, or computed from the
blade structure, hub and generator (reflected through the gearbox). Aerodynamics are quasi-steady (no
dynamic inflow); the drivetrain is rigid.

### Aeroelastic turbine (time domain)

The *Turbine dynamics (aeroelastic)* block turns the connected HAWT and its structure (blade, and optionally
tower, nacelle and hub) into a plant for the same simulation:

- **structure**: the rotor–tower model of the coupled Campbell diagram (tower modes and the rotating
  modes of every blade, second-order hub kinematics). The blade basis is taken at a reference speed and
  its stiffness and gyroscopic terms follow the actual speed,
  $K_b(\Omega) = \operatorname{diag}(\omega_\text{ref}^2) + (\Omega^2 - \Omega_\text{ref}^2)\,\Phi^\mathsf{T} S\,\Phi$,
  $G_b(\Omega) = (\Omega/\Omega_\text{ref})\,G_\text{ref}$; Newmark average-acceleration integration;
- **rotor speed**: $J\dot\Omega = Q_\text{aero} - N\,T_\text{gen}$ with $J$ from the blades, hub and
  generator (rigid drivetrain);
- **aerodynamics per element**: local wind (power-law shear with the element height) minus the element's
  structural velocity (tower top and blade modes, hence aerodynamic damping); the equilibrium BEMT
  induction for that flow, warm-started from the previous step, drives Øye's dynamic-inflow filter on the
  axial induced velocity
  ($\tau_1 = 1.1/(1-1.3a)\,R/V$, $\tau_2 = (0.39 - 0.26 (r/R)^2)\,\tau_1$); loads from the polar at the
  resulting angle of attack; collective pitch from the controller. The loads are evaluated at the start of
  each step (loose coupling, step at most 0.02 s).

Not modelled: tower shadow, yaw and skewed wake, dynamic stall, gravity, drivetrain torsion, blade torsion
and large-deflection geometry; turbulence enters only through the wind signal.

Checks (`backend/tests/test_dynamics.py`, AOC 15/50 example structure): at fixed speed and constant wind
the mean power and thrust converge to the steady BEMT within 0.5 %; the free decay of the tower (no
aerodynamics) oscillates at the coupled fore-aft frequency of the multi-blade analysis within 2 %; with the
kω² law and a PI pitch controller the rotor holds its speed above rated. Template `aeroelastic_turbine`.

### The same controller in OpenFAST

Connect the control chain to *OpenFAST case from rotor* (with the hub, nacelle, tower and blade structure) to
free the rotor speed in OpenFAST: ElastoDyn gets the generator degree of freedom, gearbox ratio and
generator inertia; ServoDyn runs `PCMode = VSContrl = 5` with **Nova DISCON**, a small Bladed-style library
(`backend/nova/adapters/discon/nova_discon.c`, Apache-2.0) that implements exactly the kω² law with its
rated-torque cap and the PI pitch controller with limits, conditional anti-windup and gain schedule of the
control blocks. Nova compiles it once with the system C compiler (cached by the source hash) and copies it
into the case with its parameter file; the wind source becomes an InflowWind uniform wind file. Elements
without an OpenFAST counterpart (transfer functions, state space, FMUs, a derivative term) are refused.

On the AOC 15/50 example, with a wind ramp from 8 to 14 m/s (`backend/tests/test_openfast_controller.py`
checks a shorter step):

| t | Rotor speed Nova / OpenFAST | Pitch | Power | Tower-top fore-aft |
| --- | --- | --- | --- | --- |
| 15 s | 68.69 / 68.56 rpm | 7.7 / 8.0° | 48.1 / 47.9 kW | 16.6 / 16.6 mm |
| 25 s | 65.72 / 65.63 rpm | 13.0 / 12.8° | 42.2 / 42.0 kW | 11.9 / 13.0 mm |
| 40 s | 64.95 / 64.95 rpm | 13.3 / 13.0° | 40.7 / 40.7 kW | 11.7 / 13.0 mm |

Above rated Nova's thrust is about 9 % higher than AeroDyn's (low incidence on the pitched blade, where the
two inflow models differ most); OpenFAST also includes gravity, which Nova does not. Template
`openfast_closed_loop`.

### FMU import

FMUs are run through FMPy (BSD-2, optional: `pip install fmpy`), co-simulation only: Nova sets the
mapped inputs, calls `doStep` with the simulation step and reads the mapped outputs; parameters are
set during initialisation. This replaces a dedicated OpenModelica integration: any tool that exports
an FMI 2.0 co-simulation FMU works the same way. The wrapper is tested against a stand-in FMPy module;
no real FMU was available in this session.

### Checks

`backend/tests/test_control.py`: a PI controller ($k_p = k_i = 1$) on $1/(s+1)$ follows
$y = 1 - e^{-t}$; a state-space model matches its transfer function; saturation with anti-windup; the
kω² law settles the rotor at $\lambda_\text{opt}$ and recovers $C_{P,\max}$; a PI pitch controller
holds rated speed through a wind step.

### Code

- `backend/nova/physics/control.py`, `backend/nova/blocks/control.py`.
