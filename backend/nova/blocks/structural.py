"""Structural-dynamics blocks: attachments, blade and tower modes, Campbell diagram (no aerodynamics).

All modal blocks use the 3-D coupled beam of ``nova.physics.modal``. Attachment blocks chain: each takes
the list built upstream and appends its own item, so any number of point masses, springs and dampers
reach the modal blocks through one optional input.
"""
import math

import numpy as np

from nova.physics import coupled, modal, rotors

TARGETS = ('blade', 'tower')
DIRECTIONS = ('both', 'flap', 'edge', 'fore_aft', 'side_side', 'torsion', 'axial')
BLADE_ONLY, TOWER_ONLY = ('flap', 'edge'), ('fore_aft', 'side_side')
MAX_ATTACHMENTS = 50
MODEL_NOTE = ('3-D Timoshenko beam (axial, shear, bending and torsion coupled through structural twist and centre-of-mass '
              'offset), spectral elements; no aerodynamics')


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
    if (target == 'blade' and direction in TOWER_ONLY) or (target == 'tower' and direction in BLADE_ONLY):
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
    """Blade count, radii, operating rpm (None when not fixed) and the blade orientation (twist + pitch) over the span."""
    built, rotor, _ = rotors.build(spec)
    if built['kind'] not in ('hawt', 'propeller', 'marine'):
        raise StructuralError('Rotor-based structural blocks apply to axial rotors (HAWT, air and marine propellers)')
    try:
        rpm = rotors.resolve_operating(built, rotor)[1]
    except ValueError:
        rpm = None
    tip, hub = float(rotor.tip_radius_m), float(rotor.hub_radius_m)
    fraction = (np.asarray(rotor.radius_m) - hub) / (tip - hub)
    angle = np.asarray(rotor.twist_deg) + float(rotor.pitch_deg)
    return {'kind': built['kind'], 'blades': int(rotor.blades), 'tip': tip, 'hub': hub, 'rpm': rpm,
            'twist': lambda x: np.interp(x, fraction, angle)}


def _blade_setup(config, blade, spec):
    rotor = _rotor(spec) if spec is not None else None
    length = _number(config, 'length_m', 0.01, 500.0, positive=True)
    if length is None:
        if rotor is None:
            raise StructuralError('Connect a rotor or set length_m')
        length = rotor['tip'] - rotor['hub']
    notes = []
    twist = None
    if 'structural_twist_deg' in (blade.get('extended') or {}):
        notes.append('Structural twist from the blade stations')
    elif rotor is not None and config.get('use_aerodynamic_twist', True):
        twist = rotor['twist']
        notes.append('Structural twist taken equal to the aerodynamic twist plus pitch (principal axes follow the chord)')
    else:
        notes.append('No structural twist: flap and edge principal axes stay aligned with the rotor plane')
    return rotor, length, twist, notes


def _family_counts(config, keys, defaults):
    return {family: _integer(config, key, 0, modal.MAX_MODES, default) for family, key, default in zip(*keys, defaults)}


def _missing_note(component, counts, available):
    lacking = [f for f, n in counts.items() if n and f not in available]
    notes = []
    if 'torsion' in lacking:
        notes.append(f'No {component} torsion modes: add torsional stiffness and torsional inertia columns (torsion is rigid otherwise)')
    if 'axial' in lacking:
        notes.append(f'No {component} axial modes: add an axial stiffness column (the {component} is axially rigid otherwise)')
    return notes


def _modes_output(beam, found, component, rpm):
    rows, record, shapes = [], {}, []
    for family, modes in found.items():
        for k, m in enumerate(modes):
            key = f'{component}_{family}{k + 1}'
            view = modal.describe(beam, m, component)
            rows.append({'mode': key, 'rpm': rpm, 'frequency_hz': m['frequency_hz'], 'natural_hz': m['natural_hz'],
                         'damping_ratio': m['damping_ratio'], 'nodes': view['nodes'],
                         **{f'share_{f}': round(v, 4) for f, v in m['participation'].items()}})
            record[f'{key}_hz'] = m['frequency_hz']
            shapes.append({'id': key, 'label': f'{component.capitalize()} {family} {k + 1}', 'component': component, 'direction': family,
                           'rpm': rpm, 'frequency_hz': m['frequency_hz'], 'damping_ratio': m['damping_ratio'],
                           'participation': m['participation'], **view})
    rows.sort(key=lambda r: r['frequency_hz'])
    shapes.sort(key=lambda s: s['frequency_hz'])
    return rows, record, shapes


