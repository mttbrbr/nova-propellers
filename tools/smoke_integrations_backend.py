#!/usr/bin/env python3
"""Check optional integrations in a frozen backend; fixtures are not solvers."""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from smoke_desktop_backend import wait_for_endpoint

SOURCE = b'NOVA fixture\nTime GenPwr\n(s) (kW)\n0 10\n1 20\n'
CASE = {'wake_model': 'noj', 'turbine': {'name': 'Fixture', 'diameter_m': 80, 'hub_height_m': 100,
        'wind_speed_m_s': [0, 5, 10, 25], 'power_w': [0, 100, 1000, 1000], 'ct': [.8, .8, .8, .1]},
        'layout': {'x_m': [0], 'y_m': [0]}, 'wind': {'directions_deg': [270], 'speeds_m_s': [5, 10],
        'probabilities': [[.5, .5]], 'turbulence_intensity': .1}}


def smoke(executable, pywake_python=None):
    with tempfile.TemporaryDirectory(prefix='nova-integrations-smoke-') as temporary:
        directory = Path(temporary)
        env = {**os.environ, 'NOVA_SESSION_TOKEN': 'temporary-integration-session'}
        backend = subprocess.Popen([str(executable), '--port', '0', '--data-dir', str(directory / 'library')],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        try:
            endpoint = wait_for_endpoint(backend)
            def request(path, body=None):
                req = urllib.request.Request(endpoint + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json', 'X-Nova-Session': env['NOVA_SESSION_TOKEN']})
                with urllib.request.urlopen(req, timeout=40) as response:
                    payload = response.read()
                    return json.loads(payload) if 'json' in response.headers.get('Content-Type', '') else payload
            def wait(run):
                deadline = time.monotonic() + 60
                while run['state'] in ('queued', 'running', 'cancelling') and time.monotonic() < deadline:
                    time.sleep(.1)
                    run = request('/v1/runs/' + run['id'])
                assert run['state'] == 'succeeded', run
                return run
            assert {a['id'] for a in request('/v1/adapters')} == {'pywake', 'openfast'}
            saved_case = request('/v1/external-cases', {'name': 'Frozen PyWake inputs', 'case': CASE, 'demonstration': True})
            assert saved_case['case'] == CASE and saved_case['demonstration']
            assert request('/v1/external-cases/' + saved_case['id'])['case_hash'] == saved_case['case_hash']
            assert any(case['id'] == saved_case['id'] for case in request('/v1/external-cases'))
            imported = request('/v1/openfast/import', {'filename': 'sample.out', 'content_base64': base64.b64encode(SOURCE).decode()})
            assert imported['result']['data']['values'] == [[10], [20]]
            assert request(f"/v1/external-runs/{imported['id']}/artifacts/source/sample.out") == SOURCE
            assert b'GenPwr [kW]' in request(f"/v1/external-runs/{imported['id']}/csv")
            archive = request(f"/v1/external-runs/{imported['id']}/archive")
            restored = request('/v1/external-runs/import', {'content_base64': base64.b64encode(archive).decode()})
            assert restored['id'] != imported['id'] and restored['imported_from_run'] == imported['id']
            assert restored['external_job']['operation'] == 'portable_import'
            assert restored['result']['data'] == imported['result']['data']
            assert request(f"/v1/external-runs/{restored['id']}/artifacts/source/sample.out") == SOURCE
            inputs = directory / 'input-case'
            inputs.mkdir()
            (inputs / 'main.fst').write_text('NOVA fixture input\n')
            inspection = request('/v1/openfast/inspect', {'case': {
                'case_directory': str(inputs), 'input_file': 'main.fst', 'output_file': 'main.out', 'timeout_seconds': 10}})
            assert inspection['file_count'] == 1 and inspection['input_files'][0]['path'] == 'main.fst'
            selected = directory / 'openfast-fixture'
            selected.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\n'
                'if sys.argv[1:] == ["-v"]:\n print("OpenFAST-v4.1.1")\n raise SystemExit(0)\n'
                'assert sys.argv[1:] == ["case/main.fst"]\nPath("case/main.out").write_bytes(' + repr(SOURCE) + ')\n')
            selected.chmod(0o755)
            configuration = request('/v1/adapters/openfast/configure', {'executable': str(selected), 'environment_kind': 'local_executable'})
            executed = wait(request('/v1/external-runs', {'integration_id': configuration['id'], 'case': {
                'case_directory': str(inputs), 'input_file': 'main.fst', 'output_file': 'main.out', 'timeout_seconds': 10}}))
            assert executed['result']['data']['values'] == [[10], [20]]
            assert json.loads(request(f"/v1/external-runs/{executed['id']}/artifacts/workflow.json")) == executed['workflow']
            if pywake_python is None:
                selected = directory / 'python-fixture'
                selected.write_text('#!' + sys.executable + '\nimport json,sys\nfrom pathlib import Path\n'
                    'if sys.argv[1] == "-c":\n print(json.dumps({"available":True,"compatible":True,"version":"2.6.fixture"}))\n'
                    'else:\n'
                    ' c=json.loads(Path("input.json").read_text())\n'
                    ' out={"power_w":[[[100,1000]]],"effective_speed_m_s":[[[5,10]]],"power_without_wakes_w":[[[100,1000]]],'
                    '"program_version":"2.6.fixture",**{k:c["wind"][k] for k in ("directions_deg","speeds_m_s","probabilities")}}\n'
                    ' Path("output.json").write_text(json.dumps(out))\n')
                selected.chmod(0o755)
            else:
                selected = pywake_python
            configuration = request('/v1/adapters/pywake/configure', {'executable': str(selected), 'environment_kind': 'python_environment'})
            result = wait(request('/v1/external-runs', {'integration_id': configuration['id'], 'case': CASE}))
            assert abs(result['result']['data']['total_aep_gwh'] - .004818) < 1e-10
            assert request('/v1/runs/' + result['id'])['result'] == result['result']
            assert b'power_W' in request(f"/v1/external-runs/{result['id']}/csv")
        finally:
            backend.terminate()
            try:
                backend.wait(timeout=12)
            finally:
                if backend.poll() is None:
                    backend.kill()
                    backend.wait()
                backend.stdout.close()
    print('Frozen integrations, output import, external worker protocol, CSV/artifacts and shutdown passed.'
          + (' PyWake real environment used.' if pywake_python else ' External execution fixtures used.'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    parser.add_argument('--pywake-python', type=Path)
    args = parser.parse_args()
    smoke(args.executable.resolve(), args.pywake_python)
