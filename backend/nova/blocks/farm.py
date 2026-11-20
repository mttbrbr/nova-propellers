"""Wind-farm blocks on the native NOJ model or the PyWake adapter, and the DUST rotor block (phase 5)."""
import copy
import math

import numpy as np

from nova.physics import farm, rotors


class FarmBlockError(ValueError):
    pass


def _number(config, key, low, high, default=None, required=False):
    value = config.get(key, default)
    if value is None:
        if required:
            raise FarmBlockError(f'Set {key}')
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise FarmBlockError(f'{key} must be a number between {low:g} and {high:g}')
    return float(value)


def _integration(adapter_id, chosen):
    from nova.infrastructure import library
    records = [r for r in library.list_records('integration') if r.get('adapter_id') == adapter_id]
    found = next((r for r in records if r['id'] == chosen), None) if chosen else (records[0] if records else None)
    if found is None:
        raise FarmBlockError(f'No {adapter_id} integration is configured: add one in Settings → Integrations')
    return found


def farm_turbine(node, args):
    """Power and thrust curves of the connected rotor along an operating schedule."""
    config = node.get('config', {})
    spec = rotors.merged(args['spec'])
    _, rotor, _ = rotors.build(spec)
    if spec['kind'] != 'hawt':
        raise FarmBlockError('Wind-farm turbines are horizontal-axis rotors')
    rows = [r for r in args['table'].get('rows', []) if isinstance(r.get('wind_speed_m_s'), (int, float))
            and isinstance(r.get('power_w'), (int, float)) and isinstance(r.get('rpm'), (int, float))]
    if len(rows) < 2:
        raise FarmBlockError('Connect the operating-strategy schedule (wind_speed_m_s, rpm, power_w)')
    out = []
    for row in sorted(rows, key=lambda r: r['wind_speed_m_s']):
        point = copy.deepcopy(spec)
        point['operating'] = {'velocity_m_s': row['wind_speed_m_s'], 'rpm': row['rpm']}
        ct = rotors.analyze(point)['coefficients']['CT']
        if 'CP_available' in row and row['CP_available'] > 0:
            ct *= row['CP'] / row['CP_available']  # rated region: thrust shed with power (pitch not computed)
        out.append({'wind_speed_m_s': row['wind_speed_m_s'], 'power_w': row['power_w'], 'ct': float(min(max(ct, 0.0), 0.99))})
    turbine = {'kind': 'farm_turbine', 'name': str(config.get('name') or 'Nova rotor')[:120], 'diameter_m': 2 * float(rotor.tip_radius_m),
               'hub_height_m': _number(config, 'hub_height_m', 1.0, 400.0, required=True),
               'wind_speed_m_s': [r['wind_speed_m_s'] for r in out], 'power_w': [r['power_w'] for r in out], 'ct': [r['ct'] for r in out]}
    notes = ['Thrust coefficient from the BEMT at each schedule point; above rated power it is scaled by CP/CP_available '
             '(an approximation of pitch regulation, which is not computed)']
    return {'turbine': turbine, 'table': {'kind': 'turbine_curve', 'rows': out},
            'values': {'diameter_m': turbine['diameter_m'], 'rated_power_w': max(turbine['power_w'])}, 'notes': notes}


def farm_layout(node, args):
    config = node.get('config', {})
    diameter = (args.get('turbine') or {}).get('diameter_m') or _number(config, 'diameter_m', 0.1, 500.0)
    mode = config.get('mode', 'grid')
    if mode == 'explicit':
        x, y = config.get('x_m') or [], config.get('y_m') or []
        if not x or len(x) != len(y):
            raise FarmBlockError('Give x_m and y_m lists of equal length')
        x, y = [float(v) for v in x], [float(v) for v in y]
    elif mode == 'grid':
        if diameter is None:
            raise FarmBlockError('Connect the turbine or set diameter_m (spacings are in rotor diameters)')
        rows_, cols = int(config.get('rows', 2)), int(config.get('columns', 3))
        if not 1 <= rows_ * cols <= 128:
            raise FarmBlockError('A grid holds 1–128 turbines')
        sx = _number(config, 'spacing_x_d', 1.0, 50.0, 7.0) * diameter
        sy = _number(config, 'spacing_y_d', 1.0, 50.0, 5.0) * diameter
        stagger = _number(config, 'stagger', 0.0, 1.0, 0.0)
        angle = math.radians(_number(config, 'angle_deg', -180.0, 180.0, 0.0))
        x, y = [], []
        for i in range(rows_):
            for j in range(cols):
                px, py = j * sx + (stagger * sx if i % 2 else 0.0), i * sy
                x.append(px * math.cos(angle) - py * math.sin(angle))
                y.append(px * math.sin(angle) + py * math.cos(angle))
    else:
        raise FarmBlockError('mode must be grid or explicit')
    if len(set(zip(x, y))) != len(x):
        raise FarmBlockError('Turbine positions must be distinct')
    layout = {'kind': 'farm_layout', 'x_m': x, 'y_m': y}
    return {'layout': layout, 'values': {'turbines': float(len(x))}}


