"""Blade layup (2-D section properties) and CalculiX shell modes (phase 4)."""
import math
import re

import numpy as np

from nova.adapters import openfast_structure as st
from nova.physics import rotors
from nova.physics.section_properties import SectionError, properties


class FemError(ValueError):
    pass


MATERIAL_KEYS = ('E_pa', 'G_pa', 'density_kg_m3', 'thickness_m')


def _material(config, key, extra=()):
    item = config.get(key)
    if not isinstance(item, dict):
        raise FemError(f'{key} must be an object with {", ".join(MATERIAL_KEYS + tuple(extra))}')
    for k in MATERIAL_KEYS + tuple(extra):
        v = item.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise FemError(f'{key}.{k} must be a non-negative number')
    if item['E_pa'] <= 0 or item['G_pa'] <= 0:
        raise FemError(f'{key}: moduli must be positive')
    return dict(item)


def _airfoil(config, rotor):
    code = str(config.get('airfoil', 'auto'))
    if code != 'auto':
        return code
    name = rotor.section.name
    match = re.search(r'NACA\s*(\d{4})\b', name)
    if match:
        return match[1]
    thickness = max(6, min(40, round(float(rotor.section.thickness or 0.18) * 100)))
    return f'44{thickness:02d}'


def blade_layup(node, args):
    config = node.get('config', {})
    spec = rotors.merged(args['spec'])
    built, rotor, _ = rotors.build(spec)
    if built['kind'] != 'hawt':
        raise FemError('The blade layup applies to horizontal-axis rotors')
    shell = _material(config, 'shell')
    cap = _material(config, 'spar_cap', ('centre', 'width', 'tip_thickness_m')) if config.get('spar_cap') else None
    webs = [_material({'w': w}, 'w', ('position',)) for w in config.get('webs') or []]
    count = config.get('stations', 11)
    if type(count) is not int or not 3 <= count <= 41:
        raise FemError('stations must be an integer in 3–41')
    root_cylinder = float(config.get('root_cylinder_fraction', 0.0))
    transition = float(config.get('transition_fraction', 0.15))
    root_diameter = config.get('root_diameter_m')
    pitch_axis = float(config.get('pitch_axis', 0.25))
    hub, tip = float(rotor.hub_radius_m), float(rotor.tip_radius_m)
    length = tip - hub
    code = _airfoil(config, rotor)
    radius, chord, twist = np.asarray(rotor.radius_m), np.asarray(rotor.chord_m), np.asarray(rotor.twist_deg) + float(rotor.pitch_deg)
    rows, sections, layup_stations = [], [], []
    for x in np.linspace(0.0, 1.0, count):
        r = hub + x * length
        c = float(np.interp(r, radius, chord))
        blend = 1.0 if x >= root_cylinder + transition else (0.0 if x <= root_cylinder else (x - root_cylinder) / transition)
        if blend < 1 and root_diameter is not None:
            c = blend * c + (1 - blend) * float(root_diameter)
        local_cap = None
        if cap:
            local_cap = {**cap, 'thickness_m': cap['thickness_m'] + x * (cap['tip_thickness_m'] - cap['thickness_m'])}
        try:
            p = properties(c, code, shell=shell, spar_cap=local_cap, webs=webs, blend=blend)
        except SectionError as exc:
            raise FemError(f'Station {x:.2f}: {exc}') from exc
        aero = float(np.interp(r, radius, twist))
        sections.append({'fraction': float(x), 'radius_m': r, 'chord_m': c, 'blend': blend, **{k: v for k, v in p.items() if k != 'cells'}})
        rows.append({'span_fraction': float(x), 'mass_per_length_kg_m': p['mass_kg_m'], 'flap_stiffness_nm2': p['EI_flap_nm2'],
                     'edge_stiffness_nm2': p['EI_edge_nm2'], 'structural_twist_deg': aero + p['principal_angle_deg'],
                     'axial_stiffness_n': p['EA_n'], 'torsional_stiffness_nm2': p['GJ_nm2'], 'edge_shear_stiffness_n': p['GA_edge_n'],
                     'flap_shear_stiffness_n': p['GA_flap_n'], 'torsional_inertia_kg_m': p['torsional_inertia_kg_m'],
                     'flap_inertia_kg_m': p['flap_inertia_kg_m'], 'edge_inertia_kg_m': p['edge_inertia_kg_m'], 'cm_offset_m': p['cm_offset_m']})
        layup_stations.append({'fraction': float(x), 'chord_m': c, 'twist_deg': aero, 'blend': blend})
    damping = {k: config.get(k, 1.0) for k in ('flap_damping_pct', 'edge_damping_pct')}
    try:
        blade = st.blade_record({'stations': rows, 'tip_mass_kg': float(config.get('tip_mass_kg', 0.0)), **damping})
    except st.StructureError as exc:
        raise FemError(str(exc)) from exc
    x = np.array([s['fraction'] for s in sections])
    mass = float(np.trapezoid([s['mass_kg_m'] for s in sections], x) * length)
    layup = {'kind': 'layup', 'airfoil': code, 'length_m': length, 'hub_radius_m': hub, 'pitch_axis': pitch_axis, 'shell': shell,
             'spar_cap': cap, 'webs': webs, 'stations': layup_stations, 'blades': int(rotor.blades)}
    notes = [f'Thin-walled sections (NACA {code}, smeared isotropic layers): E-weighted centroid and principal bending stiffnesses, '
             'multi-cell Bredt–Batho torsion with the webs, shear stiffness without correction factor; structural twist = aerodynamic '
             'twist + principal-axis angle. Laminate couplings and warping are not modelled']
    if root_cylinder or transition and root_diameter is not None:
        notes.append(f'Circular root to {root_cylinder:g} of the span, blended into the airfoil over {transition:g}')
    return {'blade': blade, 'layup': layup, 'table': {'kind': 'sections', 'rows': sections},
            'values': {'blade_mass_kg': mass, 'root_flap_stiffness_nm2': rows[0]['flap_stiffness_nm2'],
                       'tip_flap_stiffness_nm2': rows[-1]['flap_stiffness_nm2']}, 'notes': notes}


