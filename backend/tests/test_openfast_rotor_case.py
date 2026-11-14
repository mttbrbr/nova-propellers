"""Rigid-rotor OpenFAST case generated from a Nova rotor; the real solver is used when installed."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app
import numpy as np

from nova.adapters import openfast_structure as structure
from nova.adapters.openfast_case import CaseError, write_case, write_rigid_case
from nova.blocks import engine, templates
from nova.physics import beam_modes, rotors

REAL = Path(os.path.expanduser('~/.local/share/nova-external/openfast/5.0.0/bin/openfast'))


class WriterTests(unittest.TestCase):
    def test_files_and_operating_point(self):
        with tempfile.TemporaryDirectory() as folder:
            info = write_rigid_case({'kind': 'hawt'}, folder, {'duration_s': 2, 'dt_s': 0.05})
            root = Path(folder)
            for name in ('rigid.fst', 'rigid_SED.dat', 'rigid_AeroDyn.dat', 'rigid_InflowWind.dat', 'blade.dat'):
                self.assertTrue((root / name).exists(), name)
            self.assertEqual(len(list((root / 'airfoils').glob('*.dat'))), info['rotor']['stations'])
            self.assertAlmostEqual(info['operating']['tip_speed_ratio'], 7.0, places=6)
            self.assertIn('CompElast', (root / 'rigid.fst').read_text())
            again = write_rigid_case({'kind': 'hawt'}, Path(folder) / 'b', {'duration_s': 2, 'dt_s': 0.05})
            self.assertEqual(info['case_hash'], again['case_hash'])

    def test_rejects_other_families_and_bad_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(CaseError, 'horizontal-axis'):
                write_rigid_case({'kind': 'propeller'}, folder)
            with self.assertRaisesRegex(CaseError, 'dt_s'):
                write_rigid_case({'kind': 'hawt'}, folder, {'dt_s': 0.0})
            with self.assertRaisesRegex(CaseError, 'Unsupported'):
                write_rigid_case({'kind': 'hawt'}, folder, {'bogus': 1})


def example_structure():
    t = templates.TEMPLATES['openfast_flexible_example']
    config = {n['id']: n['config'] for n in t['nodes']}
    return {'hub': structure.hub_record(config['hub']), 'nacelle': structure.nacelle_record(config['nacelle']),
            'tower': structure.tower_record(config['tower']), 'blade': structure.blade_record(config['blade'])}


EXAMPLE_ROTOR = {'kind': 'hawt', 'geometry': {'blades': 3, 'radius_m': 7.49, 'hub_radius_m': 0.28, 'design_tsr': 5.0},
                 'operating': {'velocity_m_s': 10.0, 'rpm': 60.0}}


class ModeTests(unittest.TestCase):
    def test_uniform_cantilever_matches_theory(self):
        length, m, ei = 10.0, 20.0, 5e6
        f, x, shapes = beam_modes.cantilever_modes([0, 1], [m, m], [ei, ei], length, modes=2)
        scale = np.sqrt(ei / (m * length**4)) / (2 * np.pi)
        self.assertAlmostEqual(f[0] / scale, 3.5160, places=3)
        self.assertAlmostEqual(f[1] / scale, 22.0345, places=2)
        f_tip, _, _ = beam_modes.cantilever_modes([0, 1], [m, m], [ei, ei], length, tip_mass_kg=500.0, modes=1)
        self.assertAlmostEqual(f_tip[0], np.sqrt(3 * ei / ((500 + 0.2357 * m * length) * length**3)) / (2 * np.pi), delta=1e-3)

    def test_polynomial_sums_to_one_and_fits(self):
        _, x, shapes = beam_modes.cantilever_modes([0, 1], [20, 20], [5e6, 5e6], 10.0, modes=2)
        coefficients, rms, _ = beam_modes.polynomial_shape(x, shapes[0])
        self.assertAlmostEqual(float(coefficients.sum()), 1.0, places=12)
        self.assertLess(rms, 1e-4)


class StructureTests(unittest.TestCase):
    def test_missing_values_are_named(self):
        with self.assertRaisesRegex(structure.StructureError, r'mass_kg is required.*inertia_kg_m2 is required'):
            structure.hub_record({})
        with self.assertRaisesRegex(structure.StructureError, 'overhang_m is required'):
            structure.nacelle_record({'mass_kg': 1, 'yaw_inertia_kg_m2': 1})
        with self.assertRaisesRegex(structure.StructureError, 'stations needs'):
            structure.blade_record({})
        with self.assertRaisesRegex(structure.StructureError, 'wall_thickness_m'):
            structure.tower_record({'height_m': 20, 'base_diameter_m': 2, 'top_diameter_m': 1})

    def test_tubular_tower_mass_and_stiffness_follow_the_material(self):
        record = structure.tower_record({'height_m': 20, 'base_diameter_m': 2.0, 'top_diameter_m': 1.0, 'wall_thickness_m': 0.02})
        x, mass, fa, ss = record['stations'][0]
        area = np.pi / 4 * (2.0**2 - 1.96**2)
        self.assertAlmostEqual(mass, 7850 * area, places=6)
        self.assertAlmostEqual(fa, 2.1e11 * np.pi / 64 * (2.0**4 - 1.96**4), delta=1.0)

    def test_flexible_case_needs_every_part(self):
        parts = example_structure()
        parts['tower'] = None
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(CaseError, 'also needs: Tower'):
                write_case(EXAMPLE_ROTOR, folder, {}, parts)

    def test_flexible_case_files_and_time_step(self):
        with tempfile.TemporaryDirectory() as folder:
            info = write_case(EXAMPLE_ROTOR, folder, {'duration_s': 2, 'dt_s': 0.05}, example_structure())
            root = Path(folder)
            for name in ('flex.fst', 'flex_ElastoDyn.dat', 'flex_ElastoDyn_blade.dat', 'flex_ElastoDyn_tower.dat'):
                self.assertTrue((root / name).exists(), name)
            self.assertIn('1   CompElast', (root / 'flex.fst').read_text())
            self.assertLess(info['settings']['dt_s'], 0.05)
            self.assertTrue(any('Time step reduced' in a for a in info['assumptions']))
            self.assertAlmostEqual(info['frequencies_hz']['tower_fa1'], 1.647, places=2)


class SpanSectionTests(unittest.TestCase):
    def test_equal_sections_reproduce_the_single_section(self):
        name = {'name': 'Wind turbine 21% (synthetic)'}
        single = rotors.analyze({'kind': 'hawt'})['performance']['power_w']
        spanned = rotors.analyze({'kind': 'hawt', 'sections': [{'r_over_R': 0.2, 'section': name}, {'r_over_R': 1.0, 'section': name}]})
        self.assertAlmostEqual(spanned['performance']['power_w'], single, places=6)

    def test_different_sections_change_the_result_and_are_reported(self):
        spec = {'kind': 'hawt', 'sections': [{'r_over_R': 0.2, 'section': {'name': 'NACA 0021'}},
                                             {'r_over_R': 0.6, 'section': {'name': 'Wind turbine 21% (synthetic)'}},
                                             {'r_over_R': 1.0, 'section': {'name': 'NACA 0012'}}]}
        result = rotors.analyze(spec)
        self.assertNotAlmostEqual(result['performance']['power_w'], rotors.analyze({'kind': 'hawt'})['performance']['power_w'], places=0)
        self.assertEqual([s['name'] for s in result['section']['span']], ['NACA 0021', 'Wind turbine 21% (synthetic)', 'NACA 0012'])

    def test_resolved_inflow_with_dynamic_stall_and_rotational_corrections(self):
        name = {'name': 'Wind turbine 21% (synthetic)'}
        for augmentation in ('snel', 'du_selig'):
            base = {'kind': 'hawt', 'inflow': {'resolved': True, 'yaw_deg': 15, 'shear_exponent': 0.14, 'hub_height_m': 10, 'azimuth_steps': 12},
                    'corrections': {'tip_loss': 'prandtl', 'hub_loss': 'prandtl', 'high_induction': 'buhl', 'rotational_augmentation': augmentation,
                                    'compressibility': 'none', 'dynamic_stall': 'oye'}}
            single = rotors.analyze(base)['performance']['power_w']
            spanned = rotors.analyze({**base, 'sections': [{'r_over_R': 0.2, 'section': name}, {'r_over_R': 1.0, 'section': name}]})
            self.assertAlmostEqual(spanned['performance']['power_w'], single, places=6, msg=augmentation)

    def test_propeller_accepts_sections(self):
        spec = {'kind': 'propeller', 'sections': [{'r_over_R': 0.2, 'section': {'name': 'NACA 4412'}}, {'r_over_R': 1.0, 'section': {'name': 'NACA 2412'}}]}
        self.assertEqual(rotors.analyze(spec)['section']['name'], 'NACA 4412 → NACA 2412')

    def test_rejections(self):
        with self.assertRaisesRegex(ValueError, 'wind turbines and propellers'):
            rotors.analyze({'kind': 'vawt', 'sections': [{'r_over_R': 0, 'section': {'name': 'NACA 0018'}}, {'r_over_R': 1, 'section': {'name': 'NACA 0018'}}]})
        with self.assertRaisesRegex(ValueError, 'increase strictly'):
            rotors.analyze({'kind': 'hawt', 'sections': [{'r_over_R': 0.8, 'section': {'name': 'NACA 0012'}}, {'r_over_R': 0.3, 'section': {'name': 'NACA 0012'}}]})
        with self.assertRaisesRegex(ValueError, 'at least two|2–20'):
            rotors.analyze({'kind': 'hawt', 'sections': [{'r_over_R': 0.5, 'section': {'name': 'NACA 0012'}}]})

    def test_openfast_files_carry_each_stations_blended_polar(self):
        spec = {'kind': 'hawt', 'sections': [{'r_over_R': 0.2, 'section': {'name': 'NACA 0021'}}, {'r_over_R': 1.0, 'section': {'name': 'NACA 0012'}}]}
        with tempfile.TemporaryDirectory() as folder:
            write_rigid_case(spec, folder, {'duration_s': 1, 'dt_s': 0.05})
            first = (Path(folder) / 'airfoils/station_01.dat').read_text()
            last = (Path(folder) / 'airfoils/station_24.dat').read_text()
            self.assertNotEqual(first.split('NumAlf')[1], last.split('NumAlf')[1])


class BlockTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = patch.object(database, 'DB_PATH', Path(self.directory.name) / 'library.sqlite')
        self.db.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db.stop()
        self.directory.cleanup()

    def workflow(self):
        t = templates.TEMPLATES['openfast_rigid_vs_bemt']
        return {'schema_version': 2, 'kind': 'blocks', 'name': 't', 'nodes': t['nodes'], 'edges': t['edges']}

    def test_case_block_without_solver(self):
        flow = self.workflow()
        flow['nodes'] = [n for n in flow['nodes'] if n['id'] in ('rotor', 'operating', 'case')]
        flow['edges'] = [e for e in flow['edges'] if e['target'] in ('operating', 'case')]
        result = engine.execute(flow)
        out = result['blocks']['case']
        self.assertEqual(out['status'], 'succeeded', out)
        self.assertTrue((Path(out['outputs']['case']['case_directory']) / 'rigid.fst').exists())
        self.assertGreater(out['outputs']['reference']['nova_power_w'], 0)

    @unittest.skipUnless(REAL.exists(), 'OpenFAST 5.0.0 is not installed')
    def test_real_openfast_agrees_with_bemt(self):
        response = self.client.post('/api/v1/adapters/openfast/configure', json={'executable': str(REAL), 'environment_kind': 'local_executable'})
        self.assertEqual(response.status_code, 200, response.text)
        result = engine.execute(self.workflow())
        self.assertEqual(result['blocks']['run']['status'], 'succeeded', result['blocks']['run'])
        values = result['blocks']['difference']['outputs']['values']
        for key in ('power_difference_pct', 'thrust_difference_pct', 'torque_difference_pct'):
            self.assertLess(abs(values[key]), 5.0, (key, values))

    def test_structure_blocks_report_their_own_missing_values(self):
        flow = {'schema_version': 2, 'kind': 'blocks', 'name': 't', 'nodes': [{'id': 'hub', 'type': 'hub', 'config': {}}], 'edges': []}
        result = engine.execute(flow)
        self.assertEqual(result['blocks']['hub']['status'], 'failed')
        self.assertIn('mass_kg is required', result['blocks']['hub']['error'])

    def test_flexible_template_builds_and_reports_modes(self):
        t = templates.TEMPLATES['openfast_flexible_example']
        flow = {'schema_version': 2, 'kind': 'blocks', 'name': 't', 'nodes': [n for n in t['nodes'] if n['id'] != 'run' and n['id'] not in ('limits', 'report')],
                'edges': [e for e in t['edges'] if e['target'] in ('operating', 'case')]}
        result = engine.execute(flow)
        reference = result['blocks']['case']['outputs']['reference']
        self.assertAlmostEqual(reference['nova_tower_fa1_hz'], 1.647, places=2)

    @unittest.skipUnless(REAL.exists(), 'OpenFAST 5.0.0 is not installed')
    def test_real_openfast_flexible_case(self):
        response = self.client.post('/api/v1/adapters/openfast/configure', json={'executable': str(REAL), 'environment_kind': 'local_executable'})
        self.assertEqual(response.status_code, 200, response.text)
        t = templates.TEMPLATES['openfast_flexible_example']
        nodes = [dict(n) for n in t['nodes'] if n['id'] not in ('limits', 'report')]
        for n in nodes:
            if n['id'] == 'case':
                n['config'] = {**n['config'], 'duration_s': 12.0}
            if n['id'] == 'run':
                n['config'] = {**n['config'], 'start_time_s': 8.0}
        flow = {'schema_version': 2, 'kind': 'blocks', 'name': 't', 'nodes': nodes,
                'edges': [e for e in t['edges'] if e['target'] in ('operating', 'case', 'run')]}
        result = engine.execute(flow)
        self.assertEqual(result['blocks']['run']['status'], 'succeeded', result['blocks']['run'])
        values, reference = result['blocks']['run']['outputs']['values'], result['blocks']['case']['outputs']['reference']
        self.assertLess(abs(values['power_w'] / reference['nova_power_w'] - 1), 0.08)
        self.assertGreater(values['tip_flap_m_max'], 0.0)
        self.assertGreater(values['tower_base_knm_max'], 100.0)


if __name__ == '__main__':
    unittest.main()
