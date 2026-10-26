import base64
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_api_contract
import test_nova_workflow
from fastapi.testclient import TestClient

import database
from main import app
from nova.adapters.base import (
    AdapterConfiguration,
    AdapterDescriptor,
    AdapterError,
    ExternalAdapter,
    PreparedCase,
    execute_adapter,
)
from nova.adapters.process import (
    ProcessCancelled,
    ProcessFailure,
    ProcessSpec,
    external_environment,
    run_process,
)
from nova.adapters.registry import register, unregister
from nova.application.studies import build_cases, execute_study, validate_study_result
from nova.core.data import Port
from nova.infrastructure import jobs, library
from nova.workflow.engine import execute, template


def snapshot():
    return {'inputs': test_api_contract.ApiContractTests.geometry_payload(), 'workflow': template(),
            'polar_asset': test_nova_workflow.demo(), 'conditions': {}}


class StudyTests(unittest.TestCase):
    def test_cases_match_direct_workflow_and_do_not_mutate_inputs(self):
        original = snapshot()
        checkpoints = []
        result = execute_study(original, {'parameter': 'rpm', 'values': [3500, 4250, 5000]}, checkpoint=checkpoints.append)
        self.assertEqual(result['study_status'], 'succeeded')
        self.assertEqual(result['completed_cases'], 3)
        self.assertEqual(checkpoints[0]['completed_cases'], 1)
        self.assertEqual(original['inputs']['rpm'], 5000)
        thrust = []
        for case in result['cases']:
            reference = execute(original['workflow'], case['inputs'], original['polar_asset'], case['conditions'])
            actual = case['result']['analyses'][0]['performance']['thrust_n']
            self.assertAlmostEqual(actual, reference['analyses'][0]['performance']['thrust_n'], places=10)
            thrust.append(actual)
        self.assertEqual(thrust, sorted(thrust))
        self.assertEqual(len(set(thrust)), 3)
        invalid = copy.deepcopy(result)
        invalid['cases'] = invalid['cases'][:1]
        with self.assertRaises(ValueError):
            validate_study_result(invalid, original)

    def test_failures_and_cancelled_checkpoints_are_retained(self):
        config = snapshot()
        config['workflow']['nodes'][3]['config']['max_iterations'] = 1
        result = execute_study(config, {'parameter': 'rpm', 'values': [3500, 5000]})
        self.assertEqual(result['study_status'], 'failed')
        self.assertEqual(result['failed_cases'], 2)
        self.assertTrue(all(not c['diagnostics']['convergence']['converged'] for c in result['cases']))
        checkpoints = []
        with self.assertRaises(InterruptedError):
            execute_study(snapshot(), {'parameter': 'rpm', 'values': [3500, 5000]},
                          checkpoint=checkpoints.append, cancelled=lambda: bool(checkpoints))
        self.assertEqual(checkpoints[0]['completed_cases'], 1)

    def test_invalid_and_ineffective_sweeps_are_rejected(self):
        for values in ([1, 1], [float('nan'), 5000], [True, 5000], [0, 5000], [5000], list(range(1, 34)), [3500, 70000]):
            with self.assertRaises(ValueError):
                build_cases(snapshot(), {'parameter': 'rpm', 'values': values})
        ideal = snapshot()
        ideal['workflow']['nodes'][1]['config']['mode'] = 'actuator_disk'
        with self.assertRaises(ValueError):
            build_cases(ideal, {'parameter': 'diameter', 'values': [.2, .3]})
        viscosity = {'parameter': 'air_viscosity_pa_s', 'values': [1.7e-5, 1.9e-5]}
        self.assertEqual(len(build_cases(snapshot(), viscosity)), 2)
        default_model = snapshot()
        default_model['workflow']['nodes'][3]['config'].pop('model')
        self.assertEqual(len(build_cases(default_model, viscosity)), 2)
        for model in ('llt', 'vlm', 'bem'):
            approximate = snapshot()
            approximate['workflow']['nodes'][3]['config']['model'] = model
            with self.assertRaisesRegex(ValueError, 'requires BEMT'):
                build_cases(approximate, viscosity)


