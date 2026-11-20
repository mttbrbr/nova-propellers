import os
import sys
import unittest

import numpy as np
from scipy.linalg import eigh
from scipy.optimize import brentq

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nova.blocks import engine, templates  # noqa: E402
from nova.physics import beam_modes, modal  # noqa: E402


def unit_beam():
    # L = m = EI = 1, so ω (rad/s) is the non-dimensional frequency
    return modal.Beam([0, 1], [1.0, 1.0], [1.0, 1.0], 1.0)


def omegas(found):
    return [m['natural_hz'] * 2 * np.pi for m in found]


class BeamTests(unittest.TestCase):
    def test_clamped_beam_matches_theory(self):
        w = omegas(modal.modes(unit_beam(), modes=3))
        for got, beta in zip(w, (1.875104, 4.694091, 7.854757)):
            self.assertAlmostEqual(got, beta**2, delta=1e-4 * beta**2)

    def test_rotating_beam_matches_wright_1982(self):
        # Uniform cantilever, no hub offset; first flap frequency against non-dimensional rotor speed.
        reference = {1: 3.6816, 2: 4.1373, 3: 4.7973, 4: 5.5850, 5: 6.4495}
        beam = unit_beam()
        for speed, expected in reference.items():
            got = omegas(modal.modes(beam, modes=1, omega=speed))[0]
            self.assertAlmostEqual(got, expected, delta=2e-4 * expected)

    def test_edgewise_spin_softening(self):
        beam = unit_beam()
        flap = omegas(modal.modes(beam, modes=2, omega=3.0, direction='flap'))
        edge = omegas(modal.modes(beam, modes=2, omega=3.0, direction='edge'))
        for f, e in zip(flap, edge):
            self.assertAlmostEqual(e**2, f**2 - 9.0, delta=1e-6 * f**2)

    def test_hub_offset_stiffens_more(self):
        beam = unit_beam()
        bare = modal.modes(beam, modes=1, omega=3.0)[0]['natural_hz']
        offset = modal.modes(beam, modes=1, omega=3.0, hub_radius=0.5)[0]['natural_hz']
        self.assertGreater(offset, bare)

    def test_tip_mass_matches_characteristic_equation(self):
        ratio = 1.0  # tip mass / beam mass

        def characteristic(b):
            return (1 + np.cos(b) * np.cosh(b)) + ratio * b * (np.cos(b) * np.sinh(b) - np.sin(b) * np.cosh(b))

        beta = brentq(characteristic, 0.5, 1.8)
        beam = unit_beam()
        beam.add_point(1.0, mass=ratio)
        self.assertAlmostEqual(omegas(modal.modes(beam, modes=1))[0], beta**2, delta=1e-4 * beta**2)
        f, _, _ = beam_modes.cantilever_modes([0, 1], [1, 1], [1, 1], 1.0, tip_mass_kg=ratio, modes=1)
        self.assertAlmostEqual(f[0] * 2 * np.pi, beta**2, delta=1e-4 * beta**2)

    def test_stiff_spring_pins_the_tip(self):
        beam = unit_beam()
        beam.add_point(1.0, stiffness=1e9)
        self.assertAlmostEqual(omegas(modal.modes(beam, modes=1))[0], 3.926602**2, delta=1e-3 * 3.926602**2)

    def test_point_mass_between_nodes_is_continuous(self):
        values = []
        for position in (0.5, 0.5 + 1e-9, 0.5 + 0.5 / modal.ELEMENTS):
            beam = unit_beam()
            beam.add_point(position, mass=0.3)
            values.append(modal.modes(beam, modes=1)[0]['natural_hz'])
        self.assertAlmostEqual(values[0], values[1], places=6)
        self.assertLess(abs(values[2] - values[0]) / values[0], 1e-2)

    def test_modal_damping_ratio_is_kept(self):
        found = modal.modes(unit_beam(), modes=2, damping_ratio=0.02)
        for m in found:
            self.assertAlmostEqual(m['damping_ratio'], 0.02)
            self.assertAlmostEqual(m['frequency_hz'], m['natural_hz'] * np.sqrt(1 - 0.02**2))

    def test_discrete_damper_matches_modal_estimate(self):
        c = 0.05
        beam = unit_beam()
        free = slice(2, beam.K.shape[0])
        lam, phi = eigh(beam.K[free, free], beam.M[free, free])
        expected = c * phi[-2, 0] ** 2 / (2 * np.sqrt(lam[0]))  # tip translation of the mass-normalised first mode
        beam.add_point(1.0, damping=c)
        found = modal.modes(beam, modes=1)
        self.assertAlmostEqual(found[0]['damping_ratio'], expected, delta=0.02 * expected)

    def test_mode_shapes_and_nodes(self):
        found = modal.modes(unit_beam(), modes=3)
        self.assertEqual([m['nodes'] for m in found], [0, 1, 2])
        for m in found:
            self.assertAlmostEqual(np.max(np.abs(m['shape'])), 1.0)
            self.assertEqual(m['shape'][0], 0.0)

    def test_tracking_restores_swapped_modes(self):
        found = modal.modes(unit_beam(), modes=3)
        ordered, similarity = modal.track(found, [found[2], found[0], found[1]])
        self.assertEqual([m['label'] for m in ordered], [m['label'] for m in found])
        self.assertTrue(all(s > 0.999 for s in similarity))

    def test_rejects_bad_input(self):
        with self.assertRaises(modal.ModalError):
            modal.Beam([0, 1], [1, -1], [1, 1], 1.0)
        with self.assertRaises(modal.ModalError):
            modal.modes(unit_beam(), modes=0)
        with self.assertRaises(modal.ModalError):
            unit_beam().add_point(1.5, mass=1)


