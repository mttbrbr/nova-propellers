"""Protocol verification; fake environment is not scientific validation."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from nova.adapters.base import AdapterConfiguration, AdapterError, execute_adapter
from nova.adapters.pywake import PyWakeAdapter


def case():
    return {'turbine': {'name': 'Fixture', 'diameter_m': 80, 'hub_height_m': 70,
                        'wind_speed_m_s': [0, 5, 10, 25], 'power_w': [0, 100, 1000, 0], 'ct': [0, .8, .8, 0]},
            'layout': {'x_m': [0, 500], 'y_m': [0, 0]},
            'wind': {'directions_deg': [270, 90], 'speeds_m_s': [5, 10],
                     'probabilities': [[.1, .2], [.3, .4]], 'turbulence_intensity': .1}, 'wake_model': 'noj'}


class PyWakeTests(unittest.TestCase):
    def setUp(self):
        self.adapter = PyWakeAdapter()
        self.configuration = AdapterConfiguration(Path(sys.executable), 'python_environment')

    def test_strict_case_validation(self):
        self.adapter.validate(case(), self.configuration)
        mutations = [lambda c: c['wind'].update(probabilities=[[1, 1], [1, 1]]),
                     lambda c: c['layout'].update(x_m=[0, 0]),
                     lambda c: c['turbine'].update(ct=[0, 2, .8, 0]),
                     lambda c: c['turbine'].update(wind_speed_m_s=[0, 5, 5, 25]),
                     lambda c: c['wind'].update(speeds_m_s=[30]),
                     lambda c: c['wind'].update(turbulence_intensity=True),
                     lambda c: c['layout'].update(y_m=[float('nan'), 0]),
                     lambda c: c['wind'].update(probabilities=[[1], [0]]),
                     lambda c: c.update(timeout_seconds=float('inf')),
                     lambda c: c.update(extra=True)]
        for mutate in mutations:
            invalid = case()
            mutate(invalid)
            with self.subTest(case=invalid), self.assertRaises(ValueError):
                self.adapter.validate(invalid, self.configuration)

    def fixture_output(self, c):
        return {'_case': c, 'program_version': 'fixture-not-PyWake',
                **{key: c['wind'][key] for key in ('directions_deg', 'speeds_m_s', 'probabilities')},
                'power_w': [[[100, 1000], [100, 1000]], [[50, 500], [100, 1000]]],
                'power_without_wakes_w': [[[100, 1000], [100, 1000]]] * 2,
                'effective_speed_m_s': [[[5, 10], [5, 10]]] * 2}

    def test_joint_weights_aep_and_zero_denominator(self):
        output = self.fixture_output(case())
        result = self.adapter.normalize(output)
        self.assertAlmostEqual(result['aep_gwh'][0], 640 * 8760 / 1e9)
        self.assertAlmostEqual(result['aep_gwh'][1], 535 * 8760 / 1e9)
        self.assertAlmostEqual(result['wake_loss_fraction'], 105/1280)
        for key in ('power_w', 'power_without_wakes_w'):
            output[key] = [[[0, 0], [0, 0]]] * 2
        self.assertIsNone(self.adapter.normalize(output)['wake_loss_fraction'])

    def test_invalid_output_rejected(self):
        output = self.fixture_output(case())
        output['power_w'][0][0][0] = float('inf')
        with self.assertRaises(AdapterError):
            self.adapter.normalize(output)
        output = self.fixture_output(case())
        output['directions_deg'] = [90, 270]
        with self.assertRaises(AdapterError):
            self.adapter.normalize(output)

    def test_external_protocol_preserves_standalone_runner(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            executable = root / 'fake python'
            output = self.fixture_output(case())
            output.pop('_case')
            executable.write_text('#!' + sys.executable + '\nimport json,sys\nfrom pathlib import Path\n'
                'if sys.argv[1] == "-c":\n'
                ' print(json.dumps({"available":True,"compatible":True,"version":"2.6.fixture"}))\n'
                'else:\n'
                ' assert Path("pywake_runner.py").is_file()\n'
                ' assert json.loads(Path("input.json").read_text())["wake_model"] == "noj"\n'
                ' Path("output.json").write_text(' + repr(json.dumps(output)) + ')\n')
            executable.chmod(0o755)
            configuration = AdapterConfiguration(executable, 'python_environment')
            result = execute_adapter(self.adapter, configuration, case(), root / 'cases')
            self.assertEqual(result['data']['kind'], 'wind_farm_result')
            directory = Path(result['working_directory'])
            self.assertIn('pywake_runner.py', result['artifacts'])
            self.assertTrue((directory / 'input.json').exists())
            self.assertEqual(result['provenance']['program']['version'], '2.6.fixture')

    @unittest.skipUnless(os.getenv('NOVA_PYWAKE_PYTHON'), 'Separate real PyWake environment not configured')
    def test_real_pywake_single_turbine_and_downstream_loss(self):
        configuration = AdapterConfiguration(Path(os.environ['NOVA_PYWAKE_PYTHON']), 'python_environment')
        with tempfile.TemporaryDirectory() as root:
            c = case()
            c['wind'].update(directions_deg=[270], probabilities=[[.5, .5]])
            result = execute_adapter(self.adapter, configuration, c, Path(root))['data']
            self.assertGreater(result['wake_loss_fraction'], 0)
            self.assertAlmostEqual(result['total_aep_without_wakes_gwh'], 2 * 550 * 8760 / 1e9)
            self.assertLess(result['power_w'][1][0][1], result['power_w'][0][0][1])
            c['layout'] = {'x_m': [0], 'y_m': [0]}
            single = execute_adapter(self.adapter, configuration, c, Path(root))['data']
            self.assertAlmostEqual(single['wake_loss_fraction'], 0, places=10)
            self.assertAlmostEqual(single['total_aep_gwh'], 550 * 8760 / 1e9)


if __name__ == '__main__':
    unittest.main()