def wind_climate(node, _args):
    config = node.get('config', {})
    try:
        climate = farm.weibull_climate(sectors=int(config.get('sectors', 12)), frequencies=config.get('frequencies'),
                                       mean_wind_m_s=_number(config, 'mean_wind_m_s', 0.5, 30.0, 8.0),
                                       shape=_number(config, 'weibull_k', 0.5, 10.0, 2.0),
                                       speeds=np.arange(_number(config, 'speed_min_m_s', 0.0, 50.0, 3.0),
                                                        _number(config, 'speed_max_m_s', 1.0, 60.0, 25.0) + 1e-9,
                                                        _number(config, 'speed_step_m_s', 0.1, 10.0, 1.0)))
    except farm.FarmError as exc:
        raise FarmBlockError(str(exc)) from exc
    climate['turbulence_intensity'] = _number(config, 'turbulence_intensity', 0.0, 1.0, 0.1)
    return {'climate': {'kind': 'wind_climate', **climate},
            'values': {'excluded_probability': climate['excluded_probability']}}


def wind_farm(node, args, cancelled=None):
    config = node.get('config', {})
    turbine, layout, climate = args['turbine'], args['layout'], args['climate']
    engine = config.get('engine', 'native')
    k = _number(config, 'wake_expansion', 0.0, 1.0, 0.1)
    n = len(layout['x_m'])
    if min(climate['speeds_m_s']) < turbine['wind_speed_m_s'][0] or max(climate['speeds_m_s']) > turbine['wind_speed_m_s'][-1]:
        raise FarmBlockError('The wind-climate speed bins must lie inside the turbine curve (cut-in to cut-out)')
    if engine == 'native':
        waked, gross = farm.farm_aep(layout, turbine, climate, k=k)
        notes = ['Native NOJ (Jensen) wake model: top-hat deficit, area overlap, root-sum-square superposition, C_T at the upstream '
                 f'effective speed, k = {k:g}; flat terrain, no shear']
    elif engine == 'pywake':
        import uuid

        import database
        from nova.adapters.base import AdapterError, execute_adapter
        from nova.adapters.registry import get
        from nova.application.external import configuration
        if k != 0.1:
            raise FarmBlockError('The PyWake adapter runs NOJ with k = 0.1')
        integration = _integration('pywake', config.get('integration_id'))
        case = {'turbine': {key: turbine[key] for key in ('name', 'diameter_m', 'hub_height_m', 'wind_speed_m_s', 'power_w', 'ct')},
                'layout': {'x_m': layout['x_m'], 'y_m': layout['y_m']},
                'wind': {key: climate[key] for key in ('directions_deg', 'speeds_m_s', 'probabilities', 'turbulence_intensity')},
                'wake_model': 'noj'}
        root = database.DB_PATH.parent / 'external-runs' / str(uuid.uuid4())
        root.mkdir(parents=True)
        try:
            output = execute_adapter(get('pywake'), configuration(integration), case, root, cancelled=cancelled)
        except (AdapterError, ValueError) as exc:
            raise FarmBlockError(str(exc)) from exc
        scale = 1 - climate.get('excluded_probability', 0.0)
        waked = np.asarray(output['data']['aep_gwh']) * scale
        gross = np.asarray(output['data']['aep_without_wakes_gwh']) * scale
        notes = [f'PyWake {output["data"].get("program_version", "")} NOJ (k = 0.1) through the external adapter']
    else:
        raise FarmBlockError('engine must be native or pywake')
    availability = _number(config, 'availability', 0.0, 1.0, 1.0)
    waked, gross = waked * availability, gross * availability
    total, reference = float(waked.sum()), float(gross.sum())
    rated = max(turbine['power_w'])
    rows = [{'turbine': i + 1, 'x_m': layout['x_m'][i], 'y_m': layout['y_m'][i], 'aep_gwh': float(waked[i]), 'gross_aep_gwh': float(gross[i]),
             'efficiency': float(waked[i] / gross[i]) if gross[i] > 0 else None} for i in range(n)]
    if climate.get('excluded_probability'):
        notes.append(f'{climate["excluded_probability"] * 100:.2f} % of the time is outside the speed bins (no production)')
    return {'table': {'kind': 'wind_farm', 'rows': rows, 'diameter_m': turbine['diameter_m']},
            'values': {'aep_gwh': total, 'aep_without_wakes_gwh': reference, 'wake_loss_pct': (reference - total) / reference * 100 if reference else 0.0,
                       'capacity_factor': total * 1e9 / (n * rated * 8760) if rated else 0.0, 'turbines': float(n),
                       'aep_kwh': total * 1e6, 'rated_power_w': rated * n},
            'notes': notes}