class CampbellTests(unittest.TestCase):
    blade = {'stations': [[0, 1.0, 1.0, 4.0], [1, 1.0, 1.0, 4.0]], 'tip_mass_kg': 0.0, 'flap_damping_pct': 0.0, 'edge_damping_pct': 0.0}

    def test_crossings_lie_on_excitation_lines(self):
        result = modal.campbell(self.blade, 1.0, 0.0, 3, np.linspace(0, 60, 61), flap_modes=2, edge_modes=1)
        self.assertEqual(result['harmonics'], [1, 3, 6])
        self.assertTrue(result['crossings'])
        for c in result['crossings']:
            h = int(c['harmonic'][:-1])
            self.assertAlmostEqual(c['frequency_hz'], h * c['rpm'] / 60, delta=0.02 * c['frequency_hz'])
        for curve in result['curves']:
            self.assertGreater(curve['tracking_mac_min'], 0.99)
        flap = next(c for c in result['curves'] if c['id'] == 'blade_flap1')
        self.assertTrue(np.all(np.diff(flap['frequency_hz']) > 0))

    def test_margin_and_whirl(self):
        result = modal.campbell(self.blade, 1.0, 0.0, 3, [0.0, 10.0, 20.0], flap_modes=1, edge_modes=0)
        values, worst, at = modal.margins(result, 10.0)
        f = values['blade_flap1']
        expected = min(abs(f - h * 10 / 60) / (h * 10 / 60) * 100 for h in (1, 3, 6))
        self.assertAlmostEqual(worst, expected)
        self.assertIn('blade_flap1', at)
        whirl = modal.whirl(result['curves'][0], result['rpm'])
        self.assertAlmostEqual(whirl['forward'][1] - whirl['backward'][1], 2 * 10 / 60)

    def test_rejects_bad_speeds(self):
        with self.assertRaises(modal.ModalError):
            modal.campbell(self.blade, 1.0, 0.0, 3, [10.0, 5.0])


