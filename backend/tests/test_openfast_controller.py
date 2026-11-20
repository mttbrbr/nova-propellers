"""Nova DISCON: mapping of the control blocks, the compiled library, and native vs OpenFAST in closed loop."""
import ctypes
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from nova.adapters import discon
from nova.adapters import openfast_structure as st
from nova.adapters.openfast import read_openfast_output
from nova.adapters.openfast_case import write_case
from nova.blocks import control as control_blocks
from nova.blocks import engine
from nova.blocks.templates import TEMPLATES
from nova.physics import control

OPENFAST = Path(os.environ.get('NOVA_OPENFAST', Path.home() / '.local/share/nova-external/openfast/5.0.0/bin/openfast'))
COMPILER = shutil.which('cc') or shutil.which('gcc')


def _chain(extra=()):
    return [{'element': 'source', 'output': 'wind_speed', 'kind': 'ramp', 'value': 8.0, 'amplitude': 4.0, 'time': 2.0, 'end_time': 6.0},
            {'element': 'torque_law', 'input': 'rotor_speed', 'output': 'gen_torque', 'k': 120.0, 'rated_torque_nm': 6000.0},
            {'element': 'lookup', 'input': 'pitch', 'output': 'gain', 'breakpoints': [0, 20], 'values': [1.0, 0.5]},
            {'element': 'pid', 'output': 'pitch', 'measurement': 'rotor_speed', 'setpoint': 6.8, 'kp': 8.0, 'ki': 3.0, 'min': 0.0,
             'max': 30.0, 'reverse': True, 'gain_signal': 'gain'}, *extra]


class Mapping(unittest.TestCase):
    def test_chain_becomes_controller(self):
        out = discon.from_chain(_chain(), 10.0)
        self.assertEqual(out['torque_k_nms2'], 120.0)
        self.assertEqual(out['pitch']['schedule_values'], [1.0, 0.5])
        self.assertAlmostEqual(out['wind']['speeds'][0], 8.0)
        self.assertAlmostEqual(out['wind']['speeds'][-1], 12.0)
        text = discon.parameters(out)
        self.assertIn('schedule_point 20 0.5', text)
        self.assertIn('reverse 1', text)

    def test_unsupported_elements_are_refused(self):
        tf = {'element': 'transfer_function', 'input': 'u', 'output': 'y', 'numerator': [1.0], 'denominator': [1.0, 1.0]}
        with self.assertRaisesRegex(discon.DisconError, 'transfer_function'):
            discon.from_chain(_chain([tf]), 10.0)


@unittest.skipUnless(COMPILER, 'No C compiler')
class Library(unittest.TestCase):
    def test_torque_and_pitch_logic(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = ctypes.CDLL(str(discon.build(Path(tmp))))
            parameters = Path(tmp) / 'nova_discon.in'
            parameters.write_text(discon.parameters({'torque_k_nms2': 100.0, 'rated_torque_nm': 4000.0, 'gearbox_ratio': 2.0,
                                                     'pitch': {'kp': 2.0, 'ki': 1.0, 'setpoint': 6.0, 'min': 0.0, 'max': 30.0, 'reverse': True}}))
            swap = (ctypes.c_float * 200)()
            fail = ctypes.c_int(0)
            message = ctypes.create_string_buffer(256)
            name = str(parameters).encode()
            swap[48], swap[49], swap[50] = 255, len(name) + 1, 2
            pitches = []
            for k, (status, speed) in enumerate([(0, 5.0), (1, 5.0), (1, 7.0), (1, 7.0), (1, 7.0)]):
                swap[0], swap[1], swap[20] = status, 0.1 * k, speed
                library.DISCON(swap, ctypes.byref(fail), name, b'case', message)
                self.assertEqual(fail.value, 0, message.value)
                pitches.append(swap[44])
            self.assertAlmostEqual(swap[46], min(100.0 * 49.0, 4000.0) / 2.0, places=3)
            self.assertEqual(pitches[0], 0.0)
            self.assertGreater(pitches[-1], pitches[-2])
            self.assertEqual(swap[34], 1.0)


@unittest.skipUnless(OPENFAST.exists() and COMPILER, 'OpenFAST or a C compiler not available')
class AgainstOpenFAST(unittest.TestCase):
    """AOC 15/50 example: the same controller and wind step, Nova's aeroelastic model against OpenFAST."""

    def test_closed_loop(self):
        nodes = {n['id']: n for n in TEMPLATES['structural_campbell']['nodes']}
        spec = engine._operating(nodes['operating'], {'spec': engine._rotor(nodes['rotor'], {})['spec']})['spec']
        parts = {'blade': st.blade_record(nodes['blade']['config']), 'tower': st.tower_record(nodes['tower']['config']),
                 'hub': st.hub_record(nodes['hub']['config']), 'nacelle': st.nacelle_record(nodes['nacelle']['config'])}
        parts['hub']['precone_deg'] = 0.0
        law = control_blocks.torque_law({'config': {'rated_torque_nm': 7000.0}}, {'spec': spec})
        plant = control_blocks.turbine_dynamics({'config': {'initial_rpm': 62.0}}, {'spec': spec, **parts})
        wind = {'element': 'source', 'output': 'wind_speed', 'kind': 'table', 'times': [0.0, 4.0, 10.0, 20.0], 'values': [10.0, 10.0, 13.0, 13.0]}
        pid = {'element': 'pid', 'output': 'pitch', 'measurement': 'rotor_speed', 'setpoint': 6.8, 'kp': 8.0, 'ki': 3.0, 'min': 0.0, 'max': 30.0,
               'reverse': True}
        chain = [wind, *law['dynamics'], pid, *plant['dynamics']]
        t, native = control.simulate(chain, duration=20.0, dt=0.02, initial={'pitch': 0.0, 'gen_torque': 0.0},
                                     record=['rotor_speed', 'pitch', 'power'])
        with tempfile.TemporaryDirectory() as tmp:
            controller = discon.from_chain(chain, 20.0)
            library = discon.build(Path(tmp) / 'lib')
            start = dict(spec)
            start['operating'] = {'velocity_m_s': 10.0, 'rpm': 62.0}
            info = write_case(start, Path(tmp) / 'case', {'duration_s': 20.0, 'dt_s': 0.005}, parts, controller=controller, library=library)
            subprocess.run([str(OPENFAST), info['input_file']], cwd=Path(tmp) / 'case', check=True, capture_output=True, timeout=900)
            data = read_openfast_output(Path(tmp) / 'case' / info['output_file'])
        names = [c['name'] for c in data['channels']]
        values = np.asarray(data['values'])
        keep = np.asarray(data['time_s']) >= 16.0
        tail = t >= 16.0
        rpm_of = values[keep, names.index('RotSpeed')].mean()
        self.assertAlmostEqual(native['rotor_speed'][tail].mean() * 30 / np.pi, rpm_of, delta=0.01 * rpm_of)
        self.assertAlmostEqual(native['pitch'][tail].mean(), values[keep, names.index('BldPitch1')].mean(), delta=1.0)
        power_of = values[keep, names.index('GenPwr')].mean() * 1000
        self.assertAlmostEqual(native['power'][tail].mean(), power_of, delta=0.03 * power_of)


if __name__ == '__main__':
    unittest.main()
