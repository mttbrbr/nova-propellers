"""Neutral projects and typed configurations over the existing job coordinator."""
import base64
import copy
import io
import json
import uuid
import zipfile
from typing import Literal

import database
from fastapi import APIRouter, HTTPException, Response
from pydantic import Field

from nova.adapters.registry import get as adapter_for
from nova.application.external import configuration as local_configuration
from nova.application.simulation_cases import freeze_case, materialize_asset, revise_case, validate_asset
from nova.core.data import content_hash
from nova.infrastructure import jobs, library
from nova.transport.api import ProjectRequest, Request, checked_project, project
from nova.transport.external_api import discard_unreferenced
from nova.transport.simulation_api import CloneRequest, RunRequest, run_simulation as run_native
from nova.workflow.engine import external_template

router = APIRouter(prefix='/api/v2')
ERRORS = (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError, OverflowError)


def invalid(exc):
    return HTTPException(409 if 'Revision conflict' in str(exc) else 422, str(exc))


class NeutralProjectRequest(Request):
    name: str = Field(min_length=1, max_length=120)
    id: str | None = None
    expected_revision: int | None = Field(None, ge=0, strict=True)


class TypedSimulationRequest(NeutralProjectRequest):
    project_id: str = Field(min_length=1)
    kind: Literal['propeller', 'openfast', 'pywake']
    configuration: dict


class TypedRunRequest(RunRequest):
    integration_id: str | None = None


def typed(stored):
    if stored.get('kind') in ('openfast', 'pywake'):
        return stored
    return {**stored, 'kind': 'propeller', 'configuration': {key: stored[key] for key in
        ('inputs', 'workflow', 'conditions', 'polar_asset_id', 'geometry_id', 'geometry_revision') if key in stored}}


@router.get('/projects')
def projects():
    return library.list_records('project')


@router.get('/projects/{project_id}')
def get_project(project_id: str):
    return project(project_id)


@router.post('/projects')
def save_project(request: NeutralProjectRequest):
    try:
        previous = project(request.id) if request.id else {}
        return library.save('project', {**previous, 'schema_version': 2, 'name': request.name},
                            request.id, request.expected_revision)
    except ERRORS as exc:
        raise invalid(exc) from exc


@router.get('/projects/{project_id}/simulations')
def simulations(project_id: str):
    project(project_id)
    return [typed(s) for s in library.list_records('simulation') if s['project_id'] == project_id]


@router.get('/simulations/{simulation_id}')
def simulation(simulation_id: str):
    try:
        return typed(library.get('simulation', simulation_id))
    except KeyError as exc:
        raise HTTPException(404, 'Simulation not found') from exc


@router.post('/simulations')
def save_simulation(request: TypedSimulationRequest):
    project(request.project_id)
    try:
        if request.id:
            previous = simulation(request.id)
            if previous['project_id'] != request.project_id or previous['kind'] != request.kind:
                raise ValueError('Simulation ownership and kind cannot change')
        document = {'schema_version': 2, 'name': request.name, 'project_id': request.project_id, 'kind': request.kind}
        new_asset = None
        if request.kind == 'propeller':
            validated = checked_project(ProjectRequest(name=request.name, **request.configuration))
            document.update(validated)
            document.update(schema_version=2, configuration={key: validated[key] for key in
                ('inputs', 'workflow', 'conditions', 'polar_asset_id', 'geometry_id', 'geometry_revision') if key in validated})
        else:
            config = request.configuration
            if set(config) - {'case', 'asset_id', 'notes', 'demonstration'}:
                raise ValueError('Scientific configuration cannot contain local software settings')
            if config.get('asset_id'):
                asset = library.get('asset', config['asset_id'])
                validate_asset(asset)
                if asset['kind'] != request.kind:
                    raise ValueError('Scientific asset kind differs from simulation')
                case = config.get('case', asset['case'])
                notes = config.get('notes', asset.get('notes', ''))
                demonstration = config.get('demonstration', asset.get('demonstration', False))
                if case != asset['case'] or notes != asset.get('notes', '') or demonstration != asset.get('demonstration', False):
                    payload = revise_case(asset, case, notes=notes, demonstration=demonstration)
                    new_asset = asset = {**payload, 'content_hash': content_hash(payload), 'id': str(uuid.uuid4()),
                                         'revision': 1, 'updated_at': library.now()}
            else:
                payload = {**freeze_case(request.kind, request.name, config['case'],
                    notes=config.get('notes', ''), demonstration=config.get('demonstration', False)), 'schema_version': 1}
                new_asset = asset = {**payload, 'content_hash': content_hash(payload), 'id': str(uuid.uuid4()),
                                     'revision': 1, 'updated_at': library.now()}
            document.update(asset_id=asset['id'], asset_ids=[asset['id']],
                configuration={'case': asset['case'], 'asset_id': asset['id'],
                               'notes': asset.get('notes', ''), 'demonstration': asset.get('demonstration', False)},
                workflow=external_template(request.kind))
        return typed(library.save('simulation', document, request.id, request.expected_revision, new_asset=new_asset))
    except ERRORS as exc:
        raise invalid(exc) from exc