def dust_rotor(node, args, cancelled=None):
    """Mid-fidelity check of the rotor with DUST (lifting lines + vortex particles), compared with Nova's BEMT."""
    import shutil
    import uuid

    import database
    from nova.adapters.base import AdapterError, execute_adapter
    from nova.adapters.registry import get
    from nova.application.external import configuration
    from nova.physics import dust_case
    config = node.get('config', {})
    spec = rotors.merged(args['spec'])
    built, rotor, fluid = rotors.build(spec)
    if built['kind'] != 'hawt':
        raise FarmBlockError('The DUST block models horizontal-axis rotors')
    if abs(fluid.density_kg_m3 - 1.225) > 0.05:
        raise FarmBlockError('The DUST case uses DUST\'s default air density: connect an air operating point')
    velocity, rpm = rotors.resolve_operating(built, rotor)
    integration = _integration('dust', config.get('integration_id'))
    root = database.DB_PATH.parent / 'external-runs' / str(uuid.uuid4())
    source = root / 'dust_source'
    source.mkdir(parents=True)
    try:
        info = dust_case.write(source, rotor, rotor.section, velocity=velocity, rpm=rpm,
                               revolutions=int(config.get('revolutions', 4)), steps_per_revolution=int(config.get('steps_per_revolution', 48)),
                               nelem_span=int(config.get('span_elements', 24)), particles=int(config.get('particles', 60000)),
                               kinematic_viscosity=fluid.viscosity_pa_s / fluid.density_kg_m3)
        case = {'case_directory': str(source), 'loads_file': info['loads_file'], 'timeout_seconds': float(config.get('timeout_seconds', 3600.0))}
        output = execute_adapter(get('dust'), configuration(integration), case, root, cancelled=cancelled)
        loads = dust_case.read_loads(output['data']['loads_text'])
        performance = dust_case.rotor_performance(loads, window=info['last_revolution'], omega=rpm * math.pi / 30, velocity=velocity,
                                                  density=fluid.density_kg_m3, tip_radius=float(rotor.tip_radius_m))
    except (AdapterError, dust_case.DustError) as exc:
        shutil.rmtree(source, ignore_errors=True)
        raise FarmBlockError(str(exc)) from exc
    bemt = rotors.analyze(spec)
    values = {f'dust_{k}': v for k, v in performance.items() if k != 'samples'}
    values.update(bemt_CP=bemt['coefficients']['CP'], bemt_CT=bemt['coefficients']['CT'],
                  CP_difference_pct=(performance['CP'] - bemt['coefficients']['CP']) / bemt['coefficients']['CP'] * 100)
    rows = [{'time_s': float(t), 'thrust_n': float(fz), 'torque_nm': float(mz)} for t, fz, mz in zip(loads[:, 0], loads[:, 3], loads[:, 6])]
    notes = [f'DUST lifting-line rotor with vortex-particle wake, {config.get("revolutions", 4)} revolutions, means over the last one '
             f'({performance["samples"]} samples); airfoil tables tabulated from Nova\'s polars (no pitching moment). '
             'Not qualified against a reference DUST run in this build']
    return {'table': {'kind': 'time_series', 'rows': rows}, 'values': values, 'notes': notes}