class BlockTests(unittest.TestCase):
    def run_template(self):
        return engine.execute(templates.template('structural_campbell'))

    def test_template_runs(self):
        result = self.run_template()
        self.assertEqual(result['status'], 'succeeded')
        blocks = result['blocks']
        clamped = blocks['blade_clamped']['outputs']['values']
        rotating = blocks['blade_rotating']['outputs']['values']
        self.assertGreater(rotating['blade_flap1_hz'], clamped['blade_flap1_hz'])
        tower = blocks['tower_modes']['outputs']['values']
        campbell = blocks['campbell']['outputs']['values']
        self.assertAlmostEqual(tower['tower_fa1_hz'], campbell['tower_fa1_hz'], places=9)
        self.assertAlmostEqual(campbell['blade_flap1_hz'], rotating['blade_flap1_hz'], places=3)
        self.assertEqual(campbell['operating_rpm'], 60.0)
        self.assertGreater(campbell['min_excitation_margin_pct'], 0)
        modal_out = blocks['campbell']['outputs']['modal']
        self.assertEqual(len(modal_out['campbell']['rpm']), 41)
        self.assertIn('fixed_frame', modal_out['campbell']['curves'][0])
        self.assertEqual(len(blocks['blade_clamped']['outputs']['modal']['modes'][0]['shape']), modal.SHAPE_POINTS)

    def test_tower_frequencies_match_openfast_case(self):
        import tempfile

        from nova.adapters.openfast_case import write_case
        from tests.test_openfast_rotor_case import EXAMPLE_ROTOR, example_structure
        with tempfile.TemporaryDirectory() as folder:
            info = write_case(EXAMPLE_ROTOR, folder, {'duration_s': 2, 'dt_s': 0.05}, example_structure())
        values = self.run_template()['blocks']['blade_clamped']['outputs']['values']
        self.assertAlmostEqual(values['blade_flap1_hz'], info['frequencies_hz']['blade_flap1'], delta=1e-3 * values['blade_flap1_hz'])

    def test_chained_attachments_change_tower_modes(self):
        workflow = templates.template('structural_campbell')
        workflow['nodes'] += [
            {'id': 'guy', 'type': 'spring_damper', 'config': {'target': 'tower', 'position': 0.8, 'stiffness_n_m': 2e6, 'damping_ns_m': 2e4},
             'position': {'x': 0, 'y': 0}},
            {'id': 'mass', 'type': 'point_mass', 'config': {'target': 'tower', 'position': 0.5, 'mass_kg': 500.0},
             'position': {'x': 0, 'y': 0}}]
        workflow['edges'] += [{'source': 'guy', 'source_port': 'attachments', 'target': 'mass', 'target_port': 'attachments'},
                              {'source': 'mass', 'source_port': 'attachments', 'target': 'tower_modes', 'target_port': 'attachments'}]
        base = self.run_template()['blocks']['tower_modes']['outputs']['values']
        result = engine.execute(workflow)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(result['blocks']['mass']['outputs']['attachments']), 2)
        values = result['blocks']['tower_modes']['outputs']['values']
        self.assertGreater(values['tower_fa1_hz'], base['tower_fa1_hz'])
        damping = [r['damping_ratio'] for r in result['blocks']['tower_modes']['outputs']['table']['rows']]
        self.assertGreater(damping[0], 0.03)

    def test_attachment_validation(self):
        node = {'id': 'x', 'type': 'point_mass', 'config': {'target': 'tower', 'direction': 'flap', 'mass_kg': 1.0}}
        with self.assertRaisesRegex(ValueError, 'does not apply'):
            engine.HANDLERS['point_mass'](node, {})
        node['config'] = {'target': 'blade'}
        with self.assertRaisesRegex(ValueError, 'mass or a rotary inertia'):
            engine.HANDLERS['point_mass'](node, {})
        node = {'id': 'y', 'type': 'spring_damper', 'config': {'position': 0.0, 'stiffness_n_m': 1.0}}
        with self.assertRaisesRegex(ValueError, 'clamped end'):
            engine.HANDLERS['spring_damper'](node, {})

    def test_blade_modes_need_a_length(self):
        workflow = templates.template('structural_campbell')
        workflow['edges'] = [e for e in workflow['edges'] if not (e['target'] == 'blade_clamped' and e['target_port'] == 'spec')]
        result = engine.execute(workflow)
        self.assertEqual(result['blocks']['blade_clamped']['status'], 'failed')
        self.assertIn('length_m', result['blocks']['blade_clamped']['error'])


if __name__ == '__main__':
    unittest.main()
