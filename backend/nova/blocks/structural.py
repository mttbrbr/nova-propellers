"""Structural-dynamics blocks: attachments, blade and tower modes, Campbell diagram (no aerodynamics).

Attachment blocks chain: each takes the list built upstream and appends its own item, so any number of
point masses, springs and dampers reach the modal blocks through one optional input.
"""
import math

import numpy as np

from nova.physics import modal, rotors

TARGETS = ('blade', 'tower')
DIRECTIONS = ('both', 'flap', 'edge', 'fore_aft', 'side_side')
MAX_ATTACHMENTS = 50


class StructuralError(ValueError):
    pass


def _number(config, key, low, high, default=None, positive=False):
    value = config.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise StructuralError(f'{key} must be a finite number')
    if not low <= value <= high or (positive and value <= 0):
        raise StructuralError(f'{key} must be {"above 0 and " if positive else ""}between {low:g} and {high:g}')
    return float(value)


def _integer(config, key, low, high, default):
    value = config.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise StructuralError(f'{key} must be an integer in {low}–{high}')
    return value


def _attachment(config, kind):
    target = config.get('target', 'blade')
    if target not in TARGETS:
        raise StructuralError('target must be blade or tower')
    direction = config.get('direction', 'both')
    if direction not in DIRECTIONS:
        raise StructuralError(f'direction must be one of {", ".join(DIRECTIONS)}')
    if (target == 'blade' and direction in ('fore_aft', 'side_side')) or (target == 'tower' and direction in ('flap', 'edge')):
        raise StructuralError(f'direction {direction} does not apply to the {target}')
    item = {'kind': kind, 'target': target, 'direction': direction, 'position': _number(config, 'position', 0.0, 1.0, 1.0)}
    if kind == 'point_mass':
        item['mass_kg'] = _number(config, 'mass_kg', 0.0, 1e8, 0.0)
        item['inertia_kg_m2'] = _number(config, 'inertia_kg_m2', 0.0, 1e12, 0.0)
        if not item['mass_kg'] and not item['inertia_kg_m2']:
            raise StructuralError('A point mass needs a mass or a rotary inertia')
    else:
        for key, high in (('stiffness_n_m', 1e12), ('damping_ns_m', 1e10), ('rotational_stiffness_nm_rad', 1e14),
                          ('rotational_damping_nms_rad', 1e12)):
            item[key] = _number(config, key, 0.0, high, 0.0)
        if not any(item[k] for k in ('stiffness_n_m', 'damping_ns_m', 'rotational_stiffness_nm_rad', 'rotational_damping_nms_rad')):
            raise StructuralError('A spring/damper needs at least one non-zero stiffness or damping')
        if item['position'] == 0.0:
            raise StructuralError('A spring/damper at the clamped end has no effect')
    return item


def attachment_handler(kind):
    def handler(node, args):
        upstream = list(args.get('attachments') or [])
        if len(upstream) >= MAX_ATTACHMENTS:
            raise StructuralError(f'At most {MAX_ATTACHMENTS} attachments can be chained')
        return {'attachments': upstream + [_attachment(node.get('config', {}), kind)]}
    return handler


def _rotor(spec):
    """Blade count, tip and hub radius and operating rpm (None when the operating point is incomplete)."""
    built, rotor, _ = rotors.build(spec)
    if built['kind'] != 'hawt':
        raise StructuralError('Rotor-based structural blocks apply to horizontal-axis wind turbines')
    try:
        rpm = rotors.resolve_operating(built, rotor)[1]
    except ValueError:
        rpm = None
    return int(rotor.blades), float(rotor.tip_radius_m), float(rotor.hub_radius_m), rpm


def _blade_length(config, spec):
    length = _number(config, 'length_m', 0.01, 500.0, positive=True)
    hub = 0.0
    if spec is not None:
        _, tip, hub, _ = _rotor(spec)
        if length is None:
            length = tip - hub
    if length is None:
        raise StructuralError('Connect a rotor or set length_m')
    return length, hub


