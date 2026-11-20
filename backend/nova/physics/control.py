"""Signal-based time-domain simulation for control design (phase 6).

A system is an ordered list of elements that read and write *named signals* (any identifier): sources
(constant, step, ramp, sine, table), PID controllers with gain scheduling, saturation and anti-windup,
the kω² generator-torque law, lookup tables (e.g. pitch schedules), continuous transfer functions and
state-space models (discretised with the bilinear transform), FMUs (co-simulation through FMPy) and a
rotor–drivetrain plant whose aerodynamic torque and thrust come from a Cp(λ, β) / C_T(λ, β) table.

Every time step evaluates the elements in list order; an element reading a signal written by a later
element sees its value from the previous step (one-sample delay that breaks algebraic loops). The plant
integrates its state with a fourth-order Runge–Kutta step holding the inputs constant over the step.
"""
import math
import re

import numpy as np

NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
MAX_STEPS = 200000


class ControlError(ValueError):
    pass


def _name(value, label):
    if not isinstance(value, str) or not NAME.match(value):
        raise ControlError(f'{label} must be a signal name (letters, digits, underscore)')
    return value


def _value(signals, ref, label='input'):
    """A number, or the current value of a named signal."""
    if isinstance(ref, (int, float)) and not isinstance(ref, bool):
        return float(ref)
    if isinstance(ref, str):
        if ref not in signals:
            raise ControlError(f'Signal {ref} is not defined (set an initial value or a source)')
        return signals[ref]
    raise ControlError(f'{label} must be a number or a signal name')


# ------------------------------------------------------------------ elements

class Source:
    def __init__(self, item):
        self.output = _name(item.get('output'), 'Source output')
        self.kind = item.get('kind', 'constant')
        if self.kind not in ('constant', 'step', 'ramp', 'sine', 'table'):
            raise ControlError('Source kind must be constant, step, ramp, sine or table')
        self.item = item
        if self.kind == 'table':
            t, v = item.get('times') or [], item.get('values') or []
            if len(t) < 2 or len(t) != len(v) or any(b <= a for a, b in zip(t, t[1:])):
                raise ControlError('A table source needs increasing times and matching values')

    def step(self, t, signals, dt):
        i = self.item
        base = float(i.get('value', 0.0))
        if self.kind == 'constant':
            value = base
        elif self.kind == 'step':
            value = base + (float(i.get('amplitude', 1.0)) if t >= float(i.get('time', 0.0)) else 0.0)
        elif self.kind == 'ramp':
            start, end = float(i.get('time', 0.0)), float(i.get('end_time', i.get('time', 0.0) + 1.0))
            value = base + float(i.get('amplitude', 1.0)) * min(max((t - start) / max(end - start, 1e-12), 0.0), 1.0)
        elif self.kind == 'sine':
            value = base + float(i.get('amplitude', 1.0)) * math.sin(2 * math.pi * float(i.get('frequency_hz', 0.1)) * t + float(i.get('phase', 0.0)))
        else:
            value = float(np.interp(t, i['times'], i['values']))
        signals[self.output] = value


class PID:
    def __init__(self, item):
        self.output = _name(item.get('output'), 'PID output')
        self.measurement = _name(item.get('measurement'), 'PID measurement')
        self.setpoint = item.get('setpoint', 0.0)
        self.kp, self.ki, self.kd = (float(item.get(k, 0.0)) for k in ('kp', 'ki', 'kd'))
        self.tf = float(item.get('derivative_filter_s', 0.0))
        self.low, self.high = item.get('min'), item.get('max')
        self.gain = item.get('gain_signal')
        self.reverse = bool(item.get('reverse', False))
        self.offset = float(item.get('offset', 0.0))
        self.integral, self.previous, self.derivative = 0.0, None, 0.0

    def step(self, t, signals, dt):
        error = _value(signals, self.setpoint, 'setpoint') - _value(signals, self.measurement)
        if self.reverse:
            error = -error
        scale = _value(signals, self.gain, 'gain_signal') if self.gain else 1.0
        if self.previous is not None and dt > 0:
            raw = (error - self.previous) / dt
            alpha = dt / (self.tf + dt) if self.tf > 0 else 1.0
            self.derivative += alpha * (raw - self.derivative)
        self.previous = error
        trial = self.integral + self.ki * error * dt
        u = self.offset + scale * (self.kp * error + trial + self.kd * self.derivative)
        clipped = min(max(u, self.low if self.low is not None else -math.inf), self.high if self.high is not None else math.inf)
        if clipped == u or (u > clipped and error < 0) or (u < clipped and error > 0):
            self.integral = trial  # conditional integration (anti-windup)
        signals[self.output] = clipped


