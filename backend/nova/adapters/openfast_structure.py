"""Structural description of a wind turbine for an OpenFAST (ElastoDyn) case.

Four records — hub, nacelle, tower, blade — are validated here, each block reporting exactly which
numbers are missing. Nothing is defaulted that the user has not seen: required values start empty,
and the few assumptions that remain (structural damping, mode-shape basis) are named in the case
manifest. Distributions are tables over the normalised length, as ElastoDyn reads them.
"""
import math

HUB = {'mass_kg': None, 'inertia_kg_m2': None, 'cm_downwind_m': 0.0, 'precone_deg': 0.0}
NACELLE = {'mass_kg': None, 'yaw_inertia_kg_m2': None, 'overhang_m': None, 'shaft_tilt_deg': 0.0, 'tower_top_to_shaft_m': None,
           'cm_downwind_m': 0.0, 'cm_lateral_m': 0.0, 'cm_up_m': 0.0}
TOWER = {'shape': 'tubular', 'height_m': None, 'base_height_m': 0.0, 'base_diameter_m': None, 'top_diameter_m': None,
         'wall_thickness_m': None, 'youngs_modulus_pa': 2.1e11, 'density_kg_m3': 7850.0, 'damping_pct': 1.0, 'stations': []}
BLADE = {'stations': [], 'tip_mass_kg': 0.0, 'flap_damping_pct': 1.0, 'edge_damping_pct': 1.0}
LIMITS = {'mass_kg': (0.0, 1e8), 'inertia_kg_m2': (0.0, 1e12), 'yaw_inertia_kg_m2': (0.0, 1e12), 'cm_downwind_m': (-100.0, 100.0),
          'cm_lateral_m': (-100.0, 100.0), 'cm_up_m': (-100.0, 100.0), 'precone_deg': (-30.0, 30.0), 'overhang_m': (-100.0, 100.0),
          'shaft_tilt_deg': (-30.0, 30.0), 'tower_top_to_shaft_m': (0.0, 100.0), 'height_m': (0.1, 1000.0),
          'base_height_m': (-200.0, 1000.0), 'base_diameter_m': (0.01, 50.0), 'top_diameter_m': (0.01, 50.0),
          'wall_thickness_m': (1e-4, 5.0), 'youngs_modulus_pa': (1e8, 1e12), 'density_kg_m3': (100.0, 2e4),
          'damping_pct': (0.0, 20.0), 'tip_mass_kg': (0.0, 1e6), 'flap_damping_pct': (0.0, 20.0), 'edge_damping_pct': (0.0, 20.0)}
MINIMUM_STATIONS = 2


class StructureError(ValueError):
    pass


def _value(config, key, label, problems, required=True, positive=False):
    value = config.get(key)
    if value is None:
        if required:
            problems.append(f'{key} is required')
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        problems.append(f'{key} must be a finite number')
        return None
    low, high = LIMITS[key]
    if not low <= value <= high or (positive and value <= 0):
        problems.append(f'{key} must be {"above 0 and " if positive else ""}between {low:g} and {high:g}')
        return None
    return float(value)


def _finish(label, problems):
    if problems:
        raise StructureError(f'{label}: ' + '; '.join(problems))


def _unknown(label, config, defaults, problems):
    extra = set(config) - set(defaults) - {'name'}
    if extra:
        problems.append(f'unsupported fields {", ".join(sorted(extra))}')


def hub_record(config):
    problems = []
    _unknown('Hub', config, HUB, problems)
    record = {'kind': 'hub', 'mass_kg': _value(config, 'mass_kg', 'Hub', problems, positive=True),
              'inertia_kg_m2': _value(config, 'inertia_kg_m2', 'Hub', problems, positive=True),
              'cm_downwind_m': _value(config, 'cm_downwind_m', 'Hub', problems, False) or 0.0,
              'precone_deg': _value(config, 'precone_deg', 'Hub', problems, False) or 0.0}
    _finish('Hub', problems)
    return record


def nacelle_record(config):
    problems = []
    _unknown('Nacelle', config, NACELLE, problems)
    record = {'kind': 'nacelle', 'mass_kg': _value(config, 'mass_kg', 'Nacelle', problems, positive=True),
              'yaw_inertia_kg_m2': _value(config, 'yaw_inertia_kg_m2', 'Nacelle', problems, positive=True),
              'overhang_m': _value(config, 'overhang_m', 'Nacelle', problems),
              'shaft_tilt_deg': _value(config, 'shaft_tilt_deg', 'Nacelle', problems, False) or 0.0,
              'tower_top_to_shaft_m': _value(config, 'tower_top_to_shaft_m', 'Nacelle', problems),
              'cm_downwind_m': _value(config, 'cm_downwind_m', 'Nacelle', problems, False) or 0.0,
              'cm_lateral_m': _value(config, 'cm_lateral_m', 'Nacelle', problems, False) or 0.0,
              'cm_up_m': _value(config, 'cm_up_m', 'Nacelle', problems, False) or 0.0}
    _finish('Nacelle', problems)
    return record