def _mode_rows(found, component, direction, rpm, beam, short=None):
    short = short or direction
    rows, record = [], {}
    for k, m in enumerate(found):
        key = f'{component}_{short}{k + 1}'
        rows.append({'mode': key, 'rpm': rpm, 'frequency_hz': m['frequency_hz'], 'natural_hz': m['natural_hz'],
                     'damping_ratio': m['damping_ratio'], 'nodes': m['nodes']})
        record[f'{key}_hz'] = m['frequency_hz']
    shapes = [{'id': f'{component}_{short}{k + 1}', 'label': m['label'], 'component': component, 'direction': direction,
               'rpm': rpm, 'frequency_hz': m['frequency_hz'], 'damping_ratio': m['damping_ratio'],
               'shape': modal.sample(beam, m['shape'])} for k, m in enumerate(found)]
    return rows, record, shapes


def blade_modes(node, args, rotating=False):
    config = node.get('config', {})
    blade, spec, attachments = args['blade'], args.get('spec'), args.get('attachments') or []
    length, hub = _blade_length(config, spec)
    rpm = _number(config, 'rpm', 0.0, 1e5, None) if rotating else 0.0
    if rotating and rpm is None:
        if spec is None:
            raise StructuralError('Connect a rotor or set rpm')
        rpm = _rotor(spec)[3]
        if rpm is None:
            raise StructuralError('The rotor operating point does not fix the rotor speed; set rpm')
    rows, record, shapes = [], {}, []
    for direction, key in (('flap', 'flap_modes'), ('edge', 'edge_modes')):
        count = _integer(config, key, 0, modal.MAX_MODES, 3 if direction == 'flap' else 2)
        if not count:
            continue
        beam = modal.blade_beam(blade, length, direction, attachments)
        found = modal.modes(beam, modes=count, omega=rpm * math.pi / 30, hub_radius=hub if rotating else 0.0,
                            direction=direction, damping_ratio=blade[f'{direction}_damping_pct'] / 100, label=f'Blade {direction}')
        r, v, s = _mode_rows(found, 'blade', direction, rpm, beam)
        rows += r
        record.update(v)
        shapes += s
    if not rows:
        raise StructuralError('Ask for at least one flap or edge mode')
    record['blade_mass_kg'] = modal.blade_mass_kg(blade, length, attachments)
    record['rpm'] = rpm
    notes = ['Euler–Bernoulli beam, flap and edge uncoupled (no structural twist, precone or Coriolis coupling); no aerodynamics']
    if rotating:
        notes.append('Centrifugal stiffening from the blade mass about the rotor axis; edgewise modes include spin softening')
    else:
        notes.append('Clamped, non-rotating blade')
    modal_out = {'kind': 'modal', 'component': 'blade', 'length_m': length, 'x': np.linspace(0, 1, modal.SHAPE_POINTS).tolist(),
                 'modes': shapes}
    return {'table': {'kind': 'modes', 'rows': rows}, 'values': record, 'modal': modal_out, 'notes': notes}


def _top_mass(config, args):
    top = _number(config, 'top_mass_kg', 0.0, 1e8, None)
    if top is not None:
        return top, 'top mass from the block setting'
    parts, total = [], 0.0
    if args.get('nacelle'):
        total += args['nacelle']['mass_kg']
        parts.append('nacelle')
    if args.get('hub'):
        total += args['hub']['mass_kg']
        parts.append('hub')
    if args.get('blade') and args.get('spec'):
        blades, tip, hub, _ = _rotor(args['spec'])
        total += blades * modal.blade_mass_kg(args['blade'], tip - hub)
        parts.append(f'{blades} blades')
    return total, ('top mass: ' + ' + '.join(parts)) if parts else 'no top mass'


def tower_modes(node, args):
    config = node.get('config', {})
    tower, attachments = args['tower'], args.get('attachments') or []
    count = _integer(config, 'modes', 1, modal.MAX_MODES, 2)
    top, source = _top_mass(config, args)
    inertia = _number(config, 'top_inertia_kg_m2', 0.0, 1e12, 0.0)
    rows, record, shapes = [], {}, []
    for direction, short in (('fore_aft', 'fa'), ('side_side', 'ss')):
        beam = modal.tower_beam(tower, direction, top, inertia, attachments)
        found = modal.modes(beam, modes=count, direction='none', damping_ratio=tower['damping_pct'] / 100,
                            label=f'Tower {direction.replace("_", "-")}')
        r, v, s = _mode_rows(found, 'tower', direction, 0.0, beam, short)
        rows += r
        record.update(v)
        shapes += s
    record['tower_top_mass_kg'] = top
    notes = [f'Clamped tower, {source} lumped at the top (rotary inertia {inertia:g} kg·m²); no foundation flexibility, no aerodynamics']
    modal_out = {'kind': 'modal', 'component': 'tower', 'length_m': tower['height_m'],
                 'x': np.linspace(0, 1, modal.SHAPE_POINTS).tolist(), 'modes': shapes}
    return {'table': {'kind': 'modes', 'rows': rows}, 'values': record, 'modal': modal_out, 'notes': notes}


