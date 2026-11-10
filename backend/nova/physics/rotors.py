"""Rotor studies facade: one specification format for every rotor family.

A specification is plain JSON so it can live in projects, workflows and
API requests::

    {"kind": "hawt" | "vawt" | "propeller" | "marine",
     "fluid": {"preset": "air", ...overrides},
     "section": {"name": "NACA 0018"} | {"points": [...], "thickness": 0.12},
     "geometry": {...kind specific...},
     "operating": {"velocity_m_s": 8, "rpm": 120} | {"velocity_m_s": 8, "tip_speed_ratio": 6}
                  | {"rpm": 120, "advance_ratio": 0.7},
     "method": "bemt" | one of vawt.METHODS,
     "corrections": {...},
     "marine": {"shaft_depth_m": 4, "wake_fraction": 0.2, ...}}
"""
import copy
import math

import numpy as np

from .axial import AxialRotor, solve_axial
from .corrections import corrections_from
from .fluids import PRESETS, fluid_from
from .marine import b_series_rotor, hull_interaction, marine_assessment
from .sections import SYNTHETIC_SECTIONS, section_from
from .vawt import METHOD_LABELS, METHODS, VerticalRotor, solve_vertical

KINDS = ('hawt', 'vawt', 'propeller', 'marine')

# Corrections that are physically meaningful for each family. Others stay at
# their neutral value ("none"/off) and are rejected if switched on:
#   HAWT      – no compressibility (tip Mach ≈ 0.2–0.3)
#   propeller – no high-induction branch (propellers never reach windmill-brake
#               induction) and no Snel augmentation (a stall-delay model for
#               turbine roots)
#   marine    – additionally no compressibility (water)
APPLICABLE_CORRECTIONS = {
    'hawt': ('tip_loss', 'hub_loss', 'high_induction', 'rotational_augmentation'),
    'propeller': ('tip_loss', 'hub_loss', 'compressibility'),
    'marine': ('tip_loss', 'hub_loss'),
    'vawt': ('finite_aspect_ratio', 'flow_curvature', 'dynamic_stall', 'high_induction', 'strut_drag', 'shaft_wake'),
}
NEUTRAL = {'tip_loss': 'none', 'hub_loss': 'none', 'high_induction': 'none', 'rotational_augmentation': 'none',
           'compressibility': 'none', 'finite_aspect_ratio': False, 'flow_curvature': False, 'dynamic_stall': 'none',
           'strut_drag': False, 'shaft_wake': False}

