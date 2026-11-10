import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app


class RotorSimulationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = patch.object(database, 'DB_PATH', Path(self.directory.name) / 'library.sqlite')
        self.db.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.project = self.post('/api/v2/projects', {'name': 'Wind farm rotor'})

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db.stop()
        self.directory.cleanup()

    def post(self, path, body, status=200):
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def save(self, spec, **extra):
        return self.post('/api/v2/simulations', {'project_id': self.project['id'], 'name': 'Rotor', 'kind': 'rotor',
                                                 'configuration': {'spec': spec}, **extra})

    def test_rotor_simulation_saves_runs_and_reopens(self):
        saved = self.save({'kind': 'hawt', 'curve': {'start': 2, 'stop': 10, 'points': 9}})
        self.assertEqual(saved['kind'], 'rotor')
        self.assertEqual(saved['configuration']['spec']['geometry']['blades'], 3)
        run = self.post(f'/api/v2/simulations/{saved["id"]}/run', {'expected_revision': saved['revision']})
        self.assertEqual(run['state'], 'succeeded', run.get('error'))
        self.assertEqual(run['simulation_kind'], 'rotor')
        self.assertEqual(len(run['result']['curve']['rows']), 9)
        self.assertGreater(run['result']['analysis']['coefficients']['CP'], 0.3)
        runs = self.client.get(f'/api/v2/projects/{self.project["id"]}/runs').json()
        self.assertEqual([r['id'] for r in runs], [run['id']])
        listed = self.client.get(f'/api/v2/projects/{self.project["id"]}/simulations').json()
        self.assertEqual(listed[0]['configuration']['spec']['kind'], 'hawt')
        revised = self.save({'kind': 'hawt', 'geometry': {'radius_m': 6.0}}, id=saved['id'], expected_revision=saved['revision'])
        self.assertEqual(revised['revision'], 2)

    def test_family_cannot_change_and_invalid_specs_are_rejected(self):
        saved = self.save({'kind': 'vawt'})
        self.post('/api/v2/simulations', {'project_id': self.project['id'], 'name': 'Rotor', 'kind': 'propeller',
                                          'configuration': {}, 'id': saved['id'], 'expected_revision': 1}, 422)
        self.post('/api/v2/simulations', {'project_id': self.project['id'], 'name': 'Bad', 'kind': 'rotor',
                                          'configuration': {'spec': {'kind': 'vawt', 'corrections': {'tip_loss': 'prandtl'}}}}, 422)
        self.post('/api/v2/simulations', {'project_id': self.project['id'], 'name': 'Bad', 'kind': 'rotor',
                                          'configuration': {'spec': {'kind': 'helicopter'}}}, 422)
        self.post('/api/v2/simulations', {'project_id': self.project['id'], 'name': 'Bad', 'kind': 'rotor',
                                          'configuration': {'spec': {'kind': 'hawt', 'curve': {'start': 5, 'stop': 1}}}}, 422)

    def test_archive_round_trip_keeps_rotor_simulations_and_runs(self):
        saved = self.save({'kind': 'marine'})
        run = self.post(f'/api/v2/simulations/{saved["id"]}/run', {})
        self.assertEqual(run['state'], 'succeeded')
        archive = self.client.get(f'/api/v2/projects/{self.project["id"]}/archive')
        self.assertEqual(archive.status_code, 200, archive.text)
        import base64
        restored = self.post('/api/v2/projects/import', {'content_base64': base64.b64encode(archive.content).decode()})
        simulations = self.client.get(f'/api/v2/projects/{restored["id"]}/simulations').json()
        self.assertEqual([s['kind'] for s in simulations], ['rotor'])
        runs = self.client.get(f'/api/v2/projects/{restored["id"]}/runs').json()
        self.assertEqual(runs[0]['result']['rotor_kind'], 'marine')


if __name__ == '__main__':
    unittest.main()
