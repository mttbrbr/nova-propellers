"""Rotor-family simulations (HAWT, VAWT, marine and air propellers on the rotor engine).

A rotor simulation stores one specification (see ``nova.physics.rotors``) in
the project; running it evaluates the operating point and the performance
curve (Cp–λ for turbines, K_T/K_Q/η–J for propellers) in one immutable run.
"""
import copy

from nova.core.data import content_hash
from nova.physics import rotors

SPEC_KEYS = {'kind', 'fluid', 'section', 'geometry', 'operating', 'method', 'corrections', 'marine', 'azimuth_tubes', 'curve', 'requirements'}


def validate_configuration(configuration):
    if not isinstance(configuration, dict) or set(configuration) != {'spec'}:
        raise ValueError('A rotor simulation configuration holds exactly one specification')
    spec = configuration['spec']
    if not isinstance(spec, dict) or spec.get('kind') not in rotors.KINDS:
        raise ValueError(f'Rotor family must be one of {", ".join(rotors.KINDS)}')
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise ValueError(f'Unsupported rotor specification fields: {", ".join(sorted(unknown))}')
    merged = rotors.merged(spec)
    built, rotor, _ = rotors.build(merged)
    rotors.resolve_operating(built, rotor)
    rotors.checked_corrections(merged['kind'], merged.get('corrections'))
    requirements = merged.get('requirements') or {}
    if not isinstance(requirements, dict) or len(requirements) > 32 or any(
            not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, (int, float)) for k, v in requirements.items()):
        raise ValueError('Sizing requirements must be named numbers')
    curve = merged.get('curve') or {}
    if set(curve) - {'start', 'stop', 'points'}:
        raise ValueError('Curve range accepts start, stop and points')
    if curve:
        start, stop, points = curve.get('start'), curve.get('stop'), curve.get('points', 25)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (start, stop, points)) or stop <= start \
                or type(points) is not int or not 3 <= points <= 81:
            raise ValueError('Curve range needs start < stop and 3–81 points')
    return {'spec': merged}


def execute(configuration):
    spec = validate_configuration(configuration)['spec']
    analysis_spec = {k: v for k, v in spec.items() if k not in ('curve', 'requirements')}
    analysis = rotors.analyze(copy.deepcopy(analysis_spec))
    curve = spec.get('curve') or {}
    values = None
    if curve:
        step = (curve['stop'] - curve['start']) / (curve['points'] - 1)
        values = [curve['start'] + step * i for i in range(curve['points'])]
    performance = rotors.performance_curve(copy.deepcopy(analysis_spec), values=values)
    return {'kind': 'rotor', 'rotor_kind': spec['kind'], 'analysis': analysis, 'curve': performance,
            'specification_hash': content_hash(spec), 'warnings': analysis['warnings']}