DEFAULTS = {
    'hawt': {
        'kind': 'hawt', 'fluid': {'preset': 'air'}, 'section': {'name': 'Wind turbine 21% (synthetic)'},
        'geometry': {'blades': 3, 'radius_m': 5.0, 'hub_radius_m': 0.5, 'design_tsr': 7.0, 'stations': 24, 'pitch_deg': 0.0},
        'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 7.0}, 'method': 'bemt',
        'corrections': {'tip_loss': 'prandtl', 'hub_loss': 'prandtl', 'high_induction': 'buhl',
                        'rotational_augmentation': 'none', 'compressibility': 'none'},
    },
    'vawt': {
        'kind': 'vawt', 'fluid': {'preset': 'air'}, 'section': {'name': 'NACA 0018'},
        'geometry': {'blades': 3, 'radius_m': 1.0, 'height_m': 2.0, 'chord_m': 0.12, 'shape': 'straight',
                     'pitch_axis_fraction': 0.25, 'blade_pitch_deg': 0.0, 'struts_per_blade': 2,
                     'strut_chord_m': 0.05, 'strut_cd': 0.02, 'shaft_diameter_m': 0.08, 'shaft_cd': 1.2},
        'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 4.0}, 'method': 'double_multiple_streamtube',
        'corrections': {'finite_aspect_ratio': True, 'flow_curvature': False, 'dynamic_stall': 'none',
                        'high_induction': 'glauert', 'strut_drag': False, 'shaft_wake': False},
    },
    'propeller': {
        'kind': 'propeller', 'fluid': {'preset': 'air'}, 'section': {'name': 'NACA 4412'},
        'geometry': {'blades': 2, 'diameter_m': 0.254, 'hub_ratio': 0.15, 'pitch_ratio': 0.7, 'stations': 24,
                     'chord_over_R': [0.18, 0.20, 0.17, 0.08], 'pitch_deg': 0.0},
        'operating': {'rpm': 6000.0, 'advance_ratio': 0.4}, 'method': 'bemt',
        'corrections': {'tip_loss': 'prandtl', 'hub_loss': 'prandtl', 'high_induction': 'none',
                        'rotational_augmentation': 'none', 'compressibility': 'prandtl_glauert'},
    },
    'marine': {
        'kind': 'marine', 'fluid': {'preset': 'sea_water'}, 'section': {'name': 'Marine a=0.8 10% (synthetic)'},
        'geometry': {'blades': 4, 'diameter_m': 4.0, 'area_ratio': 0.55, 'pitch_ratio': 1.0, 'hub_ratio': 0.2,
                     'stations': 25, 'pitch_deg': 0.0},
        'operating': {'rpm': 120.0, 'advance_ratio': 0.6}, 'method': 'bemt',
        'corrections': {'tip_loss': 'prandtl', 'hub_loss': 'prandtl', 'high_induction': 'none',
                        'rotational_augmentation': 'none', 'compressibility': 'none'},
        'marine': {'shaft_depth_m': 5.0, 'wake_fraction': 0.2, 'thrust_deduction': 0.15,
                   'relative_rotative_efficiency': 1.0, 'keller_k': 0.2},
    },
}


def checked_corrections(kind, config):
    """Build the correction set for a family, rejecting corrections that do not apply to it."""
    corrections = corrections_from('vertical' if kind == 'vawt' else 'axial', config)
    misplaced = [name for name, value in corrections.to_dict().items()
                 if name not in APPLICABLE_CORRECTIONS[kind] and value != NEUTRAL[name]]
    if misplaced:
        raise ValueError(f'Corrections not applicable to {kind} rotors: {", ".join(misplaced)}')
    return corrections


def catalog():
    return {
        'kinds': list(KINDS), 'defaults': copy.deepcopy(DEFAULTS), 'sections': list(SYNTHETIC_SECTIONS),
        'vawt_methods': [{'id': m, 'label': METHOD_LABELS[m]} for m in METHODS],
        'axial_corrections': {
            'tip_loss': ['none', 'prandtl', 'shen'], 'hub_loss': ['none', 'prandtl'],
            'high_induction': ['none', 'glauert', 'buhl', 'spera'], 'rotational_augmentation': ['none', 'snel'],
            'compressibility': ['none', 'prandtl_glauert']},
        'vertical_corrections': {
            'finite_aspect_ratio': [False, True], 'flow_curvature': [False, True],
            'dynamic_stall': ['none', 'gormont_berg'], 'high_induction': ['none', 'glauert', 'buhl', 'spera'],
            'strut_drag': [False, True], 'shaft_wake': [False, True]},
        'fluids': ['air', 'fresh_water', 'sea_water'],
        'fluid_properties': {name: fluid.to_dict() for name, fluid in PRESETS.items()},
        'corrections_by_kind': {kind: list(names) for kind, names in APPLICABLE_CORRECTIONS.items()},
    }


