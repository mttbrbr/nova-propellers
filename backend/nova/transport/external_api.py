"""Optional scientific integrations, separate from propeller project transport."""
import base64
import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import Field

import database
from nova.adapters.base import safe_artifact
from nova.adapters.openfast import copy_openfast_case, inspect_openfast_case, read_openfast_bytes
from nova.adapters.registry import get
from nova.application.external import configuration, result_csv
from nova.core.data import canonical_json
from nova.infrastructure import jobs, library
from nova.transport.api import Request, run
from nova.workflow.engine import external_template

router = APIRouter(prefix='/api/v1')


def discard_unreferenced(root):
    if root is None:
        return
    # Shutdown may interrupt submission after the immutable snapshot is stored.
    # Keep inputs referenced by that record for diagnosis/recovery.
    try:
        referenced = any((r.get('external_job') or {}).get('artifact_root') == str(root.resolve())
                         for r in library.list_records('run'))
    except Exception:
        return
    if not referenced:
        shutil.rmtree(root, ignore_errors=True)


class ExternalRunRequest(Request):
    integration_id: str
    case: dict


class OpenFASTInspectRequest(Request):
    case: dict


@router.post('/openfast/inspect')
def inspect_openfast(request: OpenFASTInspectRequest):
    try:
        return inspect_openfast_case(request.case)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, OverflowError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/external-runs')
def external_runs():
    return [record for record in library.list_records('run') if record.get('external_job')]


@router.post('/external-runs')
def submit_external_run(request: ExternalRunRequest):
    root = None
    try:
        integration = library.get('integration', request.integration_id)
        adapter = get(integration['adapter_id'])
        adapter.validate(request.case, configuration(integration))
        root = database.DB_PATH.parent / 'external-runs' / str(uuid.uuid4())
        root.mkdir(parents=True)
        inputs = request.case
        if integration['adapter_id'] == 'openfast':
            inputs = copy_openfast_case(request.case, root / 'source_case')
        return jobs.submit({'name': adapter.describe().name + ' analysis', 'project_id': None,
                            'workflow': external_template(integration['adapter_id']), 'inputs': inputs,
                            'external_job': {'adapter_id': integration['adapter_id'], 'configuration': {
                                key: integration[key] for key in ('executable', 'environment_kind', 'options')},
                                'integration_id': request.integration_id, 'artifact_root': str(root.resolve())}})
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        discard_unreferenced(root)
        raise HTTPException(422, str(exc)) from exc


class OpenFASTImportRequest(Request):
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(max_length=28_000_000)


@router.post('/openfast/import')
def import_openfast(request: OpenFASTImportRequest):
    root = None
    try:
        filename = request.filename
        if Path(filename).name != filename or '\\' in filename or Path(filename).suffix.lower() not in ('.out', '.outb'):
            raise ValueError('Select an OpenFAST .out or .outb file with a plain filename')
        source = base64.b64decode(request.content_base64, validate=True)
        if len(source) > 20 * 1024 * 1024:
            raise ValueError('Imported outputs are limited to 20 MiB')
        data = read_openfast_bytes(source, filename)
        root = database.DB_PATH.parent / 'external-runs' / str(uuid.uuid4())
        root.mkdir(parents=True)
        (root / 'source').mkdir()
        source_name = 'source/' + filename
        (root / source_name).write_bytes(source)
        provenance = {'state': 'imported', 'source_sha256': hashlib.sha256(source).hexdigest(),
                      'source_filename': filename, 'operation': 'OpenFAST output import', 'solver_version': None}
        (root / 'execution.json').write_text(canonical_json(provenance))
        (root / 'result.json').write_text(canonical_json(data))
        result = {'kind': 'external', 'schema_version': 1, 'adapter_id': 'openfast', 'data': data,
                  'provenance': provenance, 'working_directory': str(root.resolve()),
                  'artifacts': [source_name, 'execution.json', 'result.json']}
        return library.save('run', {'schema_version': 1, 'name': filename, 'project_id': None, 'inputs': {},
                                    'external_job': {'adapter_id': 'openfast', 'operation': 'import', 'artifact_root': str(root.resolve())},
                                    'state': 'succeeded', 'progress': 1., 'logs': ['Imported output; no solver executed'],
                                    'created_at': library.now(), 'finished_at': library.now(), 'result': result})
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        discard_unreferenced(root)
        raise HTTPException(422, str(exc)) from exc


@router.get('/external-runs/{id}/csv')
def external_csv(id: str):
    result = run(id).get('result') or {}
    if result.get('kind') != 'external' or not result.get('data'):
        raise HTTPException(404, 'Run has no normalized external result')
    return Response(result_csv(result['data']), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="external-results.csv"'})


@router.get('/external-runs/{id}/artifacts/{filename:path}')
def external_artifact(id: str, filename: str):
    record = run(id)
    result = record.get('result') or {}
    if result.get('kind') != 'external' or filename not in result.get('artifacts', []):
        raise HTTPException(404, 'Artifact not found')
    directory = Path(result['working_directory']).resolve()
    root = Path(record['external_job']['artifact_root']).resolve()
    if not directory.is_relative_to(root):
        raise HTTPException(404, 'Artifact not found')
    try:
        path = safe_artifact(directory, filename)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(404, 'Artifact unavailable') from exc
    return FileResponse(path, filename=path.name, media_type='application/octet-stream')
