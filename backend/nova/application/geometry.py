"""Canonical geometry and loft service shared by HTTP and workflows."""
import numpy as np

from airfoil_management import AirfoilLoft
from database import get_airfoil
from geometry_engine import PropellerSpec, build_canonical_geometry


def create_propeller_geometry(inputs):
    if inputs.get('propeller_type', 'traditional') != 'traditional':
        raise ValueError('Only traditional propeller geometry is available')
    spec = PropellerSpec(thrust_target=inputs['thrust_target'], rpm=inputs['rpm'],
                        diameter=inputs['diameter'], blades=inputs['blades'], airfoil=inputs['airfoil'])
    geometry = build_canonical_geometry(spec, inputs['geometry_method'], inputs['geometry_parameters'])
    assignments = inputs.get('airfoil_assignments', [])
    if assignments:
        positions = sorted(float(a['radial_fraction']) for a in assignments)
        if len(positions) < 2 or len(set(positions)) != len(positions) or positions[0] != 0 or positions[-1] != 1:
            raise ValueError('Unique airfoil assignments must cover span fractions 0 to 1')
        profiles = {}
        for item in assignments:
            coords = item.get('coordinates') or get_airfoil(item['airfoil']).get('coordinates')
            if not coords:
                raise ValueError('Airfoil assignment has no coordinates')
            profiles[item['radial_fraction']] = np.asarray(coords)
        loft = AirfoilLoft(profiles)
        for station in geometry['stations']:
            station['airfoil_coordinates'] = np.round(loft.section(station['r_over_R'], 'linear'), 8).tolist()
        geometry['airfoil_loft'] = assignments
    return geometry
