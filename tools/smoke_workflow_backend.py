#!/usr/bin/env python3
"""Verify the installed/frozen workflow without importing project Python code."""
import argparse
import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from smoke_desktop_backend import wait_for_endpoint


def smoke(executable):
    with tempfile.TemporaryDirectory(prefix='nova-workflow-smoke-') as directory:
        env = {**os.environ, 'NOVA_SESSION_TOKEN': 'temporary-smoke-session'}
        process = subprocess.Popen([str(executable), '--port', '0', '--data-dir', directory],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        try:
            endpoint = wait_for_endpoint(process)
            def request(path, body=None):
                payload = json.dumps(body).encode() if body is not None else None
                req = urllib.request.Request(endpoint + path, data=payload,
                    headers={'Content-Type': 'application/json', 'X-Nova-Session': env['NOVA_SESSION_TOKEN']})
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = response.read()
                    return json.loads(data) if 'json' in response.headers.get('Content-Type', '') else data
            asset = request('/v1/assets/demonstration-polar', {'airfoil': 'NACA 4412'})
            workflow = request('/v1/workflow-template')
            inputs = {'project_name': 'Frozen workflow', 'propeller_type': 'traditional', 'thrust_target': 2,
                      'rpm': 5000, 'diameter': .25, 'blades': 2, 'airfoil': 'NACA 4412',
                      'geometry_method': 'bezier', 'airfoil_assignments': [], 'geometry_parameters': {
                        'chord_points': [{'x': 0, 'y': .026}, {'x': .33, 'y': .029}, {'x': .72, 'y': .016}, {'x': 1, 'y': .006}],
                        'twist_points': [{'x': 0, 'y': 34}, {'x': .33, 'y': 25}, {'x': .72, 'y': 14}, {'x': 1, 'y': 7}]}}
            payload = {'name': 'Frozen workflow', 'inputs': inputs, 'workflow': workflow,
                       'polar_asset_id': asset['id'], 'conditions': {}}
            project = request('/v1/projects', payload)
            run = request('/v1/runs', {**payload, 'id': project['id']})
            deadline = time.monotonic() + 30
            while run['state'] in ('queued', 'running', 'cancelling') and time.monotonic() < deadline:
                time.sleep(.1)
                run = request('/v1/runs/' + run['id'])
            assert run['state'] == 'succeeded', run.get('error') or run['state']
            result = run['result']['analyses'][0]
            assert result['convergence']['converged'] and result['performance']['thrust_n'] > 0
            assert len(request('/v1/runs/' + run['id'] + '/stl')) > 1000
            archive = request('/v1/projects/' + project['id'] + '/archive')
            imported = request('/v1/projects/import', {'content_base64': base64.b64encode(archive).decode()})
            assert imported['id'] != project['id']
            assert imported['inputs'] == project['inputs']
            study = request('/v1/studies', {**payload, 'id': project['id'], 'study': {'parameter': 'rpm', 'values': [3500, 5000]}})
            deadline = time.monotonic() + 30
            while study['state'] in ('queued', 'running', 'cancelling') and time.monotonic() < deadline:
                time.sleep(.1)
                study = request('/v1/runs/' + study['id'])
            assert study['state'] == 'succeeded', study.get('error') or study['state']
            assert study['result']['completed_cases'] == 2 and study['result']['failed_cases'] == 0
            assert b'thrust_n' in request('/v1/runs/' + study['id'] + '/study.csv')
            grid = request('/v1/studies', {**payload, 'id': project['id'], 'study': {
                'parameter': 'rpm', 'values': [4500, 5000],
                'secondary': {'parameter': 'air_density_kg_m3', 'values': [1.1, 1.225]}}})
            deadline = time.monotonic() + 30
            while grid['state'] in ('queued', 'running', 'cancelling') and time.monotonic() < deadline:
                time.sleep(.1)
                grid = request('/v1/runs/' + grid['id'])
            assert grid['state'] == 'succeeded', grid
            assert grid['result']['completed_cases'] == 4 and grid['result']['failed_cases'] == 0
            assert b'secondary_value' in request('/v1/runs/' + grid['id'] + '/study.csv')
            comparison = request('/v1/runs/compare', {'run_ids': [run['id'], study['id']]})
            assert len(comparison['rows']) == 3
            simulation = request('/v1/simulations', {**payload, 'name': 'BEMT baseline', 'project_id': project['id']})
            variant = request('/v1/simulations/' + simulation['id'] + '/clone', {'name': 'LLT comparison'})
            batch = request('/v1/projects/' + project['id'] + '/comparisons', {
                'name': 'Frozen identical baseline comparison', 'simulations': [
                    {'id': simulation['id'], 'expected_revision': simulation['revision']},
                    {'id': variant['id'], 'expected_revision': variant['revision']}]})
            deadline = time.monotonic() + 30
            while batch['state'] in ('queued', 'running', 'cancelling') and time.monotonic() < deadline:
                time.sleep(.1)
                batch = request('/v1/runs/' + batch['id'])
            assert batch['state'] == 'succeeded', batch
            assert len(batch['result']['rows']) == 2
            assert batch['result']['rows'][1]['baseline_differences_pct']['thrust_n'] == 0
            assert b'baseline_differences_pct' in request('/v1/runs/' + batch['id'] + '/comparison.csv')
            variant['inputs']['rpm'] = 6500
            variant['workflow']['nodes'][3]['config']['model'] = 'llt'
            variant = request('/v1/simulations', {key: variant[key] for key in ('name', 'inputs', 'workflow', 'conditions', 'polar_asset_id', 'project_id', 'id')} | {'expected_revision': variant['revision']})
            named_run = request('/v1/simulations/' + variant['id'] + '/run', {'expected_revision': variant['revision']})
            deadline = time.monotonic() + 30
            while named_run['state'] in ('queued', 'running', 'cancelling') and time.monotonic() < deadline:
                time.sleep(.1)
                named_run = request('/v1/runs/' + named_run['id'])
            assert named_run['state'] == 'succeeded', named_run
            assert named_run['simulation_id'] == variant['id'] and named_run['simulation_revision'] == 2
            assert named_run['result']['analyses'][0]['model'] == 'llt' and named_run['inputs']['rpm'] == 6500
            unchanged = request('/v1/simulations/' + simulation['id'])
            assert unchanged['revision'] == 1 and unchanged['inputs']['rpm'] == 5000
            assert unchanged['workflow']['nodes'][3]['config']['model'] == 'bemt'
            assert simulation['geometry_id'] == variant['geometry_id']
            assert simulation['geometry_revision'] == variant['geometry_revision'] == 1
            assert named_run['geometry_id'] == simulation['geometry_id']
            assert named_run['geometry_role'] == 'baseline_input_geometry'
            geometries = request('/v1/projects/' + project['id'] + '/geometries')
            assert len(geometries) == 1 and geometries[0]['canonical_geometry']['diameter_m'] == .25
            revised_inputs = {**inputs, 'diameter': .27}
            revised_geometry = request('/v1/projects/' + project['id'] + '/geometries', {
                'name': 'Rotor geometry', 'inputs': revised_inputs,
                'geometry_id': simulation['geometry_id'], 'expected_geometry_revision': 1})
            assert revised_geometry['geometry_revision'] == 2
            request('/v1/projects/' + project['id'] + '/geometries/' + simulation['geometry_id'] + '/adopt', {
                'geometry_revision': 2, 'simulations': [{'id': variant['id'], 'expected_revision': variant['revision']}]})
            adopted = request('/v1/simulations/' + variant['id'])
            assert adopted['geometry_revision'] == 2 and adopted['inputs']['diameter'] == .27
            assert adopted['inputs']['rpm'] == 6500 and adopted['workflow']['nodes'][3]['config']['model'] == 'llt'
            assert request('/v1/simulations/' + simulation['id']) == unchanged
            historical = request('/v1/runs/' + named_run['id'])
            assert historical['geometry_revision'] == 1 and historical['inputs']['diameter'] == .25
            assert historical['result']['geometry']['diameter_m'] == .25
            assert {a['id'] for a in request('/v1/adapters')} == {'pywake', 'openfast'}
            study_archive = request('/v1/projects/' + project['id'] + '/archive')
            imported = request('/v1/projects/import', {'content_base64': base64.b64encode(study_archive).decode()})
            configurations = request('/v1/projects/' + imported['id'] + '/simulations')
            assert len(configurations) == 2 and {s['name'] for s in configurations} == {'BEMT baseline', 'LLT comparison'}
            assert all(s['project_id'] == imported['id'] for s in configurations)
            assert len({s['geometry_id'] for s in configurations}) == 1
            assert {s['geometry_revision'] for s in configurations} == {1, 2}
            imported_geometries = request('/v1/projects/' + imported['id'] + '/geometries')
            assert len(imported_geometries) == 2
            assert all(g['project_id'] == imported['id'] for g in imported_geometries)
        finally:
            process.terminate()
            try:
                process.wait(timeout=12)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdout:
                    process.stdout.close()
        print('Frozen workflow, shared geometry/revision adoption/history, model isolation, study/comparison, archive and shutdown passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    smoke(args.executable.resolve())
