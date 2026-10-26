import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import test_api_contract
from fastapi.testclient import TestClient

import database
from inverse_design import BEMTSolver, GeometryData
from main import app
from nova.core.data import Port, convert
from nova.core.polars import PolarProvider, parse_polar
from nova.infrastructure import library
from nova.workflow.engine import NumericalFailure, clone, execute, template, validate
from polar_database import ALPHA_GRID, REYNOLDS_GRID, build_seed_table


def demo():
    table = build_seed_table('NACA 4412')
    return {'airfoil': 'NACA 4412', 'mach': .03, 'ncrit': 9., 'demonstration': True,
            'points': [{'reynolds': float(re), 'mach': .03, 'ncrit': 9., 'alpha_deg': float(a),
                        'cl': float(table['cl'][i, j]), 'cd': float(table['cd'][i, j]), 'cm': 0.}
                       for i, re in enumerate(REYNOLDS_GRID) for j, a in enumerate(ALPHA_GRID)]}


class WorkflowTests(unittest.TestCase):
    def test_service_import_does_not_initialize_fastapi(self):
        result = subprocess.run([sys.executable, '-c',
            "from nova.application.analysis import run_propeller_analysis; import sys; assert 'main' not in sys.modules"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_semantic_units_cannot_confuse_efficiencies(self):
        self.assertEqual(convert(250, Port('length', 'mm'), Port('length', 'm')), .25)
        with self.assertRaises(ValueError):
            convert(.7, Port('figure_of_merit', 'dimensionless'), Port('propulsive_efficiency', 'dimensionless'))

    def test_import_and_irregular_slice_interpolation(self):
        points = parse_polar('reynolds,alpha_deg,cl,cd\n100000,0,1,.02\n100000,10,3,.04\n200000,0,2,.03\n200000,5,3,.04\n200000,10,4,.05\n')
        provider = PolarProvider(points, .03, 9.)
        cl, cd = provider(np.array([5.]), np.array([100000.]))
        self.assertAlmostEqual(cl[0], 2.)
        self.assertAlmostEqual(cd[0], .03)
        high_cl, _ = provider(np.array([5.]), np.array([200000.]))
        self.assertAlmostEqual(high_cl[0], 3.)
        self.assertEqual(provider.context(5., 100000.)['reynolds_segment'], [100000., 100000.])
        with self.assertRaises(ValueError):
            parse_polar('reynolds,alpha_deg,cl,cd\n100000,0,nan,.01\n100000,5,1,.02\n')
        xfoil = parse_polar('Mach = 0.03 Re = 0.100 e 6 Ncrit = 9\n alpha CL CD CDp CM\n ----- ---- ---- ---- ----\n 0 .2 .01 .005 -.02\n 5 .7 .02 .01 -.03', 'xfoil')
        self.assertEqual(xfoil[0]['reynolds'], 100000)
        self.assertEqual(xfoil[1]['cm'], -.03)

    def test_graph_validation_and_independent_clone(self):
        original = template()
        customized = clone(original)
        customized['nodes'][3]['config']['model'] = 'llt'
        self.assertEqual(original['nodes'][3]['config']['model'], 'bemt')
        self.assertTrue(validate(customized)['guided_compatible'])
        invalid_budget = copy.deepcopy(customized)
        invalid_budget['nodes'][3]['config']['max_iterations'] = 2.5
        with self.assertRaises(ValueError):
            validate(invalid_budget)
        broken = copy.deepcopy(original)
        broken['edges'][0]['source'] = 'sizing'
        with self.assertRaisesRegex(ValueError, 'cycle'):
            validate(broken)
        broken = copy.deepcopy(original)
        broken['edges'][-1]['source_port'] = 'geometry'
        with self.assertRaisesRegex(ValueError, 'Incompatible'):
            validate(broken)

    def test_workflow_matches_direct_solver_and_keeps_failed_diagnostics(self):
        inputs = test_api_contract.ApiContractTests.geometry_payload()
        result = execute(template(), inputs, demo())
        geometry = GeometryData.from_dict(result['geometry'])
        direct = BEMTSolver(polar_provider=PolarProvider(demo()['points'], .03, 9.)).evaluate(geometry, inputs['rpm'])
        self.assertAlmostEqual(result['analyses'][0]['performance']['thrust_n'], direct['thrust'], places=10)
        failed = template()
        failed['nodes'][3]['config']['max_iterations'] = 1
        with self.assertRaises(NumericalFailure) as raised:
            execute(failed, inputs, demo())
        self.assertFalse(raised.exception.result['convergence']['converged'])
        with self.assertRaises(ValueError):
            execute(template(), inputs, None)
        branch = clone(template())
        branch['nodes'].append({'id': 'second_analysis', 'type': 'analysis', 'config': {'model': 'llt'}})
        branch['edges'].append({'source': 'geometry', 'source_port': 'geometry', 'target': 'second_analysis', 'target_port': 'geometry'})
        self.assertFalse(validate(branch)['guided_compatible'])
        compared = execute(branch, inputs, demo())
        self.assertEqual({r['node_id'] for r in compared['analyses']}, {'analysis', 'second_analysis'})
        self.assertEqual(compared['analyses'][1]['operating_point']['axial_velocity_m_s'], 0)
        wrong = demo()
        wrong['airfoil'] = 'NACA 0012'
        with self.assertRaises(ValueError):
            execute(template(), inputs, wrong)
        with self.assertRaises(ValueError):
            execute(template(), inputs, demo(), {'axial_velocity_m_s': 10})

    def test_library_assets_are_immutable_and_archive_checksum_is_checked(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'):
            library.initialize()
            asset = library.make_asset(demo())
            with self.assertRaises(ValueError):
                library.save('asset', demo(), asset['id'])
            project = library.save('project', {'inputs': {}, 'workflow': template(), 'polar_asset_id': asset['id']})
            archive = library.export_project(project['id'])
            self.assertEqual(library.read_archive(archive)['assets'][0]['content_hash'], asset['content_hash'])
            broken = io.BytesIO()
            with zipfile.ZipFile(broken, 'w') as z:
                z.writestr('manifest.json', json.dumps({'schema_version': 1, 'sha256': 'wrong'}))
                z.writestr('project.json', '{}')
            with self.assertRaises(ValueError):
                library.read_archive(broken.getvalue())

    def test_geometry_rejects_nonfinite_and_nonintegral_values(self):
        with self.assertRaises(ValueError):
            GeometryData(np.array([.01, .02, .03, .04]), np.array([.01, .01, np.nan, .01]), np.zeros(4), .1, 2)
        with self.assertRaises(ValueError):
            GeometryData(np.array([.01, .02, .03, .04]), np.ones(4)*.01, np.zeros(4), .1, 2.5)


class DesktopWorkflowJourney(unittest.TestCase):
    def test_http_project_run_archive_reopen_cancel_and_auth(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            asset = client.post('/api/v1/assets/demonstration-polar', json={'airfoil': 'NACA 4412'}).json()
            payload = {'name': 'Round trip', 'inputs': test_api_contract.ApiContractTests.geometry_payload(), 'workflow': template(),
                       'polar_asset_id': asset['id'], 'conditions': {}}
            response = client.post('/api/v1/projects', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            project = response.json()
            payload.update(id=project['id'], expected_revision=project['revision'])
            response = client.post('/api/v1/runs', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            run = self.wait(client, response.json()['id'])
            self.assertEqual(run['state'], 'succeeded', run)
            self.assertTrue(run['result']['analyses'][0]['convergence']['converged'])
            self.assertGreater(len(client.get(f"/api/v1/runs/{run['id']}/stl").content), 1000)
            self.assertIn('thrust_N', client.get(f"/api/v1/runs/{run['id']}/results.csv").text)
            archive = client.get(f"/api/v1/projects/{project['id']}/archive").content
            import base64
            response = client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(archive).decode()})
            self.assertEqual(response.status_code, 200, response.text)
            imported = response.json()
            self.assertNotEqual(imported['id'], project['id'])
            reopened = client.get(f"/api/v1/projects/{imported['id']}").json()
            self.assertEqual(reopened['inputs'], project['inputs'])
            malformed = library.read_archive(archive)
            malformed['project']['asset_ids'] = ['missing-asset']
            raw = json.dumps(malformed).encode()
            import hashlib
            invalid_archive = io.BytesIO()
            with zipfile.ZipFile(invalid_archive, 'w') as z:
                z.writestr('project.json', raw)
                z.writestr('manifest.json', json.dumps({'schema_version': 1, 'sha256': hashlib.sha256(raw).hexdigest()}))
            before = len(client.get('/api/v1/assets').json())
            rejected = client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(invalid_archive.getvalue()).decode()})
            self.assertEqual(rejected.status_code, 422, rejected.text)
            self.assertEqual(len(client.get('/api/v1/assets').json()), before)
            self.assertEqual(client.post('/api/v1/workflows/validate', json={'schema_version': 1, 'nodes': [None]}).status_code, 422)
            slow = copy.deepcopy(payload)
            slow['workflow']['nodes'][3]['config'].update(max_iterations=10000, tolerance=1e-30)
            pending = client.post('/api/v1/runs', json=slow).json()
            client.post(f"/api/v1/runs/{pending['id']}/cancel")
            self.assertEqual(self.wait(client, pending['id'])['state'], 'cancelled')
            with patch.dict(os.environ, {'NOVA_SESSION_TOKEN': 'test-session'}):
                self.assertEqual(client.get('/api/v1/projects').status_code, 401)
                self.assertEqual(client.get('/api/v1/projects', headers={'X-Nova-Session': 'test-session'}).status_code, 200)
                self.assertEqual(client.get('/api/health').status_code, 200)

    def wait(self, client, id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run = client.get(f'/api/v1/runs/{id}').json()
            if run['state'] not in ('queued', 'running', 'cancelling'):
                return run
            time.sleep(.05)
        self.fail('Worker did not finish within the small-case test budget')
