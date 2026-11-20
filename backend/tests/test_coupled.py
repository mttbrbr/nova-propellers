"""Rotor–tower coupled modes in multi-blade coordinates."""
import copy
import unittest

import numpy as np

from nova.adapters import openfast_structure as st
from nova.blocks import engine, structural
from nova.blocks.templates import TEMPLATES
from nova.physics import coupled, modal


def _example():
    nodes = {n['id']: n for n in TEMPLATES['structural_campbell']['nodes']}
    blade = st.blade_record(nodes['blade']['config'])
    tower = st.tower_record(nodes['tower']['config'])
    hub = st.hub_record(nodes['hub']['config'])
    nacelle = st.nacelle_record(nodes['nacelle']['config'])
    spec = engine._operating(nodes['operating'], {'spec': engine._rotor(nodes['rotor'], {})['spec']})['spec']
    return blade, tower, hub, nacelle, spec


def _nacelle_body(nacelle):
    return [(nacelle['mass_kg'], (nacelle['cm_up_m'], nacelle['cm_lateral_m'], nacelle['cm_downwind_m']),
             np.diag([nacelle['yaw_inertia_kg_m2'], 0.0, 0.0]))]


class CoupledLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blade, cls.tower, cls.hub, cls.nacelle, cls.spec = _example()
        cls.rotor = structural._rotor(cls.spec)
        cls.length = cls.rotor['tip'] - cls.rotor['hub']
        cls.blade_beam = modal.blade_beam(cls.blade, cls.length, cls.rotor['twist'])

    def _campbell(self, tower, rpm, blade_beam=None):
        tower_beam = modal.tower_beam(tower, _nacelle_body(self.nacelle))
        curves, _ = coupled.campbell(blade_beam or self.blade_beam, tower_beam, blades=3, hub_radius=self.rotor['hub'],
                                     hub_offset=(self.nacelle['tower_top_to_shaft_m'], 0.0, self.nacelle['overhang_m']), rpm=rpm,
                                     blade_counts={'flap': 1, 'edge': 1}, tower_counts={'fa': 1, 'ss': 1}, blade_damping={},
                                     tower_damping=0.0, hub=self.hub)
        return {c['id']: c for c in curves}

    def test_rigid_tower_gives_isolated_rotor_whirl(self):
        """With a rigid tower the collective mode is the rotating blade mode and the cyclic modes are f ∓ Ω (flap)."""
        stiff = copy.deepcopy(self.tower)
        stiff['stations'] = [(x, m, fa * 1e5, ss * 1e5) for x, m, fa, ss in self.tower['stations']]
        rpm = 64.0
        curves = self._campbell(stiff, [20.0, rpm])
        rotating = modal.pick(modal.solve(self.blade_beam, omega=rpm * np.pi / 30, hub_radius=self.rotor['hub']), {'flap': 1, 'edge': 1})
        f_flap, f_edge, p = rotating['flap'][0]['frequency_hz'], rotating['edge'][0]['frequency_hz'], rpm / 60
        self.assertAlmostEqual(curves['coupled_blade_flap_collective1']['frequency_hz'][-1], f_flap, delta=1e-3 * f_flap)
        self.assertAlmostEqual(curves['coupled_blade_flap_backward1']['frequency_hz'][-1], f_flap - p, delta=1e-3 * f_flap)
        self.assertAlmostEqual(curves['coupled_blade_flap_forward1']['frequency_hz'][-1], f_flap + p, delta=1e-3 * f_flap)
        self.assertAlmostEqual(curves['coupled_blade_edge_backward1']['frequency_hz'][-1], f_edge - p, delta=2e-3 * f_edge)
        self.assertAlmostEqual(curves['coupled_blade_edge_forward1']['frequency_hz'][-1], f_edge + p, delta=2e-3 * f_edge)

    def test_standstill_rigid_blades_match_parked_rotor_body(self):
        """At standstill and with very stiff blades the tower modes match a tower carrying the rotor as a rigid body."""
        stiff_blade = copy.deepcopy(self.blade)
        stiff_blade['stations'] = [(x, m, f * 1e4, e * 1e4) for x, m, f, e in self.blade['stations']]
        blade_beam = modal.blade_beam(stiff_blade, self.length, self.rotor['twist'])
        curves = self._campbell(self.tower, [0.0, 1.0], blade_beam)
        bodies, _, _ = structural._top_bodies({}, {'nacelle': self.nacelle, 'hub': self.hub, 'blade': self.blade, 'spec': self.spec})
        found = modal.pick(modal.solve(modal.tower_beam(self.tower, bodies), component='tower'), {'fa': 1, 'ss': 1})
        for family in ('fa', 'ss'):
            reference = found[family][0]['frequency_hz']
            self.assertAlmostEqual(curves[f'coupled_tower_{family}1']['frequency_hz'][0], reference, delta=2e-3 * reference)

    def test_mbc_needs_three_blades(self):
        tower_beam = modal.tower_beam(self.tower, _nacelle_body(self.nacelle))
        with self.assertRaises(coupled.CoupledError):
            coupled.campbell(self.blade_beam, tower_beam, blades=2, hub_radius=0.5, hub_offset=(0, 0, 1), rpm=[0, 10],
                             blade_counts={'flap': 1}, tower_counts={'fa': 1}, blade_damping={}, tower_damping=0.0)


