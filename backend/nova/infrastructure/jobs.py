"""One local worker at a time; coordinator owns all SQLite writes."""
import copy
import json
import os
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nova.infrastructure import library
from nova.workflow.engine import validate

_executor = None
_accepting = False
_lock = threading.RLock()
_controls = {}


def start():
    global _executor, _accepting
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='nova-run')
        _accepting = True


def _terminate(process):
    try:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    def force_stop():
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    timer = threading.Timer(5, force_stop)
    timer.daemon = True
    timer.start()


def submit(snapshot):
    with _lock:
        if not _accepting:
            raise ValueError('Workflow service is shutting down')
    validate(snapshot['workflow'])
    if snapshot.get('comparison'):
        from nova.application.comparisons import validate_comparison
        validate_comparison(snapshot['comparison'])
    if snapshot.get('external_job'):
        from nova.application.external import validate_job
        validate_job(snapshot['external_job'], snapshot['inputs'])
    if snapshot.get('study'):
        from nova.application.studies import build_cases
        build_cases(snapshot, snapshot['study'])
    record = library.save('run', {**copy.deepcopy(snapshot), 'schema_version': 1,
                                 'state': 'queued', 'progress': 0, 'logs': [], 'created_at': library.now()})
    control = {'cancel': threading.Event(), 'process': None}
    with _lock:
        if not _accepting:
            library.save('run', {**record, 'state': 'interrupted'}, record['id'])
            raise ValueError('Workflow service is shutting down')
        _controls[record['id']] = control
        _executor.submit(_run, record['id'], control)
    return record


def _worker_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--workflow-worker']
    return [sys.executable, '-m', 'nova.workflow.worker']


def _run(id, control):
    with _lock:
        record = library.get('run', id)
        if control['cancel'].is_set():
            library.save('run', {**record, 'state': 'cancelled', 'finished_at': library.now()}, id)
            _controls.pop(id, None)
            return
        record = library.save('run', {**record, 'state': 'running', 'started_at': library.now()}, id)
    try:
        command = _worker_command()
        env = dict(os.environ)
        root = str(Path(__file__).resolve().parents[2])
        env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, start_new_session=True, env=env)
        with _lock:
            control['process'] = process
            if control['cancel'].is_set():
                _terminate(process)
        process.stdin.write(json.dumps(record, allow_nan=False))
        process.stdin.close()
        result, error, diagnostics = None, None, None
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                message = {'event': {'message': line.strip()[:2000]}}
            if 'event' in message:
                record['logs'] = (record['logs'] + [message['event']['message']])[-200:]
                record['progress'] = message['event'].get('progress', record['progress'])
                with _lock:
                    record['state'] = 'cancelling' if control['cancel'].is_set() else 'running'
                    library.save('run', record, id)
            if 'checkpoint' in message:
                result = message['checkpoint']
                with _lock:
                    record['result'] = result
                    record['state'] = 'cancelling' if control['cancel'].is_set() else 'running'
                    library.save('run', record, id)
            if 'result' in message:
                result = message['result']
            if 'error' in message:
                error, diagnostics = message['error'], message.get('diagnostics')
        process.stdout.close()
        code = process.wait()
        record.update(result=result, error=error, diagnostics=diagnostics,
                      state='cancelled' if control['cancel'].is_set() else ('succeeded' if code == 0 and result else 'failed'))
    except Exception as exc:
        record.update(state='cancelled' if control['cancel'].is_set() else 'failed', error=str(exc))
    finally:
        with _lock:
            process = control['process']
            if process:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                if process.stdout and not process.stdout.closed:
                    process.stdout.close()
            if record['state'] == 'succeeded':
                record['progress'] = 1
            if record.get('external_job') and not record.get('result') and record['state'] != 'succeeded':
                from nova.application.external import failure_artifacts
                exception = InterruptedError('Run cancelled') if record['state'] == 'cancelled' else RuntimeError(record.get('error') or 'Worker exited before returning a result')
                record['result'] = failure_artifacts(exception, record['external_job'])
            if (record.get('result') or {}).get('kind') == 'study' and record['result']['study_status'] == 'running':
                record['result']['study_status'] = 'interrupted' if record['state'] == 'failed' else record['state']
            if (record.get('result') or {}).get('kind') == 'comparison':
                from nova.application.comparisons import comparison_rows
                if record['result']['comparison_status'] == 'running':
                    record['result']['comparison_status'] = 'interrupted' if record['state'] == 'failed' else record['state']
                record['result']['rows'] = comparison_rows(record)
            record['finished_at'] = library.now()
            library.save('run', record, id)
            _controls.pop(id, None)


def cancel(id):
    with _lock:
        record = library.get('run', id)
        control = _controls.get(id)
        if control:
            control['cancel'].set()
            record = library.save('run', {**record, 'state': 'cancelling'}, id)
            process = control['process']
            if process and process.poll() is None:
                _terminate(process)
        return record


def shutdown():
    global _executor, _accepting
    with _lock:
        _accepting = False
        ids = list(_controls)
        executor = _executor
    for id in ids:
        cancel(id)
    if executor:
        executor.shutdown(wait=True)
    _executor = None
