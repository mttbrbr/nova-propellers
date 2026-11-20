"""Aeroelastic time-domain turbine: steady state, free decay, closed loop."""
import math
import unittest

import numpy as np

from nova.adapters import openfast_structure as st
from nova.blocks import control as control_blocks
from nova.blocks import engine
from nova.blocks.templates import TEMPLATES
from nova.physics import control, coupled, dynamics, rotors


def _aoc():
    nodes = {n['id']: n for n in TEMPLATES['structural_campbell']['nodes']}
    spec = engine._operating(nodes['operating'], {'spec': engine._rotor(nodes['rotor'], {})['spec']})['spec']
    parts = {'blade': st.blade_record(nodes['blade']['config']), 'tower': st.tower_record(nodes['tower']['config']),
             'hub': st.hub_record(nodes['hub']['config']), 'nacelle': st.nacelle_record(nodes['nacelle']['config'])}
    return spec, parts


class Turbine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec, cls.parts = _aoc()
        built, rotor, _ = rotors.build(rotors.merged(cls.spec))
        cls.V, cls.rpm = rotors.resolve_operating(built, rotor)

    def test_steady_state_matches_bemt(self):
        model = dynamics.Turbine(self.spec, **self.parts)
        omega = self.rpm * math.pi / 30
        history = [model.step(0.02, self.V, 0.0, 0.0, fixed_speed=omega) for _ in range(400)]
        last = history[-100:]
        reference = rotors.analyze(self.spec)['performance']
        self.assertAlmostEqual(np.mean([h['aero_power'] for h in last]), reference['power_w'], delta=0.005 * reference['power_w'])
        self.assertAlmostEqual(np.mean([h['thrust'] for h in last]), reference['thrust_n'], delta=0.005 * reference['thrust_n'])
        self.assertGreater(np.mean([h['tower_top_fa'] for h in last]), 0)
        self.assertGreater(np.mean([h['tip_flap_b1'] for h in last]), 0)

    def test_free_decay_at_the_coupled_frequency(self):
        model = dynamics.Turbine(self.spec, **self.parts)
        fa = model.tower.families.index('fa')
        model.x[fa] = 0.01 / abs(model.tower.A_u[2, fa])
        omega = self.rpm * math.pi / 30
        dt = 0.005
        trace = np.array([model.step(dt, self.V, 0.0, 0.0, fixed_speed=omega, aero=False)['tower_top_fa'] for _ in range(2400)])
        crossings = np.nonzero(np.diff(np.signbit(trace - trace.mean())))[0]
        period = 2 * np.mean(np.diff(crossings)) * dt
        blade = coupled.Blade(model.beam, omega, model.hub_r, {'flap': 2, 'edge': 1}, {})
        found = coupled.modes(coupled.System(model.tower, blade, 3, omega, model.offset, model.system.hub_ring))
        expected = next(m['frequency_hz'] for m in found if m['dominant'] == 'tower_fa')
        self.assertAlmostEqual(1 / period, expected, delta=0.02 * expected)


class ClosedLoop(unittest.TestCase):
    def test_pitch_controller_holds_speed_above_rated(self):
        spec, parts = _aoc()
        law = control_blocks.torque_law({'config': {'rated_torque_nm': 7000.0}}, {'spec': spec})
        plant = control_blocks.turbine_dynamics({'config': {'initial_rpm': 64.0}}, {'spec': spec, **parts})
        elements = [{'element': 'source', 'output': 'wind_speed', 'kind': 'constant', 'value': 15.0}, *law['dynamics'],
                    {'element': 'pid', 'output': 'pitch', 'measurement': 'rotor_speed', 'setpoint': 6.8, 'kp': 8.0, 'ki': 3.0,
                     'min': 0.0, 'max': 30.0, 'reverse': True, 'offset': 12.0}, *plant['dynamics']]
        t, s = control.simulate(elements, duration=25.0, dt=0.04, initial={'pitch': 12.0, 'gen_torque': 0.0},
                                record=['rotor_speed', 'pitch', 'tower_top_fa'])
        tail = t >= 18.0
        self.assertAlmostEqual(np.mean(s['rotor_speed'][tail]), 6.8, delta=0.1)
        self.assertGreater(np.mean(s['pitch'][tail]), 5.0)


if __name__ == '__main__':
    unittest.main()
