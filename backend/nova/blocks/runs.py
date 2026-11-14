"""Background execution of block workflows with progress and cancellation.

Runs live in this process only: they report progress while the application is
open and are not persisted. Finished runs are evicted oldest-first.
"""
import threading
import time
import uuid

from . import engine

MAX_RUNS = 20
_runs = {}
_lock = threading.Lock()


def _public(run):
    return {key: run[key] for key in ('id', 'state', 'progress', 'message', 'node', 'started_at', 'finished_at', 'result', 'error')}


def start(workflow):
    engine.validate(workflow)
    run = {'id': uuid.uuid4().hex, 'state': 'running', 'progress': 0.0, 'message': 'Starting', 'node': None,
           'started_at': time.time(), 'finished_at': None, 'result': None, 'error': None, 'cancel': threading.Event()}

    def progress(event):
        run.update(progress=float(event.get('progress', run['progress'])), message=str(event.get('message', ''))[-300:], node=event.get('node', run['node']))

    def work():
        try:
            run['result'] = engine.execute(workflow, progress=progress, cancelled=run['cancel'].is_set)
            run.update(state='succeeded', progress=1.0, message='Finished')
        except InterruptedError:
            run.update(state='cancelled', message='Cancelled')
        except Exception as exc:  # the thread must always leave a terminal state
            run.update(state='failed', error=str(exc) or exc.__class__.__name__, message='Failed')
        finally:
            run['finished_at'] = time.time()

    with _lock:
        finished = sorted((r for r in _runs.values() if r['state'] != 'running'), key=lambda r: r['started_at'])
        for old in finished[:max(0, len(_runs) + 1 - MAX_RUNS)]:
            del _runs[old['id']]
        _runs[run['id']] = run
    threading.Thread(target=work, name=f'blocks-{run["id"][:8]}', daemon=True).start()
    return _public(run)


def get(run_id):
    run = _runs.get(run_id)
    if run is None:
        raise KeyError(run_id)
    return _public(run)


def cancel(run_id):
    run = _runs.get(run_id)
    if run is None:
        raise KeyError(run_id)
    if run['state'] == 'running':
        run['cancel'].set()
        run['message'] = 'Cancelling'
    return _public(run)
