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
