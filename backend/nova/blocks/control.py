"""Control and co-simulation blocks (phase 6).

Every element block appends one element to the ``dynamics`` chain it receives; the simulation block runs
the chain. Elements communicate only through freely named signals, so any controller can drive any plant
(including an FMU exported from OpenModelica or another tool).
"""
import copy
import math

import numpy as np

from nova.physics import control, rotors

MAX_ELEMENTS = 40


class ControlBlockError(ValueError):
    pass


def _chain(args, element):
    upstream = list(args.get('dynamics') or [])
    if len(upstream) >= MAX_ELEMENTS:
        raise ControlBlockError(f'At most {MAX_ELEMENTS} control elements can be chained')
    return {'dynamics': upstream + [element]}


def _check(element):
    try:
        control.build([element])
    except (control.ControlError, KeyError, TypeError, ValueError) as exc:
        raise ControlBlockError(str(exc)) from exc
    return element


def element_block(kind, keys):
    def handler(node, args):
        config = node.get('config', {})
        return _chain(args, _check({'element': kind, **{k: copy.deepcopy(config[k]) for k in keys if k in config}}))
    return handler


SOURCE_KEYS = ('output', 'kind', 'value', 'amplitude', 'time', 'end_time', 'frequency_hz', 'phase', 'times', 'values')
PID_KEYS = ('output', 'measurement', 'setpoint', 'kp', 'ki', 'kd', 'derivative_filter_s', 'min', 'max', 'gain_signal', 'reverse', 'offset')
LOOKUP_KEYS = ('input', 'output', 'breakpoints', 'values')
TF_KEYS = ('input', 'output', 'numerator', 'denominator')
SS_KEYS = ('inputs', 'outputs', 'A', 'B', 'C', 'D', 'initial_state')
FMU_KEYS = ('path', 'inputs', 'outputs', 'parameters')


def _optimum(spec):
    curve = rotors.performance_curve(spec, values=np.linspace(2.0, 14.0, 49).tolist())
    if not curve['optimum']:
        raise ControlBlockError('No Cp–λ optimum found for the connected rotor')
    return curve['optimum']['value'], curve['optimum']['tip_speed_ratio']


def torque_law(node, args):
    config = node.get('config', {})
    k = config.get('k')
    notes = []
    if k is None:
        if args.get('spec') is None:
            raise ControlBlockError('Set k or connect the rotor (k = ½ρπR⁵ Cp_max / λ_opt³)')
        spec = rotors.merged(args['spec'])
        _, rotor, fluid = rotors.build(spec)
        cp, lam = _optimum(spec)
        radius = float(rotor.tip_radius_m)
        k = 0.5 * fluid.density_kg_m3 * math.pi * radius**5 * cp / lam**3
        notes.append(f'k = {k:.4g} N·m·s² from Cp_max = {cp:.4f} at λ = {lam:.3f} (low-speed shaft)')
    element = _check({'element': 'torque_law', 'input': config.get('input', 'rotor_speed'), 'output': config.get('output', 'gen_torque'),
                      'k': float(k), 'rated_torque_nm': config.get('rated_torque_nm')})
    out = _chain(args, element)
    out['values'] = {'k_nms2': float(k)}
    out['notes'] = notes
    return out


