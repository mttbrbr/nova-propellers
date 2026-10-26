import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_pywake_adapter import case

import database
from main import app
from nova.application.external_cases import MAX_CASE_BYTES, save_case
from nova.core.data import content_hash
from nova.infrastructure import library
from nova.transport.external_case_api import router

if not any(route.path == '/api/v1/external-cases' for route in app.routes):
    app.include_router(router)


class ExternalCaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_patch = patch.object(database, 'DB_PATH', Path(self.directory.name) / 'nova.db')
        self.database_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.database_patch.stop()
        self.directory.cleanup()

    def test_save_copy_load_hash_immutability_without_execution_or_integration(self):
        original = case()
        before = copy.deepcopy(original)
        with patch('nova.adapters.pywake.PyWakeAdapter.probe', side_effect=AssertionError('Must not probe')), \
             patch('nova.adapters.pywake.run_process', side_effect=AssertionError('Must not execute')), \
             patch('subprocess.Popen', side_effect=AssertionError('Must not launch processes')):
            response = self.client.post('/api/v1/external-cases', json={
                'name': 'Synthetic turbine example', 'case': original, 'notes': 'Protocol fixture', 'demonstration': True})
            self.assertEqual(response.status_code, 200, response.text)
            saved = response.json()
            self.assertEqual(saved['case'], before)
            self.assertEqual(saved['case_hash'], content_hash(before))
            self.assertEqual(saved['kind'], 'external_case')
            self.assertEqual(saved['schema_version'], 1)
            self.assertEqual(saved['adapter_id'], 'pywake')
            self.assertEqual(saved['source_origin'], 'user_saved')
            self.assertTrue(saved['demonstration'])
            duplicate = self.client.post('/api/v1/external-cases', json={'name': 'Copied example', 'case': original}).json()
            self.assertNotEqual(duplicate['id'], saved['id'])
            self.assertEqual(duplicate['case_hash'], saved['case_hash'])
            self.assertFalse(duplicate['demonstration'])
            self.assertEqual(self.client.get(f"/api/v1/external-cases/{saved['id']}").json(), saved)
            original['wind']['probabilities'][0][0] = .99
            self.assertEqual(self.client.get(f"/api/v1/external-cases/{saved['id']}").json()['case'], before)
            self.assertEqual(library.list_records('integration'), [])
            self.assertEqual(library.list_records('run'), [])
            with self.assertRaises(ValueError):
                library.save('asset', {**saved, 'name': 'Overwrite'}, saved['id'])
            self.assertEqual(self.client.post('/api/v1/external-cases', json={'id': saved['id'], 'name': 'Update', 'case': before}).status_code, 422)
            self.assertEqual(self.client.get(f"/api/v1/external-cases/{saved['id']}").json(), saved)

    def test_reject_invalid_scientific_data_and_unknown_local_configuration(self):
        invalid_cases = []
        probabilities = case()
        probabilities['wind']['probabilities'] = [[.1, .1], [.1, .1]]
        invalid_cases.append(probabilities)
        duplicates = case()
        duplicates['layout']['x_m'] = [0, 0]
        invalid_cases.append(duplicates)
        unknown = case()
        unknown['executable'] = '/private/python'
        invalid_cases.append(unknown)
        overflow = case()
        overflow['turbine']['diameter_m'] = 10**400
        invalid_cases.append(overflow)
        invalid_cases.extend([{'turbine': []}, {**case(), 'wake_model': 'other'}])
        for invalid in invalid_cases:
            with self.subTest(case=invalid):
                response = self.client.post('/api/v1/external-cases', json={'name': 'Invalid', 'case': invalid})
                self.assertEqual(response.status_code, 422, response.text)
        for extra in ({'integration_id': 'machine-local'}, {'executable': '/private/python'}, {'adapter_id': 'openfast'}, {'source_origin': '/private/path'}, {'demonstration': 'yes'}):
            with self.subTest(extra=extra):
                self.assertEqual(self.client.post('/api/v1/external-cases', json={'name': 'Invalid', 'case': case(), **extra}).status_code, 422)
        self.assertEqual(self.client.post('/api/v1/external-cases', json={'name': '   ', 'case': case()}).status_code, 422)
        self.assertEqual(self.client.post('/api/v1/external-cases', json={'name': 'Invalid', 'case': case(), 'notes': 'x'*801}).status_code, 422)
        self.assertEqual(library.list_records('asset'), [])
        with self.assertRaises(ValueError):
            save_case('Oversized', {'unexpected': 'x' * MAX_CASE_BYTES})

    def test_list_and_detail_filter_unrelated_assets(self):
        other = library.make_asset({'kind': 'polar_family', 'label': 'Not a reusable case'})
        future = library.make_asset({'kind': 'external_case', 'adapter_id': 'other'})
        response = self.client.post('/api/v1/external-cases', json={'name': 'Reusable layout', 'case': case()})
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(self.client.get('/api/v1/external-cases').json(), [saved])
        for id in (other['id'], future['id'], 'absent'):
            self.assertEqual(self.client.get(f'/api/v1/external-cases/{id}').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/assets').status_code, 200)
        self.assertEqual(len(self.client.get('/api/v1/assets').json()), 3)


if __name__ == '__main__':
    unittest.main()
