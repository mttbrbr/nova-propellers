"""Annual energy and cost blocks (phase 3)."""
import math

from nova.physics import costs, rotors


class EconomicsError(ValueError):
    pass


def _number(config, key, low, high, default=None, required=False):
    value = config.get(key, default)
    if value is None:
        if required:
            raise EconomicsError(f'Set {key}')
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise EconomicsError(f'{key} must be a number between {low:g} and {high:g}')
    return float(value)


def annual_energy(node, args):
    config = node.get('config', {})
    rows = [r for r in args['table'].get('rows', []) if r.get('state', 'succeeded') == 'succeeded'
            and isinstance(r.get('wind_speed_m_s'), (int, float)) and isinstance(r.get('power_w'), (int, float))]
    if len(rows) < 2:
        raise EconomicsError('Connect a power curve: a table with wind_speed_m_s and power_w (e.g. the operating strategy schedule)')
    rows.sort(key=lambda r: r['wind_speed_m_s'])
    mean = _number(config, 'mean_wind_m_s', 0.5, 30.0, 7.0)
    shape = _number(config, 'weibull_k', 0.5, 10.0, 2.0)
    availability = _number(config, 'availability', 0.0, 1.0, 0.97)
    losses = _number(config, 'losses', 0.0, 0.9, 0.0)
    try:
        aep, scale = costs.weibull_aep([r['wind_speed_m_s'] for r in rows], [r['power_w'] for r in rows], mean_wind_m_s=mean,
                                       shape=shape, availability=availability, losses=losses)
    except costs.CostError as exc:
        raise EconomicsError(str(exc)) from exc
    rated = max(r['power_w'] for r in rows)
    record = {'aep_kwh': aep, 'aep_mwh': aep / 1000, 'rated_power_w': rated, 'capacity_factor': aep / (rated / 1000 * 8760),
              'weibull_scale_m_s': scale, 'mean_wind_m_s': mean}
    notes = [f'Weibull wind distribution, mean {mean:g} m/s, k = {shape:g} (scale {scale:.3g} m/s); power curve from the '
             f'connected table between {rows[0]["wind_speed_m_s"]:g} and {rows[-1]["wind_speed_m_s"]:g} m/s, zero outside; '
             f'availability {availability:g}, other losses {losses:g}']
    return {'values': record, 'notes': notes}


def cost_model(node, args):
    config = node.get('config', {})
    values = args.get('values') or {}
    spec = args.get('spec')
    blades = config.get('blades')
    diameter = _number(config, 'rotor_diameter_m', 1.0, 400.0)
    if spec is not None:
        built_spec, rotor, _ = rotors.build(rotors.merged(spec))
        if built_spec['kind'] != 'hawt':
            raise EconomicsError('The NREL cost model applies to horizontal-axis wind turbines')
        diameter = diameter or 2 * float(rotor.tip_radius_m)
        blades = blades or int(rotor.blades)
    if diameter is None:
        raise EconomicsError('Connect a rotor or set rotor_diameter_m')
    blades = blades or 3
    rating = _number(config, 'rating_kw', 1.0, 50000.0)
    notes = []
    if rating is None:
        if 'rated_power_w' not in values:
            raise EconomicsError('Set rating_kw or connect values with rated_power_w (e.g. from the annual energy block)')
        rating = values['rated_power_w'] / 1000
        notes.append(f'Machine rating {rating:.4g} kW from the connected values')
    hub = _number(config, 'hub_height_m', 1.0, 300.0, required=True)
    tip = _number(config, 'max_tip_speed_m_s', 10.0, 150.0)
    if tip is None:
        tip = values.get('tip_speed_m_s') or 80.0
        notes.append(f'Maximum tip speed {tip:.3g} m/s' + (' from the connected values' if 'tip_speed_m_s' in values else ' (default)'))
    turbine_class = config.get('turbine_class', 2)
    if turbine_class not in (1, 2, 3):
        raise EconomicsError('turbine_class must be 1, 2 or 3')
    blade_mass = _number(config, 'blade_mass_kg', 0.0, 1e6)
    if blade_mass is None and 'blade_mass_kg' in values and config.get('use_connected_blade_mass', True):
        blade_mass = values['blade_mass_kg']
        notes.append('Blade mass from the connected values (structural model) instead of the scaling law')
    try:
        result = costs.turbine(rotor_diameter_m=diameter, rating_kw=rating, hub_height_m=hub, blades=blades, max_tip_speed_m_s=tip,
                               drivetrain_efficiency=_number(config, 'drivetrain_efficiency', 0.5, 1.0, 0.95),
                               turbine_class=turbine_class, carbon_spar=bool(config.get('carbon_spar', False)),
                               main_bearings=int(config.get('main_bearings', 2)), crane=bool(config.get('crane', False)),
                               blade_mass_kg=blade_mass, tower_mass_kg=_number(config, 'tower_mass_kg', 0.0, 1e7))
    except costs.CostError as exc:
        raise EconomicsError(str(exc)) from exc
    record = {k: float(v) for k, v in result['totals'].items()}
    record['blade_mass_kg'] = float(next(r['mass_kg'] for r in result['components'] if r['component'] == 'blade'))
    record['rotor_diameter_m'], record['rating_kw'] = diameter, rating
    bos, opex = _number(config, 'bos_per_kw', 0.0, 1e5), _number(config, 'opex_per_kw_yr', 0.0, 1e4)
    fcr = _number(config, 'fixed_charge_rate', 0.0, 1.0, 0.075)
    if 'aep_kwh' in values and bos is not None and opex is not None:
        value, icc = costs.lcoe(turbine_cost_usd=record['turbine_cost_usd'], rating_kw=rating, aep_kwh=values['aep_kwh'],
                                bos_per_kw=bos, opex_per_kw_yr=opex, fixed_charge_rate=fcr,
                                wake_losses=_number(config, 'wake_losses', 0.0, 0.9, 0.0))
        record.update(lcoe_usd_kwh=value, lcoe_usd_mwh=value * 1000, icc_per_kw=icc)
    else:
        notes.append('No LCOE: it needs aep_kwh in the connected values and bos_per_kw and opex_per_kw_yr (site-specific inputs, '
                     'nothing is assumed)')
    notes.insert(0, 'NREL Cost and Scaling Model, 2015 mass–cost update with the coefficients of NREL WISDEM (land-based, '
                    'three-stage geared drivetrain); scaling estimates in the coefficients\' USD, for comparing designs')
    return {'values': record, 'table': {'kind': 'costs', 'rows': result['components']}, 'notes': notes}
