import os
import sys
import tempfile
import unittest

import numpy as np
from scipy.linalg import expm
from scipy.optimize import brentq

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nova.adapters import openfast_structure as structure  # noqa: E402
from nova.adapters.openfast_case import write_case  # noqa: E402
from nova.blocks import engine, templates  # noqa: E402
from nova.physics import modal  # noqa: E402


def unit_beam(**fields):
    # L = m = EI = 1, so ω (rad/s) is the non-dimensional frequency
    values = {'mass': [1.0, 1.0], 'ei_out': [1.0, 1.0], 'ei_in': [1.0, 1.0]}
    values.update({k: [v, v] if np.isscalar(v) else v for k, v in fields.items()})
    return modal.Beam(modal.Sections([0, 1], **values), 1.0)


def omegas(modes):
    return [m['natural_hz'] * 2 * np.pi for m in modes]


def family(beam, name, count, **kwargs):
    return omegas(modal.pick(modal.solve(beam, **kwargs), {name: count})[name])


def timoshenko_cantilever(ei, ga, m, rotary, length, guess):
    """Exact Timoshenko cantilever frequency nearest `guess` from the transfer matrix of the uniform beam."""
    def determinant(w):
        A = np.array([[0, 1, 0, 1 / ga], [0, 0, 1 / ei, 0], [0, -rotary * w**2, 0, -1], [-m * w**2, 0, 0, 0]])
        T = expm(A * length)
        return np.linalg.det(T[2:, 2:])  # w = ψ = 0 at the root, M = Q = 0 at the tip
    grid = np.linspace(0.6 * guess, 1.4 * guess, 400)
    values = [determinant(w) for w in grid]
    i = next(i for i in range(len(grid) - 1) if np.sign(values[i]) != np.sign(values[i + 1]))
    return brentq(determinant, grid[i], grid[i + 1])


