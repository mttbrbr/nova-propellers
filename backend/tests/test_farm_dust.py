"""Phase 5: native NOJ wind farm, wind climate, farm blocks and the DUST case/adapter."""
import copy
import math
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import numpy as np

from nova.adapters.base import AdapterConfiguration, execute_adapter
from nova.adapters.dust import DustAdapter
from nova.blocks import engine
from nova.physics import dust_case, farm, rotors


class Overlap(unittest.TestCase):
    def test_limits_and_lens(self):
        self.assertEqual(farm.overlap_fraction(2.0, 1.0, 3.5), 0.0)
        self.assertEqual(farm.overlap_fraction(2.0, 1.0, 0.5), 1.0)
        self.assertAlmostEqual(farm.overlap_fraction(0.5, 1.0, 0.0), 0.25)
        # equal circles of radius r at distance r: lens area = (2π/3 − √3/2) r²
        self.assertAlmostEqual(farm.overlap_fraction(1.0, 1.0, 1.0), (2 * math.pi / 3 - math.sqrt(3) / 2) / math.pi, places=10)


class Noj(unittest.TestCase):
    def test_single_aligned_wake(self):
        D, ct, k, V = 80.0, 0.75, 0.1, 9.0
        x = 7 * D
        speeds = farm.effective_speeds([0.0, x], [0.0, 0.0], direction_deg=270.0, speed=V, diameter=D, ct_curve=lambda v: ct, k=k)
        expected = V * (1 - (1 - math.sqrt(1 - ct)) * (D / 2 / (D / 2 + k * x)) ** 2)
        self.assertAlmostEqual(speeds[0], V)
        self.assertAlmostEqual(speeds[1], expected, places=10)

    def test_crosswind_row_has_no_wake(self):
        speeds = farm.effective_speeds([0.0, 0.0], [0.0, 400.0], direction_deg=270.0, speed=8.0, diameter=80.0, ct_curve=lambda v: 0.8)
        np.testing.assert_allclose(speeds, [8.0, 8.0])

    def test_climate(self):
        climate = farm.weibull_climate(sectors=4, mean_wind_m_s=7.0, shape=2.0, speeds=np.arange(4.0, 20.01, 1.0))
        self.assertAlmostEqual(sum(map(sum, climate['probabilities'])), 1.0)
        c = climate['weibull_scale_m_s'][0]
        inside = math.exp(-(3.5 / c) ** 2) - math.exp(-(20.5 / c) ** 2)
        self.assertAlmostEqual(climate['excluded_probability'], 1 - inside, places=10)


def _node(nid, kind, config=None):
    return {'id': nid, 'type': kind, 'config': config or {}}


def _edge(a, ap, b, bp):
    return {'source': a, 'source_port': ap, 'target': b, 'target_port': bp}


class FarmWorkflow(unittest.TestCase):
    def test_farm_chain_to_cost(self):
        nodes = [_node('rotor', 'rotor_hawt', copy.deepcopy(engine.BLOCKS['rotor_hawt']['defaults'])),
                 _node('op', 'operating_point', {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 7.0}}),
                 _node('curve', 'performance_curve', {'points': 11, 'start': 3.0, 'stop': 11.0}),
                 _node('strategy', 'operating_strategy', {'rated_power_w': 20000.0, 'rpm_max': 160.0, 'cut_in_m_s': 3.0, 'cut_out_m_s': 25.0, 'points': 12}),
                 _node('turbine', 'farm_turbine', {'hub_height_m': 25.0}),
                 _node('layout', 'farm_layout', {'rows': 2, 'columns': 3}),
                 _node('climate', 'wind_climate', {'sectors': 8, 'mean_wind_m_s': 7.0, 'speed_min_m_s': 3.0, 'speed_max_m_s': 25.0,
                                                   'speed_step_m_s': 2.0}),
                 _node('farm', 'wind_farm', {}),
                 _node('cost', 'cost_model', {'hub_height_m': 25.0, 'rating_kw': 20.0, 'bos_per_kw': 600.0, 'opex_per_kw_yr': 40.0})]
        edges = [_edge('rotor', 'spec', 'op', 'spec'), _edge('op', 'spec', 'curve', 'spec'), _edge('op', 'spec', 'strategy', 'spec'),
                 _edge('curve', 'table', 'strategy', 'table'), _edge('op', 'spec', 'turbine', 'spec'), _edge('strategy', 'table', 'turbine', 'table'),
                 _edge('turbine', 'turbine', 'layout', 'turbine'), _edge('turbine', 'turbine', 'farm', 'turbine'),
                 _edge('layout', 'layout', 'farm', 'layout'), _edge('climate', 'climate', 'farm', 'climate'), _edge('op', 'spec', 'cost', 'spec')]
        result = engine.execute({'schema_version': 2, 'kind': 'blocks', 'name': 'farm', 'nodes': nodes, 'edges': edges})
        self.assertEqual(result['status'], 'succeeded', {k: v.get('error') for k, v in result['blocks'].items()})
        values = result['blocks']['farm']['outputs']['values']
        self.assertGreater(values['wake_loss_pct'], 0.0)
        self.assertLess(values['wake_loss_pct'], 30.0)
        self.assertEqual(values['turbines'], 6.0)
        self.assertLess(values['aep_gwh'], values['aep_without_wakes_gwh'])


