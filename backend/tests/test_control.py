"""Phase 6: signal-based control simulation, rotor plant and FMU wrapper."""
import copy
import math
import sys
import types
import unittest

import numpy as np

from nova.blocks import control as control_blocks
from nova.blocks import engine
from nova.physics import control, rotors


def _pi_loop(plant):
    return [{'element': 'source', 'output': 'r', 'kind': 'constant', 'value': 1.0},
            {'element': 'pid', 'output': 'u', 'measurement': 'y', 'setpoint': 'r', 'kp': 1.0, 'ki': 1.0}, plant]


class Loops(unittest.TestCase):
    def test_pi_on_first_order_plant(self):
        """PI kp = ki = 1 on 1/(s+1): the loop transfer is 1/s, so y(t) = 1 − e^{−t}."""
        t, s = control.simulate(_pi_loop({'element': 'transfer_function', 'input': 'u', 'output': 'y', 'numerator': [1.0],
                                          'denominator': [1.0, 1.0]}), duration=3.0, dt=1e-3, initial={'y': 0.0})
        for time in (0.5, 1.0, 2.0):
            self.assertAlmostEqual(np.interp(time, t, s['y']), 1 - math.exp(-time), delta=3e-3)

    def test_state_space_matches_transfer_function(self):
        tf = control.simulate(_pi_loop({'element': 'transfer_function', 'input': 'u', 'output': 'y', 'numerator': [2.0],
                                        'denominator': [1.0, 3.0, 2.0]}), duration=4.0, dt=5e-3, initial={'y': 0.0})[1]['y']
        ss = control.simulate(_pi_loop({'element': 'state_space', 'inputs': ['u'], 'outputs': ['y'], 'A': [[0.0, 1.0], [-2.0, -3.0]],
                                        'B': [[0.0], [1.0]], 'C': [[2.0, 0.0]], 'D': [[0.0]]}), duration=4.0, dt=5e-3, initial={'y': 0.0})[1]['y']
        np.testing.assert_allclose(tf, ss, atol=1e-9)

    def test_saturation_and_anti_windup(self):
        loop = _pi_loop({'element': 'transfer_function', 'input': 'u', 'output': 'y', 'numerator': [1.0], 'denominator': [1.0, 1.0]})
        loop[1].update(max=0.5)
        t, s = control.simulate(loop, duration=10.0, dt=1e-2, initial={'y': 0.0})
        self.assertLessEqual(s['u'].max(), 0.5)
        self.assertAlmostEqual(s['y'][-1], 0.5, delta=1e-2)

    def test_unknown_signal(self):
        with self.assertRaises(control.ControlError):
            control.simulate([{'element': 'lookup', 'input': 'missing', 'output': 'z', 'breakpoints': [0, 1], 'values': [0, 1]}],
                             duration=1.0, dt=0.1)


class RotorPlant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = rotors.merged({'kind': 'hawt'})
        cls.plant = control_blocks.rotor_dynamics({'config': {'inertia_kg_m2': 300.0, 'initial_rpm': 70.0}}, {'spec': cls.spec})
        cls.cp_max, cls.lam_opt = control_blocks._optimum(cls.spec)

    def _run(self, elements, duration, dt=0.01):
        return control.simulate(elements, duration=duration, dt=dt, initial={'gen_torque': 0.0, 'pitch': 0.0})

    def test_torque_law_tracks_optimal_tsr(self):
        law = control_blocks.torque_law({'config': {}}, {'spec': self.spec})
        elements = [{'element': 'source', 'output': 'wind_speed', 'kind': 'constant', 'value': 7.0}, *law['dynamics'],
                    *self.plant['dynamics']]
        t, s = self._run(elements, 120.0)
        self.assertAlmostEqual(s['tsr'][-1], self.lam_opt, delta=0.03 * self.lam_opt)
        cp = s['power'][-1] / (0.5 * 1.225 * math.pi * 25 * 7.0**3)
        self.assertAlmostEqual(cp, self.cp_max, delta=0.01)

    def test_pitch_controller_holds_rated_speed(self):
        rated_speed = 12.0  # rad/s
        torque = 1800.0
        elements = [{'element': 'source', 'output': 'wind_speed', 'kind': 'step', 'value': 11.0, 'amplitude': 3.0, 'time': 20.0},
                    {'element': 'source', 'output': 'gen_torque', 'kind': 'constant', 'value': torque},
                    {'element': 'pid', 'output': 'pitch', 'measurement': 'rotor_speed', 'setpoint': rated_speed, 'kp': 4.0, 'ki': 1.5,
                     'min': 0.0, 'max': 30.0, 'reverse': True},
                    *control_blocks.rotor_dynamics({'config': {'inertia_kg_m2': 300.0, 'initial_rpm': 115.0}}, {'spec': self.spec})['dynamics']]
        t, s = self._run(elements, 90.0)
        self.assertAlmostEqual(s['rotor_speed'][-1], rated_speed, delta=0.02 * rated_speed)
        self.assertGreater(s['pitch'][-1], 0.5)