class BeamTests(unittest.TestCase):
    def test_euler_bernoulli_limit(self):
        beam = unit_beam()
        for name in ('flap', 'edge'):
            for got, beta in zip(family(beam, name, 3), (1.875104, 4.694091, 7.854757)):
                self.assertAlmostEqual(got, beta**2, delta=2e-4 * beta**2)

    def test_rotating_beam_matches_wright_1982(self):
        reference = {1: 3.6816, 2: 4.1373, 3: 4.7973, 4: 5.5850, 5: 6.4495}
        beam = unit_beam()
        for speed, expected in reference.items():
            self.assertAlmostEqual(family(beam, 'flap', 1, omega=speed)[0], expected, delta=3e-4 * expected)

    def test_spin_softening_and_coriolis(self):
        rigid = unit_beam()
        flap, edge = family(rigid, 'flap', 2, omega=3.0), family(rigid, 'edge', 2, omega=3.0)
        for f, e in zip(flap, edge):
            self.assertAlmostEqual(e**2, f**2 - 9.0, delta=1e-3 * f**2)
        modes = modal.solve(unit_beam(ea=50.0), omega=3.0)
        edge_soft = omegas(modal.pick(modes, {'edge': 1})['edge'])[0]
        self.assertLess(edge_soft, edge[0])  # Coriolis coupling with axial stretch lowers the edge frequency
        self.assertTrue(all(abs(m['damping_ratio']) < 1e-8 for m in modes[:6]))  # gyroscopic: no damping

    def test_timoshenko_shear_and_rotary_inertia(self):
        ga, rotary = 40.0, 0.004
        beam = unit_beam(ga_out=ga, i_out=rotary)
        for got, beta in zip(family(beam, 'flap', 3), (1.875104, 4.694091, 7.854757)):
            exact = timoshenko_cantilever(1.0, ga, 1.0, rotary, 1.0, 0.9 * beta**2)
            self.assertLess(got, beta**2)
            self.assertAlmostEqual(got, exact, delta=1e-4 * exact)

    def test_uniform_torsion(self):
        beam = unit_beam(gj=1.0, i_torsion=1.0)
        for got, k in zip(family(beam, 'torsion', 2), (1, 3)):
            self.assertAlmostEqual(got, k * np.pi / 2, delta=1e-5)

    def test_propeller_moment_stiffens_torsion(self):
        beam = unit_beam(gj=1.0, i_torsion=0.01, i_in=0.01)  # thin section with its chord in the rotor plane
        still = family(beam, 'torsion', 1)[0]
        spinning = family(beam, 'torsion', 1, omega=2.0)[0]
        self.assertAlmostEqual(spinning**2, still**2 + 4.0, delta=1e-3 * spinning**2)

    def test_constant_twist_rotates_principal_axes_only(self):
        straight = sorted(m['natural_hz'] for m in modal.solve(unit_beam(ei_in=[4.0, 4.0]))[:6])
        twisted = sorted(m['natural_hz'] for m in modal.solve(unit_beam(ei_in=[4.0, 4.0], twist_deg=30.0))[:6])
        np.testing.assert_allclose(twisted, straight, rtol=1e-5)
        varying = sorted(m['natural_hz'] for m in modal.solve(unit_beam(ei_in=[4.0, 4.0], twist_deg=[0.0, 60.0]))[:6])
        self.assertGreater(np.max(np.abs(np.array(varying) - straight)), 1e-3)

    def test_mass_offset_couples_flap_and_torsion(self):
        aligned = modal.solve(unit_beam(gj=1.0, i_torsion=0.01))
        offset = modal.solve(unit_beam(gj=1.0, i_torsion=0.01, cm_in=0.05))
        self.assertLess(aligned[0]['participation']['torsion'], 1e-10)
        flap = modal.pick(offset, {'flap': 1})['flap'][0]
        self.assertGreater(flap['participation']['torsion'], 1e-4)

    def test_tip_mass_matches_characteristic_equation(self):
        ratio = 1.0

        def characteristic(b):
            return (1 + np.cos(b) * np.cosh(b)) + ratio * b * (np.cos(b) * np.sinh(b) - np.sin(b) * np.cosh(b))

        beta = brentq(characteristic, 0.5, 1.8)
        beam = unit_beam()
        beam.add_body(1.0, mass=ratio)
        self.assertAlmostEqual(family(beam, 'flap', 1)[0], beta**2, delta=2e-4 * beta**2)

    def test_stiff_spring_pins_the_tip(self):
        beam = unit_beam()
        beam.add_spring(1.0, stiffness=(0, 0, 1e9, 0, 0, 0))
        self.assertAlmostEqual(family(beam, 'flap', 1)[0], 3.926602**2, delta=1e-3 * 3.926602**2)
        self.assertAlmostEqual(family(beam, 'edge', 1)[0], 1.875104**2, delta=1e-3)

    def test_point_mass_across_element_boundary_is_continuous(self):
        values = []
        for position in (0.5 - 1e-9, 0.5, 0.5 + 1e-9):
            beam = unit_beam()
            beam.add_body(position, mass=0.3)
            values.append(family(beam, 'flap', 1)[0])
        self.assertAlmostEqual(values[0], values[1], places=5)
        self.assertAlmostEqual(values[1], values[2], places=5)

    def test_modal_damping_ratio_is_kept(self):
        for m in modal.pick(modal.solve(unit_beam(), damping={'flap': 0.02, 'edge': 0.01}), {'flap': 2, 'edge': 2})['flap']:
            self.assertAlmostEqual(m['damping_ratio'], 0.02)
            self.assertAlmostEqual(m['frequency_hz'], m['natural_hz'] * np.sqrt(1 - 0.02**2))

    def test_discrete_damper_matches_modal_estimate(self):
        c = 0.05
        beam = unit_beam(ei_in=[4.0, 4.0])  # distinct flap and edge frequencies
        first = modal.pick(modal.solve(beam), {'flap': 1})['flap'][0]
        expected = c * abs(first['q'][-4]) ** 2 / (2 * first['natural_hz'] * 2 * np.pi)  # tip u3 of the mass-normalised mode
        beam.add_spring(1.0, damping=(0, 0, c, 0, 0, 0))
        damped = modal.pick(modal.solve(beam), {'flap': 1})['flap'][0]
        self.assertAlmostEqual(damped['damping_ratio'], expected, delta=0.02 * expected)

    def test_shapes_and_nodes(self):
        beam = unit_beam()
        flap = modal.pick(modal.solve(beam), {'flap': 3})['flap']
        views = [modal.describe(beam, m) for m in flap]
        self.assertEqual([v['nodes'] for v in views], [0, 1, 2])
        for v in views:
            self.assertAlmostEqual(np.max(np.abs(v['shape'])), 1.0, places=5)
            self.assertEqual(v['shape'][0], 0.0)
            self.assertGreater(v['shape'][-1], 0)
            self.assertEqual(len(v['components']['edge']), modal.SHAPE_POINTS)

    def test_tracking_restores_swapped_modes(self):
        found = modal.solve(unit_beam(ei_in=[3.0, 3.0]))[:3]
        ordered, similarity = modal.track(found, [found[2], found[0], found[1]])
        self.assertEqual([m['natural_hz'] for m in ordered], [m['natural_hz'] for m in found])
        self.assertTrue(all(s > 0.999 for s in similarity))

    def test_rejects_bad_input(self):
        with self.assertRaises(modal.ModalError):
            unit_beam(mass=[1, -1])
        with self.assertRaises(modal.ModalError):
            unit_beam(gj=1.0)  # torsional stiffness without torsional inertia
        with self.assertRaises(modal.ModalError):
            unit_beam().add_body(1.5, mass=1)