def blade_modes(node, args, rotating=False):
    config = node.get('config', {})
    blade, spec, attachments = args['blade'], args.get('spec'), args.get('attachments') or []
    rotor, length, twist, notes = _blade_setup(config, blade, spec)
    rpm = _number(config, 'rpm', 0.0, 1e5, None) if rotating else 0.0
    if rotating and rpm is None:
        if rotor is None:
            raise StructuralError('Connect a rotor or set rpm')
        rpm = rotor['rpm']
        if rpm is None:
            raise StructuralError('The rotor operating point does not fix the rotor speed; set rpm')
    hub = rotor['hub'] if rotor is not None else 0.0
    counts = _family_counts(config, (('flap', 'edge', 'torsion'), ('flap_modes', 'edge_modes', 'torsion_modes')), (3, 2, 1))
    beam = modal.blade_beam(blade, length, twist, attachments)
    available = modal.available(beam, 'blade')
    notes = [MODEL_NOTE, *notes, *_missing_note('blade', counts, available)]
    wanted = {f: n for f, n in counts.items() if n and f in available}
    if not wanted:
        raise StructuralError('Ask for at least one flap or edge mode')
    found = modal.pick(modal.solve(beam, omega=rpm * math.pi / 30, hub_radius=hub if rotating else 0.0,
                                   damping=modal.blade_damping(blade)), wanted)
    short = [f'{f} ({len(found[f])} of {n})' for f, n in wanted.items() if len(found[f]) < n]
    if short:
        notes.append(f'Fewer modes than requested within the first {modal.BASIS}: {", ".join(short)}')
    rows, record, shapes = _modes_output(beam, found, 'blade', rpm)
    record['blade_mass_kg'] = beam.mass_kg
    record['rpm'] = rpm
    if rotating:
        notes.append('Rotating frame: centrifugal stiffening, spin softening, Coriolis and propeller-moment terms; precone not modelled')
    else:
        notes.append('Clamped, non-rotating blade')
    modal_out = {'kind': 'modal', 'component': 'blade', 'length_m': length, 'x': np.linspace(0, 1, modal.SHAPE_POINTS).tolist(),
                 'modes': shapes, 'layout': _layout(rotor, length, None, None)}
    return {'table': {'kind': 'modes', 'rows': rows}, 'values': record, 'modal': modal_out, 'notes': notes}


