import base64
import copy
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_project_simulations as fixtures
import test_studies_adapters as studies_fixtures

from nova.application.studies import build_cases, execute_study, validate_study_result
from nova.infrastructure import jobs, library
from nova.workflow.engine import execute


def definition():
    return {'parameter': 'rpm', 'values': [3500, 5000],
            'secondary': {'parameter': 'air_density_kg_m3', 'values': [1.1, 1.225]}}


def snapshot():
    result = studies_fixtures.snapshot()
    result['workflow']['nodes'][3]['config']['model'] = 'llt'
    return result


class TwoAxisScientificTests(unittest.TestCase):
    def test_cartesian_matches_direct_workflows_and_preserves_inputs(self):
        original = snapshot()
        before = copy.deepcopy(original)
        result = execute_study(original, definition())
        self.assertEqual(result['study_status'], 'succeeded')
        self.assertEqual(result['secondary_units'], 'kg/m^3')
        self.assertEqual([(c['value'], c['secondary_value']) for c in result['cases']],
                         [(3500, 1.1), (3500, 1.225), (5000, 1.1), (5000, 1.225)])
        self.assertEqual(len({c['input_hash'] for c in result['cases']}), 4)
        for case in result['cases']:
            direct = execute(original['workflow'], case['inputs'], original['polar_asset'], case['conditions'])
            self.assertEqual(case['result']['analyses'][0]['performance'], direct['analyses'][0]['performance'])
            self.assertEqual(case['secondary_parameter'], 'air_density_kg_m3')
            self.assertEqual(case['secondary_units'], 'kg/m^3')
        self.assertEqual(original, before)
        validate_study_result(result, {**original, 'study': definition(), 'state': 'succeeded'})
        invalid = copy.deepcopy(result)
        invalid['cases'][0]['secondary_value'] = 2
        with self.assertRaises(ValueError):
            validate_study_result(invalid, original)

    def test_cartesian_limits_types_distinct_axes_and_effective_parameters(self):
        for secondary in ({'parameter': 'rpm', 'values': [3000, 4000]},
                          {'parameter': 'diameter', 'values': [.2, .2]},
                          {'parameter': 'diameter', 'values': [True, .3]},
                          {'parameter': 'diameter', 'values': [0, .3]},
                          {'parameter': 'diameter', 'values': [float('nan'), .3]},
                          {'parameter': 'air_viscosity_pa_s', 'values': [1e-5, 2e-5]}):
            with self.subTest(secondary=secondary), self.assertRaises(ValueError):
                build_cases(snapshot(), {**definition(), 'secondary': secondary})
        too_large = {'parameter': 'rpm', 'values': list(range(3000, 3006)),
                     'secondary': {'parameter': 'air_density_kg_m3', 'values': [1, 1.1, 1.2, 1.3, 1.4, 1.5]}}
        with self.assertRaises(ValueError):
            build_cases(snapshot(), too_large)
        automatic = snapshot()
        automatic['workflow']['nodes'][1]['config'] = {'mode': 'actuator_disk'}
        with self.assertRaisesRegex(ValueError, 'manual sizing'):
            build_cases(automatic, {**definition(), 'secondary': {'parameter': 'diameter', 'values': [.2, .3]}})
        expensive = snapshot()
        for index in range(4):
            expensive['workflow']['nodes'].append({'id': f'extra{index}', 'type': 'analysis', 'config': {'model': 'llt'}})
            expensive['workflow']['edges'].append({'source': 'geometry', 'source_port': 'geometry', 'target': f'extra{index}', 'target_port': 'geometry'})
        with self.assertRaisesRegex(ValueError, '128'):
            build_cases(expensive, {'parameter': 'rpm', 'values': list(range(3000, 3016)),
                                    'secondary': {'parameter': 'air_density_kg_m3', 'values': [1.1, 1.2]}})