class CoupledBlock(unittest.TestCase):
    def test_template_with_coupling(self):
        workflow = copy.deepcopy(TEMPLATES['structural_campbell'])
        workflow = {'schema_version': 2, 'kind': 'blocks', 'name': 'coupled', 'nodes': workflow['nodes'], 'edges': workflow['edges']}
        for node in workflow['nodes']:
            if node['id'] == 'campbell':
                node['config'].update(coupling='mbc', points=7)
        result = engine.execute(workflow)
        block = result['blocks']['campbell']
        self.assertEqual(block['status'], 'succeeded', block.get('error'))
        curves = block['outputs']['modal']['campbell']['curves']
        self.assertTrue(all(c['frame'] == 'fixed' for c in curves))
        whirls = {c['whirl'] for c in curves if c['component'] == 'coupled'}
        self.assertTrue({'collective', 'forward', 'backward'} <= whirls)
        self.assertIn('min_excitation_margin_pct', block['outputs']['values'])

    def test_shapes_show_whirl_phase(self):
        workflow = copy.deepcopy(TEMPLATES['structural_campbell'])
        workflow = {'schema_version': 2, 'kind': 'blocks', 'name': 'coupled', 'nodes': workflow['nodes'], 'edges': workflow['edges']}
        for node in workflow['nodes']:
            if node['id'] == 'campbell':
                node['config'].update(coupling='mbc', points=5, rpm_min=40.0, rpm_max=70.0)
        modal_out = engine.execute(workflow)['blocks']['campbell']['outputs']['modal']
        self.assertIn('overhang_m', modal_out['layout'])
        curves = {c['id']: c for c in modal_out['campbell']['curves']}

        def tips(curve):
            fields = curve['shapes'][-1]['blades']
            return [complex(f['flap'][0][-1], f['flap'][1][-1]) for f in fields]
        collective = tips(curves['coupled_blade_flap_collective1'])
        self.assertLess(max(abs(np.angle(a / collective[0])) for a in collective), 0.05)
        whirl = tips(curves['coupled_blade_flap_backward1'])
        gaps = sorted(abs(np.degrees(np.angle(whirl[(k + 1) % 3] / whirl[k]))) for k in range(3))
        np.testing.assert_allclose(gaps, [120.0, 120.0, 120.0], atol=3.0)
        tower = curves['coupled_tower_fa1']['shapes'][-1]['tower']['fa']
        self.assertAlmostEqual(max(abs(v) for v in tower[0]), 1.0, places=3)

    def test_coupling_without_tower_fails_clearly(self):
        workflow = copy.deepcopy(TEMPLATES['structural_campbell'])
        edges = [e for e in workflow['edges'] if not (e['target'] == 'campbell' and e['target_port'] in ('tower', 'nacelle'))]
        workflow = {'schema_version': 2, 'kind': 'blocks', 'name': 'coupled', 'nodes': workflow['nodes'], 'edges': edges}
        for node in workflow['nodes']:
            if node['id'] == 'campbell':
                node['config'].update(coupling='mbc', points=3)
        block = engine.execute(workflow)['blocks']['campbell']
        self.assertEqual(block['status'], 'failed')
        self.assertIn('tower and nacelle', block['error'])


if __name__ == '__main__':
    unittest.main()