class TorqueLaw:
    """Generator torque T = k ω² on the low-speed shaft, optional minimum speed and rated-torque cap."""

    def __init__(self, item):
        self.input = _name(item.get('input'), 'Torque-law input')
        self.output = _name(item.get('output'), 'Torque-law output')
        self.k = float(item['k'])
        self.rated = item.get('rated_torque_nm')

    def step(self, t, signals, dt):
        omega = signals[self.input] if self.input in signals else 0.0
        torque = self.k * omega * abs(omega)
        if self.rated is not None:
            torque = min(torque, float(self.rated))
        signals[self.output] = torque


class Lookup:
    def __init__(self, item):
        self.input = _name(item.get('input'), 'Lookup input')
        self.output = _name(item.get('output'), 'Lookup output')
        x, y = item.get('breakpoints') or [], item.get('values') or []
        if len(x) < 2 or len(x) != len(y) or any(b <= a for a, b in zip(x, x[1:])):
            raise ControlError('A lookup table needs increasing breakpoints and matching values')
        self.x, self.y = np.asarray(x, float), np.asarray(y, float)

    def step(self, t, signals, dt):
        signals[self.output] = float(np.interp(_value(signals, self.input), self.x, self.y))


class StateSpace:
    """Continuous LTI model discretised with the bilinear (Tustin) transform at the simulation step."""

    def __init__(self, item, A, B, C, D):
        self.inputs = [_name(n, 'State-space input') for n in item.get('inputs') or []]
        self.outputs = [_name(n, 'State-space output') for n in item.get('outputs') or []]
        A, B, C, D = (np.atleast_2d(np.asarray(m, float)) for m in (A, B, C, D))
        if A.shape[0] != A.shape[1] or B.shape != (A.shape[0], len(self.inputs)) or C.shape != (len(self.outputs), A.shape[0]) \
                or D.shape != (len(self.outputs), len(self.inputs)):
            raise ControlError('State-space dimensions do not match the inputs and outputs')
        self.continuous = (A, B, C, D)
        self.discrete = None
        self.x = np.asarray(item.get('initial_state') or np.zeros(A.shape[0]), float)

    def prepare(self, dt):
        from scipy.signal import cont2discrete
        A, B, C, D = self.continuous
        if A.shape[0] == 0:
            self.discrete = (A, B, C, D)
        else:
            Ad, Bd, Cd, Dd, _ = cont2discrete((A, B, C, D), dt, method='bilinear')
            self.discrete = (Ad, Bd, Cd, Dd)

    def step(self, t, signals, dt):
        u = np.array([_value(signals, n) for n in self.inputs])
        Ad, Bd, Cd, Dd = self.discrete
        y = Cd @ self.x + Dd @ u
        self.x = Ad @ self.x + Bd @ u
        for name, value in zip(self.outputs, y):
            signals[name] = float(value)


def transfer_function(item):
    from scipy.signal import tf2ss
    num, den = item.get('numerator') or [], item.get('denominator') or []
    if not num or not den or len(num) > len(den) or not float(den[0]):
        raise ControlError('A transfer function needs a proper numerator and a denominator with a non-zero leading coefficient')
    A, B, C, D = tf2ss(num, den)
    return StateSpace({'inputs': [item.get('input')], 'outputs': [item.get('output')]}, A, B, C, D)