def rotor_dynamics(node, args, cancelled=None):
    config = node.get('config', {})
    spec = rotors.merged(args['spec'])
    built, rotor, fluid = rotors.build(spec)
    if built['kind'] != 'hawt':
        raise ControlBlockError('The rotor plant models horizontal-axis turbines')
    tsr = np.asarray(config.get('tsr_grid') or np.linspace(1.0, 14.0, 14), float)
    pitch = np.asarray(config.get('pitch_grid') or [-2.0, 0.0, 2.0, 4.0, 6.0, 9.0, 12.0, 16.0, 20.0, 25.0, 30.0], float)
    if len(tsr) < 2 or len(pitch) < 2 or np.any(np.diff(tsr) <= 0) or np.any(np.diff(pitch) <= 0):
        raise ControlBlockError('tsr_grid and pitch_grid must increase')
    if len(tsr) * len(pitch) > 600:
        raise ControlBlockError('At most 600 Cp(λ, β) points')
    velocity = rotors.resolve_operating(built, rotor)[0]
    cp, ct = np.zeros((len(tsr), len(pitch))), np.zeros((len(tsr), len(pitch)))
    base_pitch = float(spec['geometry'].get('pitch_deg', 0.0))
    for j, beta in enumerate(pitch):
        for i, lam in enumerate(tsr):
            if cancelled and cancelled():
                raise InterruptedError('Run cancelled')
            point = copy.deepcopy(spec)
            point['geometry']['pitch_deg'] = base_pitch + float(beta)
            point['operating'] = {'velocity_m_s': velocity, 'tip_speed_ratio': float(lam)}
            try:
                result = rotors.analyze(point)
                cp[i, j], ct[i, j] = result['coefficients']['CP'], result['coefficients']['CT']
            except ValueError:
                cp[i, j], ct[i, j] = np.nan, np.nan
    for table in (cp, ct):  # fill failed points along λ
        for j in range(len(pitch)):
            good = np.isfinite(table[:, j])
            if not good.any():
                raise ControlBlockError(f'No BEMT solution at pitch {pitch[j]:g}°')
            table[:, j] = np.interp(tsr, tsr[good], table[good, j])
    inertia = config.get('inertia_kg_m2')
    notes = []
    if inertia is None:
        blade = args.get('blade')
        if blade is None:
            raise ControlBlockError('Set inertia_kg_m2 or connect the blade structure (and hub) for the rotor inertia')
        x, mass = (np.array(c) for c in list(zip(*blade['stations']))[:2])
        hub, tip = float(rotor.hub_radius_m), float(rotor.tip_radius_m)
        r = hub + x * (tip - hub)
        inertia = int(rotor.blades) * (np.trapezoid(mass * r**2, r) + blade.get('tip_mass_kg', 0.0) * tip**2)
        inertia += (args.get('hub') or {}).get('inertia_kg_m2', 0.0)
        inertia += float(config.get('generator_inertia_kg_m2', 0.0)) * float(config.get('gearbox_ratio', 1.0)) ** 2
        notes.append(f'Rotor inertia {inertia:.4g} kg·m² from the blade structure' + (', hub' if args.get('hub') else '')
                     + ' and the generator reflected through the gearbox')
    names = {k: config.get(k, default) for k, default in (('wind', 'wind_speed'), ('generator_torque', 'gen_torque'), ('pitch', 'pitch'),
                                                          ('speed', 'rotor_speed'), ('aero_torque', 'aero_torque'), ('power', 'power'),
                                                          ('thrust', 'thrust'), ('tsr', 'tsr'))}
    initial = config.get('initial_rpm')
    if initial is None:
        initial = rotors.resolve_operating(built, rotor)[1]
    element = _check({'element': 'rotor_plant', **names, 'radius_m': float(rotor.tip_radius_m), 'density_kg_m3': fluid.density_kg_m3,
                      'inertia_kg_m2': float(inertia), 'gearbox_ratio': float(config.get('gearbox_ratio', 1.0)),
                      'generator_efficiency': float(config.get('generator_efficiency', 1.0)), 'friction_nms': float(config.get('friction_nms', 0.0)),
                      'tsr_grid': tsr.tolist(), 'pitch_grid': pitch.tolist(), 'cp': cp.tolist(), 'ct': ct.tolist(),
                      'initial_speed_rad_s': float(initial) * math.pi / 30, 'substeps': int(config.get('substeps', 4))})
    notes.insert(0, f'Rigid rotor–drivetrain plant (one degree of freedom) with Cp(λ, β) and C_T(λ, β) from {len(tsr) * len(pitch)} BEMT '
                    'solutions (pitch relative to the rotor geometry); quasi-steady aerodynamics (no dynamic inflow)')
    out = _chain(args, element)
    out['values'] = {'inertia_kg_m2': float(inertia), 'cp_max': float(np.nanmax(cp))}
    out['notes'] = notes
    return out


