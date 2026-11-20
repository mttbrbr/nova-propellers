"""Steady aeroelastic rotor: limits, torsion sign and comparison with OpenFAST (AeroDyn + ElastoDyn)."""
import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from nova.adapters import openfast_structure as st
from nova.adapters.openfast import read_openfast_output
from nova.adapters.openfast_case import write_case
from nova.blocks import engine, fem
from nova.blocks.templates import TEMPLATES
from nova.physics import aeroelastic, rotors

OPENFAST = Path(os.environ.get('NOVA_OPENFAST', Path.home() / '.local/share/nova-external/openfast/5.0.0/bin/openfast'))


def _layup_blade(scale=1.0, offset=None):
    spec = rotors.merged({'kind': 'hawt'})
    blade = copy.deepcopy(fem.blade_layup({'config': engine.BLOCKS['blade_layup']['defaults']}, {'spec': spec})['blade'])
    blade['stations'] = [(x, m, f * scale, e * scale) for x, m, f, e in blade['stations']]
    blade['extended']['torsional_stiffness_nm2'] = [g * scale for g in blade['extended']['torsional_stiffness_nm2']]
    if offset is not None:
        blade['extended']['elastic_axis_offset_m'] = [offset] * len(blade['stations'])
    return spec, blade


class Limits(unittest.TestCase):
    def test_stiff_blade_is_rigid(self):
        spec, blade = _layup_blade(scale=1e4)
        out = aeroelastic.solve(spec, blade)
        self.assertAlmostEqual(out['CP'], out['CP_rigid'], delta=2e-5)
        self.assertAlmostEqual(out['CT'], out['CT_rigid'], delta=2e-5)
        self.assertTrue(out['converged'])

    def test_elastic_axis_behind_quarter_chord_twists_nose_up(self):
        """Lift ahead of the elastic axis twists the blade nose-up: incidence and thrust rise."""
        spec, aft = _layup_blade(scale=0.1, offset=0.08)
        _, centred = _layup_blade(scale=0.1, offset=0.0)
        twisted, flat = aeroelastic.solve(spec, aft), aeroelastic.solve(spec, centred)
        self.assertGreater(twisted['tip_twist_deg'], 0.05)
        self.assertAlmostEqual(flat['tip_twist_deg'], 0.0, places=9)
        self.assertGreater(twisted['CT'], flat['CT'])

    def test_flexibility_reduces_power_near_optimum(self):
        spec, blade = _layup_blade(scale=0.1, offset=0.0)
        out = aeroelastic.solve(spec, blade)
        self.assertLess(out['CP'], out['CP_rigid'])
        self.assertGreater(out['tip_flap_m'], 0.01)


@unittest.skipUnless(OPENFAST.exists(), 'OpenFAST executable not installed')
class AgainstOpenFAST(unittest.TestCase):
    """AOC 15/50 example rotor, bending stiffness divided by 10, tower locked, prescribed speed, steady wind."""

    def test_flexible_cp_and_tip_deflection(self):
        nodes = {n['id']: n for n in TEMPLATES['structural_campbell']['nodes']}
        spec = engine._operating(nodes['operating'], {'spec': engine._rotor(nodes['rotor'], {})['spec']})['spec']
        structure = {'hub': st.hub_record(nodes['hub']['config']), 'nacelle': st.nacelle_record(nodes['nacelle']['config']),
                     'tower': st.tower_record(nodes['tower']['config']), 'blade': st.blade_record(nodes['blade']['config'])}
        structure['hub']['precone_deg'] = 0.0
        structure['blade']['stations'] = [(x, m, f * 0.1, e * 0.1) for x, m, f, e in structure['blade']['stations']]
        V = rotors.resolve_operating(*rotors.build(rotors.merged(spec))[:2])[0]
        spec['operating'] = {'velocity_m_s': V, 'tip_speed_ratio': 5.0}
        nova = aeroelastic.solve(spec, structure['blade'])
        results = {}
        with tempfile.TemporaryDirectory() as tmp:
            for name, parts in (('rigid', None), ('flex', structure)):
                case = Path(tmp) / name
                info = write_case(spec, case, {'duration_s': 20.0, 'dt_s': 0.005, 'tower_fa_dof': False, 'tower_ss_dof': False}, parts)
                subprocess.run([str(OPENFAST), info['input_file']], cwd=case, check=True, capture_output=True, timeout=900)
                data = read_openfast_output(case / info['output_file'])
                names = [c['name'] for c in data['channels']]
                keep = np.asarray(data['time_s']) >= 12.0
                values = np.asarray(data['values'])[keep]
                results[name] = {k: float(values[:, names.index(k)].mean()) for k in ('RtAeroCp', 'TipDxb1') if k in names}
        of_delta = results['flex']['RtAeroCp'] / results['rigid']['RtAeroCp'] - 1
        nova_delta = nova['CP'] / nova['CP_rigid'] - 1
        self.assertLess(of_delta, 0)
        self.assertLess(nova_delta, 0)
        self.assertAlmostEqual(nova_delta, of_delta, delta=0.004)
        self.assertAlmostEqual(nova['tip_flap_m'], results['flex']['TipDxb1'], delta=0.15 * results['flex']['TipDxb1'])


if __name__ == '__main__':
    unittest.main()