class RotorPlant:
    """Rotor and drivetrain on the low-speed shaft: J dω/dt = Q_aero(V, ω, β) − N·T_gen − c ω."""

    def __init__(self, item):
        self.item = item
        self.names = {k: _name(item[k], k) for k in ('wind', 'generator_torque', 'pitch', 'speed', 'aero_torque', 'power', 'thrust', 'tsr')}
        self.radius, self.density = float(item['radius_m']), float(item['density_kg_m3'])
        self.inertia = float(item['inertia_kg_m2'])
        self.gear = float(item.get('gearbox_ratio', 1.0))
        self.efficiency = float(item.get('generator_efficiency', 1.0))
        self.friction = float(item.get('friction_nms', 0.0))
        self.tsr, self.pitch = np.asarray(item['tsr_grid'], float), np.asarray(item['pitch_grid'], float)
        self.cp, self.ct = np.asarray(item['cp'], float), np.asarray(item['ct'], float)
        self.omega = float(item.get('initial_speed_rad_s', 1.0))
        self.substeps = int(item.get('substeps', 4))

    def _table(self, table, lam, beta):
        lam = min(max(lam, self.tsr[0]), self.tsr[-1])
        beta = min(max(beta, self.pitch[0]), self.pitch[-1])
        i = min(max(np.searchsorted(self.tsr, lam) - 1, 0), len(self.tsr) - 2)
        j = min(max(np.searchsorted(self.pitch, beta) - 1, 0), len(self.pitch) - 2)
        u = (lam - self.tsr[i]) / (self.tsr[i + 1] - self.tsr[i])
        v = (beta - self.pitch[j]) / (self.pitch[j + 1] - self.pitch[j])
        return float((1 - u) * (1 - v) * table[i, j] + u * (1 - v) * table[i + 1, j] + (1 - u) * v * table[i, j + 1] + u * v * table[i + 1, j + 1])

    def aero(self, V, omega, beta):
        if V <= 0:
            return 0.0, 0.0, 0.0
        lam = max(omega, 0.0) * self.radius / V
        area = math.pi * self.radius**2
        cp, ct = self._table(self.cp, lam, beta), self._table(self.ct, lam, beta)
        power = 0.5 * self.density * area * V**3 * cp
        torque = power / omega if omega > 1e-6 else 0.5 * self.density * area * V**2 * self.radius * max(cp, 0.0) / max(lam, 0.1)
        return torque, 0.5 * self.density * area * V**2 * ct, lam

    def publish(self, signals):
        """Outputs of the initial state, so controllers earlier in the chain can read them at t = 0."""
        n = self.names
        signals.setdefault(n['speed'], self.omega)
        for key in ('aero_torque', 'thrust', 'tsr', 'power'):
            signals.setdefault(n[key], 0.0)

    def step(self, t, signals, dt):
        n = self.names
        V = _value(signals, n['wind'])
        beta = signals.get(n['pitch'], 0.0)
        load = self.gear * signals.get(n['generator_torque'], 0.0)
        h = dt / self.substeps

        def rate(omega):
            return (self.aero(V, omega, beta)[0] - load - self.friction * omega) / self.inertia
        for _ in range(self.substeps):
            k1 = rate(self.omega)
            k2 = rate(self.omega + h / 2 * k1)
            k3 = rate(self.omega + h / 2 * k2)
            k4 = rate(self.omega + h * k3)
            self.omega = max(self.omega + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4), 0.0)
        torque, thrust, lam = self.aero(V, self.omega, beta)
        signals[n['speed']] = self.omega
        signals[n['aero_torque']] = torque
        signals[n['thrust']] = thrust
        signals[n['tsr']] = lam
        signals[n['power']] = load * self.omega * self.efficiency