def campbell(node, args):
    config = node.get('config', {})
    blade, spec, attachments = args['blade'], args['spec'], args.get('attachments') or []
    blades, tip, hub, spec_rpm = _rotor(spec)
    operating = _number(config, 'operating_rpm', 0.0, 1e5, None, positive=True) or spec_rpm
    low = _number(config, 'rpm_min', 0.0, 1e5, 0.0)
    high = _number(config, 'rpm_max', 0.0, 1e5, None, positive=True)
    if high is None:
        if not operating:
            raise StructuralError('Set rpm_max or an operating rotor speed')
        high = 1.25 * operating
    if high <= low:
        raise StructuralError('rpm_max must be above rpm_min')
    points = _integer(config, 'points', 3, 101, 31)
    harmonics = config.get('harmonics') or []
    if not isinstance(harmonics, list) or any(type(h) is not int or not 1 <= h <= 30 for h in harmonics) or len(harmonics) > 10:
        raise StructuralError('harmonics must be a list of at most 10 integers in 1–30')
    tower = args.get('tower')
    top, source = _top_mass(config, {**args, 'blade': blade, 'spec': spec}) if tower else (0.0, '')
    try:
        result = modal.campbell(blade, tip - hub, hub, blades, np.linspace(low, high, points), tower=tower, top_mass_kg=top,
                                top_inertia_kg_m2=_number(config, 'top_inertia_kg_m2', 0.0, 1e12, 0.0),
                                flap_modes=_integer(config, 'flap_modes', 0, modal.MAX_MODES, 2),
                                edge_modes=_integer(config, 'edge_modes', 0, modal.MAX_MODES, 1),
                                tower_modes=_integer(config, 'tower_modes', 0, modal.MAX_MODES, 2) if tower else 0,
                                harmonics=harmonics or None, attachments=attachments)
    except modal.ModalError as exc:
        raise StructuralError(str(exc)) from exc
    for curve in result['curves']:
        if curve['frame'] == 'rotating' and blades >= 3:
            curve['fixed_frame'] = modal.whirl(curve, result['rpm'])
    rows = []
    for i, speed in enumerate(result['rpm']):
        row = {'rpm': speed}
        for curve in result['curves']:
            row[f'{curve["id"]}_hz'] = curve['frequency_hz'][i]
        for name, line in result['excitation'].items():
            row[f'{name}_hz'] = line[i]
        rows.append(row)
    record = {'crossings': len(result['crossings'])}
    notes = ['Blade modes in the rotating frame (centrifugal stiffening, spin softening); tower modes fixed; no aerodynamics, '
             'no rotor–tower coupling. Fixed-frame whirl frequencies f ± Ω/2π assume an isotropic rotor.']
    if tower is not None:
        notes.append(f'Tower: {source} lumped at the top')
    if operating:
        values, worst, at = modal.margins(result, operating)
        record.update({f'{k}_hz': v for k, v in values.items()})
        record['operating_rpm'] = operating
        record['min_excitation_margin_pct'] = worst
        if at:
            notes.append(f'Smallest excitation margin at {operating:g} rpm: {at} ({worst:.1f} %)')
        crossing_in = [c for c in result['crossings'] if abs(c['rpm'] - operating) / operating <= 0.1]
        record['crossings_near_operating'] = len(crossing_in)
    weak = [c['id'] for c in result['curves'] if c['tracking_mac_min'] < 0.8]
    if weak:
        notes.append(f'Mode tracking uncertain (MAC < 0.8) for {", ".join(weak)}: modes may swap between speeds')
    modal_out = {'kind': 'modal', 'component': 'system', 'blade_length_m': tip - hub, 'blades': blades,
                 'tower_height_m': tower['height_m'] if tower else None, 'x': np.linspace(0, 1, modal.SHAPE_POINTS).tolist(),
                 'campbell': result, 'operating_rpm': operating}
    return {'table': {'kind': 'campbell', 'rows': rows}, 'values': record, 'modal': modal_out, 'notes': notes}
