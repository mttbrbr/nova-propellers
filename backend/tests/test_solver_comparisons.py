import base64
import copy
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_project_simulations as fixtures

from nova.application.comparisons import comparison_rows, execute_comparison, fingerprint, scientific_polar_hash
from nova.infrastructure import jobs, library
from nova.transport.simulation_api import ComparisonRequest, frozen_comparison


class SolverComparisonTests(unittest.TestCase):
    setUp = fixtures.ProjectSimulationTests.setUp
    tearDown = fixtures.ProjectSimulationTests.tearDown
    save = fixtures.ProjectSimulationTests.save
    edit_payload = fixtures.ProjectSimulationTests.edit_payload
    archive_request = fixtures.ProjectSimulationTests.archive_request

    def selection(self, *simulations):
        return {'name': 'BEMT versus LLT', 'simulations': [{'id': s['id'], 'expected_revision': s['revision']} for s in simulations]}

    def endpoint(self, suffix=''):
        return f"/api/v1/projects/{self.project['id']}/comparisons" + suffix

    def wait(self, record):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            record = self.client.get(f"/api/v1/runs/{record['id']}").json()
            if record['state'] not in ('queued', 'running', 'cancelling'):
                return record
            time.sleep(.05)
        self.fail('Small comparison exceeded test budget')

    def test_compare_saved_models_frozen_provenance_differences_and_archive(self):
        a, b = self.save(), self.save('LLT variant', 'llt')
        # An unused but recorded polar on the second source must survive only in batch history.
        secondary_asset = self.client.post('/api/v1/assets/demonstration-polar', json={'airfoil': 'NACA 4412'}).json()
        edit = self.edit_payload(b)
        edit['polar_asset_id'] = secondary_asset['id']
        b = self.client.post('/api/v1/simulations', json=edit).json()
        selection = self.selection(a, b)
        validation = self.client.post(self.endpoint('/validate'), json=selection)
        self.assertEqual(validation.status_code, 200, validation.text)
        self.assertTrue(validation.json()['warnings'])
        response = self.client.post(self.endpoint(), json=selection)
        self.assertEqual(response.status_code, 200, response.text)
        # Renaming after queueing must not mutate any frozen captions or inputs.
        edit = self.edit_payload(b)
        edit['name'] = 'Later renamed LLT'
        self.assertEqual(self.client.post('/api/v1/simulations', json=edit).status_code, 200)
        run = self.wait(response.json())
        self.assertEqual(run['state'], 'succeeded', run.get('error'))
        self.assertEqual(run['result']['comparison_status'], 'succeeded')
        self.assertEqual(len(run['result']['cases']), 2)
        rows = run['result']['rows']
        self.assertEqual([r['model'] for r in rows], ['bemt', 'llt'])
        self.assertEqual(rows[1]['simulation_name'], 'LLT variant')
        self.assertAlmostEqual(rows[1]['baseline_differences_pct']['thrust_n'],
                               100*(rows[1]['thrust_n']-rows[0]['thrust_n'])/abs(rows[0]['thrust_n']))
        self.assertEqual(rows[0]['baseline_differences_pct']['power_w'], 0)
        self.assertEqual(run['comparison']['simulations'][1]['revision'], b['revision'])
        self.assertEqual(self.client.get(f"/api/v1/projects/{self.project['id']}").json(), self.project)
        csv = self.client.get(f"/api/v1/runs/{run['id']}/comparison.csv")
        self.assertEqual(csv.status_code, 200)
        self.assertIn('baseline_differences_pct', csv.text)
        with self.assertRaises(ValueError):
            library.save('run', run, run['id'])
        latest = self.client.get(f"/api/v1/simulations/{b['id']}").json()
        edit = self.edit_payload(latest)
        edit['polar_asset_id'] = self.asset['id']
        self.client.post('/api/v1/simulations', json=edit)
        archive = library.export_project(self.project['id'])
        self.assertIn(secondary_asset['id'], {asset['id'] for asset in library.read_archive(archive)['assets']})
        imported = self.client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(archive).decode()})
        self.assertEqual(imported.status_code, 200, imported.text)
        new_run = next(r for r in library.list_records('run') if r.get('project_id') == imported.json()['id'])
        self.assertNotEqual(new_run['comparison']['simulations'][0]['id'], a['id'])
        self.assertEqual(new_run['result']['rows'][0]['simulation_id'], new_run['comparison']['simulations'][0]['id'])
        self.assertEqual(new_run['result']['rows'][1]['thrust_n'], rows[1]['thrust_n'])
        second = library.export_project(imported.json()['id'])
        self.assertEqual(self.client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(second).decode()}).status_code, 200)

    def test_reject_mismatches_stale_complex_and_atomic_submission_race(self):
        a, b = self.save(), self.save('LLT', 'llt')
        for field, value in [('rpm', 5500), ('diameter', .27), ('thrust_target', 3)]:
            edit = self.edit_payload(b)
            edit['inputs'] = copy.deepcopy(edit['inputs'])
            edit['inputs'][field] = value
            changed = self.client.post('/api/v1/simulations', json=edit).json()
            before = len(library.list_records('run'))
            self.assertEqual(self.client.post(self.endpoint(), json=self.selection(a, changed)).status_code, 422)
            self.assertEqual(len(library.list_records('run')), before)
            reset = self.edit_payload(changed)
            reset['inputs'] = copy.deepcopy(a['inputs'])
            b = self.client.post('/api/v1/simulations', json=reset).json()
        self.assertEqual(self.client.post(self.endpoint(), json=self.selection(a, {**b, 'revision': 1})).status_code, 409)
        self.assertEqual(self.client.post(self.endpoint(), json=self.selection(a, a)).status_code, 422)
        density = self.edit_payload(b)
        density['conditions'] = {'air_density_kg_m3': 1.1}
        altered = self.client.post('/api/v1/simulations', json=density).json()
        self.assertEqual(self.client.post(self.endpoint('/validate'), json=self.selection(a, altered)).status_code, 422)
        reset = self.edit_payload(altered)
        reset['conditions'] = {}
        b = self.client.post('/api/v1/simulations', json=reset).json()
        complex_config = self.edit_payload(b)
        complex_config['workflow'] = copy.deepcopy(complex_config['workflow'])
        complex_config['workflow']['nodes'].append({'id': 'extra_export', 'type': 'export', 'config': {}})
        complex_config['workflow']['edges'].append({'source': 'results', 'source_port': 'result', 'target': 'extra_export', 'target_port': 'result'})
        altered = self.client.post('/api/v1/simulations', json=complex_config).json()
        self.assertEqual(self.client.post(self.endpoint('/validate'), json=self.selection(a, altered)).status_code, 422)
        reset = self.edit_payload(altered)
        reset['workflow'] = copy.deepcopy(a['workflow'])
        reset['workflow']['nodes'][3]['config']['model'] = 'llt'
        b = self.client.post('/api/v1/simulations', json=reset).json()
        _, comparison, _ = frozen_comparison(self.project['id'], ComparisonRequest(**self.selection(a, b)))
        edit = self.edit_payload(b)
        edit['name'] = 'Changed just before atomic queue write'
        self.client.post('/api/v1/simulations', json=edit)
        with self.assertRaisesRegex(ValueError, 'Revision conflict'):
            jobs.submit({**a, 'project_id': self.project['id'], 'comparison': comparison})
        self.assertEqual(library.list_records('run'), [])

    def test_all_failed_comparison_is_failed_with_retained_diagnostics(self):
        configurations = [self.save('BEMT first'), self.save('BEMT second')]
        changed = []
        for configuration in configurations:
            edit = self.edit_payload(configuration)
            edit['workflow'] = copy.deepcopy(edit['workflow'])
            edit['workflow']['nodes'][3]['config']['max_iterations'] = 1
            changed.append(self.client.post('/api/v1/simulations', json=edit).json())
        response = self.client.post(self.endpoint(), json=self.selection(*changed))
        self.assertEqual(response.status_code, 200, response.text)
        run = self.wait(response.json())
        self.assertEqual(run['state'], 'failed')
        self.assertEqual(run['result']['comparison_status'], 'failed')
        self.assertEqual(run['result']['failed_cases'], 2)
        self.assertTrue(all(c.get('diagnostics') for c in run['result']['cases']))

    def test_zero_baseline_and_polar_mismatch_are_explicit(self):
        a, b = self.save('LLT baseline', 'llt'), self.save('LLT candidate', 'llt')
        _, comparison, _ = frozen_comparison(self.project['id'], ComparisonRequest(**self.selection(a, b)))
        result = execute_comparison({'id': 'unit-fixture', 'state': 'running', 'comparison': comparison})
        # Artificial zero coefficients exercise reporting semantics, not solver validation.
        result['cases'][0]['result']['analyses'][0]['performance'].update(thrust_n=0, torque_nm=0, power_w=0, efficiency=0)
        rows = comparison_rows({'id': 'unit-fixture', 'state': 'succeeded', 'comparison': comparison, 'result': result})
        self.assertTrue(all(v is None for v in rows[1]['baseline_differences_pct'].values()))
        self.assertEqual(set(rows[1]['baseline_difference_reasons'].values()), {'zero_baseline'})
        a, b = self.save('BEMT one'), self.save('BEMT two')
        document = {k: v for k, v in self.asset.items() if k not in ('id', 'revision', 'updated_at', 'content_hash')}
        document['points'] = copy.deepcopy(document['points'])
        document['points'][0]['cl'] += .01
        changed_asset = library.make_asset(document)
        edit = self.edit_payload(b)
        edit['polar_asset_id'] = changed_asset['id']
        b = self.client.post('/api/v1/simulations', json=edit).json()
        rejected = self.client.post(self.endpoint('/validate'), json=self.selection(a, b))
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertIn('same scientific polar', rejected.text)

    def test_polar_scientific_identity_ignores_import_metadata_and_sample_order(self):
        a, b = self.save('BEMT original'), self.save('BEMT reimport')
        document = {k: copy.deepcopy(v) for k, v in self.asset.items()
                    if k not in ('id', 'revision', 'updated_at', 'content_hash')}
        document.update(filename='reordered-copy.csv', source='Same coefficient samples reimported', demonstration=False)
        document['points'].reverse()
        # Integral numeric values may be represented as JSON integers by another importer.
        for point in document['points']:
            point['reynolds'] = int(point['reynolds'])
        alternate = library.make_asset(document)
        self.assertNotEqual(alternate['content_hash'], self.asset['content_hash'])
        self.assertEqual(scientific_polar_hash(alternate), scientific_polar_hash(self.asset))
        edit = self.edit_payload(b)
        edit['polar_asset_id'] = alternate['id']
        b = self.client.post('/api/v1/simulations', json=edit).json()
        response = self.client.post(self.endpoint('/validate'), json=self.selection(a, b))
        self.assertEqual(response.status_code, 200, response.text)
        _, comparison, _ = frozen_comparison(self.project['id'], ComparisonRequest(**self.selection(a, b)))
        original_fingerprint = fingerprint(comparison['simulations'][0])
        different_origin = copy.deepcopy(comparison['simulations'][0])
        different_origin['polar_asset'] = alternate
        self.assertNotEqual(fingerprint(different_origin), original_fingerprint)
        self.assertEqual(comparison['simulations'][0]['polar_asset']['content_hash'], self.asset['content_hash'])
        self.assertEqual(comparison['simulations'][1]['polar_asset']['content_hash'], alternate['content_hash'])
        changed = {k: copy.deepcopy(v) for k, v in alternate.items()
                   if k not in ('id', 'revision', 'updated_at', 'content_hash')}
        changed['points'][0]['cl'] += .01
        changed_asset = library.make_asset(changed)
        self.assertNotEqual(scientific_polar_hash(changed_asset), scientific_polar_hash(alternate))
        edit = self.edit_payload(b)
        edit['polar_asset_id'] = changed_asset['id']
        b = self.client.post('/api/v1/simulations', json=edit).json()
        rejected = self.client.post(self.endpoint('/validate'), json=self.selection(a, b))
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertIn('same scientific polar', rejected.text)

    def test_partial_failure_keeps_success_and_unavailable_baseline(self):
        a, b = self.save(), self.save('LLT', 'llt')
        edit = self.edit_payload(a)
        edit['workflow'] = copy.deepcopy(edit['workflow'])
        edit['workflow']['nodes'][3]['config']['max_iterations'] = 1
        a = self.client.post('/api/v1/simulations', json=edit).json()
        response = self.client.post(self.endpoint(), json=self.selection(a, b))
        self.assertEqual(response.status_code, 200, response.text)
        run = self.wait(response.json())
        self.assertEqual(run['state'], 'succeeded', run.get('error'))
        self.assertEqual(run['result']['comparison_status'], 'completed_with_failures')
        self.assertEqual([c['state'] for c in run['result']['cases']], ['failed', 'succeeded'])
        self.assertFalse(run['result']['cases'][0]['diagnostics']['convergence']['converged'])
        self.assertIsNone(run['result']['rows'][1]['baseline_differences_pct']['thrust_n'])
        self.assertEqual(run['result']['rows'][1]['baseline_difference_reasons']['thrust_n'], 'baseline_failed')
        records = library.read_archive(library.export_project(self.project['id']))
        invalid = copy.deepcopy(records)
        invalid['runs'][0]['result']['cases'][1]['simulation_revision'] = 99
        before = len(library.list_records('project'))
        self.assertEqual(self.client.post('/api/v1/projects/import', json=self.archive_request(invalid)).status_code, 422)
        self.assertEqual(len(library.list_records('project')), before)
        self.assertEqual(self.client.post('/api/v1/projects/import', json=self.archive_request(records)).status_code, 200)

    def test_cancellation_retains_completed_comparison_checkpoint(self):
        a, b = self.save(), self.save('LLT', 'llt')
        selection = self.selection(a, b)
        _, comparison, _ = frozen_comparison(self.project['id'], ComparisonRequest(**selection))
        checkpoints = []
        with self.assertRaises(InterruptedError):
            execute_comparison({'id': 'checkpoint-fixture', 'state': 'running', 'comparison': comparison},
                               checkpoint=checkpoints.append, cancelled=lambda: bool(checkpoints))
        worker = Path(self.directory.name) / 'checkpoint.py'
        worker.write_text('import json,sys,time\njson.load(sys.stdin)\nprint(' + repr(json.dumps({'checkpoint': checkpoints[0]})) + ',flush=True)\ntime.sleep(30)\n')
        with patch.object(jobs, '_worker_command', return_value=[sys.executable, str(worker)]):
            run = self.client.post(self.endpoint(), json=selection).json()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                current = self.client.get(f"/api/v1/runs/{run['id']}").json()
                if (current.get('result') or {}).get('completed_cases') == 1:
                    break
                time.sleep(.05)
            else:
                self.fail('Comparison checkpoint was not persisted')
            self.client.post(f"/api/v1/runs/{run['id']}/cancel")
            stopped = self.wait(run)
        self.assertEqual(stopped['state'], 'cancelled')
        self.assertEqual(stopped['result']['completed_cases'], 1)
        self.assertEqual(stopped['result']['comparison_status'], 'cancelled')
        recovery = library.save('run', {**a, 'id': None, 'project_id': self.project['id'],
                                        'comparison': comparison, 'state': 'running', 'result': checkpoints[0]})
        library.initialize()
        restored = library.get('run', recovery['id'])
        self.assertEqual(restored['state'], 'interrupted')
        self.assertEqual(restored['result']['comparison_status'], 'interrupted')
        records = library.read_archive(library.export_project(self.project['id']))
        self.assertEqual(self.client.post('/api/v1/projects/import', json=self.archive_request(records)).status_code, 200)