def _table(config, key, fields, problems, label):
    rows = config.get(key) or []
    if not isinstance(rows, list) or len(rows) < MINIMUM_STATIONS or len(rows) > 200:
        problems.append(f'{key} needs {MINIMUM_STATIONS}–200 stations')
        return None
    out = []
    for i, row in enumerate(rows):
        values = []
        for field in fields:
            v = row.get(field) if isinstance(row, dict) else None
            if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                problems.append(f'{key}[{i + 1}].{field} must be a finite number')
                return None
            values.append(float(v))
        out.append(values)
    first = fields[0]
    positions = [r[0] for r in out]
    if abs(positions[0]) > 1e-9 or abs(positions[-1] - 1.0) > 1e-9 or any(b <= a for a, b in zip(positions, positions[1:])):
        problems.append(f'{key}: {first} must start at 0, end at 1 and increase strictly')
        return None
    for i, row in enumerate(out):
        if any(v <= 0 for v in row[1:]):
            problems.append(f'{key}[{i + 1}]: mass and stiffness must be positive')
            return None
    return out


def tower_record(config):
    problems = []
    _unknown('Tower', config, TOWER, problems)
    shape = config.get('shape', 'tubular')
    if shape not in ('tubular', 'table'):
        problems.append('shape must be "tubular" or "table"')
    record = {'kind': 'tower', 'shape': shape, 'height_m': _value(config, 'height_m', 'Tower', problems, positive=True),
              'base_height_m': _value(config, 'base_height_m', 'Tower', problems, False) or 0.0,
              'damping_pct': _value(config, 'damping_pct', 'Tower', problems, False)}
    if record['damping_pct'] is None:
        record['damping_pct'] = TOWER['damping_pct']
    if shape == 'tubular':
        base = _value(config, 'base_diameter_m', 'Tower', problems)
        top = _value(config, 'top_diameter_m', 'Tower', problems)
        wall = _value(config, 'wall_thickness_m', 'Tower', problems)
        young = _value(config, 'youngs_modulus_pa', 'Tower', problems, False) or TOWER['youngs_modulus_pa']
        density = _value(config, 'density_kg_m3', 'Tower', problems, False) or TOWER['density_kg_m3']
        if base and top and wall and (2 * wall >= min(base, top)):
            problems.append('wall_thickness_m must be less than half of the smallest diameter')
        _finish('Tower', problems)
        rows = []
        for i in range(11):
            x = i / 10
            d = base + (top - base) * x
            area = math.pi / 4 * (d**2 - (d - 2 * wall) ** 2)
            inertia = math.pi / 64 * (d**4 - (d - 2 * wall) ** 4)
            rows.append([x, density * area, young * inertia, young * inertia])
        record['stations'] = rows
        record['material'] = {'youngs_modulus_pa': young, 'density_kg_m3': density}
    elif shape == 'table':
        rows = _table(config, 'stations', ('height_fraction', 'mass_per_length_kg_m', 'fore_aft_stiffness_nm2', 'side_side_stiffness_nm2'), problems, 'Tower')
        _finish('Tower', problems)
        record['stations'] = rows
    _finish('Tower', problems)
    return record


def blade_record(config):
    problems = []
    _unknown('Blade structure', config, BLADE, problems)
    rows = _table(config, 'stations', ('span_fraction', 'mass_per_length_kg_m', 'flap_stiffness_nm2', 'edge_stiffness_nm2'), problems, 'Blade structure')
    record = {'kind': 'blade', 'stations': rows, 'tip_mass_kg': _value(config, 'tip_mass_kg', 'Blade structure', problems, False) or 0.0}
    for key in ('flap_damping_pct', 'edge_damping_pct'):
        v = _value(config, key, 'Blade structure', problems, False)
        record[key] = BLADE[key] if v is None else v
    _finish('Blade structure', problems)
    return record


def missing(structure):
    names = {'hub': 'Hub', 'nacelle': 'Nacelle', 'tower': 'Tower', 'blade': 'Blade structure'}
    return [label for key, label in names.items() if structure.get(key) is None]