def control_simulation(node, args, cancelled=None):
    config = node.get('config', {})
    elements = args.get('dynamics') or []
    if not elements:
        raise ControlBlockError('Connect a chain of control elements')
    duration = float(config.get('duration_s', 60.0))
    dt = float(config.get('dt_s', 0.01))
    record = config.get('record') or None
    window = float(config.get('statistics_from_s', 0.0))
    try:
        times, signals = control.simulate(elements, duration=duration, dt=dt, initial=config.get('initial') or {}, record=record,
                                          cancelled=cancelled)
    except (control.ControlError, KeyError, TypeError) as exc:
        raise ControlBlockError(str(exc)) from exc
    keep = times >= window
    if not keep.any():
        raise ControlBlockError('statistics_from_s is after the end of the simulation')
    values = {}
    for name, series in signals.items():
        part = series[keep]
        values.update({f'{name}_final': float(series[-1]), f'{name}_mean': float(part.mean()), f'{name}_min': float(part.min()),
                       f'{name}_max': float(part.max()), f'{name}_std': float(part.std())})
    stride = max(1, len(times) // 2000)
    rows = [{'time_s': float(times[i]), **{k: float(v[i]) for k, v in signals.items()}} for i in range(0, len(times), stride)]
    notes = [f'{len(times) - 1} steps of {dt:g} s; elements evaluated in chain order, signals written later in the chain are read '
             f'with a one-step delay; statistics from t = {window:g} s']
    return {'table': {'kind': 'time_series', 'rows': rows, 'signals': list(signals)}, 'values': values, 'notes': notes}


DYNAMIC_SIGNALS = (('wind', 'wind_speed'), ('generator_torque', 'gen_torque'), ('pitch', 'pitch'), ('speed', 'rotor_speed'), ('power', 'power'),
                   ('aero_power', 'aero_power'), ('thrust', 'thrust'), ('tower_top_fa', 'tower_top_fa'), ('tower_top_ss', 'tower_top_ss'),
                   ('tip_flap', 'tip_flap'), ('root_flap_moment', 'root_flap_moment'), ('tsr', 'tsr'))


def turbine_dynamics(node, args):
    """Aeroelastic turbine element: the connected rotor and structure as a time-domain plant."""
    config = node.get('config', {})
    spec = rotors.merged(args['spec'])
    item = {'element': 'aeroelastic_turbine', 'spec': spec, 'blade': args['blade'],
            **{k: args[k] for k in ('tower', 'nacelle', 'hub') if args.get(k) is not None},
            **{k: config[k] for k in ('rpm_ref', 'hub_height_m', 'shear_exponent', 'dynamic_inflow', 'generator_inertia_kg_m2',
                                      'gearbox_ratio', 'generator_efficiency', 'initial_rpm', 'fixed_rpm', 'max_step_s') if config.get(k) is not None},
            **{k: config.get(k, default) for k, default in DYNAMIC_SIGNALS}}
    if item.get('tower') is not None and item.get('nacelle') is None:
        raise ControlBlockError('Connect the nacelle with the tower (overhang, shaft height and mass)')
    _check(item)
    notes = ['Aeroelastic turbine: rotor–tower modes (blade basis at the reference speed, stiffness and gyroscopic terms updated '
             'with the actual speed), rotor-speed degree of freedom, BEMT per element on the local flow (structural velocities '
             'included) with Øye dynamic inflow, shear, collective pitch; Newmark integration, loads from the start of each step. '
             'No tower shadow, yaw, dynamic stall, gravity or drivetrain torsion']
    if item.get('tower') is None:
        notes.append('No tower connected: the hub is fixed (blade dynamics and rotor speed only)')
    out = _chain(args, item)
    out['notes'] = notes
    return out
