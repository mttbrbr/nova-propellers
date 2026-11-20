"""Structure workspace: structural data of a project version and the structural run.

The structure is kept apart from the aerodynamic specification: it reads the version's rotor geometry
(chord, twist, sections) and one aerodynamic run chosen by the user (its operating point and its load
distribution), never changes them, and stores its own data and results:

* ``structure`` record (one per simulation/version): blade (layup or station table), and for wind turbines
  hub, nacelle and tower; analysis settings;
* ``structure_run`` record (immutable): sections, blade modes, Campbell diagram (rotor–tower coupled when
  the tower and nacelle are given), tower modes, deflection under the aerodynamic run's loads and, for wind
  turbines, the steady aeroelastic operating point and Cp–λ curve.
"""
import copy
import math

import numpy as np

from nova.adapters import openfast_structure as st
from nova.blocks import fem, performance, structural
from nova.blocks.catalog import BLOCKS
from nova.physics import aeroelastic, flexible, modal, rotors

FAMILIES = ('hawt', 'propeller', 'marine')
WIND = ('hawt',)
SOLID_MATERIALS = {'nylon_gf30': {'label': 'Nylon PA6 30 % glass', 'E_pa': 8.0e9, 'G_pa': 3.0e9, 'density_kg_m3': 1360.0},
                   'aluminium_7075': {'label': 'Aluminium 7075-T6', 'E_pa': 71.7e9, 'G_pa': 26.9e9, 'density_kg_m3': 2810.0},
                   'nickel_aluminium_bronze': {'label': 'Nickel-aluminium bronze', 'E_pa': 120e9, 'G_pa': 45e9, 'density_kg_m3': 7600.0},
                   'birch_plywood': {'label': 'Birch (along grain)', 'E_pa': 12e9, 'G_pa': 0.8e9, 'density_kg_m3': 680.0}}


class StructureError(ValueError):
    pass


def family(spec):
    kind = rotors.merged(spec)['kind']
    if kind not in FAMILIES:
        raise StructureError('The Structure workspace covers axial rotors: HAWT, air and marine propellers')
    return kind


def default(spec):
    """Starting structure for a family: a layup (or a solid section for propellers); masses and tower start empty."""
    kind = family(spec)
    layup = copy.deepcopy(BLOCKS['blade_layup']['defaults'])
    if kind != 'hawt':
        layup['construction'] = 'solid'
        layup['solid'] = {k: v for k, v in SOLID_MATERIALS['nickel_aluminium_bronze' if kind == 'marine' else 'nylon_gf30'].items()
                          if k != 'label'}
    config = {'family': kind, 'blade': {'mode': 'layup', 'layup': layup, 'stations': []},
              'analysis': {'rpm_max': None, 'points': 15, 'curve_points': 11}}
    if kind in WIND:
        config['hub'] = {'mass_kg': None, 'inertia_kg_m2': None}
        config['nacelle'] = {'mass_kg': None, 'yaw_inertia_kg_m2': None, 'overhang_m': None, 'tower_top_to_shaft_m': None}
        config['tower'] = {'shape': 'tubular', 'height_m': None, 'base_diameter_m': None, 'top_diameter_m': None,
                           'wall_thickness_m': None, 'youngs_modulus_pa': 2.1e11, 'density_kg_m3': 7850.0, 'damping_pct': 1.0}
    return config


def _filled(record):
    return isinstance(record, dict) and all(v is not None for k, v in record.items() if k not in ('stations',))


def _records(config, spec):
    """Blade, hub, nacelle and tower records from the configuration (incomplete wind-turbine parts are left out)."""
    kind = family(spec)
    blade_config = config.get('blade') or {}
    notes = []
    if blade_config.get('mode', 'layup') == 'layup':
        out = fem.blade_layup({'config': blade_config.get('layup') or {}}, {'spec': spec})
        blade, sections, notes = out['blade'], out['table']['rows'], out['notes']
    else:
        try:
            blade = st.blade_record({'stations': blade_config.get('stations') or [], 'tip_mass_kg': blade_config.get('tip_mass_kg', 0.0)})
        except st.StructureError as exc:
            raise StructureError(str(exc)) from exc
        sections = []
    parts = {'blade': blade}
    if kind in WIND:
        for name, build in (('hub', st.hub_record), ('nacelle', st.nacelle_record), ('tower', st.tower_record)):
            item = config.get(name)
            if _filled(item):
                try:
                    parts[name] = build({**item, **({'stations': []} if name == 'tower' and item.get('shape') == 'tubular' else {})})
                except st.StructureError as exc:
                    raise StructureError(str(exc)) from exc
            elif item and any(v is not None for k, v in item.items() if k not in ('youngs_modulus_pa', 'density_kg_m3', 'damping_pct', 'shape')):
                notes.append(f'{name.capitalize()} incomplete: left out until every value is given')
    return parts, sections, notes


def _loads(aero_run, rotor):
    """Distributed loads per blade (N/m out of plane and in plane) at the stations of an aerodynamic run."""
    analysis = (aero_run.get('result') or {}).get('analysis') or {}
    stations = analysis.get('stations') or []
    if not stations:
        raise StructureError('The selected aerodynamic run has no spanwise loads')
    r = np.array([s['radius_m'] for s in stations])
    B = int(rotor.blades)
    thrust = np.array([s['d_thrust_n_m'] for s in stations]) / B
    torque = np.array([s['d_torque_nm_m'] for s in stations]) / B
    return r, thrust, torque / np.maximum(r, 1e-9), analysis