class FMU:
    """FMI 2.0 co-simulation FMU through FMPy (optional dependency)."""

    def __init__(self, item):
        self.path = item.get('path', '')
        self.inputs = {_name(k, 'FMU input signal'): v for k, v in (item.get('inputs') or {}).items()}
        self.outputs = {_name(k, 'FMU output signal'): v for k, v in (item.get('outputs') or {}).items()}
        self.parameters = item.get('parameters') or {}
        self.instance = None

    def prepare(self, dt, start=0.0):
        try:
            from fmpy import extract, read_model_description
            from fmpy.fmi2 import FMU2Slave
        except ImportError as exc:
            raise ControlError('FMU import needs the optional FMPy package (pip install fmpy)') from exc
        description = read_model_description(self.path)
        if description.coSimulation is None:
            raise ControlError('Only co-simulation FMUs are supported')
        refs = {v.name: v.valueReference for v in description.modelVariables}
        missing = [v for v in [*self.inputs.values(), *self.outputs.values(), *self.parameters] if v not in refs]
        if missing:
            raise ControlError(f'FMU variables not found: {", ".join(missing)}')
        self.refs = refs
        self.instance = FMU2Slave(guid=description.guid, unzipDirectory=extract(self.path),
                                  modelIdentifier=description.coSimulation.modelIdentifier, instanceName='nova')
        self.instance.instantiate()
        self.instance.setupExperiment(startTime=start)
        self.instance.enterInitializationMode()
        for name, value in self.parameters.items():
            self.instance.setReal([refs[name]], [float(value)])
        self.instance.exitInitializationMode()

    def step(self, t, signals, dt):
        for signal, variable in self.inputs.items():
            self.instance.setReal([self.refs[variable]], [_value(signals, signal)])
        self.instance.doStep(currentCommunicationPoint=t, communicationStepSize=dt)
        for signal, variable in self.outputs.items():
            signals[signal] = float(self.instance.getReal([self.refs[variable]])[0])

    def close(self):
        if self.instance is not None:
            self.instance.terminate()
            self.instance.freeInstance()


def build(elements):
    out = []
    for item in elements:
        kind = item.get('element')
        if kind == 'source':
            out.append(Source(item))
        elif kind == 'pid':
            out.append(PID(item))
        elif kind == 'torque_law':
            out.append(TorqueLaw(item))
        elif kind == 'lookup':
            out.append(Lookup(item))
        elif kind == 'transfer_function':
            out.append(transfer_function(item))
        elif kind == 'state_space':
            out.append(StateSpace(item, item.get('A') or [], item.get('B') or [], item.get('C') or [], item.get('D') or []))
        elif kind == 'rotor_plant':
            out.append(RotorPlant(item))
        elif kind == 'fmu':
            out.append(FMU(item))
        else:
            raise ControlError(f'Unknown control element {kind!r}')
    return out


def simulate(elements, *, duration, dt, initial=None, record=None, cancelled=None):
    """Run the system; returns the time vector and the recorded signals."""
    if not 0 < dt <= duration:
        raise ControlError('Time step must be positive and not longer than the duration')
    steps = int(round(duration / dt))
    if steps > MAX_STEPS:
        raise ControlError(f'At most {MAX_STEPS} time steps')
    signals = {_name(k, 'Initial signal'): float(v) for k, v in (initial or {}).items()}
    system = build(elements)
    for element in system:
        if hasattr(element, 'prepare'):
            element.prepare(dt)
        if hasattr(element, 'publish'):
            element.publish(signals)
    times, history = [], {}
    try:
        for k in range(steps + 1):
            if cancelled and k % 500 == 0 and cancelled():
                raise InterruptedError('Run cancelled')
            t = k * dt
            for element in system:
                element.step(t, signals, dt)
            times.append(t)
            for name in (record or signals):
                if name in signals:
                    history.setdefault(name, []).append(signals[name])
    finally:
        for element in system:
            if hasattr(element, 'close'):
                element.close()
    return np.asarray(times), {k: np.asarray(v) for k, v in history.items()}
