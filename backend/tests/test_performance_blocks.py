"""Phase 2: performance maps, flexible/sheared Cp–λ and the operating strategy."""
import copy
import math
import unittest

import numpy as np

from nova.adapters import openfast_structure as st
from nova.blocks import engine, performance
from nova.physics import flexible, modal, rotors


def _hawt():
    return rotors.merged({'kind': 'hawt'})


def _blade(ei_scale=1.0):
    """Uniform blade for the default 5 m HAWT (4.5 m from hub to tip)."""
    return st.blade_record({'stations': [
        {'span_fraction': x, 'mass_per_length_kg_m': 12.0, 'flap_stiffness_nm2': 2.0e5 * ei_scale, 'edge_stiffness_nm2': 8.0e5 * ei_scale}
        for x in (0.0, 0.5, 1.0)]})


class Deflection(unittest.TestCase):
    def test_uniform_load_cantilever(self):
        blade = _blade()
        beam = modal.blade_beam(blade, 4.5)
        q = 100.0
        x, w, v = flexible.deflection(beam, omega=0.0, hub_radius=0.0, positions=[0.0, 1.0], loads_out=[q, q], loads_in=[0.0, 0.0])
        self.assertAlmostEqual(w[-1], q * 4.5**4 / (8 * 2.0e5), delta=1e-3 * w[-1])
        self.assertAlmostEqual(v[-1], 0.0, places=9)

    def test_rotation_stiffens(self):
        beam = modal.blade_beam(_blade(), 4.5)
        args = dict(hub_radius=0.5, positions=[0.0, 1.0], loads_out=[100.0, 100.0], loads_in=[0.0, 0.0])
        still = flexible.deflection(beam, omega=0.0, **args)[1][-1]
        spinning = flexible.deflection(beam, omega=10.0, **args)[1][-1]
        self.assertLess(spinning, still)


class PerformanceMap(unittest.TestCase):
    def test_one_variable_matches_dense_curve(self):
        spec = _hawt()
        dense = rotors.performance_curve(spec, values=np.linspace(4, 10, 121).tolist())
        node = {'config': {'variables': [{'path': 'operating.tip_speed_ratio', 'min': 3.0, 'max': 12.0}], 'points': 5, 'levels': 4}}
        out = performance.performance_map(node, {'spec': spec})
        self.assertLess(out['values']['evaluations'], 30)
        self.assertGreaterEqual(out['values']['objective'], dense['optimum']['value'] * 0.999)
        self.assertAlmostEqual(out['values']['tip_speed_ratio'], dense['optimum']['tip_speed_ratio'], delta=0.15)
        self.assertLess(out['values']['surface_error_pct'], 1.0)

    def test_two_variables_and_spec_output(self):
        node = {'config': {'variables': [{'path': 'operating.tip_speed_ratio', 'min': 4.0, 'max': 10.0},
                                         {'path': 'geometry.pitch_deg', 'min': -3.0, 'max': 4.0}], 'points': 4, 'levels': 3,
                           'max_evaluations': 60}}
        out = performance.performance_map(node, {'spec': _hawt()})
        self.assertGreaterEqual(out['values']['objective'], out['values']['objective_sampled'] - 1e-12)
        self.assertEqual(out['spec']['geometry']['pitch_deg'], out['values']['pitch_deg'])
        self.assertTrue(out['table']['surface'])

    def test_rpm_is_replaced_by_tip_speed_ratio(self):
        spec = _hawt()
        spec['operating'] = {'velocity_m_s': 8.0, 'rpm': 100.0}
        out = performance.apply(copy.deepcopy(spec), 'operating.tip_speed_ratio', 6.0)
        self.assertNotIn('rpm', out['operating'])