def run(spec, config, aero_run):
    """Every structural result for a version and one of its aerodynamic runs."""
    kind = family(spec)
    spec = rotors.merged(copy.deepcopy(spec))
    operating = (aero_run.get('inputs') or {}).get('spec', {}).get('operating')
    if operating:
        spec['operating'] = copy.deepcopy(operating)
    parts, sections, notes = _records(config, spec)
    blade = parts['blade']
    rotor_info = structural._rotor(spec)
    rpm = rotor_info['rpm']
    analysis_config = config.get('analysis') or {}
    results = {'family': kind, 'sections': sections, 'notes': list(notes)}
    clamped = structural.blade_modes({'config': {'flap_modes': 3, 'edge_modes': 2, 'torsion_modes': 1}}, {'blade': blade, 'spec': spec})
    rotating = structural.blade_modes({'config': {'flap_modes': 3, 'edge_modes': 2, 'torsion_modes': 1}}, {'blade': blade, 'spec': spec},
                                      rotating=True)
    results['blade_modes'] = clamped['modal']
    results['rotating_modes'] = rotating['modal']
    coupled = kind in WIND and all(k in parts for k in ('tower', 'nacelle'))
    rpm_max = analysis_config.get('rpm_max') or 1.25 * rpm
    campbell_config = {'rpm_max': float(rpm_max), 'points': int(analysis_config.get('points', 15)), 'flap_modes': 2, 'edge_modes': 1,
                       'tower_modes': 2, 'coupling': 'mbc' if coupled and rotor_info['blades'] >= 3 else 'none'}
    campbell_args = {'blade': blade, 'spec': spec, **{k: parts[k] for k in ('tower', 'nacelle', 'hub') if k in parts}}
    campbell = structural.campbell({'config': campbell_config}, campbell_args)
    results['campbell'] = campbell['modal']
    results['notes'] += campbell['notes'][1:]
    metrics = {'blade_mass_kg': clamped['values']['blade_mass_kg'], 'rpm': rpm,
               'first_flap_hz': rotating['values'].get('blade_flap1_hz'), 'first_edge_hz': rotating['values'].get('blade_edge1_hz'),
               'min_margin_pct': campbell['values'].get('min_excitation_margin_pct')}
    if 'tower' in parts:
        tower = structural.tower_modes({'config': {'modes': 2}}, {'tower': parts['tower'], 'spec': spec,
                                                                  **{k: parts[k] for k in ('nacelle', 'hub') if k in parts},
                                                                  **({'blade': blade} if 'nacelle' in parts else {})})
        results['tower_modes'] = tower['modal']
        metrics['first_tower_hz'] = min(m['frequency_hz'] for m in tower['modal']['modes']) if tower['modal']['modes'] else None
    # deflection under the selected aerodynamic run's loads (one way)
    _, rotor, _ = rotors.build(spec)
    r, out_of_plane, in_plane, analysis = _loads(aero_run, rotor)
    length = rotor_info['tip'] - rotor_info['hub']
    beam = modal.blade_beam(blade, length, rotor_info['twist'])
    positions = (r - rotor_info['hub']) / length
    x, w, v = flexible.deflection(beam, omega=rpm * math.pi / 30, hub_radius=rotor_info['hub'], positions=positions,
                                  loads_out=out_of_plane, loads_in=in_plane)
    results['deflection'] = {'x': x.tolist(), 'flap_m': w.tolist(), 'edge_m': v.tolist(), 'length_m': length,
                             'source': analysis.get('method_label') or 'aerodynamic run'}
    metrics['tip_deflection_m'] = float(w[-1])
    metrics['tip_edge_m'] = float(v[-1])
    if kind in WIND:
        steady = aeroelastic.solve(spec, blade, twist=rotor_info['twist'])
        results['aeroelastic'] = {k: v for k, v in steady.items() if k != 'stations'} | {'stations': steady['stations']}
        metrics['cp_loss_pct'] = (steady['CP_rigid'] - steady['CP']) / steady['CP_rigid'] * 100
        metrics['tip_twist_deg'] = steady['tip_twist_deg']
        velocity = steady['velocity_m_s']
        tsr = rpm * math.pi / 30 * rotor_info['tip'] / velocity
        count = int(analysis_config.get('curve_points', 11))
        curve = performance.cp_flexible({'config': {'start': max(1.0, 0.4 * tsr), 'stop': 1.6 * tsr, 'points': count, 'model': 'aeroelastic'}},
                                        {'spec': spec, 'blade': blade})
        results['curve'] = curve['table']
        metrics['cp_max'] = curve['values']['CP_max']
    else:
        results['notes'].append('Propellers: blade only (no hub, nacelle or tower); deflection under the aerodynamic run’s thrust and '
                                'torque, one way (the aerodynamics are not recomputed on the deflected blade)')
    results['layout'] = results['campbell'].get('layout')
    results['metrics'] = {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in metrics.items()}
    return results