class FakeFmu(unittest.TestCase):
    def test_fmu_element_with_stand_in_fmpy(self):
        """Gain FMU y = 2u through the FMPy calls the wrapper uses."""
        state = {}

        class Slave:
            def __init__(self, **kwargs):
                state['args'] = kwargs

            def instantiate(self):
                pass

            def setupExperiment(self, startTime):
                pass

            def enterInitializationMode(self):
                pass

            def exitInitializationMode(self):
                pass

            def setReal(self, refs, values):
                state.update(dict(zip(refs, values)))

            def doStep(self, currentCommunicationPoint, communicationStepSize):
                state[2] = state[3] * state[1]

            def getReal(self, refs):
                return [state[r] for r in refs]

            def terminate(self):
                state['terminated'] = True

            def freeInstance(self):
                pass
        description = types.SimpleNamespace(coSimulation=types.SimpleNamespace(modelIdentifier='gain'), guid='g',
                                            modelVariables=[types.SimpleNamespace(name=n, valueReference=r) for n, r in (('u', 1), ('y', 2), ('k', 3))])
        fmpy = types.ModuleType('fmpy')
        fmpy.extract = lambda path: '/tmp/fmu'
        fmpy.read_model_description = lambda path: description
        fmi2 = types.ModuleType('fmpy.fmi2')
        fmi2.FMU2Slave = Slave
        saved = {k: sys.modules.get(k) for k in ('fmpy', 'fmpy.fmi2')}
        sys.modules.update({'fmpy': fmpy, 'fmpy.fmi2': fmi2})
        try:
            t, s = control.simulate([{'element': 'source', 'output': 'a', 'kind': 'constant', 'value': 3.0},
                                     {'element': 'fmu', 'path': 'gain.fmu', 'inputs': {'a': 'u'}, 'outputs': {'b': 'y'}, 'parameters': {'k': 2.0}}],
                                    duration=0.2, dt=0.1)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        np.testing.assert_allclose(s['b'], 6.0)
        self.assertTrue(state['terminated'])


class Workflow(unittest.TestCase):
    def test_variable_speed_turbine_workflow(self):
        rotor = copy.deepcopy(engine.BLOCKS['rotor_hawt']['defaults'])
        nodes = [{'id': 'rotor', 'type': 'rotor_hawt', 'config': rotor},
                 {'id': 'op', 'type': 'operating_point', 'config': {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 7.0, 'tip_speed_ratio': 5.0}}},
                 {'id': 'wind', 'type': 'control_source', 'config': {'output': 'wind_speed', 'kind': 'ramp', 'value': 6.0, 'amplitude': 2.0,
                                                                     'time': 10.0, 'end_time': 30.0}},
                 {'id': 'law', 'type': 'torque_law', 'config': {}},
                 {'id': 'plant', 'type': 'rotor_dynamics', 'config': {'inertia_kg_m2': 300.0, 'tsr_grid': [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
                                                                      'pitch_grid': [0.0, 10.0]}},
                 {'id': 'sim', 'type': 'control_simulation', 'config': {'duration_s': 60.0, 'dt_s': 0.02, 'initial': {'pitch': 0.0},
                                                                        'statistics_from_s': 40.0}}]
        edges = [{'source': 'rotor', 'source_port': 'spec', 'target': 'op', 'target_port': 'spec'},
                 {'source': 'wind', 'source_port': 'dynamics', 'target': 'law', 'target_port': 'dynamics'},
                 {'source': 'op', 'source_port': 'spec', 'target': 'law', 'target_port': 'spec'},
                 {'source': 'law', 'source_port': 'dynamics', 'target': 'plant', 'target_port': 'dynamics'},
                 {'source': 'op', 'source_port': 'spec', 'target': 'plant', 'target_port': 'spec'},
                 {'source': 'plant', 'source_port': 'dynamics', 'target': 'sim', 'target_port': 'dynamics'}]
        result = engine.execute({'schema_version': 2, 'kind': 'blocks', 'name': 'ctrl', 'nodes': nodes, 'edges': edges})
        self.assertEqual(result['status'], 'succeeded', {k: v.get('error') for k, v in result['blocks'].items()})
        values = result['blocks']['sim']['outputs']['values']
        self.assertGreater(values['power_mean'], 0.0)
        self.assertLess(values['rotor_speed_std'], 0.05 * values['rotor_speed_mean'])


if __name__ == '__main__':
    unittest.main()