class TwoAxisHttpTests(unittest.TestCase):
    setUp = fixtures.ProjectSimulationTests.setUp
    tearDown = fixtures.ProjectSimulationTests.tearDown
    save = fixtures.ProjectSimulationTests.save
    wait_run = fixtures.ProjectSimulationTests.wait_run
    archive_request = fixtures.ProjectSimulationTests.archive_request

    def test_normalized_rows_csv_and_old_new_archive_round_trip(self):
        simulation = self.save('LLT study', 'llt')
        response = self.client.post(f"/api/v1/simulations/{simulation['id']}/study", json={'study': definition()})
        self.assertEqual(response.status_code, 200, response.text)
        run = self.wait_run(response.json())
        normalized = self.client.get(f"/api/v1/runs/{run['id']}/study.rows")
        self.assertEqual(normalized.status_code, 200, normalized.text)
        self.assertEqual(len(normalized.json()['rows']), 4)
        self.assertEqual(normalized.json()['axes'][1], {'parameter': 'air_density_kg_m3', 'values': [1.1, 1.225], 'units': 'kg/m^3'})
        self.assertEqual([r['secondary_value'] for r in normalized.json()['rows']], [1.1, 1.225, 1.1, 1.225])
        self.assertIn('secondary_parameter,secondary_units,secondary_value', self.client.get(f"/api/v1/runs/{run['id']}/study.csv").text)
        one = self.client.post(f"/api/v1/simulations/{simulation['id']}/study", json={'study': {'parameter': 'rpm', 'values': [3500, 5000]}})
        legacy = self.wait_run(one.json())
        self.assertNotIn('secondary', legacy['study'])
        self.assertNotIn('secondary', legacy['result']['definition'])
        self.assertNotIn('secondary_units', legacy['result'])
        self.assertNotIn('secondary_value', legacy['result']['cases'][0])
        self.assertNotIn('secondary_', self.client.get(f"/api/v1/runs/{legacy['id']}/study.csv").text)
        records = library.read_archive(library.export_project(self.project['id']))
        invalid = copy.deepcopy(records)
        target = next(r for r in invalid['runs'] if r['study'].get('secondary'))
        target['result']['cases'][0]['secondary_units'] = 'wrong'
        before = len(library.list_records('project'))
        self.assertEqual(self.client.post('/api/v1/projects/import', json=self.archive_request(invalid)).status_code, 422)
        self.assertEqual(len(library.list_records('project')), before)
        response = self.client.post('/api/v1/projects/import', json=self.archive_request(records))
        self.assertEqual(response.status_code, 200, response.text)
        imported = [r for r in library.list_records('run') if r.get('project_id') == response.json()['id']]
        self.assertEqual(sorted(r['result']['total_cases'] for r in imported), [2, 4])
        archive = library.export_project(response.json()['id'])
        self.assertEqual(self.client.post('/api/v1/projects/import', json={
            'content_base64': base64.b64encode(archive).decode()}).status_code, 200)

    def test_cancelled_checkpoint_keeps_two_axis_configuration(self):
        simulation = self.save('LLT cancelled study', 'llt')
        frozen = {**simulation, 'polar_asset': self.asset}
        checkpoints = []
        with self.assertRaises(InterruptedError):
            execute_study(frozen, definition(), checkpoint=checkpoints.append, cancelled=lambda: bool(checkpoints))
        checkpoint = checkpoints[0]
        worker = Path(self.directory.name) / 'two_axis_checkpoint.py'
        worker.write_text('import json,sys,time\njson.load(sys.stdin)\nprint(' + repr(json.dumps({'checkpoint': checkpoint})) + ',flush=True)\ntime.sleep(30)\n')
        with patch.object(jobs, '_worker_command', return_value=[sys.executable, str(worker)]):
            response = self.client.post(f"/api/v1/simulations/{simulation['id']}/study", json={'study': definition()})
            self.assertEqual(response.status_code, 200, response.text)
            record = response.json()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                current = self.client.get(f"/api/v1/runs/{record['id']}").json()
                if (current.get('result') or {}).get('completed_cases') == 1:
                    break
                time.sleep(.05)
            else:
                self.fail('Two-axis checkpoint was not retained')
            self.client.post(f"/api/v1/runs/{record['id']}/cancel")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                current = self.client.get(f"/api/v1/runs/{record['id']}").json()
                if current['state'] == 'cancelled':
                    break
                time.sleep(.05)
            self.assertEqual(current['state'], 'cancelled')
        self.assertEqual(current['result']['cases'][0]['secondary_value'], 1.1)
        self.assertEqual(current['result']['comparison_status'] if 'comparison_status' in current['result'] else current['result']['study_status'], 'cancelled')
        archive = library.export_project(self.project['id'])
        response = self.client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(archive).decode()})
        self.assertEqual(response.status_code, 200, response.text)
