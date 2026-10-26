#!/usr/bin/env python3
"""Qualify an independently installed OpenFAST through NOVA and direct execution.

No solver, official input files, binaries or numerical outputs belong in the
repository. The executable, selected case and report must all be external.
"""
import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from smoke_desktop_backend import wait_for_endpoint

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def qualify(args):
    import numpy as np

    executable, case_directory, report = (p.expanduser().resolve() for p in
                                          (args.executable, args.case_directory, args.report))
    if any(path.is_relative_to(ROOT) for path in (executable, case_directory, report)):
        raise ValueError('Keep OpenFAST, its input cases and qualification artifacts outside the NOVA repository')
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('Select an existing executable OpenFAST program')
    if report.exists():
        raise ValueError('Choose a new report path; earlier qualification evidence is preserved')
    if not 0 < args.timeout <= 3600:
        raise ValueError('Timeout must be positive and at most 3600 seconds')
    report.parent.mkdir(parents=True, exist_ok=True)
    session = report.parent / ('nova-openfast-' + uuid.uuid4().hex[:12])
    session.mkdir()
    token = secrets.token_urlsafe(24)
    env = {**os.environ, 'NOVA_SESSION_TOKEN': token, 'NOVA_DB_PATH': str(session / 'library/nova.db'),
           'NOVA_LOG_LEVEL': 'warning', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}
    backend_command = [str(args.backend.resolve())] if args.backend else [sys.executable, str(ROOT / 'backend/desktop_launcher.py')]
    backend_command += ['--port', '0', '--data-dir', str(session / 'library')]
    backend = subprocess.Popen(backend_command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True)
    evidence = {'state': 'running', 'executable': str(executable), 'executable_sha256': digest(executable),
                'case_directory': str(case_directory), 'session_directory': str(session),
                'backend_mode': 'frozen' if args.backend else 'source',
                'scope': 'One declared case: NOVA versus the same independently installed OpenFAST executable; not global solver certification'}
    try:
        endpoint = wait_for_endpoint(backend)

        def request(path, payload=None):
            data = json.dumps(payload).encode() if payload is not None else None
            req = urllib.request.Request(endpoint + path, data=data, headers={
                'Content-Type': 'application/json', 'X-Nova-Session': token})
            try:
                with urllib.request.urlopen(req, timeout=args.timeout + 10) as response:
                    raw = response.read()
                    return json.loads(raw) if 'json' in response.headers.get('Content-Type', '') else raw
            except urllib.error.HTTPError as exc:
                details = exc.read(4096).decode('utf-8', errors='replace')
                raise RuntimeError(f'{path}: HTTP {exc.code}: {details}') from exc

        def wait_run(record):
            deadline = time.monotonic() + args.timeout + 30
            while record['state'] in ('queued', 'running', 'cancelling') and time.monotonic() < deadline:
                time.sleep(.1)
                record = request('/v1/runs/' + record['id'])
            if record['state'] != 'succeeded':
                raise RuntimeError(record.get('error') or f"NOVA run ended {record['state']}")
            return record

        definition = {'case_directory': str(case_directory), 'input_file': args.input_file,
                      'output_file': args.output_file, 'timeout_seconds': args.timeout}
        inspection = request('/v1/openfast/inspect', {'case': definition})
        evidence['inspection'] = inspection
        reference = session / 'direct-case'
        reference.mkdir()
        for item in inspection['input_files']:
            source, target = case_directory / item['path'], reference / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if digest(source) != item['sha256']:
                raise ValueError('Case changed after inspection')
            shutil.copy2(source, target)
            if digest(target) != item['sha256']:
                raise ValueError('Reference input copy differs from inspected source')
        direct_env = {key: value for key, value in env.items() if not key.startswith('NOVA_')}
        with (session / 'direct.log').open('w') as log:
            direct = subprocess.Popen([str(executable), args.input_file], cwd=reference, env=direct_env,
                                      stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                direct.wait(timeout=args.timeout)
                if direct.returncode != 0:
                    raise RuntimeError(f'Direct OpenFAST exited {direct.returncode}; see {session / "direct.log"}')
            finally:
                stop(direct)
        integration = request('/v1/adapters/openfast/configure', {
            'executable': str(executable), 'environment_kind': 'local_executable'})
        evidence['program'] = integration['probe']
        if args.project_mode:
            project_source = session / 'project-source-case'
            for item in inspection['input_files']:
                target = project_source / item['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(reference / item['path'], target)
                if digest(target) != item['sha256']:
                    raise ValueError('Project source inputs differ from the direct reference')
            project = request('/v2/projects', {'name': 'Independent OpenFAST qualification'})
            simulation = request('/v2/simulations', {
                'project_id': project['id'], 'name': 'OpenFAST AOC baseline', 'kind': 'openfast',
                'configuration': {'case': {**definition, 'case_directory': str(project_source)}}})
            if 'case_directory' in simulation['configuration']['case']:
                raise ValueError('Saved simulation still depends on its source directory')
            # Only remove the test-owned copy, never the installed source case.
            shutil.rmtree(project_source)
            cloned = request(f"/v2/simulations/{simulation['id']}/clone", {'name': 'Independent configuration copy'})
            if cloned['id'] == simulation['id'] or cloned['configuration']['asset_id'] != simulation['configuration']['asset_id']:
                raise ValueError('Cloned simulation does not retain the immutable scientific asset')
            run = request(f"/v2/simulations/{simulation['id']}/run", {
                'expected_revision': simulation['revision'], 'integration_id': integration['id']})
            if run['project_id'] != project['id'] or run['simulation_id'] != simulation['id'] or run['simulation_revision'] != simulation['revision']:
                raise ValueError('Project execution lineage differs from the saved configuration')
            evidence['project'] = {'id': project['id'], 'simulation_id': simulation['id'],
                                   'clone_id': cloned['id'], 'source_removed_after_save': True}
        else:
            run = request('/v1/external-runs', {'integration_id': integration['id'], 'case': definition})
        run = wait_run(run)
        evidence.update(run_id=run['id'], run_state=run['state'])
        if run['state'] != 'succeeded':
            raise RuntimeError(run.get('error') or f"NOVA run ended {run['state']}")
        if run['inputs']['input_hashes'] != {item['path']: item['sha256'] for item in inspection['input_files']}:
            raise ValueError('Queued inputs differ from inspected reference inputs')
        # Parse the independently generated reference with the same documented
        # importer; this checks orchestration, not independent parser accuracy.
        sys.path.insert(0, str(ROOT / 'backend'))
        from nova.adapters.openfast import read_openfast_output
        baseline = read_openfast_output(reference / args.output_file)
        result = run['result']['data']
        if len(result['time_s']) < 2:
            raise ValueError('Qualification requires at least two output samples; check TStart, TMax and DT_Out')
        if result['channels'] != baseline['channels']:
            raise ValueError('Direct/NOVA channel metadata differ')
        actual, expected = np.asarray(result['values']), np.asarray(baseline['values'])
        if result['time_s'] != baseline['time_s'] or actual.shape != expected.shape or not np.allclose(actual, expected, rtol=1e-9, atol=1e-10):
            raise ValueError('Direct/NOVA sampled results differ beyond rtol=1e-9, atol=1e-10')
        evidence['comparison'] = {'samples': len(result['time_s']), 'channels': len(result['channels']),
                                  'time_start_s': result['time_s'][0], 'time_end_s': result['time_s'][-1],
                                  'maximum_absolute_difference': float(np.max(np.abs(actual - expected))),
                                  'rtol': 1e-9, 'atol': 1e-10}
        archive = request(f"/v1/external-runs/{run['id']}/archive")
        (session / 'result.nova-run').write_bytes(archive)
        restored = request('/v1/external-runs/import', {'content_base64': base64.b64encode(archive).decode()})
        if restored['result']['data'] != result or restored['id'] == run['id']:
            raise ValueError('Portable result restoration differs')
        restored_source = request(f"/v1/external-runs/{restored['id']}/artifacts/case/{args.output_file}")
        if hashlib.sha256(restored_source).hexdigest() != result['source']['sha256']:
            raise ValueError('Restored raw OpenFAST output differs from executed source')
        if args.project_mode:
            project_archive = request(f"/v2/projects/{project['id']}/archive")
            (session / 'project.nova').write_bytes(project_archive)
            imported = request('/v2/projects/import', {'content_base64': base64.b64encode(project_archive).decode()})
            imported_simulations = request(f"/v2/projects/{imported['id']}/simulations")
            if imported['id'] == project['id'] or len(imported_simulations) != 2:
                raise ValueError('Mixed project import did not restore independent configurations')
            imported_simulation = next(s for s in imported_simulations if s['name'] == simulation['name'])
            imported_runs = request(f"/v2/projects/{imported['id']}/runs")
            historical = next(r for r in imported_runs if r.get('simulation_id') == imported_simulation['id'])
            if historical.get('simulation_revision') != simulation['revision'] or historical.get('simulation_name') != simulation['name']:
                raise ValueError('Project archive lost the historical simulation revision or name')
            if historical['result']['data'] != result:
                raise ValueError('Project archive changed the historical scientific result')
            imported_raw = request(f"/v1/external-runs/{historical['id']}/artifacts/case/{args.output_file}")
            if hashlib.sha256(imported_raw).hexdigest() != result['source']['sha256']:
                raise ValueError('Project archive changed the original OpenFAST output bytes')
            rerun = wait_run(request(f"/v2/simulations/{imported_simulation['id']}/run", {
                'expected_revision': imported_simulation['revision'], 'integration_id': integration['id']}))
            rerun_data = rerun['result']['data']
            if any(rerun_data[key] != result[key] for key in ('channels', 'time_s', 'values')):
                raise ValueError('Reopened project produced different scientific samples')
            evidence['project'].update(imported_id=imported['id'], rerun_id=rerun['id'],
                archive_sha256=hashlib.sha256(project_archive).hexdigest(),
                imported_history_and_raw_bytes_match=True, reopened_case_execution_matches=True)
        if digest(executable) != evidence['executable_sha256']:
            raise ValueError('OpenFAST executable changed during qualification')
        evidence.update(state='passed', restored_run_id=restored['id'],
                        archive_sha256=hashlib.sha256(archive).hexdigest(),
                        provenance=run['result']['provenance'])
    except Exception as exc:
        evidence.update(state='failed', error=str(exc))
        raise
    finally:
        stop(backend)
        if backend.stdout:
            backend.stdout.close()
        evidence['backend_stopped'] = backend.poll() is not None
        report.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'state': evidence['state'], 'report': str(report), 'comparison': evidence['comparison']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--case-directory', type=Path, required=True)
    parser.add_argument('--input-file', required=True)
    parser.add_argument('--output-file', required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--backend', type=Path, help='Optional frozen NOVA backend instead of source')
    parser.add_argument('--project-mode', action='store_true', help='Also qualify saved v2 simulations, source independence and mixed project archive restoration')
    qualify(parser.parse_args())