def _top_bodies(config, args):
    """Rigid bodies at the tower top (tower frame: x up, y lateral, z downwind) and a description of them."""
    override = _number(config, 'top_mass_kg', 0.0, 1e8, None)
    extra = _number(config, 'top_inertia_kg_m2', 0.0, 1e12, 0.0)
    bending = np.diag([0.0, extra, extra])
    if override is not None:
        return [(override, (0.0, 0.0, 0.0), bending)], f'top mass {override:g} kg from the block setting', override
    bodies, parts, total = [], [], 0.0
    nacelle = args.get('nacelle')
    if nacelle:
        bodies.append((nacelle['mass_kg'], (nacelle['cm_up_m'], nacelle['cm_lateral_m'], nacelle['cm_downwind_m']),
                       np.diag([nacelle['yaw_inertia_kg_m2'], 0.0, 0.0])))
        parts.append('nacelle (with its centre-of-mass offset and yaw inertia)')
    rotor_mass, shaft_inertia = 0.0, 0.0
    if args.get('hub'):
        rotor_mass += args['hub']['mass_kg']
        shaft_inertia += args['hub']['inertia_kg_m2']
        parts.append('hub')
    if args.get('blade') and args.get('spec'):
        rotor = _rotor(args['spec'])
        fraction, mass = (np.array(c) for c in list(zip(*args['blade']['stations']))[:2])
        length = rotor['tip'] - rotor['hub']
        x = np.linspace(0, 1, 401)
        m = np.interp(x, fraction, mass)
        r = rotor['hub'] + x * length
        tip = args['blade'].get('tip_mass_kg', 0.0)
        rotor_mass += rotor['blades'] * (np.trapezoid(m, x) * length + tip)
        shaft_inertia += rotor['blades'] * (np.trapezoid(m * r**2, x) * length + tip * rotor['tip'] ** 2)
        parts.append(f'{rotor["blades"]} blades')
    if rotor_mass:
        if not nacelle:
            raise StructuralError('Connect the nacelle block to place the rotor mass (overhang and shaft height)')
        # parked rotor as a disc: polar inertia about the shaft (z), half of it about the two other axes
        bodies.append((rotor_mass, (nacelle['tower_top_to_shaft_m'], 0.0, nacelle['overhang_m']),
                       np.diag([shaft_inertia / 2, shaft_inertia / 2, shaft_inertia])))
    if extra:
        bodies.append((0.0, (0.0, 0.0, 0.0), bending))
    total = sum(b[0] for b in bodies)
    return bodies, ('top: ' + ', '.join(parts)) if parts else 'no top mass', total


def tower_modes(node, args):
    config = node.get('config', {})
    tower, attachments = args['tower'], args.get('attachments') or []
    counts = _family_counts(config, (('fa', 'ss', 'torsion'), ('modes', 'modes', 'torsion_modes')), (2, 2, 1))
    bodies, source, total = _top_bodies(config, args)
    beam = modal.tower_beam(tower, bodies, attachments)
    available = modal.available(beam, 'tower')
    wanted = {f: n for f, n in counts.items() if n and f in available}
    found = modal.pick(modal.solve(beam, damping={f: tower['damping_pct'] / 100 for f in modal.FAMILIES['tower']},
                                   component='tower'), wanted)
    rows, record, shapes = _modes_output(beam, found, 'tower', 0.0)
    record['tower_top_mass_kg'] = float(total)
    notes = [MODEL_NOTE, f'Clamped tower; {source}; parked rotor (no gyroscopic coupling), no foundation flexibility',
             *_missing_note('tower', counts, available)]
    if tower.get('shape') == 'tubular':
        notes.append(f'Tubular tower: axial, shear (factor {0.5:g}) and torsional properties from the material, Poisson ratio 0.3')
    modal_out = {'kind': 'modal', 'component': 'tower', 'length_m': tower['height_m'],
                 'x': np.linspace(0, 1, modal.SHAPE_POINTS).tolist(), 'modes': shapes,
                 'layout': _tower_layout(args, tower)}
    return {'table': {'kind': 'modes', 'rows': rows}, 'values': record, 'modal': modal_out, 'notes': notes}


