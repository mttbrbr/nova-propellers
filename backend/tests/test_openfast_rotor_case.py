"""Rigid-rotor OpenFAST case generated from a Nova rotor; the real solver is used when installed."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app
from nova.adapters.openfast_case import CaseError, write_rigid_case
from nova.blocks import engine, templates

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


if __name__ == '__main__':
    unittest.main()
