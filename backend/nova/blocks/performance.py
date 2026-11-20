"""Performance-curve and operating-strategy blocks (phase 2).

* performance_map  – optimum of any rotor output over one or two specification fields (Cp over λ and pitch,
                     η over J, …) on a grid that is refined progressively around the best point, with an
                     interpolating response surface (thin-plate radial basis functions) whose optimum is
                     verified by a direct evaluation.
* cp_flexible      – Cp–λ (and C_T) of the rotor in sheared inflow and with the steady flapwise deflection of
                     a flexible blade (cos³β coning of every element), next to the rigid, uniform-inflow curve.
* operating_strategy – rotor speed for a chosen tip-speed ratio and wind speed, and the variable-speed
                     schedule over a wind-speed range with rotor-speed limits and rated power.
"""
import copy
import math

import numpy as np

from nova.physics import aeroelastic, flexible, modal, rotors

from .expressions import ExpressionError, evaluate

MAX_EVALUATIONS = 400


class PerformanceError(ValueError):
    pass


def _number(value, label, low=-math.inf, high=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PerformanceError(f'{label} must be a finite number')
    if not low <= value <= high:
        raise PerformanceError(f'{label} must be between {low:g} and {high:g}')
    return float(value)


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise PerformanceError(f'{label} must be an integer in {low}–{high}')
    return value


def apply(spec, path, value):
    """Set a specification field; a tip-speed or advance ratio replaces the quantity it fixes."""
    from .engine import set_path
    spec = set_path(spec, path, value)
    operating = spec.get('operating') or {}
    if path == 'operating.tip_speed_ratio':
        operating.pop('rpm', None)
    elif path == 'operating.advance_ratio':
        operating.pop('velocity_m_s', None)
    return spec


def _evaluate(spec, objective):
    result = rotors.analyze(spec)
    values = rotors.scalar_outputs(result)
    values['converged'] = 1.0 if result['converged'] else 0.0
    return evaluate(objective, values), values


# ------------------------------------------------------------------ performance map

def performance_map(node, args, cancelled=None):
    from scipy.interpolate import RBFInterpolator
    from scipy.optimize import minimize
    config = node.get('config', {})
    variables = config.get('variables') or []
    if not 1 <= len(variables) <= 2:
        raise PerformanceError('A performance map has one or two variables')
    bounds = []
    for item in variables:
        apply({}, item.get('path'), 0.0)
        lo, hi = _number(item.get('min'), f'{item.get("path")} minimum'), _number(item.get('max'), f'{item.get("path")} maximum')
        if hi <= lo:
            raise PerformanceError(f'{item["path"]}: maximum must exceed minimum')
        bounds.append((lo, hi))
    bounds = np.array(bounds)
    objective = config.get('objective', 'CP')
    sense = config.get('sense', 'maximize')
    if sense not in ('maximize', 'minimize'):
        raise PerformanceError('sense must be maximize or minimize')
    sign = 1.0 if sense == 'maximize' else -1.0
    points = _integer(config.get('points', 7), 'points', 3, 21)
    levels = _integer(config.get('levels', 4), 'levels', 1, 10)
    shrink = _number(config.get('shrink', 0.4), 'shrink', 0.1, 0.9)
    budget = _integer(config.get('max_evaluations', 150), 'max_evaluations', 4, MAX_EVALUATIONS)
    dims = len(variables)
    rows, cache = [], {}

    def run(x, level):
        key = tuple(round(float(v), 10) for v in x)
        if key in cache:
            return cache[key]
        if len(rows) >= budget:
            return None
        if cancelled and cancelled():
            raise InterruptedError('Run cancelled')
        spec = copy.deepcopy(args['spec'])
        for item, value in zip(variables, x):
            apply(spec, item['path'], float(value))
        row = {'evaluation': len(rows) + 1, 'level': level, **{item['path']: float(v) for item, v in zip(variables, x)}}
        try:
            score, values = _evaluate(spec, objective)
            row.update(state='succeeded', objective=float(score), **values)
            cache[key] = float(score)
        except (ValueError, ExpressionError) as exc:
            row.update(state='failed', error=str(exc))
            cache[key] = None
        rows.append(row)
        return cache[key]

    centre = bounds.mean(axis=1)
    half = (bounds[:, 1] - bounds[:, 0]) / 2
    for level in range(levels):
        lo = np.maximum(centre - half, bounds[:, 0])
        hi = np.minimum(centre + half, bounds[:, 1])
        axes = [np.linspace(lo[d], hi[d], points) for d in range(dims)]
        grid = np.stack([a.ravel() for a in np.meshgrid(*axes, indexing='ij')], axis=1)
        for x in grid:
            run(x, level)
        good = [(r['objective'], r) for r in rows if r['state'] == 'succeeded']
        if not good:
            raise PerformanceError('No evaluation succeeded')
        best = max(good, key=lambda item: sign * item[0])[1]
        centre = np.array([best[item['path']] for item in variables])
        half = half * shrink
        if len(rows) >= budget:
            break
    good = [r for r in rows if r['state'] == 'succeeded']
    best = max(good, key=lambda r: sign * r['objective'])
    span = bounds[:, 1] - bounds[:, 0]
    X = np.array([[r[item['path']] for item in variables] for r in good])
    y = np.array([r['objective'] for r in good])
    record = {'objective_sampled': best['objective'], 'evaluations': float(len(rows))}
    for item in variables:
        record[f'{_short(item["path"])}_sampled'] = best[item['path']]
    surface_rows, notes = [], []
    if len(good) >= dims + 2:
        unit = (X - bounds[:, 0]) / span
        surface = RBFInterpolator(unit, y, kernel='thin_plate_spline', degree=1)
        resolution = 201 if dims == 1 else 41
        axes = [np.linspace(0, 1, resolution)] * dims
        grid = np.stack([a.ravel() for a in np.meshgrid(*axes, indexing='ij')], axis=1)
        values = surface(grid)
        start = grid[int(np.argmax(sign * values))]
        polished = minimize(lambda u: -sign * float(surface(u[None, :])[0]), start, method='L-BFGS-B', bounds=[(0, 1)] * dims)
        optimum = bounds[:, 0] + polished.x * span
        predicted = sign * -polished.fun
        verified = run(optimum, 'verification')
        record['objective_surface'] = float(predicted)
        for item, value in zip(variables, optimum):
            record[f'{_short(item["path"])}_surface'] = float(value)
        if verified is not None:
            record['objective_verified'] = float(verified)
            record['surface_error_pct'] = abs(predicted - verified) / max(abs(verified), 1e-12) * 100
            if sign * verified >= sign * best['objective']:
                record['objective'] = float(verified)
                for item, value in zip(variables, optimum):
                    record[_short(item['path'])] = float(value)
        coarse = 61 if dims == 1 else 25
        axes = [np.linspace(0, 1, coarse)] * dims
        grid = np.stack([a.ravel() for a in np.meshgrid(*axes, indexing='ij')], axis=1)
        for u, value in zip(grid, surface(grid)):
            surface_rows.append({**{item['path']: float(bounds[d, 0] + u[d] * span[d]) for d, item in enumerate(variables)},
                                 'objective': float(value)})
        notes.append('Response surface: thin-plate radial basis functions through every successful evaluation (linear trend); '
                     'its optimum was evaluated directly')
    else:
        notes.append('Too few successful evaluations for a response surface')
    if 'objective' not in record:
        record['objective'] = best['objective']
        for item in variables:
            record[_short(item['path'])] = best[item['path']]
    notes.append(f'{len(rows)} evaluations over {levels} refinement levels ({points} points per axis, box shrunk by {shrink:g} around '
                 'the best point each level)')
    table = {'kind': 'performance_map', 'variables': [v['path'] for v in variables], 'objective': objective, 'sense': sense, 'rows': rows,
             'surface': surface_rows}
    best_spec = copy.deepcopy(args['spec'])
    for item in variables:
        apply(best_spec, item['path'], record[_short(item['path'])])
    return {'table': table, 'values': record, 'spec': best_spec, 'notes': notes}


def _short(path):
    return path.split('.')[-1]


# ------------------------------------------------------------------ flexible Cp–λ

def cp_flexible(node, args, cancelled=None):
    from .structural import _blade_setup
    config = node.get('config', {})
    spec = rotors.merged(copy.deepcopy(args['spec']))
    if spec['kind'] != 'hawt':
        raise PerformanceError('Flexibility and shear apply to horizontal-axis turbines')
    start = _number(config.get('start', 2.0), 'start', 0.1, 30.0)
    stop = _number(config.get('stop', 12.0), 'stop', 0.2, 30.0)
    if stop <= start:
        raise PerformanceError('stop must exceed start')
    points = _integer(config.get('points', 21), 'points', 3, 61)
    shear = _number(config.get('shear_exponent', 0.0), 'shear_exponent', 0.0, 1.0)
    hub_height = config.get('hub_height_m')
    precone = _number(config.get('precone_deg', 0.0), 'precone_deg', -15.0, 15.0)
    notes = []
    inflow = None
    if shear > 0:
        if hub_height is None:
            raise PerformanceError('Wind shear needs hub_height_m')
        inflow = {'resolved': True, 'shear_exponent': shear, 'hub_height_m': _number(hub_height, 'hub_height_m', 1.0, 1000.0),
                  'azimuth_steps': _integer(config.get('azimuth_steps', 24), 'azimuth_steps', 8, 72)}
        notes.append(f'Power-law wind shear α = {shear:g} about a {inflow["hub_height_m"]:g} m hub, azimuthally resolved BEMT')
    blade = args.get('blade')
    beam = None
    model = config.get('model', 'aeroelastic')
    if model not in ('aeroelastic', 'cone_factor'):
        raise PerformanceError('model must be aeroelastic or cone_factor')
    if blade is not None:
        rotor, length, twist, twist_notes = _blade_setup({}, blade, spec)
        beam = modal.blade_beam(blade, length, twist, args.get('attachments') or [])
        notes += twist_notes
        if model == 'aeroelastic':
            notes.append('Steady aeroelastic solution: BEMT on the deformed blade (local cone angle, in-plane radius, normal wind '
                         'V cos β, elastic twist from the lift at the quarter chord about the elastic axis) iterated with the rotating '
                         '3-D beam until cone and twist settle. Without torsional stiffness and elastic-axis offset the twist stays rigid')
            if 'elastic_axis_offset_m' not in (blade.get('extended') or {}):
                notes.append('No elastic_axis_offset_m column: the elastic axis is taken at the quarter chord (no aerodynamic torsion)')
        else:
            notes.append('Steady flapwise deflection of the rotating 3-D beam under the BEMT loads; every element coned by '
                         'β = precone + atan(dw/ds) contributes cos³β of its rigid power and thrust (fixed-point iteration). '
                         'Elastic twist and the in-plane deflection are not fed back into the aerodynamics')
        if inflow and model == 'aeroelastic':
            notes.append('With shear, the sheared rigid coefficients are scaled by the aeroelastic-to-rigid ratio in uniform inflow')
    elif precone:
        notes.append(f'Rigid blade with {precone:g}° precone (cos³ factor)')
    else:
        notes.append('No blade structure connected: the curve is rigid')
    _, built, _ = rotors.build(spec)
    radius = float(built.tip_radius_m)
    velocity = rotors.resolve_operating(spec, built)[0]
    rows = []
    for tsr in np.linspace(start, stop, points):
        if cancelled and cancelled():
            raise InterruptedError('Run cancelled')
        point = copy.deepcopy(spec)
        point['operating'] = {'velocity_m_s': velocity, 'tip_speed_ratio': float(tsr)}
        row = {'tip_speed_ratio': float(tsr)}
        try:
            rigid = rotors.analyze(point)
            row['CP_rigid'] = rigid['coefficients']['CP']
            row['CT_rigid'] = rigid['coefficients']['CT']
            result = rigid
            if inflow:
                point['inflow'] = inflow
                result = rotors.analyze(point)
            cp, ct = result['coefficients']['CP'], result['coefficients']['CT']
            if beam is not None and model == 'aeroelastic':
                uniform = copy.deepcopy(point)
                uniform.pop('inflow', None)
                solved = aeroelastic.solve(uniform, blade, precone_deg=precone, twist=twist, attachments=args.get('attachments') or [])
                cp *= solved['CP'] / solved['CP_rigid']
                ct *= solved['CT'] / solved['CT_rigid']
                row.update(tip_flap_m=solved['tip_flap_m'], tip_edge_m=solved['tip_edge_m'], tip_twist_deg=solved['tip_twist_deg'],
                           tip_cone_deg=solved['tip_cone_deg'], iterations=solved['iterations'])
            elif beam is not None:
                omega = result['operating']['omega_rad_s']
                cone = flexible.coned(result, beam, blades=int(built.blades), hub_radius=float(built.hub_radius_m), omega=omega,
                                      precone_deg=precone)
                cp, ct = cp * cone['power_factor'], ct * cone['thrust_factor']
                row.update(tip_flap_m=cone['tip_flap_m'], tip_edge_m=cone['tip_edge_m'], mean_cone_deg=cone['mean_cone_deg'])
            elif precone:
                factor = math.cos(math.radians(precone)) ** 3
                cp, ct = cp * factor, ct * factor
            row.update(state='succeeded', CP=cp, CT=ct, rpm=result['operating']['rpm'],
                       power_w=0.5 * result['fluid']['density_kg_m3'] * math.pi * radius**2 * velocity**3 * cp)
        except (ValueError, flexible.FlexibilityError, aeroelastic.AeroelasticError) as exc:
            row.update(state='failed', error=str(exc))
        rows.append(row)
    good = [r for r in rows if r['state'] == 'succeeded']
    if not good:
        raise PerformanceError('No point of the curve succeeded')
    best = max(good, key=lambda r: r['CP'])
    rigid_best = max(good, key=lambda r: r['CP_rigid'])
    record = {'CP_max': best['CP'], 'tip_speed_ratio_at_CP_max': best['tip_speed_ratio'], 'CP_rigid_max': rigid_best['CP_rigid'],
              'tip_speed_ratio_at_CP_rigid_max': rigid_best['tip_speed_ratio'],
              'CP_loss_pct': (rigid_best['CP_rigid'] - best['CP']) / rigid_best['CP_rigid'] * 100}
    if 'tip_flap_m' in best:
        record['tip_flap_at_CP_max_m'] = best['tip_flap_m']
        record['max_tip_flap_m'] = max(r['tip_flap_m'] for r in good)
    return {'table': {'kind': 'performance_curve', 'variable': 'tip_speed_ratio', 'rows': rows, 'rotor_kind': 'hawt',
                      'optimum': {'quantity': 'CP', 'value': best['CP'], 'tip_speed_ratio': best['tip_speed_ratio']},
                      'reference_series': 'CP_rigid', 'betz_limit': 16 / 27},
            'values': record, 'notes': notes}


# ------------------------------------------------------------------ operating strategy

def _cp_curve(table, kind):
    if table is None:
        return None
    rows = [r for r in table.get('rows', []) if r.get('state', 'succeeded') == 'succeeded']
    key = 'tip_speed_ratio'
    rows = [r for r in rows if isinstance(r.get(key), (int, float)) and isinstance(r.get('CP'), (int, float))]
    if len(rows) < 3:
        raise PerformanceError('The connected table needs a Cp–λ curve (tip_speed_ratio and CP columns)')
    rows.sort(key=lambda r: r[key])
    return np.array([r[key] for r in rows]), np.array([r['CP'] for r in rows])


def operating_strategy(node, args):
    config = node.get('config', {})
    spec = rotors.merged(copy.deepcopy(args['spec']))
    if spec['kind'] not in ('hawt', 'vawt'):
        raise PerformanceError('The operating strategy applies to turbines (tip-speed ratio and wind speed)')
    built_spec, built, fluid = rotors.build(spec)
    radius = float(built.tip_radius_m if hasattr(built, 'tip_radius_m') else built.radius_m)
    area = math.pi * radius**2 if spec['kind'] == 'hawt' else 2 * radius * float(built.height_m)
    density = fluid.density_kg_m3 if hasattr(fluid, 'density_kg_m3') else fluid.to_dict()['density_kg_m3']
    curve = _cp_curve(args.get('table'), spec['kind'])
    tsr = config.get('tip_speed_ratio')
    notes = []
    if tsr is None:
        if curve is None:
            raise PerformanceError('Set tip_speed_ratio or connect a Cp–λ table (its optimum is used)')
        tsr = float(curve[0][int(np.argmax(curve[1]))])
        notes.append(f'Tip-speed ratio {tsr:.3g} from the optimum of the connected Cp–λ curve')
    tsr = _number(tsr, 'tip_speed_ratio', 0.1, 30.0)
    velocity = _number(config.get('wind_speed_m_s', 8.0), 'wind_speed_m_s', 0.1, 100.0)
    rpm_min = _number(config.get('rpm_min', 0.0), 'rpm_min', 0.0, 1e5)
    rpm_max = config.get('rpm_max')
    rpm_max = math.inf if rpm_max is None else _number(rpm_max, 'rpm_max', 0.0, 1e5)
    rated = config.get('rated_power_w')
    rated = math.inf if rated is None else _number(rated, 'rated_power_w', 1.0, 1e10)

    def rpm_for(v, ratio):
        return ratio * v / radius * 60 / (2 * math.pi)

    def cp_at(ratio):
        if curve is None:
            return None
        if not curve[0][0] <= ratio <= curve[0][-1]:
            return None
        return float(np.interp(ratio, *curve))

    def point(v):
        rpm = min(max(rpm_for(v, tsr), rpm_min), rpm_max)
        ratio = rpm * 2 * math.pi / 60 * radius / v
        region = '2 (optimal λ)' if rpm == rpm_for(v, tsr) else ('1.5 (minimum speed)' if rpm == rpm_min else '2.5 (maximum speed)')
        cp = cp_at(ratio)
        row = {'wind_speed_m_s': v, 'rpm': rpm, 'tip_speed_ratio': ratio, 'tip_speed_m_s': rpm * 2 * math.pi / 60 * radius, 'region': region}
        if cp is not None:
            power = 0.5 * density * area * v**3 * cp
            if power > rated:
                row.update(region='3 (rated power, pitch regulated)', power_w=rated, CP=rated / (0.5 * density * area * v**3),
                           CP_available=cp)
            else:
                row.update(power_w=power, CP=cp)
        return row

    chosen = point(velocity)
    record = {'rpm': chosen['rpm'], 'omega_rad_s': chosen['rpm'] * math.pi / 30, 'tip_speed_m_s': chosen['tip_speed_m_s'],
              'tip_speed_ratio': chosen['tip_speed_ratio'], 'wind_speed_m_s': velocity}
    if 'power_w' in chosen:
        record['power_w'], record['CP'] = chosen['power_w'], chosen['CP']
    if chosen['region'] != '2 (optimal λ)':
        notes.append(f'At {velocity:g} m/s the rotor speed is limited: region {chosen["region"]}')
    rows = []
    v_in = config.get('cut_in_m_s', 3.0)
    v_out = config.get('cut_out_m_s', 25.0)
    if v_in is not None and v_out is not None:
        v_in, v_out = _number(v_in, 'cut_in_m_s', 0.1, 100), _number(v_out, 'cut_out_m_s', 0.2, 100)
        if v_out <= v_in:
            raise PerformanceError('cut_out_m_s must exceed cut_in_m_s')
        count = _integer(config.get('points', 23), 'points', 2, 200)
        rows = [point(float(v)) for v in np.linspace(v_in, v_out, count)]
        rated_rows = [r for r in rows if r['region'].startswith('3')]
        if rated_rows:
            record['rated_wind_speed_m_s'] = rated_rows[0]['wind_speed_m_s']
    if curve is None:
        notes.append('No Cp–λ curve connected: rotor speed only (no power)')
    else:
        notes.append('Power from the connected Cp–λ curve at the actual tip-speed ratio; above rated power the excess is assumed '
                     'shed by pitch (the pitch angle itself is not computed)')
    out = copy.deepcopy(args['spec'])
    out['operating'] = {'velocity_m_s': velocity, 'rpm': chosen['rpm']}
    return {'spec': out, 'values': record, 'table': {'kind': 'operating_schedule', 'rows': rows}, 'notes': notes}
