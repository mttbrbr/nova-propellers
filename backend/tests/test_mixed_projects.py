import base64
import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import test_api_contract
from test_pywake_adapter import case as wind_case

import database
from main import app
from nova.infrastructure import library
from nova.workflow.engine import template


class MixedProjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.db = patch.object(database, 'DB_PATH', self.root / 'library.sqlite')
        self.db.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.project = self.post('/api/v2/projects', {'name': 'Mixed engineering'})

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db.stop()
        self.directory.cleanup()

    def post(self, path, body):
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save(self, kind, configuration, **extra):
        return self.post('/api/v2/simulations', {'project_id': self.project['id'], 'name': kind,
                                                'kind': kind, 'configuration': configuration, **extra})

    def openfast(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'main.fst').write_text('"blade.dat" BldFile\n')
        (source / 'blade.dat').write_text('user supplied scientific data\n')
        (source / 'stale.out').write_text('old results')
        return {'case_directory': str(source), 'input_file': 'main.fst',
                'output_file': 'main.out', 'timeout_seconds': 15}

    def test_three_kinds_reopen_clone_conflicts_and_native_compatibility(self):
        graph = template()
        graph['nodes'][3]['config']['model'] = 'llt'
        native = self.save('propeller', {'inputs': test_api_contract.ApiContractTests.geometry_payload(), 'workflow': graph, 'conditions': {}})
        wind = self.save('pywake', {'case': wind_case(), 'demonstration': True})
        turbine = self.save('openfast', {'case': self.openfast()})
        self.assertEqual(native['configuration']['geometry_id'], native['geometry_id'])
        self.assertNotIn('case_directory', turbine['configuration']['case'])
        configurations = self.client.get(f"/api/v2/projects/{self.project['id']}/simulations").json()
        self.assertEqual({item['kind'] for item in configurations}, {'propeller', 'pywake', 'openfast'})
        self.assertEqual(self.client.get('/api/v1/projects').json(), [])
        self.assertEqual(len(self.client.get(f"/api/v1/projects/{self.project['id']}/simulations").json()), 1)
        self.assertEqual(self.client.get(f"/api/v1/simulations/{wind['id']}").status_code, 422)
        clone = self.post(f"/api/v2/simulations/{turbine['id']}/clone", {})
        self.assertEqual(clone['asset_id'], turbine['asset_id'])
        assets_before = library.list_records('asset')
        response = self.client.post('/api/v2/simulations', json={'name': 'stale', 'project_id': self.project['id'],
            'id': wind['id'], 'expected_revision': 0, 'kind': 'pywake', 'configuration': {'case': wind_case()}})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(library.list_records('asset'), assets_before)
        self.assertEqual(self.client.post(f"/api/v2/simulations/{wind['id']}/run", json={'expected_revision': 9}).status_code, 409)
        with patch('nova.transport.mixed_api.run_native', return_value={'native': True}) as execute:
            self.assertEqual(self.post(f"/api/v2/simulations/{native['id']}/run", {'expected_revision': 1}), {'native': True})
            execute.assert_called_once()

    def test_saved_openfast_runs_after_source_removed_and_historical_association_is_immutable(self):
        original = self.openfast()
        turbine = self.save('openfast', {'case': original})
        shutil.rmtree(original['case_directory'])
        installation = library.save('integration', {'adapter_id': 'openfast', 'executable': '/external/openfast',
            'environment_kind': 'local_executable', 'options': {}})
        with patch('nova.transport.mixed_api.jobs.submit', side_effect=lambda document: document):
            run = self.post(f"/api/v2/simulations/{turbine['id']}/run", {'expected_revision': 1, 'integration_id': installation['id']})
        self.assertEqual(run['simulation_revision'], 1)
        self.assertEqual((Path(run['inputs']['case_directory']) / 'blade.dat').read_text(), 'user supplied scientific data\n')
        self.assertFalse((Path(run['inputs']['case_directory']) / 'stale.out').exists())
        historical = library.save('run', {'project_id': None, 'state': 'succeeded', 'name': 'Prior execution'})
        self.post(f"/api/v2/projects/{self.project['id']}/runs", {'run_id': historical['id']})
        self.post(f"/api/v2/projects/{self.project['id']}/runs", {'run_id': historical['id']})
        self.assertEqual(library.get('run', historical['id']), historical)
        self.assertEqual(len(library.list_records('run_link')), 1)
        self.assertEqual(self.client.get(f"/api/v2/projects/{self.project['id']}/runs").json(), [historical])

    def test_mixed_archive_portable_roundtrip_and_old_archive_import(self):
        graph = template()
        graph['nodes'][3]['config']['model'] = 'llt'
        native = self.save('propeller', {'inputs': test_api_contract.ApiContractTests.geometry_payload(), 'workflow': graph})
        self.save('pywake', {'case': wind_case()})
        self.save('openfast', {'case': self.openfast()})
        response = self.client.get(f"/api/v2/projects/{self.project['id']}/archive")
        self.assertEqual(response.status_code, 200, response.text)
        imported = self.post('/api/v2/projects/import', {'content_base64': base64.b64encode(response.content).decode()})
        sims = self.client.get(f"/api/v2/projects/{imported['id']}/simulations").json()
        self.assertEqual(len(sims), 3)
        self.assertNotEqual(next(s for s in sims if s['kind'] == 'propeller')['id'], native['id'])
        legacy = self.post('/api/v1/projects', {'name': 'Legacy', 'inputs': test_api_contract.ApiContractTests.geometry_payload(), 'workflow': graph})
        archive = self.client.get(f"/api/v1/projects/{legacy['id']}/archive").content
        restored = self.post('/api/v2/projects/import', {'content_base64': base64.b64encode(archive).decode()})
        self.assertEqual(restored['inputs'], legacy['inputs'])

    def test_case_revision_and_portable_executable_rejection(self):
        case = self.openfast()
        first = self.save('openfast', {'case': case})
        original_asset = library.get('asset', first['asset_id'])
        (Path(case['case_directory']) / 'blade.dat').write_text('edited data')
        second = self.save('openfast', {'case': case}, id=first['id'], expected_revision=1)
        self.assertNotEqual(first['asset_id'], second['asset_id'])
        self.assertEqual(library.get('asset', first['asset_id']), original_asset)
        (Path(case['case_directory']) / 'controller.so').write_bytes(b'\x7fELFfixture')
        response = self.client.post('/api/v2/simulations', json={'project_id': self.project['id'], 'name': 'bad',
            'kind': 'openfast', 'configuration': {'case': case}})
        self.assertEqual(response.status_code, 422)
        invalid = copy.deepcopy(second['configuration'])
        invalid['case']['timeout_seconds'] = 30
        response = self.client.post('/api/v2/simulations', json={'project_id': self.project['id'], 'name': 'bad',
            'kind': 'openfast', 'configuration': invalid})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotEqual(response.json()['asset_id'], second['asset_id'])
        self.assertEqual(library.get('asset', second['asset_id'])['case']['timeout_seconds'], 15)