class CampbellTests(unittest.TestCase):
    blade = {'stations': [[0, 1.0, 1.0, 4.0], [1, 1.0, 1.0, 4.0]], 'extended': {}, 'tip_mass_kg': 0.0,
             'flap_damping_pct': 0.0, 'edge_damping_pct': 0.0}

    def test_crossings_lie_on_excitation_lines(self):
        result = modal.campbell(self.blade, 1.0, 0.0, 3, np.linspace(0, 60, 31), counts={'flap': 2, 'edge': 1})
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
        result = modal.campbell(self.blade, 1.0, 0.0, 3, [0.0, 10.0, 20.0], counts={'flap': 1})
        values, worst, at = modal.margins(result, 10.0)
        f = values['blade_flap1']
        self.assertAlmostEqual(worst, min(abs(f - h * 10 / 60) / (h * 10 / 60) * 100 for h in (1, 3, 6)))
        self.assertIn('blade_flap1', at)
        whirl = modal.whirl(result['curves'][0], result['rpm'])
        self.assertAlmostEqual(whirl['forward'][1] - whirl['backward'][1], 2 * 10 / 60)

    def test_rejects_bad_speeds(self):
        with self.assertRaises(modal.ModalError):
            modal.campbell(self.blade, 1.0, 0.0, 3, [10.0, 5.0])


class RecordTests(unittest.TestCase):
    rows = [{'span_fraction': 0.0, 'mass_per_length_kg_m': 10, 'flap_stiffness_nm2': 1e6, 'edge_stiffness_nm2': 3e6},
            {'span_fraction': 1.0, 'mass_per_length_kg_m': 5, 'flap_stiffness_nm2': 1e5, 'edge_stiffness_nm2': 4e5}]

    def test_optional_columns(self):
        rows = [{**r, 'torsional_stiffness_nm2': 1e5, 'torsional_inertia_kg_m': 0.5} for r in self.rows]
        record = structure.blade_record({'stations': rows})
        self.assertEqual(record['extended']['torsional_stiffness_nm2'], [1e5, 1e5])
        with self.assertRaisesRegex(structure.StructureError, 'every station or at none'):
            structure.blade_record({'stations': [{**self.rows[0], 'cm_offset_m': 0.1}, self.rows[1]]})
        with self.assertRaisesRegex(structure.StructureError, 'needs torsional_inertia_kg_m'):
            structure.blade_record({'stations': [{**r, 'torsional_stiffness_nm2': 1e5} for r in self.rows]})
        with self.assertRaisesRegex(structure.StructureError, 'unsupported columns'):
            structure.blade_record({'stations': [{**r, 'bogus': 1} for r in self.rows]})

    def test_tubular_tower_has_full_properties(self):
        record = structure.tower_record({'height_m': 20, 'base_diameter_m': 2.0, 'top_diameter_m': 1.0, 'wall_thickness_m': 0.02})
        self.assertEqual(set(record['extended']), set(structure.TOWER_OPTIONAL))
        beam = modal.tower_beam(record)
        self.assertIn('torsion', modal.available(beam, 'tower'))


class BlockTests(unittest.TestCase):
    def run_template(self, workflow=None):
        return engine.execute(workflow or templates.template('structural_campbell'))

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
        first = blocks['blade_clamped']['outputs']['modal']['modes'][0]
        self.assertEqual(len(first['shape']), modal.SHAPE_POINTS)
        self.assertIn('torsion', first['components'])
        self.assertTrue(any('torsion' in n for n in blocks['blade_clamped']['outputs']['notes']))

    def test_untwisted_blade_matches_elastodyn_beam(self):
        from tests.test_openfast_rotor_case import EXAMPLE_ROTOR, example_structure
        with tempfile.TemporaryDirectory() as folder:
            info = write_case(EXAMPLE_ROTOR, folder, {'duration_s': 2, 'dt_s': 0.05}, example_structure())
        workflow = templates.template('structural_campbell')
        next(n for n in workflow['nodes'] if n['id'] == 'blade_clamped')['config']['use_aerodynamic_twist'] = False
        values = self.run_template(workflow)['blocks']['blade_clamped']['outputs']['values']
        for key in ('blade_flap1', 'blade_flap2', 'blade_edge1'):
            self.assertAlmostEqual(values[f'{key}_hz'], info['frequencies_hz'][key], delta=2e-3 * values[f'{key}_hz'])

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
        result = self.run_template(workflow)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(result['blocks']['mass']['outputs']['attachments']), 2)
        values = result['blocks']['tower_modes']['outputs']['values']
        self.assertGreater(values['tower_fa1_hz'], base['tower_fa1_hz'])
        rows = result['blocks']['tower_modes']['outputs']['table']['rows']
        self.assertGreater(min(r['damping_ratio'] for r in rows if r['mode'] == 'tower_fa1'), 0.03)

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
        result = self.run_template(workflow)
        self.assertEqual(result['blocks']['blade_clamped']['status'], 'failed')
        self.assertIn('length_m', result['blocks']['blade_clamped']['error'])


if __name__ == '__main__':
    unittest.main()