class FlexibleCurve(unittest.TestCase):
    config = {'start': 5.0, 'stop': 9.0, 'points': 3}

    def test_rigid_without_structure(self):
        out = performance.cp_flexible({'config': self.config}, {'spec': _hawt()})
        for row in out['table']['rows']:
            self.assertAlmostEqual(row['CP'], row['CP_rigid'], places=12)

    def test_precone_is_cos_cubed(self):
        out = performance.cp_flexible({'config': {**self.config, 'precone_deg': 5.0}}, {'spec': _hawt()})
        for row in out['table']['rows']:
            self.assertAlmostEqual(row['CP'], row['CP_rigid'] * math.cos(math.radians(5)) ** 3, places=12)

    def test_stiff_blade_is_rigid_soft_blade_loses_power(self):
        stiff = performance.cp_flexible({'config': self.config}, {'spec': _hawt(), 'blade': _blade(1e4)})
        soft = performance.cp_flexible({'config': self.config}, {'spec': _hawt(), 'blade': _blade(0.05)})
        for row in stiff['table']['rows']:
            self.assertAlmostEqual(row['CP'], row['CP_rigid'], delta=1e-5)
        self.assertGreater(soft['values']['CP_loss_pct'], 0.1)
        self.assertGreater(soft['values']['max_tip_flap_m'], stiff['values']['max_tip_flap_m'])

    def test_shear_lowers_power(self):
        out = performance.cp_flexible({'config': {**self.config, 'shear_exponent': 0.3, 'hub_height_m': 12.0}}, {'spec': _hawt()})
        self.assertLess(out['values']['CP_max'], out['values']['CP_rigid_max'])

    def test_shear_needs_hub_height(self):
        with self.assertRaises(performance.PerformanceError):
            performance.cp_flexible({'config': {**self.config, 'shear_exponent': 0.2}}, {'spec': _hawt()})


class OperatingStrategy(unittest.TestCase):
    def test_rotor_speed_from_tsr(self):
        out = performance.operating_strategy({'config': {'tip_speed_ratio': 7.0, 'wind_speed_m_s': 8.0}}, {'spec': _hawt()})
        self.assertAlmostEqual(out['values']['rpm'], 7.0 * 8.0 / 5.0 * 60 / (2 * math.pi))
        self.assertEqual(out['spec']['operating']['rpm'], out['values']['rpm'])
        self.assertTrue(rotors.analyze(out['spec'])['converged'])

    def test_schedule_with_curve_limits_and_rating(self):
        curve = rotors.performance_curve(_hawt(), values=np.linspace(2, 12, 41).tolist())
        table = {'rows': curve['rows']}
        config = {'wind_speed_m_s': 6.0, 'rpm_max': 120.0, 'rated_power_w': 40000.0, 'cut_in_m_s': 3.0, 'cut_out_m_s': 20.0, 'points': 35}
        out = performance.operating_strategy({'config': config}, {'spec': _hawt(), 'table': table})
        rows = out['table']['rows']
        self.assertAlmostEqual(out['values']['tip_speed_ratio'], curve['optimum']['tip_speed_ratio'])
        self.assertLessEqual(max(r['rpm'] for r in rows), 120.0 + 1e-9)
        self.assertLessEqual(max(r['power_w'] for r in rows), 40000.0 + 1e-6)
        self.assertTrue(any(r['region'].startswith('2.5') for r in rows))
        self.assertIn('rated_wind_speed_m_s', out['values'])


class Workflow(unittest.TestCase):
    def test_blocks_chain_in_a_workflow(self):
        rotor = engine.BLOCKS['rotor_hawt']['defaults']
        workflow = {'schema_version': 2, 'kind': 'blocks', 'name': 'p2', 'nodes': [
            {'id': 'rotor', 'type': 'rotor_hawt', 'config': copy.deepcopy(rotor)},
            {'id': 'op', 'type': 'operating_point', 'config': {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 7.0}}},
            {'id': 'curve', 'type': 'cp_flexible', 'config': {'start': 4.0, 'stop': 10.0, 'points': 7}},
            {'id': 'strategy', 'type': 'operating_strategy', 'config': {'wind_speed_m_s': 9.0}},
            {'id': 'solve', 'type': 'solver', 'config': {}}],
            'edges': [{'source': 'rotor', 'source_port': 'spec', 'target': 'op', 'target_port': 'spec'},
                      {'source': 'op', 'source_port': 'spec', 'target': 'curve', 'target_port': 'spec'},
                      {'source': 'op', 'source_port': 'spec', 'target': 'strategy', 'target_port': 'spec'},
                      {'source': 'curve', 'source_port': 'table', 'target': 'strategy', 'target_port': 'table'},
                      {'source': 'strategy', 'source_port': 'spec', 'target': 'solve', 'target_port': 'spec'}]}
        result = engine.execute(workflow)
        self.assertEqual(result['status'], 'succeeded', {k: v.get('error') for k, v in result['blocks'].items()})


if __name__ == '__main__':
    unittest.main()