PROGRAM = '''import json, os, pathlib, sys, time
if '--version' in sys.argv:
    print('fixture 1.0')
    raise SystemExit(0)
if '--sleep' in sys.argv:
    print('started', flush=True)
    time.sleep(30)
if '--closed' in sys.argv:
    os.close(1)
    os.close(2)
    time.sleep(30)
if '--descendant' in sys.argv:
    import subprocess
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    print(child.pid, flush=True)
    time.sleep(30)
if '--fail' in sys.argv:
    print('fixture failure', flush=True)
    raise SystemExit(3)
if '--large' in sys.argv:
    print('α' * 10000)
    raise SystemExit(0)
if '--literal' in sys.argv:
    print(json.dumps({'argument': sys.argv[-1], 'token': os.getenv('NOVA_SESSION_TOKEN')}))
    raise SystemExit(0)
value = json.loads(pathlib.Path('input.json').read_text())
print('computing fixture', flush=True)
if '--missing' not in sys.argv:
    pathlib.Path('output.json').write_text(json.dumps({'value': value['value'] * 2}))
'''


class FixtureAdapter(ExternalAdapter):
    def describe(self):
        port = Port('fixture_number', 'dimensionless')
        return AdapterDescriptor('fixture', 'Test fixture only', '1', 'Not a scientific solver', 'test-only',
                                 ('python_environment',), {'value': port}, {'value': port})

    def probe(self, configuration):
        with tempfile.TemporaryDirectory() as directory:
            result = run_process(ProcessSpec(configuration.executable, (configuration.options['script'], '--version'), 5), Path(directory))
        return {'available': True, 'compatible': result.log.strip() == 'fixture 1.0', 'version': result.log.strip()}

    def validate(self, case, configuration):
        if type(case.get('value')) not in (int, float):
            raise ValueError('Fixture requires a number')

    def prepare(self, case, configuration, directory):
        (directory / 'input.json').write_text(json.dumps(case))
        arguments = (configuration.options['script'],) + (('--missing',) if configuration.options.get('missing') else ())
        return PreparedCase((ProcessSpec(configuration.executable, (configuration.options['script'], '--version'), 5),
                             ProcessSpec(configuration.executable, arguments, 5)), ('input.json',), ('output.json',))

    def collect(self, directory, prepared):
        return json.loads((directory / 'output.json').read_text())

    def normalize(self, output):
        return {'value': output['value'], 'units': 'dimensionless'}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.program = self.root / 'fixture program.py'
        self.program.write_text(PROGRAM)

    def tearDown(self):
        self.directory.cleanup()

    def spec(self, *arguments, timeout=5):
        return ProcessSpec(Path(sys.executable), (str(self.program), *arguments), timeout)

    def test_process_handles_failures_timeouts_cancellation_and_bounded_utf8(self):
        with self.assertRaises(ProcessFailure) as failed:
            run_process(self.spec('--fail'), self.root)
        self.assertEqual(failed.exception.result.returncode, 3)
        self.assertIn('fixture failure', failed.exception.result.log)
        with self.assertRaises(ProcessFailure):
            run_process(self.spec('--sleep', timeout=.15), self.root)
        started = time.monotonic()
        with self.assertRaises(ProcessCancelled):
            run_process(self.spec('--sleep'), self.root, cancelled=lambda: time.monotonic() - started > .15)
        started = time.monotonic()
        with self.assertRaises(ProcessCancelled):
            run_process(self.spec('--closed'), self.root, cancelled=lambda: time.monotonic() - started > .15)
        with self.assertRaises(ProcessFailure) as descendants:
            run_process(self.spec('--descendant', timeout=.2), self.root)
        child_pid = int(descendants.exception.result.log.strip())
        status = Path(f'/proc/{child_pid}/stat')
        deadline = time.monotonic() + 1
        def child_alive():
            try:
                return status.read_text().split()[2] != 'Z'
            except (FileNotFoundError, ProcessLookupError):
                return False
        while child_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(child_alive())
        result = run_process(self.spec('--large'), self.root, max_log_characters=32)
        self.assertTrue(result.log_truncated)
        self.assertLessEqual(len(result.log), 32)
        self.assertNotIn('�', result.log)

    def test_no_shell_interpretation_or_desktop_secret(self):
        literal = f'$(touch {self.root}/unexpected); argument with spaces'
        with patch.dict(os.environ, {'NOVA_SESSION_TOKEN': 'not-for-external-programs',
                                      '_PYI_APPLICATION_HOME_DIR': '/bundled', 'LD_LIBRARY_PATH': '/bundled/lib'}):
            result = run_process(self.spec('--literal', literal), self.root)
            self.assertNotIn('LD_LIBRARY_PATH', external_environment())
        parsed = json.loads(result.log)
        self.assertEqual(parsed['argument'], literal)
        self.assertIsNone(parsed['token'])
        self.assertFalse((self.root / 'unexpected').exists())

    def test_selected_python_environment_is_not_resolved_to_base_interpreter(self):
        import subprocess
        environment = self.root / 'scientific environment'
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(environment)], check=True)
        site = environment / f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
        (site / 'adapter_sentinel.py').write_text('value = 42\n')
        selected = environment / 'bin/python'
        result = run_process(ProcessSpec(selected, ('-c', 'import adapter_sentinel; print(adapter_sentinel.value)')), self.root)
        self.assertEqual(result.log.strip(), '42')
        self.assertEqual(result.command[0], str(selected))

    def test_selector_setup_failure_reaps_spawned_process(self):
        import subprocess
        real_popen = subprocess.Popen
        started = []
        def tracked(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            started.append(process)
            return process
        with patch('nova.adapters.process.subprocess.Popen', side_effect=tracked), patch('nova.adapters.process.selectors.DefaultSelector', side_effect=OSError('selector fixture failure')):
            with self.assertRaises(OSError):
                run_process(self.spec('--sleep'), self.root)
        self.assertIsNotNone(started[0].poll())
        self.assertTrue(started[0].stdout.closed)

    def test_adapter_preserves_artifacts_and_missing_output_failure(self):
        adapter = FixtureAdapter()
        configuration = AdapterConfiguration(Path(sys.executable), 'python_environment', {'script': str(self.program)})
        result = execute_adapter(adapter, configuration, {'value': 3}, self.root / 'cases')
        self.assertEqual(result['data']['value'], 6)
        directory = Path(result['working_directory'])
        self.assertTrue((directory / 'input.json').is_file())
        self.assertEqual(json.loads((directory / 'execution.json').read_text())['returncode'], 0)
        self.assertEqual(len(result['provenance']['stages']), 2)
        bad = AdapterConfiguration(Path(sys.executable), 'python_environment', {'script': str(self.program), 'missing': True})
        with self.assertRaises(AdapterError):
            execute_adapter(adapter, bad, {'value': 3}, self.root / 'failed')
        self.assertEqual(len(list((self.root / 'failed').glob('*/failure.json'))), 1)


class StudyHttpJourney(unittest.TestCase):
    def test_study_export_comparison_archive_and_optimization_jobs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            asset = client.post('/api/v1/assets/demonstration-polar', json={'airfoil': 'NACA 4412'}).json()
            payload = {'name': 'Study project', 'inputs': snapshot()['inputs'], 'workflow': template(),
                       'polar_asset_id': asset['id'], 'conditions': {}}
            project = client.post('/api/v1/projects', json=payload).json()
            payload['id'] = project['id']
            run = client.post('/api/v1/studies', json={**payload, 'study': {'parameter': 'rpm', 'values': [3500, 5000]}}).json()
            study = self.wait(client, run['id'])
            self.assertEqual(study['state'], 'succeeded', study.get('error'))
            self.assertEqual(study['result']['completed_cases'], 2)
            self.assertGreater(len(client.get(f"/api/v1/runs/{run['id']}/cases/0/stl").content), 1000)
            csv = client.get(f"/api/v1/runs/{run['id']}/study.csv")
            self.assertIn('thrust_n', csv.text)
            baseline = self.wait(client, client.post('/api/v1/runs', json=payload).json()['id'])
            comparison = client.post('/api/v1/runs/compare', json={'run_ids': [run['id'], baseline['id']]}).json()
            self.assertEqual(len(comparison['rows']), 3)
            archive = client.get(f"/api/v1/projects/{project['id']}/archive").content
            response = client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(archive).decode()})
            self.assertEqual(response.status_code, 200, response.text)
            imported = response.json()
            imported_runs = [r for r in library.list_records('run') if r.get('project_id') == imported['id'] and r.get('study')]
            self.assertEqual(imported_runs[0]['result']['cases'][0]['result']['analyses'], study['result']['cases'][0]['result']['analyses'])
            repeated_archive = client.get(f"/api/v1/projects/{imported['id']}/archive").content
            self.assertEqual(client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(repeated_archive).decode()}).status_code, 200)
            rejected = client.post('/api/v1/studies', json={**payload, 'study': {'parameter': 'rpm', 'values': [3500, 70000]}})
            self.assertEqual(rejected.status_code, 422)
            failed_payload = copy.deepcopy(payload)
            failed_payload['workflow']['nodes'][3]['config']['max_iterations'] = 1
            failed = self.wait(client, client.post('/api/v1/studies', json={**failed_payload, 'study': {'parameter': 'rpm', 'values': [3500, 5000]}}).json()['id'])
            self.assertEqual(failed['state'], 'failed')
            self.assertEqual(failed['result']['failed_cases'], 2)
            candidate = self.wait(client, client.post('/api/v1/optimizations', json={**payload, 'solver': 'bemt', 'max_iterations': 10}).json()['id'])
            self.assertEqual(candidate['state'], 'succeeded', candidate.get('error'))
            self.assertEqual(candidate['result']['kind'], 'optimization')
            self.assertIn('geometry_parameters', candidate['result']['candidate'])
            applied = copy.deepcopy(payload)
            applied['inputs']['geometry_parameters'] = candidate['result']['candidate']['geometry_parameters']
            rerun = self.wait(client, client.post('/api/v1/runs', json=applied).json()['id'])
            self.assertEqual(rerun['state'], 'succeeded', rerun.get('error'))
            self.assertAlmostEqual(rerun['result']['analyses'][0]['performance']['thrust_n'],
                                   candidate['result']['candidate']['performance']['thrust'], places=10)
            self.assertEqual(rerun['result']['geometry']['stations'][0]['radius_m'],
                             candidate['result']['candidate']['geometry']['stations'][0]['radius_m'])

    def wait(self, client, id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            record = client.get(f'/api/v1/runs/{id}').json()
            if record['state'] not in ('queued', 'running', 'cancelling'):
                return record
            time.sleep(.05)
        self.fail('Small job exceeded its test budget')

    def test_cancel_preserves_completed_case_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            prepared = execute_study(snapshot(), {'parameter': 'rpm', 'values': [3500, 5000]})
            prepared['cases'] = prepared['cases'][:1]
            prepared.update(completed_cases=1, study_status='running')
            worker = Path(directory) / 'checkpoint_worker.py'
            worker.write_text('import json,sys,time\njson.load(sys.stdin)\nprint(' + repr(json.dumps({'checkpoint': prepared})) + ',flush=True)\ntime.sleep(30)\n')
            asset = client.post('/api/v1/assets/demonstration-polar', json={'airfoil': 'NACA 4412'}).json()
            payload = {'name': 'Cancelled study', 'inputs': snapshot()['inputs'], 'workflow': template(),
                       'polar_asset_id': asset['id'], 'conditions': {}, 'study': {'parameter': 'rpm', 'values': [3500, 5000]}}
            with patch.object(jobs, '_worker_command', return_value=[sys.executable, str(worker)]):
                run = client.post('/api/v1/studies', json=payload).json()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    progress = client.get(f"/api/v1/runs/{run['id']}").json()
                    if progress.get('result', {}).get('completed_cases') == 1:
                        break
                    time.sleep(.05)
                else:
                    self.fail('Worker checkpoint was not persisted')
                client.post(f"/api/v1/runs/{run['id']}/cancel")
                stopped = self.wait(client, run['id'])
                self.assertEqual(stopped['state'], 'cancelled')
                self.assertEqual(stopped['result']['completed_cases'], 1)
                self.assertEqual(stopped['result']['study_status'], 'cancelled')

    def test_recovered_study_checkpoint_can_be_exported_and_imported(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            asset = client.post('/api/v1/assets/demonstration-polar', json={'airfoil': 'NACA 4412'}).json()
            payload = {'name': 'Recovered study', 'inputs': snapshot()['inputs'], 'workflow': template(),
                       'polar_asset_id': asset['id'], 'conditions': {}}
            project = client.post('/api/v1/projects', json=payload).json()
            frozen = {**project, 'polar_asset': asset, 'study': {'parameter': 'rpm', 'values': [3500, 5000]}}
            checkpoint = execute_study(frozen, frozen['study'])
            checkpoint['cases'] = checkpoint['cases'][:1]
            checkpoint.update(completed_cases=1, study_status='running')
            stored = library.save('run', {**frozen, 'project_id': project['id'], 'state': 'running',
                                          'result': checkpoint, 'logs': [], 'progress': .5})
            library.initialize()
            recovered = library.get('run', stored['id'])
            self.assertEqual(recovered['state'], 'interrupted')
            self.assertEqual(recovered['result']['study_status'], 'interrupted')
            archive = client.get(f"/api/v1/projects/{project['id']}/archive").content
            imported = client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(archive).decode()})
            self.assertEqual(imported.status_code, 200, imported.text)

    def test_adapter_registry_probe_and_machine_local_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(database, 'DB_PATH', Path(directory) / 'nova.db'), TestClient(app) as client:
            program = Path(directory) / 'fixture.py'
            program.write_text(PROGRAM)
            register(FixtureAdapter())
            try:
                payload = {'executable': sys.executable, 'environment_kind': 'python_environment', 'options': {'script': str(program)}}
                self.assertIn('fixture', [a['id'] for a in client.get('/api/v1/adapters').json()])
                probe = client.post('/api/v1/adapters/fixture/probe', json=payload)
                self.assertEqual(probe.status_code, 200, probe.text)
                configured = client.post('/api/v1/adapters/fixture/configure', json=payload)
                self.assertEqual(configured.status_code, 200, configured.text)
                self.assertEqual(len(client.get('/api/v1/integrations').json()), 1)
                self.assertEqual(client.post('/api/v1/adapters/missing/probe', json=payload).status_code, 404)
                missing_options = {**payload, 'options': {}}
                self.assertEqual(client.post('/api/v1/adapters/fixture/probe', json=missing_options).status_code, 422)
                with patch.object(FixtureAdapter, 'probe', side_effect=AdapterError('Invalid fixture configuration')):
                    invalid = client.post('/api/v1/adapters/fixture/configure', json=payload)
                    self.assertEqual(invalid.status_code, 422)
                    self.assertEqual(invalid.json()['detail'], 'Invalid fixture configuration')
            finally:
                unregister('fixture')