def campbell(node, args):
    config = node.get('config', {})
    blade, spec, attachments = args['blade'], args['spec'], args.get('attachments') or []
    rotor, length, twist, twist_notes = _blade_setup(config, blade, spec)
    operating = _number(config, 'operating_rpm', 0.0, 1e5, None, positive=True) or rotor['rpm']
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
    counts = _family_counts(config, (('flap', 'edge', 'torsion'), ('flap_modes', 'edge_modes', 'torsion_modes')), (2, 1, 0))
    tower = args.get('tower')
    tower_counts, bodies, source = None, (), ''
    if tower is not None:
        n = _integer(config, 'tower_modes', 0, modal.MAX_MODES, 2)
        tower_counts = {'fa': n, 'ss': n, 'torsion': _integer(config, 'tower_torsion_modes', 0, modal.MAX_MODES, 0)}
        bodies, source, _ = _top_bodies(config, {**args, 'blade': blade, 'spec': spec})
    coupling = config.get('coupling', 'none')
    if coupling not in ('none', 'mbc'):
        raise StructuralError('coupling must be none or mbc')
    if coupling == 'mbc':
        return _coupled_campbell(config, args, rotor, length, twist, twist_notes, operating, np.linspace(low, high, points),
                                 harmonics, counts, attachments)
    try:
        result = modal.campbell(blade, length, rotor['hub'], rotor['blades'], np.linspace(low, high, points), twist=twist,
                                tower=tower, top_bodies=bodies, counts=counts, tower_counts=tower_counts,
                                harmonics=harmonics or None, attachments=attachments)
    except modal.ModalError as exc:
        raise StructuralError(str(exc)) from exc
    for curve in result['curves']:
        if curve['frame'] == 'rotating' and rotor['blades'] >= 3:
            curve['fixed_frame'] = modal.whirl(curve, result['rpm'])
    rows = _rows(result)
    record = {'crossings': len(result['crossings'])}
    beam = modal.blade_beam(blade, length, twist, attachments)
    notes = [MODEL_NOTE, *twist_notes, *_missing_note('blade', counts, modal.available(beam, 'blade')),
             'Blade modes in the rotating frame (centrifugal stiffening, spin softening, Coriolis); tower modes fixed with a parked '
             'rotor; no rotor–tower coupling. Fixed-frame whirl frequencies f ± Ω/2π assume an isotropic rotor.']
    if tower is not None:
        notes.append(f'Tower {source}')
    _finish_campbell(result, record, notes, operating)
    modal_out = {'kind': 'modal', 'component': 'system', 'blade_length_m': length, 'blades': rotor['blades'],
                 'tower_height_m': tower['height_m'] if tower else None, 'x': np.linspace(0, 1, modal.SHAPE_POINTS).tolist(),
                 'campbell': result, 'operating_rpm': operating, 'layout': _layout(rotor, length, tower, args.get('nacelle'))}
    return {'table': {'kind': 'campbell', 'rows': rows}, 'values': record, 'modal': modal_out, 'notes': notes}


def _rows(result):
    rows = []
    for i, speed in enumerate(result['rpm']):
        row = {'rpm': speed}
        for curve in result['curves']:
            row[f'{curve["id"]}_hz'] = curve['frequency_hz'][i]
        for name, line in result['excitation'].items():
            row[f'{name}_hz'] = line[i]
        rows.append(row)
    return rows


def _finish_campbell(result, record, notes, operating):
    if operating:
        values, worst, at = modal.margins(result, operating)
        record.update({f'{k}_hz': v for k, v in values.items()})
        record['operating_rpm'] = operating
        record['min_excitation_margin_pct'] = worst
        record['crossings_near_operating'] = len([c for c in result['crossings'] if abs(c['rpm'] - operating) / operating <= 0.1])
        if at:
            notes.append(f'Smallest excitation margin at {operating:g} rpm: {at} ({worst:.1f} %)')
    weak = [c['id'] for c in result['curves'] if c['tracking_mac_min'] < 0.8]
    if weak:
        notes.append(f'Mode tracking uncertain (MAC < 0.8) for {", ".join(weak)}: modes may swap between speeds')