def calculix_blade_modes(node, args, cancelled=None):
    import uuid

    import database
    from nova.adapters.base import AdapterError, execute_adapter
    from nova.adapters.registry import get
    from nova.application.external import configuration
    from nova.infrastructure import library
    from nova.physics.blade_shell import ShellError, deck
    config = node.get('config', {})
    integrations = [r for r in library.list_records('integration') if r.get('adapter_id') == 'calculix']
    chosen = config.get('integration_id') or ''
    integration = next((r for r in integrations if r['id'] == chosen), None) if chosen else (integrations[0] if integrations else None)
    if integration is None:
        raise FemError('No CalculiX executable is configured: add one in Settings → Integrations')
    try:
        text, mesh = deck(args['layup'], span_elements=int(config.get('span_elements', 30)),
                          perimeter_points=int(config.get('perimeter_points', 48)), modes=int(config.get('modes', 10)))
    except ShellError as exc:
        raise FemError(str(exc)) from exc
    root = database.DB_PATH.parent / 'external-runs' / str(uuid.uuid4())
    source = root / 'calculix_source'
    source.mkdir(parents=True)
    (source / 'blade.inp').write_text(text)
    case = {'case_directory': str(source), 'input_file': 'blade.inp', 'timeout_seconds': float(config.get('timeout_seconds', 900.0))}
    try:
        output = execute_adapter(get('calculix'), configuration(integration), case, root, cancelled=cancelled)
    except AdapterError as exc:
        raise FemError(str(exc)) from exc
    return modes_outputs(output['data']['modes'], mesh, args.get('modal'))


def modes_outputs(found, mesh, modal_input=None):
    rows = [{'mode': m['mode'], 'frequency_hz': m['frequency_hz']} for m in found]
    record = {f'shell_mode{m["mode"]}_hz': m['frequency_hz'] for m in found}
    notes = [f'CalculiX shell model: {mesh["nodes"]} nodes, {mesh["elements"]} S4 elements, clamped root, no rotation; '
             'spar-cap regions as one smeared isotropic shell (membrane-equivalent), webs as shell strips']
    if modal_input and modal_input.get('modes'):
        beam = sorted(modal_input['modes'], key=lambda m: m['frequency_hz'])
        for row in rows:
            nearest = min(beam, key=lambda m: abs(m['frequency_hz'] - row['frequency_hz']))
            row['beam_mode'] = nearest['id']
            row['beam_hz'] = nearest['frequency_hz']
            row['difference_pct'] = (nearest['frequency_hz'] - row['frequency_hz']) / row['frequency_hz'] * 100
        notes.append('Each shell mode is paired with the nearest-frequency beam mode of the connected modal output (no shape matching)')
    return {'table': {'kind': 'shell_modes', 'rows': rows, 'mesh': mesh}, 'values': record, 'notes': notes}
