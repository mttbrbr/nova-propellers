"""Engineering constraints: general checks and domain presets.

A check compares an expression over named quantities with a limit::

    {"quantity": "power_w / 1000", "operator": "<=", "value": 10,
     "severity": "hard", "label": "Generator rating", "unit": "kW"}

``margin`` is normalised so that positive means satisfied and its magnitude is
the fraction of the limit still available (or exceeded).
"""
import math

from .expressions import ExpressionError, evaluate

OPERATORS = ('<=', '>=', '<', '>', '==', 'between')
SEVERITIES = ('hard', 'soft')

# Domain presets: label, quantity, operator, default limit, unit, applicable rotor kinds, rationale.
PRESETS = {
    'betz_limit': ('Betz limit', 'CP', '<=', 16 / 27, '-', ('hawt', 'vawt'),
                   'Sanity check: no open rotor can exceed 16/27'),
    'rated_power': ('Rated power', 'power_w', '<=', 10000.0, 'W', ('hawt', 'vawt'),
                    'Generator or drive-train rating'),
    'minimum_power': ('Minimum power', 'power_w', '>=', 1000.0, 'W', ('hawt', 'vawt'),
                      'Required energy capture at the design point'),
    'tip_speed': ('Tip speed', 'tip_speed_m_s', '<=', 80.0, 'm/s', ('hawt', 'vawt', 'propeller', 'marine'),
                  'Noise, leading-edge erosion or structural limit'),
    'tip_mach': ('Section Mach', 'max_section_mach', '<=', 0.7, '-', ('propeller', 'hawt'),
                 'Compressibility validity of the section polars'),
    'max_thrust': ('Rotor thrust', 'thrust_n', '<=', 5000.0, 'N', ('hawt', 'propeller', 'marine'),
                   'Tower, shaft or thrust-bearing load'),
    'min_thrust': ('Required thrust', 'thrust_n', '>=', 10.0, 'N', ('propeller', 'marine'),
                   'Mission thrust requirement'),
    'max_streamwise_force': ('Rotor drag', 'streamwise_force_n', '<=', 2000.0, 'N', ('vawt',),
                             'Overturning load on the support'),
    'min_efficiency': ('Efficiency', 'efficiency', '>=', 0.6, '-', ('propeller',),
                       'Propulsive efficiency requirement'),
    'min_open_water_efficiency': ('Open-water efficiency', 'open_water_efficiency', '>=', 0.55, '-', ('marine',),
                                  'Open-water efficiency requirement'),
    'keller': ('Keller area ratio', 'keller_margin', '>=', 0.0, '-', ('marine',),
               'A_E/A_0 above Keller minimum against back cavitation'),
    'burrill': ('Burrill thrust loading', 'thrust_loading_tau_c', '<=', 0.2, '-', ('marine',),
                'τ_c below the Burrill line read at the computed σ_0.7R (enter the chart value)'),
    'local_cavitation': ('Local cavitation number', 'minimum_local_cavitation_number', '>=', 0.5, '-', ('marine',),
                         'Minimum section σ at top dead centre'),
    'torque_ripple': ('Torque ripple', 'torque_ripple', '<=', 1.5, '-', ('vawt',),
                      'Peak-to-peak blade torque over mean (fatigue, drive train)'),
    'max_alpha': ('Peak incidence', 'max_alpha_deg', '<=', 15.0, 'deg', ('hawt', 'vawt', 'propeller', 'marine'),
                  'Keep sections out of deep stall'),
    'solidity': ('Solidity', 'solidity', '<=', 0.5, '-', ('vawt', 'hawt'),
                 'Upper bound of the momentum model validity'),
}


def preset_catalog():
    return [{'id': key, 'label': p[0], 'quantity': p[1], 'operator': p[2], 'value': p[3], 'unit': p[4],
             'kinds': list(p[5]), 'rationale': p[6]} for key, p in PRESETS.items()]


def from_preset(item):
    preset = PRESETS.get(item.get('preset'))
    if not preset:
        raise ValueError(f'Unknown constraint preset {item.get("preset")!r}')
    return {'label': preset[0], 'quantity': preset[1], 'operator': preset[2], 'value': item.get('value', preset[3]),
            'unit': preset[4], 'severity': item.get('severity', 'hard'), 'preset': item['preset']}


def normalise(check):
    if not isinstance(check, dict):
        raise ValueError('A constraint must be an object')
    if check.get('preset'):
        check = from_preset(check)
    unknown = set(check) - {'label', 'quantity', 'operator', 'value', 'upper', 'tolerance', 'severity', 'unit', 'preset'}
    if unknown:
        raise ValueError(f'Unsupported constraint fields: {", ".join(sorted(unknown))}')
    if check.get('operator') not in OPERATORS:
        raise ValueError(f'Constraint operator must be one of {", ".join(OPERATORS)}')
    if check.get('severity', 'hard') not in SEVERITIES:
        raise ValueError('Constraint severity must be hard or soft')
    for key in ('value', 'upper', 'tolerance'):
        if key in check and check[key] is not None and (isinstance(check[key], bool) or not isinstance(check[key], (int, float)) or not math.isfinite(check[key])):
            raise ValueError(f'Constraint {key} must be a finite number')
    if check.get('value') is None:
        raise ValueError('Constraint needs a limit value')
    if check['operator'] == 'between' and (check.get('upper') is None or check['upper'] < check['value']):
        raise ValueError('A between constraint needs upper ≥ value')
    return {'severity': 'hard', 'label': check.get('label') or check['quantity'], 'unit': check.get('unit', ''), **check}


def evaluate_check(check, quantities):
    check = normalise(check)
    try:
        value = evaluate(check['quantity'], quantities)
    except ExpressionError as exc:
        return {**check, 'value_observed': None, 'satisfied': False, 'margin': None, 'error': str(exc)}
    limit, op = float(check['value']), check['operator']
    scale = max(abs(limit), 1e-9)
    if op in ('<=', '<'):
        ok = value <= limit if op == '<=' else value < limit
        margin = (limit - value) / scale
    elif op in ('>=', '>'):
        ok = value >= limit if op == '>=' else value > limit
        margin = (value - limit) / scale
    elif op == '==':
        tolerance = float(check.get('tolerance') or 1e-6 * scale)
        ok = abs(value - limit) <= tolerance
        margin = (tolerance - abs(value - limit)) / scale
    else:
        upper = float(check['upper'])
        ok = limit <= value <= upper
        margin = min(value - limit, upper - value) / max(upper - limit, 1e-9)
    return {**check, 'value_observed': value, 'satisfied': bool(ok), 'margin': margin}


def report(checks, quantities):
    results = [evaluate_check(c, quantities) for c in checks]
    hard = [r for r in results if r['severity'] == 'hard' and not r['satisfied']]
    soft = [r for r in results if r['severity'] == 'soft' and not r['satisfied']]
    return {'feasible': not hard, 'hard_violations': len(hard), 'soft_violations': len(soft), 'checks': results}


def penalty(checks, quantities):
    """Sum of squared normalised hard-constraint violations (0 when feasible)."""
    total = 0.0
    for r in report(checks, quantities)['checks']:
        if r['severity'] != 'hard' or r['satisfied']:
            continue
        total += 1.0 if r['margin'] is None else r['margin'] ** 2 + 1e-3
    return total
