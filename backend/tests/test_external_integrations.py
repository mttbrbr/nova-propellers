"""Transport, persistence and real worker execution for optional integrations."""
import base64
import copy
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_openfast_adapter as openfast_fixtures
from fastapi.testclient import TestClient
from test_openfast_adapter import ASCII, binary
from test_pywake_adapter import case as pywake_case

import database
from main import app
from nova.infrastructure import library
from nova.workflow.engine import execute, external_template, template, validate


class ExternalIntegrationTests(unittest.TestCase):
    def wait(self, client, id):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            run = client.get('/api/v1/runs/' + id).json()
            if run['state'] not in ('queued', 'running', 'cancelling'):
                return run
            time.sleep(.05)
        self.fail('External job timed out')

    def test_external_workflows_have_distinct_ports_and_require_context(self):
        for adapter in ('pywake', 'openfast'):
            graph = external_template(adapter)
            self.assertEqual(validate(graph)['order'], ['case', 'solver'])
            self.assertFalse(validate(graph)['guided_compatible'])
            with self.assertRaisesRegex(ValueError, 'configured integration'):
                execute(graph, {}, None)
        incompatible = external_template('pywake')
        incompatible['nodes'][1]['type'] = 'openfast'
        with self.assertRaises(ValueError):
            validate(incompatible)
        mixed = template()
        mixed['nodes'].append({'id': 'external', 'type': 'pywake', 'config': {}})
        with self.assertRaises(ValueError):
            validate(mixed)

    def test_output_import_preserves_sources_units_csv_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            self.assertTrue({'pywake', 'openfast'} <= {a['id'] for a in client.get('/api/v1/adapters').json()})
            for filename, source in [('wind.out', ASCII), ('wind.outb', binary(4))]:
                response = client.post('/api/v1/openfast/import', json={'filename': filename, 'content_base64': base64.b64encode(source).decode()})
                self.assertEqual(response.status_code, 200, response.text)
                run = response.json()
                self.assertEqual(run['state'], 'succeeded')
                self.assertEqual(run['result']['data']['values'], [[10, -2], [12, -1]])
                raw = client.get(f"/api/v1/external-runs/{run['id']}/artifacts/source/{filename}")
                self.assertEqual(raw.content, source)
                csv = client.get(f"/api/v1/external-runs/{run['id']}/csv")
                self.assertIn('RotorPwr [kW]', csv.text)
                self.assertIn('0.5,12.0,-1.0', csv.text)
                self.assertEqual(client.get(f"/api/v1/external-runs/{run['id']}/artifacts/not-listed").status_code, 404)
                library.initialize()
                self.assertEqual(client.get('/api/v1/runs/' + run['id']).json()['result'], run['result'])
                with self.assertRaises(ValueError):
                    library.save('run', {**run, 'state': 'failed'}, run['id'])
            self.assertEqual(len(client.get('/api/v1/external-runs').json()), 2)
            ids = [r['id'] for r in client.get('/api/v1/external-runs').json()]
            self.assertEqual(client.post('/api/v1/runs/compare', json={'run_ids': ids}).status_code, 422)

    def test_bad_imports_do_not_create_records(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            for filename, content in [('../wind.out', ASCII), ('wind.csv', ASCII), ('wind.out', b'not OpenFAST')]:
                response = client.post('/api/v1/openfast/import', json={'filename': filename, 'content_base64': base64.b64encode(content).decode()})
                self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(client.post('/api/v1/openfast/import', json={'filename': 'wind.out', 'content_base64': '@@'}).status_code, 422)
            self.assertEqual(client.get('/api/v1/external-runs').json(), [])
            self.assertEqual(client.post('/api/v1/external-runs', json={'integration_id': 'missing', 'case': {}}).status_code, 422)

    def configure(self, client, adapter, executable, environment='local_executable'):
        response = client.post(f'/api/v1/adapters/{adapter}/configure', json={'executable': str(executable), 'environment_kind': environment})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_queued_case_uses_frozen_inputs_and_shared_workflow(self):
        fixtures = openfast_fixtures.OpenFASTTests()
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            root = Path(directory)
            case = fixtures.case(root)
            configuration = fixtures.program(root)
            integration = self.configure(client, 'openfast', configuration.executable)
            response = client.post('/api/v1/external-runs', json={'integration_id': integration['id'], 'case': case})
            self.assertEqual(response.status_code, 200, response.text)
            queued = response.json()
            (root / 'inputs/main.fst').write_text('changed after submission')
            frozen = Path(queued['inputs']['case_directory'])
            self.assertEqual((frozen / 'main.fst').read_text(), '"sub/section.dat" AeroFile\n')
            completed = self.wait(client, queued['id'])
            self.assertEqual(completed['state'], 'succeeded', completed)
            self.assertEqual(completed['result']['data']['kind'], 'time_series_result')
            self.assertEqual(completed['workflow'], external_template('openfast'))
            self.assertTrue(completed['logs'])
            self.assertEqual(completed['progress'], 1)
            self.assertEqual(client.get(f"/api/v1/external-runs/{completed['id']}/artifacts/case/main.out").content, ASCII)
            self.assertEqual(client.get(f"/api/v1/external-runs/{completed['id']}/artifacts/workflow.json").json(), completed['workflow'])

    def test_failed_and_cancelled_execution_retain_diagnostics(self):
        fixtures = openfast_fixtures.OpenFASTTests()
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            root = Path(directory)
            case = fixtures.case(root)
            configuration = fixtures.program(root, True)
            integration = self.configure(client, 'openfast', configuration.executable)
            failed = self.wait(client, client.post('/api/v1/external-runs', json={'integration_id': integration['id'], 'case': case}).json()['id'])
            self.assertEqual(failed['state'], 'failed')
            self.assertIn('failure.json', failed['result']['artifacts'])
            self.assertEqual(client.get(f"/api/v1/external-runs/{failed['id']}/artifacts/failure.json").status_code, 200)
            program = configuration.executable
            program.write_text(program.read_text().replace('raise SystemExit(7)', 'import os,time\nprint("solver running " + str(os.getpid()), flush=True)\ntime.sleep(30)'))
            case = {**case, 'timeout_seconds': 60}
            queued = client.post('/api/v1/external-runs', json={'integration_id': integration['id'], 'case': case}).json()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                record = client.get('/api/v1/runs/' + queued['id']).json()
                if any('solver running' in log for log in record['logs']):
                    break
                time.sleep(.05)
            else:
                self.fail('Fixture did not start')
            client.post(f"/api/v1/runs/{queued['id']}/cancel")
            stopped = self.wait(client, queued['id'])
            self.assertEqual(stopped['state'], 'cancelled')
            self.assertTrue(stopped['result']['artifacts'])
            self.assertEqual(stopped['result']['provenance']['state'], 'cancelled')
            pid = int(re.search(r'solver running (\d+)', '\n'.join(record['logs']))[1])
            status = Path(f'/proc/{pid}/stat')
            try:
                self.assertEqual(status.read_text().split()[2], 'Z', 'Cancelled external solver remains alive')
            except FileNotFoundError:
                pass  # A fully reaped process is no longer alive.

    def test_interrupted_submission_preserves_referenced_snapshot(self):
        fixtures = openfast_fixtures.OpenFASTTests()
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            root = Path(directory)
            inputs = fixtures.case(root)
            config = fixtures.program(root)
            integration = self.configure(client, 'openfast', config.executable)
            def interrupted(snapshot):
                library.save('run', {**snapshot, 'state': 'interrupted', 'logs': [], 'progress': 0})
                raise ValueError('Service shut down during submission')
            with patch('nova.transport.external_api.jobs.submit', side_effect=interrupted):
                response = client.post('/api/v1/external-runs', json={'integration_id': integration['id'], 'case': inputs})
            self.assertEqual(response.status_code, 422)
            stored = client.get('/api/v1/external-runs').json()[0]
            self.assertTrue((Path(stored['inputs']['case_directory']) / 'main.fst').is_file())

    @unittest.skipUnless(os.getenv('NOVA_PYWAKE_PYTHON'), 'Separate real PyWake environment not configured')
    def test_pywake_real_queued_job(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            integration = self.configure(client, 'pywake', os.environ['NOVA_PYWAKE_PYTHON'], 'python_environment')
            inputs = copy.deepcopy(pywake_case())
            response = client.post('/api/v1/external-runs', json={'integration_id': integration['id'], 'case': inputs})
            self.assertEqual(response.status_code, 200, response.text)
            completed = self.wait(client, response.json()['id'])
            self.assertEqual(completed['state'], 'succeeded', completed)
            self.assertEqual(completed['result']['data']['kind'], 'wind_farm_result')
            self.assertEqual(completed['result']['provenance']['program']['version'], '2.6.20')
            self.assertIn('power_W', client.get(f"/api/v1/external-runs/{completed['id']}/csv").text)


if __name__ == '__main__':
    unittest.main()
