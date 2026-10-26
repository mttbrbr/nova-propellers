"""Geometry identity excludes operating conditions and transport identifiers."""
import copy

from nova.core.data import content_hash

GEOMETRY_FIELDS = ('propeller_type', 'diameter', 'blades', 'airfoil', 'geometry_method',
                   'geometry_parameters', 'airfoil_assignments')


def geometry_definition(inputs):
    return {key: copy.deepcopy(inputs[key]) for key in GEOMETRY_FIELDS}


def geometry_hash(definition):
    scientific = copy.deepcopy(definition)
    for assignment in scientific['airfoil_assignments']:
        assignment.pop('asset_id', None)
    return content_hash(scientific)
