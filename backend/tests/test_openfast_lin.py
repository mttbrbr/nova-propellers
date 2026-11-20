"""OpenFAST linearisation: .lin parsing, multi-blade coordinates and comparison with Nova's coupled model."""
import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from nova.adapters import openfast_lin
from nova.adapters import openfast_structure as st
from nova.adapters.openfast_case import write_case
from nova.blocks import engine
from nova.blocks.templates import TEMPLATES
from nova.physics import coupled, modal
from tests.test_coupled import _example, _nacelle_body

OPENFAST = Path(os.environ.get('NOVA_OPENFAST', Path.home() / '.local/share/nova-external/openfast/5.0.0/bin/openfast'))
TOWER = {'fa': 'tower fore-aft', 'ss': 'tower side-to-side'}
BLADE = {'flap': 'flapwise', 'edge': 'edgewise'}
ORDINALS = ('1st', '2nd', '3rd')


def _lin_text(A, descriptions, rotating, time_s, omega, azimuth):
    n = len(descriptions)
    lines = ['Linearized model: synthetic', '', 'Simulation information:', f'   Simulation time:  {time_s:.4f} s',
             f'   Rotor Speed:  {omega:.10f} rad/s', f'   Azimuth:  {azimuth:.10f} rad', '', 'Order of continuous states:',
             '   Row/Column Operating Point Rotating Frame? Derivative Order Description', '   ---------- ---']
    for i, (d, r) in enumerate(zip(descriptions, rotating)):
        lines.append(f'   {i + 1}   0.0   {"T" if r else "F"}   2   {d}')
    lines += ['', 'Linearized state matrices:', '', f'A: {n} x {n}']
    lines += [' '.join(f'{v:.16e}' for v in row) for row in A]
    return '\n'.join(lines) + '\n'


class SyntheticLinearisation(unittest.TestCase):
    """.lin files written from Nova's periodic coupled system must give back Nova's own MBC modes."""

    def test_round_trip(self):
        blade, tower, hub, nacelle, spec = _example()
        from nova.blocks import structural
        rotor = structural._rotor(spec)
        blade_beam = modal.blade_beam(blade, rotor['tip'] - rotor['hub'], rotor['twist'])
        tower_model = coupled.Tower(modal.tower_beam(tower, _nacelle_body(nacelle)), {'fa': 1, 'ss': 1}, 0.01)
        omega = 60 * np.pi / 30
        blade_model = coupled.Blade(blade_beam, omega, rotor['hub'], {'flap': 1, 'edge': 1}, {'flap': 0.02, 'edge': 0.02})
        system = coupled.System(tower_model, blade_model, 3, omega, (nacelle['tower_top_to_shaft_m'], 0.0, nacelle['overhang_m']))
        names = [f'ED 1st {TOWER[f]} bending mode DOF, m' for f in tower_model.families]
        rotating = [False] * len(names)
        counts = {}
        families = []
        for f in blade_model.families:
            counts[f] = counts.get(f, 0) + 1
            families.append(f'{ORDINALS[counts[f] - 1]} {BLADE[f]} bending-mode DOF')
        for b in range(3):
            for f in families:
                names.append(f'ED {f} of blade {b + 1} (internal DOF index = DOF_B(1,1)), m')
                rotating.append(True)
        # state order in .lin files: fixed-frame first, then each blade-mode group with its three blades
        n = system.n
        order = list(range(system.nt)) + [system.nt + b * system.nb + k for k in range(system.nb) for b in range(3)]
        descriptions = [names[i] for i in order] + [f'ED First time derivative of {names[i][3:]}' for i in order]
        flags = [rotating[i] for i in order] * 2
        files = []
        for k, psi in enumerate(np.linspace(0, 2 * np.pi, 24, endpoint=False)):
            M, D, K = system.matrices(psi)
            inv = np.linalg.inv(M)
            A = np.block([[np.zeros((n, n)), np.eye(n)], [-inv @ K, -inv @ D]])
            P = np.eye(n)[order]
            A = np.kron(np.eye(2), P) @ A @ np.kron(np.eye(2), P).T
            files.append(openfast_lin.parse(_lin_text(A, descriptions, flags, k * 0.1, omega, psi)))
        theirs = sorted(m['frequency_hz'] for m in openfast_lin.modes(files, 3))
        ours = sorted(m['frequency_hz'] for m in coupled.modes(system))
        np.testing.assert_allclose(theirs, ours, rtol=1e-3)