def _coupled_campbell(config, args, rotor, length, twist, twist_notes, operating, rpm, harmonics, counts, attachments):
    blade, tower, nacelle = args['blade'], args.get('tower'), args.get('nacelle')
    if tower is None or nacelle is None:
        raise StructuralError('The coupled Campbell diagram needs the tower and nacelle blocks (hub optional)')
    if rotor['blades'] < 3:
        raise StructuralError('The coupled Campbell diagram needs at least three blades (two-bladed rotors are not isotropic)')
    n = _integer(config, 'tower_modes', 0, modal.MAX_MODES, 2)
    tower_counts = {'fa': n, 'ss': n, 'torsion': _integer(config, 'tower_torsion_modes', 0, modal.MAX_MODES, 0)}
    bodies = [(nacelle['mass_kg'], (nacelle['cm_up_m'], nacelle['cm_lateral_m'], nacelle['cm_downwind_m']),
               np.diag([nacelle['yaw_inertia_kg_m2'], 0.0, 0.0]))]
    blade_model = modal.blade_beam(blade, length, twist, attachments)
    tower_model = modal.tower_beam(tower, bodies, attachments)
    blade_counts = {k: v for k, v in counts.items() if v and k in modal.available(blade_model, 'blade')}
    tower_counts = {k: v for k, v in tower_counts.items() if v and k in modal.available(tower_model, 'tower')}
    if not blade_counts or not tower_counts:
        raise StructuralError('Ask for at least one blade mode and one tower mode')
    try:
        curves, short = coupled.campbell(blade_model, tower_model, blades=rotor['blades'], hub_radius=rotor['hub'],
                                         hub_offset=(nacelle['tower_top_to_shaft_m'], 0.0, nacelle['overhang_m']), rpm=rpm,
                                         blade_counts=blade_counts, tower_counts=tower_counts,
                                         blade_damping=modal.blade_damping(blade), tower_damping=tower['damping_pct'] / 100,
                                         hub=args.get('hub'))
    except (coupled.CoupledError, modal.ModalError) as exc:
        raise StructuralError(str(exc)) from exc
    harmonics = sorted(set(harmonics or [1, rotor['blades'], 2 * rotor['blades']]))
    result = {'rpm': rpm.tolist(), 'curves': curves, 'harmonics': harmonics,
              'excitation': {f'{h}P': (h * rpm / 60.0).tolist() for h in harmonics},
              'crossings': modal.crossings(curves, rpm, harmonics), 'coupling': 'mbc'}
    record = {'crossings': len(result['crossings'])}
    notes = [MODEL_NOTE, *twist_notes, *_missing_note('blade', counts, modal.available(blade_model, 'blade')),
             'Rotor–tower coupled modes in the fixed frame: tower modes and the rotating-blade modes of every blade coupled through '
             'the hub motion (mass, Coriolis, centrifugal and gyroscopic terms), multi-blade coordinates (collective, backward and '
             'forward whirl), azimuth-averaged system (MBC3, Bir 2008). Isotropic rotor, no gravity, no aerodynamics, no shaft tilt '
             'or precone, rigid drivetrain (no generator degree of freedom).',
             f'Tower: nacelle at the top, rotor coupled through its {rotor["blades"]} flexible blades'
             + (' and a rotating hub' if args.get('hub') else ' (hub mass not connected)')]
    if short:
        notes.append('Fewer tower modes than requested: ' + ', '.join(f'{k} ({a} of {b})' for k, (a, b) in short.items()))
    _finish_campbell(result, record, notes, operating)
    modal_out = {'kind': 'modal', 'component': 'system', 'blade_length_m': length, 'blades': rotor['blades'],
                 'tower_height_m': tower['height_m'], 'x': np.linspace(0, 1, modal.SHAPE_POINTS).tolist(),
                 'shape_x': np.linspace(0, 1, coupled.SHAPE_POINTS).tolist(),
                 'campbell': result, 'operating_rpm': operating, 'layout': _layout(rotor, length, tower, nacelle)}
    return {'table': {'kind': 'campbell', 'rows': _rows(result)}, 'values': record, 'modal': modal_out, 'notes': notes}


def _tower_layout(args, tower):
    rotor = _rotor(args['spec']) if args.get('spec') else None
    return _layout(rotor, rotor['tip'] - rotor['hub'] if rotor else None, tower, args.get('nacelle'))


def _layout(rotor, length, tower, nacelle):
    """Geometry the 3-D mode view draws: what is known of tower, nacelle and rotor (missing parts are left out)."""
    out = {}
    if rotor is not None:
        out.update(blades=rotor['blades'], hub_radius_m=rotor['hub'], blade_length_m=length)
    elif length:
        out.update(blade_length_m=length)
    if tower is not None:
        out['tower_height_m'] = tower['height_m']
        out['tower_base_diameter_m'] = tower.get('base_diameter_m')
        out['tower_top_diameter_m'] = tower.get('top_diameter_m')
    if nacelle is not None:
        out.update(overhang_m=nacelle['overhang_m'], shaft_height_m=nacelle['tower_top_to_shaft_m'])
    return out