@router.post('/simulations/{simulation_id}/clone')
def clone_simulation(simulation_id: str, request: CloneRequest):
    stored = simulation(simulation_id)
    return save_simulation(TypedSimulationRequest(project_id=stored['project_id'], kind=stored['kind'],
        name=request.name or stored['name'][:115] + ' Copy', configuration=copy.deepcopy(stored['configuration'])))


@router.post('/simulations/{simulation_id}/run')
def run_simulation(simulation_id: str, request: TypedRunRequest):
    stored = simulation(simulation_id)
    if request.expected_revision is not None and request.expected_revision != stored['revision']:
        raise HTTPException(409, 'Revision conflict; reload before running')
    if stored['kind'] == 'propeller':
        return run_native(simulation_id, RunRequest(expected_revision=request.expected_revision))
    root = None
    try:
        if not request.integration_id:
            raise ValueError('Select a configured external installation for this run')
        integration = library.get('integration', request.integration_id)
        if integration['adapter_id'] != stored['kind']:
            raise ValueError('Selected installation does not match simulation kind')
        asset = library.get('asset', stored['asset_id'])
        root = database.DB_PATH.parent / 'external-runs' / str(uuid.uuid4())
        root.mkdir(parents=True)
        inputs = materialize_asset(asset, root / 'source_case')
        adapter_for(stored['kind']).validate(inputs, local_configuration(integration))
        return jobs.submit({'schema_version': 2, 'name': stored['name'], 'project_id': stored['project_id'],
            'project_revision': project(stored['project_id'])['revision'],
            'simulation_id': stored['id'], 'simulation_name': stored['name'], 'simulation_revision': stored['revision'],
            'simulation_kind': stored['kind'], 'asset_id': asset['id'], 'asset_ids': [asset['id']],
            'input_hash': asset['case_hash'], 'workflow': stored['workflow'], 'inputs': inputs,
            'external_job': {'adapter_id': stored['kind'], 'configuration': {
                key: integration[key] for key in ('executable', 'environment_kind', 'options')},
                'integration_id': integration['id'], 'artifact_root': str(root.resolve())}})
    except ERRORS as exc:
        discard_unreferenced(root)
        raise invalid(exc) from exc


class RunAssociation(Request):
    run_id: str = Field(min_length=1)


@router.post('/projects/{project_id}/runs')
def associate_run(project_id: str, request: RunAssociation):
    project(project_id)
    try:
        run = library.get('run', request.run_id)
        if run['state'] not in ('succeeded', 'failed', 'cancelled', 'interrupted'):
            raise ValueError('Only historical executions can be associated')
        if run.get('project_id') not in (None, project_id):
            raise ValueError('Associate a standalone execution; project-owned executions retain their existing project')
        existing = next((link for link in library.list_records('run_link')
                         if link['project_id'] == project_id and link['run_id'] == request.run_id), None)
        return existing or library.save('run_link', {'project_id': project_id, 'run_id': request.run_id,
                                                    'relationship': 'historical_association'})
    except ERRORS as exc:
        raise invalid(exc) from exc


@router.get('/projects/{project_id}/runs')
def project_runs(project_id: str):
    project(project_id)
    linked = {link['run_id'] for link in library.list_records('run_link') if link['project_id'] == project_id}
    return [run for run in library.list_records('run') if run.get('project_id') == project_id or run['id'] in linked]


@router.get('/projects/{project_id}/archive')
def archive(project_id: str):
    from nova.infrastructure.mixed_archives import export_project
    project(project_id)
    try:
        return Response(export_project(project_id), media_type='application/zip',
                        headers={'Content-Disposition': 'attachment; filename="project.nova"'})
    except ERRORS as exc:
        raise invalid(exc) from exc


class ArchiveImport(Request):
    content_base64: str = Field(max_length=180_000_000)


@router.post('/projects/import')
def import_archive(request: ArchiveImport):
    from nova.infrastructure.mixed_archives import import_project
    from nova.transport.api import ArchiveImport as LegacyImport, import_archive as import_legacy
    try:
        content = base64.b64decode(request.content_base64, validate=True)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            info = archive.getinfo('manifest.json')
            if info.file_size > 1_000_000:
                raise ValueError('Archive manifest too large')
            version = json.loads(archive.read(info)).get('schema_version')
        if version == 1:
            return import_legacy(LegacyImport(content_base64=request.content_base64))
        return import_project(content)
    except (*ERRORS, zipfile.BadZipFile) as exc:
        raise invalid(exc) from exc
