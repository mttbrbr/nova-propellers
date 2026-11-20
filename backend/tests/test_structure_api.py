"""Structure workspace API: data per version, structural run on a chosen aerodynamic run."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app
from nova.physics import rotors


class StructureApi(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = patch.object(database, 'DB_PATH', Path(self.directory.name) / 'library.sqlite')
        self.db.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.project = self.post('/api/v2/projects', {'name': 'Structure'})

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db.stop()
        self.directory.cleanup()

    def post(self, path, body, method='post'):
        response = getattr(self.client, method)(path, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def rotor(self, kind):
        spec = rotors.merged({'kind': kind})
        simulation = self.post('/api/v2/simulations', {'project_id': self.project['id'], 'name': kind, 'kind': 'rotor',
                                                      'configuration': {'spec': spec}})
        run = self.post(f"/api/v2/simulations/{simulation['id']}/run", {'expected_revision': simulation['revision']})
        return simulation, run

    def test_hawt_with_tower_gives_coupled_campbell(self):
        simulation, aero = self.rotor('hawt')
        base = self.client.get(f"/api/v2/simulations/{simulation['id']}/structure").json()
        self.assertIsNone(base['revision'])
        self.assertIn('tower', base['config'])
        config = base['config']
        config['hub'] = {'mass_kg': 120.0, 'inertia_kg_m2': 8.0}
        config['nacelle'] = {'mass_kg': 600.0, 'yaw_inertia_kg_m2': 300.0, 'overhang_m': -0.8, 'tower_top_to_shaft_m': 0.5}
        config['tower'].update(height_m=20.0, base_diameter_m=0.8, top_diameter_m=0.5, wall_thickness_m=0.008)
        saved = self.post(f"/api/v2/simulations/{simulation['id']}/structure", {'config': config}, method='put')
        self.assertEqual(saved['revision'], 1)
        run = self.post(f"/api/v2/simulations/{simulation['id']}/structure/runs", {'aero_run_id': aero['id']})
        result = run['result']
        self.assertEqual(result['campbell']['campbell']['coupling'], 'mbc')
        for key in ('blade_mass_kg', 'first_flap_hz', 'first_tower_hz', 'min_margin_pct', 'tip_deflection_m', 'cp_loss_pct'):
            self.assertIsNotNone(result['metrics'].get(key), key)
        self.assertTrue(result['curve']['rows'])
        self.assertIn('overhang_m', result['layout'])
        listed = self.client.get(f"/api/v2/simulations/{simulation['id']}/structure/runs").json()
        self.assertEqual([r['id'] for r in listed], [run['id']])

    def test_propeller_is_blade_only(self):
        simulation, aero = self.rotor('propeller')
        config = self.client.get(f"/api/v2/simulations/{simulation['id']}/structure").json()['config']
        self.assertNotIn('tower', config)
        self.assertEqual(config['blade']['layup']['construction'], 'solid')
        run = self.post(f"/api/v2/simulations/{simulation['id']}/structure/runs", {'aero_run_id': aero['id']})
        result = run['result']
        self.assertEqual(result['campbell']['campbell'].get('coupling', 'none'), 'none')
        self.assertNotIn('aeroelastic', result)
        self.assertGreater(result['metrics']['tip_deflection_m'], 0)

    def test_run_of_another_simulation_is_refused(self):
        first, _ = self.rotor('hawt')
        _, other = self.rotor('hawt')
        response = self.client.post(f"/api/v2/simulations/{first['id']}/structure/runs", json={'aero_run_id': other['id']})
        self.assertEqual(response.status_code, 422)


if __name__ == '__main__':
    unittest.main()