class DustCase(unittest.TestCase):
    def setUp(self):
        spec = rotors.merged({'kind': 'hawt'})
        self.built, self.rotor, _ = rotors.build(spec)

    def test_case_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = dust_case.write(Path(tmp), self.rotor, self.rotor.section, velocity=8.0, rpm=100.0, sections=5, revolutions=3,
                                   steps_per_revolution=24)
            names = {p.name for p in Path(tmp).iterdir()}
            self.assertTrue({'dust.in', 'dust_pre.in', 'dust_post.in', 'References.in', 'blade.in', 'airfoil_01.c81', 'Output'} <= names)
            blade = (Path(tmp) / 'blade.in').read_text()
            self.assertEqual(blade.count('airfoil_table'), 5)
            self.assertEqual(sum(line.startswith('span =') for line in blade.splitlines()), 4)
            refs = (Path(tmp) / 'References.in').read_text()
            self.assertIn('N_Blades = 3', refs)
            self.assertIn(f'Rot_Rate = {100 * math.pi / 30:.8f}', refs)
            self.assertAlmostEqual(info['period_s'], 0.6)
            self.assertIn('EndRes = 72', (Path(tmp) / 'dust_post.in').read_text())
            self._check_c81((Path(tmp) / 'airfoil_01.c81').read_text())

    def _check_c81(self, text):
        """Read the table as DUST's mod_c81 does (list-directed reads and a fixed 6I2 field after the name)."""
        lines = text.splitlines()
        self.assertEqual(int(lines[0].split()[0]), 1)
        line = lines[5]
        counts = line[line.index(' '):].strip()
        cl2, cl1, cd2, cd1, cm2, cm1 = (int(counts[i:i + 2]) for i in range(0, 12, 2))
        self.assertEqual((cl2, cd2, cm2), (2, 2, 2))
        self.assertEqual(len(lines), 6 + 3 * (1 + cl1))
        alpha = [float(lines[7 + i].split()[0]) for i in range(cl1)]
        self.assertTrue(all(b > a for a, b in zip(alpha, alpha[1:])))

    def test_loads_reader(self):
        text = '# t Fx Fy Fz Mx My Mz\n' + '\n'.join(f'{t:.3f} 0 0 {100 + t:.3f} 0 0 {50:.3f} ' + ' '.join(['0'] * 12)
                                                    for t in np.linspace(0, 1, 11))
        loads = dust_case.read_loads(text)
        perf = dust_case.rotor_performance(loads, window=(0.5, 1.0), omega=10.0, velocity=8.0, density=1.225, tip_radius=5.0)
        self.assertAlmostEqual(perf['thrust_n'], 100.75)
        self.assertAlmostEqual(perf['power_w'], 500.0)

    def test_adapter_with_stand_in_executables(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / 'bin'
            bin_dir.mkdir()
            scripts = {
                'dust_pre': "assert open('dust_pre.in').read().startswith('CompName'); open('geo_input.h5', 'w').write('x')",
                'dust': "import os; assert os.path.exists('geo_input.h5'); open('Output/nova_res_0001.h5', 'w').write('x')",
                'dust_post': "open('Postpro/nova_loads_rotor.dat', 'w').write('# header\\n0.0 0 0 10 0 0 5 ' + '0 ' * 12 + '\\n1.0 0 0 12 0 0 7 ' + '0 ' * 12)",
            }
            for name, body in scripts.items():
                path = bin_dir / name
                path.write_text(textwrap.dedent(f'#!{sys.executable}\nimport sys\n{body}\n'))
                path.chmod(path.stat().st_mode | stat.S_IEXEC)
            source = Path(tmp) / 'case'
            source.mkdir()
            info = dust_case.write(source, self.rotor, self.rotor.section, velocity=8.0, rpm=100.0, sections=3)
            adapter = DustAdapter()
            self.assertTrue(adapter.probe(AdapterConfiguration(bin_dir / 'dust'))['available'])
            output = execute_adapter(adapter, AdapterConfiguration(bin_dir / 'dust'),
                                     {'case_directory': str(source), 'loads_file': info['loads_file']}, Path(tmp) / 'runs')
            loads = dust_case.read_loads(output['data']['loads_text'])
            self.assertEqual(loads.shape[0], 2)


if __name__ == '__main__':
    unittest.main()