def merged(spec):
    """Fill a partial specification from the defaults of its kind."""
    kind = (spec or {}).get('kind', 'hawt')
    if kind not in KINDS:
        raise ValueError(f'Rotor kind must be one of {", ".join(KINDS)}')
    result = copy.deepcopy(DEFAULTS[kind])
    for key, value in (spec or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict) and key not in ('section',):
            if key == 'operating':
                result[key] = dict(value)
            else:
                result[key].update(value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _hawt_rotor(geometry, section):
    B, R = int(geometry['blades']), float(geometry['radius_m'])
    Rh = float(geometry.get('hub_radius_m', 0.1 * R))
    if 'r_over_R' in geometry:
        x = np.asarray(geometry['r_over_R'], dtype=float)
        chord = np.asarray(geometry['chord_over_R'], dtype=float) * R
        twist = np.asarray(geometry['twist_deg'], dtype=float)
        return AxialRotor(B, R, Rh, x * R, chord, twist, section, float(geometry.get('pitch_deg', 0)))
    tsr = float(geometry.get('design_tsr', 7.0))
    if not 1 <= tsr <= 15:
        raise ValueError('Design tip-speed ratio must be within 1–15')
    # Optimum rotor with wake rotation (Burton et al.): φ = ⅔ atan(1/λ_r),
    # c = 8πr(1 − cos φ)/(B cl_d), θ = φ − α_d at the best lift-to-drag incidence.
    alpha = np.linspace(0, 14, 141)
    cl, cd = section(alpha, np.full_like(alpha, 3e6 * R / 50))
    best = int(np.argmax(cl / cd))
    alpha_d, cl_d = float(alpha[best]), float(max(cl[best], 0.3))
    x = np.linspace(Rh / R, 1.0, int(geometry.get('stations', 24)))
    r = x * R
    phi = 2 / 3 * np.arctan(1 / (tsr * x))
    chord = np.minimum(8 * math.pi * r * (1 - np.cos(phi)) / (B * cl_d), 0.12 * R)
    twist = np.degrees(phi) - alpha_d
    return AxialRotor(B, R, Rh, r, chord, twist, section, float(geometry.get('pitch_deg', 0)))


def _propeller_rotor(geometry, section):
    if geometry.get('canonical'):
        canonical = geometry['canonical']
        stations = canonical['stations']
        R = canonical['diameter_m'] / 2
        r = np.array([s['radius_m'] for s in stations])
        hub = float(r[0])
        return AxialRotor(int(canonical['blades']), R, hub, r, [s['chord_m'] for s in stations],
                          [s['twist_deg'] for s in stations], section, float(geometry.get('pitch_deg', 0)))
    B, D = int(geometry['blades']), float(geometry['diameter_m'])
    R = D / 2
    hub = float(geometry.get('hub_ratio', 0.15))
    x = np.asarray(geometry['r_over_R'], dtype=float) if 'r_over_R' in geometry else \
        np.linspace(hub, 1.0, int(geometry.get('stations', 24)))
    if 'twist_deg' in geometry and len(geometry['twist_deg']) == len(x):
        twist = np.asarray(geometry['twist_deg'], dtype=float)
    else:
        twist = np.degrees(np.arctan(float(geometry.get('pitch_ratio', 0.7)) / (math.pi * x)))
    control = np.asarray(geometry.get('chord_over_R', [0.18, 0.2, 0.17, 0.08]), dtype=float)
    chord = np.interp(x, np.linspace(hub, 1.0, control.size), control) * R if control.size != x.size else control * R
    return AxialRotor(B, R, hub * R, x * R, chord, twist, section, float(geometry.get('pitch_deg', 0)))


def build(spec):
    spec = merged(spec)
    kind, geometry = spec['kind'], spec['geometry']
    fluid = fluid_from(spec['fluid'])
    if kind == 'vawt':
        known = set(VerticalRotor.__dataclass_fields__) - {'section'}
        unknown = set(geometry) - known
        if unknown:
            raise ValueError(f'Unsupported VAWT geometry fields: {", ".join(sorted(unknown))}')
        aspect = float(geometry.get('height_m', 2)) / float(geometry.get('chord_m', 0.1))
        section = section_from(spec['section'], aspect)
        rotor = VerticalRotor(section=section, **geometry)
    else:
        section = section_from(spec['section'])
        if kind == 'hawt':
            rotor = _hawt_rotor(geometry, section)
        elif kind == 'marine':
            rotor = b_series_rotor(section, diameter_m=float(geometry['diameter_m']), blades=int(geometry['blades']),
                                   area_ratio=float(geometry['area_ratio']), pitch_ratio=float(geometry['pitch_ratio']),
                                   hub_ratio=float(geometry.get('hub_ratio', 0.2)), stations=int(geometry.get('stations', 25)),
                                   pitch_deg=float(geometry.get('pitch_deg', 0)))
        else:
            rotor = _propeller_rotor(geometry, section)
    return spec, rotor, fluid


def _tip_radius(rotor):
    return rotor.radius_m if isinstance(rotor, VerticalRotor) else rotor.tip_radius_m


def resolve_operating(spec, rotor):
    op = dict(spec['operating'])
    R = _tip_radius(rotor)
    V = op.get('velocity_m_s', op.get('wind_speed_m_s'))
    rpm = op.get('rpm')
    if 'tip_speed_ratio' in op and V is not None and rpm is None:
        rpm = float(op['tip_speed_ratio']) * float(V) / R * 60 / (2 * math.pi)
    if 'advance_ratio' in op and rpm is not None and V is None:
        V = float(op['advance_ratio']) * float(rpm) / 60 * 2 * R
    if spec['kind'] == 'marine' and V is None and 'ship_speed_m_s' in op:
        V = float(op['ship_speed_m_s']) * (1 - float(spec['marine'].get('wake_fraction', 0)))
    if V is None or rpm is None:
        raise ValueError('Operating point needs velocity and rpm (or a tip-speed/advance ratio that fixes one)')
    return float(V), float(rpm)


def analyze(spec):
    spec, rotor, fluid = build(spec)
    V, rpm = resolve_operating(spec, rotor)
    kind = spec['kind']
    corrections = checked_corrections(kind, spec.get('corrections'))
    if kind == 'vawt':
        result = solve_vertical(rotor, method=spec.get('method', 'double_multiple_streamtube'), wind_speed_m_s=V,
                                rpm=rpm, fluid=fluid, corrections=corrections,
                                azimuth_tubes=int(spec.get('azimuth_tubes', 36)))
        result['blade'] = {'radius_m': rotor.radius_m, 'height_m': rotor.height_m, 'chord_m': rotor.chord_m,
                           'blades': rotor.blades}
    else:
        if kind != 'hawt' and spec.get('method', 'bemt') != 'bemt':
            raise ValueError('Axial rotors use the BEMT method')
        mode = 'turbine' if kind == 'hawt' else 'propeller'
        result = solve_axial(rotor, mode=mode, velocity_m_s=V, rpm=rpm, fluid=fluid, corrections=corrections)
        result['method'], result['method_label'] = 'bemt', 'Blade-element momentum (1-D residual)'
        result['blade'] = {'r_over_R': (rotor.radius_m / rotor.tip_radius_m).tolist(), 'chord_m': rotor.chord_m.tolist(),
                           'twist_deg': rotor.twist_deg.tolist(), 'blades': rotor.blades,
                           'tip_radius_m': rotor.tip_radius_m, 'hub_radius_m': rotor.hub_radius_m}
        if kind == 'marine':
            m = spec.get('marine', {})
            hull = hull_interaction(V / max(1 - float(m.get('wake_fraction', 0)), 1e-9), float(m.get('wake_fraction', 0)),
                                    float(m.get('thrust_deduction', 0)), float(m.get('relative_rotative_efficiency', 1)))
            marine, warnings = marine_assessment(result, rotor, fluid, shaft_depth_m=float(m.get('shaft_depth_m', 5)),
                                                 area_ratio=float(spec['geometry']['area_ratio']),
                                                 pitch_ratio=float(spec['geometry']['pitch_ratio']), hull=hull,
                                                 keller_k=float(m.get('keller_k', 0.2)))
            result['marine'] = marine
            result['warnings'] += warnings
    result['kind'] = kind
    result['fluid'] = fluid.to_dict()
    result['corrections'] = corrections.to_dict()
    result['section'] = {'name': rotor.section.name, 'synthetic': rotor.section.synthetic,
                         'thickness': rotor.section.thickness}
    return result


def scalar_outputs(result):
    """Flatten a rotor result into named scalars for constraints and tables."""
    values = {}
    for group in ('performance', 'coefficients', 'operating', 'geometry'):
        for key, value in (result.get(group) or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value is not None and math.isfinite(value):
                values[key] = float(value)
    for key, value in (result.get('marine') or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            values[key] = float(value)
    if 'solidity' in result and isinstance(result['solidity'], float):
        values['solidity'] = result['solidity']
    stations = result.get('stations') or []
    if stations:
        values['max_section_mach'] = max(s['mach'] for s in stations)
        values['max_alpha_deg'] = max(s['alpha_deg'] for s in stations)
    azimuth = result.get('azimuth') or []
    if azimuth:
        torques = [p['blade_torque_nm'] for p in azimuth]
        values['max_alpha_deg'] = max(abs(p['alpha_deg']) for p in azimuth)
        mean = sum(torques) / len(torques)
        values['torque_ripple'] = (max(torques) - min(torques)) / abs(mean) if abs(mean) > 1e-12 else float('inf')
    return values


def performance_curve(spec, *, variable=None, values=None, points=None):
    """Cp–λ (turbines) or K_T/K_Q/η–J (propellers) at fixed velocity/rotational speed."""
    spec = merged(spec)
    kind = spec['kind']
    variable = variable or ('tip_speed_ratio' if kind in ('hawt', 'vawt') else 'advance_ratio')
    if variable not in ('tip_speed_ratio', 'advance_ratio'):
        raise ValueError('Curve variable must be tip_speed_ratio or advance_ratio')
    if values is None:
        lo, hi = {'hawt': (1.0, 13.0), 'vawt': (1.0, 7.0), 'propeller': (0.05, 0.9), 'marine': (0.1, 1.1)}[kind]
        if variable == 'tip_speed_ratio' and kind in ('propeller', 'marine'):
            lo, hi = 3.0, 20.0
        values = np.linspace(lo, hi, int(points or 25)).tolist()
    if not 2 <= len(values) <= 200:
        raise ValueError('A performance curve needs 2–200 points')
    _, rotor, _ = build(spec)
    base_V, base_rpm = resolve_operating(spec, rotor)
    R = _tip_radius(rotor)
    rows = []
    for value in values:
        point = copy.deepcopy(spec)
        if variable == 'tip_speed_ratio':
            point['operating'] = {'velocity_m_s': base_V, 'tip_speed_ratio': float(value)}
        else:
            point['operating'] = {'rpm': base_rpm, 'advance_ratio': float(value)}
        try:
            result = analyze(point)
        except ValueError as exc:
            rows.append({variable: float(value), 'state': 'failed', 'error': str(exc)})
            continue
        row = {variable: float(value), 'state': 'succeeded', 'converged': result['converged'], **scalar_outputs(result)}
        row['tip_speed_ratio'] = result['operating']['omega_rad_s'] * R / result['operating'].get('velocity_m_s', result['operating'].get('wind_speed_m_s', 1)) \
            if result['operating'].get('velocity_m_s', result['operating'].get('wind_speed_m_s')) else None
        rows.append(row)
    good = [r for r in rows if r['state'] == 'succeeded']
    optimum = None
    if good:
        key = 'CP' if kind in ('hawt', 'vawt') else ('open_water_efficiency' if kind == 'marine' else 'efficiency')
        candidates = [r for r in good if r.get(key) is not None]
        if candidates:
            best = max(candidates, key=lambda r: r[key])
            optimum = {'quantity': key, 'value': best[key], variable: best[variable]}
    return {'kind': kind, 'variable': variable, 'rows': rows, 'optimum': optimum,
            'betz_limit': 16 / 27 if kind in ('hawt', 'vawt') else None}