class LinearisationCase(unittest.TestCase):
    def _case(self, directory):
        nodes = {n['id']: n for n in TEMPLATES['structural_campbell']['nodes']}
        spec = engine._operating(nodes['operating'], {'spec': engine._rotor(nodes['rotor'], {})['spec']})['spec']
        structure = {'hub': st.hub_record(nodes['hub']['config']), 'nacelle': st.nacelle_record(nodes['nacelle']['config']),
                     'tower': st.tower_record(nodes['tower']['config']), 'blade': st.blade_record(nodes['blade']['config'])}
        return write_case(spec, directory, {}, structure)

    def test_prepare_edits_switches(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = self._case(Path(tmp) / 'case')
            rpm, times = openfast_lin.prepare(Path(tmp) / 'case', info['input_file'], azimuths=8, settle_s=2.0)
            text = (Path(tmp) / 'case' / info['input_file']).read_text()
            self.assertEqual(rpm, 60.0)
            self.assertEqual(len(times), 8)
            self.assertAlmostEqual(times[1] - times[0], 1.0 / 8)
            for key, value in (('Linearize', 'True'), ('CompAero', '0'), ('Gravity', '0'), ('NLinTimes', '8')):
                self.assertEqual(openfast_lin._get(text, key), value)

    def test_rigid_case_is_rejected(self):
        nodes = {n['id']: n for n in TEMPLATES['structural_campbell']['nodes']}
        spec = engine._operating(nodes['operating'], {'spec': engine._rotor(nodes['rotor'], {})['spec']})['spec']
        with tempfile.TemporaryDirectory() as tmp:
            info = write_case(spec, Path(tmp) / 'case', {}, None)
            with self.assertRaises(openfast_lin.LinearizationError):
                openfast_lin.prepare(Path(tmp) / 'case', info['input_file'])

    @unittest.skipUnless(OPENFAST.exists(), 'OpenFAST executable not installed')
    def test_real_openfast_against_nova(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / 'case'
            info = self._case(case)
            rpm, times = openfast_lin.prepare(case, info['input_file'], azimuths=12, settle_s=1.0)
            subprocess.run([str(OPENFAST), info['input_file']], cwd=case, check=True, capture_output=True, timeout=600)
            found = openfast_lin.modes(openfast_lin.read_directory(case, 3), 3)
            shutil.rmtree(case)
        template = copy.deepcopy(TEMPLATES["structural_campbell"])
        workflow = {'schema_version': 2, 'kind': 'blocks', 'name': 'x', 'nodes': template['nodes'], 'edges': template['edges']}
        for node in workflow['nodes']:
            if node['id'] == 'campbell':
                node['config'] = {**node['config'], 'coupling': 'mbc', 'points': 3, 'rpm_min': 50.0, 'rpm_max': 70.0, 'tower_modes': 2}
        modal_out = engine.execute(workflow)['blocks']['campbell']['outputs']['modal']
        result = engine.linearization_outputs(found, rpm, times, 12, 1.0, modal_out)
        pairs = {p['nova_mode']: p for p in result['table']['comparison']}
        for mode in ('tower_fa1', 'tower_ss1', 'blade_flap_backward1', 'blade_flap_collective1', 'blade_flap_forward1'):
            self.assertLess(abs(pairs[mode]['difference_pct']), 4.0, mode)


if __name__ == '__main__':
    unittest.main()
