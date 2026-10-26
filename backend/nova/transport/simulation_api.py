"""Named, revisioned native simulation configurations owned by a project."""
import copy
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field

from nova.application.studies import StudyDefinition
from nova.infrastructure import library
from nova.transport.api import (
    ProjectRequest,
    Request,
    build_optimization_settings,
    checked_project,
    project,
    submit_project_job,
)
from nova.workflow.engine import clone

router = APIRouter(prefix='/api/v1')


class SimulationRequest(ProjectRequest):
    project_id: str = Field(min_length=1)
    expected_revision: int | None = Field(None, ge=0, strict=True)


class CloneRequest(Request):
    name: str | None = Field(None, min_length=1, max_length=120)


class RunRequest(Request):
    expected_revision: int | None = Field(None, ge=1, strict=True)


class SimulationStudyRequest(RunRequest):
    study: StudyDefinition


class SimulationOptimizationRequest(RunRequest):
    solver: Literal['bemt', 'llt', 'vlm', 'bem'] = 'bemt'
    max_iterations: int = Field(180, ge=10, le=1000, strict=True)


@router.get('/projects/{project_id}/simulations')
def project_simulations(project_id: str):
    project(project_id)
    return [s for s in library.list_records('simulation') if s['project_id'] == project_id and s.get('kind', 'propeller') == 'propeller']


@router.get('/simulations/{simulation_id}')
def simulation(simulation_id: str):
    try:
        stored = library.get('simulation', simulation_id)
        if stored.get('kind', 'propeller') != 'propeller':
            raise HTTPException(422, 'External configurations use the v2 simulation API')
        return stored
    except KeyError as exc:
        raise HTTPException(404, 'Simulation not found') from exc


@router.post('/simulations')
def save_simulation(request: SimulationRequest):
    project(request.project_id)
    try:
        if request.id:
            existing = simulation(request.id)
            if existing['project_id'] != request.project_id:
                raise ValueError('Simulation cannot move to another project')
        document = {**checked_project(request), 'project_id': request.project_id}
        return library.save('simulation', document, request.id, request.expected_revision)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        status = 409 if 'Revision conflict' in str(exc) else 422
        raise HTTPException(status, str(exc)) from exc


@router.post('/simulations/{simulation_id}/clone')
def clone_simulation(simulation_id: str, request: CloneRequest):
    original = simulation(simulation_id)
    request = SimulationRequest(name=request.name or (original['name'][:115] + ' Copy'),
                                project_id=original['project_id'], inputs=copy.deepcopy(original['inputs']),
                                workflow=clone(original['workflow']), conditions=copy.deepcopy(original['conditions']),
                                polar_asset_id=original.get('polar_asset_id'), geometry_id=original.get('geometry_id'),
                                geometry_revision=original.get('geometry_revision'))
    return save_simulation(request)


@router.post('/simulations/{simulation_id}/run')
def run_simulation(simulation_id: str, request: RunRequest):
    configuration, metadata = saved_configuration(simulation_id, request)
    return submit_project_job(configuration, simulation_metadata=metadata)


def saved_configuration(simulation_id, request):
    stored = simulation(simulation_id)
    if request.expected_revision is not None and request.expected_revision != stored['revision']:
        raise HTTPException(409, 'Revision conflict; reload before running')
    configuration = ProjectRequest(name=stored['name'], id=stored['project_id'],
                                   inputs=stored['inputs'], workflow=stored['workflow'],
                                   conditions=stored['conditions'], polar_asset_id=stored.get('polar_asset_id'),
                                   geometry_id=stored.get('geometry_id'), geometry_revision=stored.get('geometry_revision'))
    return configuration, {'simulation_id': stored['id'], 'simulation_name': stored['name'], 'simulation_revision': stored['revision']}


@router.post('/simulations/{simulation_id}/study')
def study_simulation(simulation_id: str, request: SimulationStudyRequest):
    configuration, metadata = saved_configuration(simulation_id, request)
    return submit_project_job(configuration, study=request.study.model_dump(exclude_none=True), simulation_metadata=metadata)


@router.post('/simulations/{simulation_id}/optimize')
def optimize_simulation(simulation_id: str, request: SimulationOptimizationRequest):
    configuration, metadata = saved_configuration(simulation_id, request)
    settings = build_optimization_settings(configuration.inputs, request.solver, request.max_iterations)
    return submit_project_job(configuration, optimization=settings, simulation_metadata=metadata)


class SimulationAdoption(Request):
    id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1, strict=True)


class GeometryPublishRequest(Request):
    name: str = Field(min_length=1, max_length=120)
    inputs: dict
    geometry_id: str | None = Field(None, min_length=1)
    expected_geometry_revision: int | None = Field(None, ge=0, strict=True)
    simulations: list[SimulationAdoption] | None = Field(None, min_length=1, max_length=128)


class GeometryAdoptRequest(Request):
    geometry_revision: int = Field(ge=1, strict=True)
    simulations: list[SimulationAdoption] = Field(min_length=1, max_length=128)


@router.get('/projects/{project_id}/geometries')
def project_geometries(project_id: str):
    project(project_id)
    return [g for g in library.list_records('geometry') if g['project_id'] == project_id]


@router.post('/projects/{project_id}/geometries')
def publish_geometry(project_id: str, request: GeometryPublishRequest):
    parent = project(project_id)
    try:
        from nova.workflow.engine import template
        inputs = checked_project(ProjectRequest(name=request.name, inputs=request.inputs, workflow=parent.get('workflow', template()),
                                               conditions=parent.get('conditions', {})))['inputs']
        updates = None
        if request.simulations is not None:
            from nova.core.geometry_assets import geometry_definition
            updates = adoption_updates(project_id, geometry_definition(inputs), request.simulations)
        return library.publish_geometry(project_id, request.name, inputs, request.geometry_id,
                                        request.expected_geometry_revision, updates)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(409 if 'Revision conflict' in str(exc) else 422, str(exc)) from exc


@router.post('/projects/{project_id}/geometries/{geometry_id}/adopt')
def adopt_geometry(project_id: str, geometry_id: str, request: GeometryAdoptRequest):
    project(project_id)
    try:
        geometry = library.get_geometry(project_id, geometry_id, request.geometry_revision)
        updates = adoption_updates(project_id, geometry['definition'], request.simulations)
        updates = [({**document, 'geometry_id': geometry_id, 'geometry_revision': request.geometry_revision}, revision)
                   for document, revision in updates]
        return {'geometry': geometry, 'simulations': library.adopt_geometry(project_id, geometry, updates)}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(409 if 'Revision conflict' in str(exc) else 422, str(exc)) from exc


def adoption_updates(project_id, definition, selections):
    if len({s.id for s in selections}) != len(selections):
        raise ValueError('Select each simulation once')
    updates = []
    for selection in selections:
        original = simulation(selection.id)
        if original['project_id'] != project_id:
            raise ValueError('Simulation belongs to another project')
        inputs = {**original['inputs'], **copy.deepcopy(definition)}
        config = ProjectRequest(name=original['name'], inputs=inputs, workflow=original['workflow'],
                                conditions=original['conditions'], polar_asset_id=original.get('polar_asset_id'))
        document = {**checked_project(config), 'id': original['id'], 'project_id': project_id}
        updates.append((document, selection.expected_revision))
    return updates


class ComparisonRequest(Request):
    name: str = Field('Solver comparison', min_length=1, max_length=120)
    simulations: list[SimulationAdoption] = Field(min_length=2, max_length=8)


def frozen_comparison(project_id, request):
    from nova.application.comparisons import validate_comparison
    parent = project(project_id)
    snapshots = []
    for selected in request.simulations:
        stored = simulation(selected.id)
        if stored['project_id'] != project_id:
            raise HTTPException(422, 'All simulations must belong to this project')
        if stored['revision'] != selected.expected_revision:
            raise HTTPException(409, 'Revision conflict; reload selected simulations')
        checked_project(ProjectRequest(**{k: stored[k] for k in ('name', 'inputs', 'workflow', 'conditions', 'polar_asset_id')}))
        snapshots.append({**copy.deepcopy(stored), 'polar_asset': library.get('asset', stored['polar_asset_id']) if stored.get('polar_asset_id') else None})
    comparison = {'name': request.name, 'simulations': snapshots}
    return parent, comparison, validate_comparison(comparison)


@router.post('/projects/{project_id}/comparisons/validate')
def validate_project_comparison(project_id: str, request: ComparisonRequest):
    try:
        return frozen_comparison(project_id, request)[2]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/projects/{project_id}/comparisons')
def submit_project_comparison(project_id: str, request: ComparisonRequest):
    from nova.infrastructure import jobs
    try:
        parent, comparison, summary = frozen_comparison(project_id, request)
        first = comparison['simulations'][0]
        document = {**copy.deepcopy(first), 'name': request.name, 'project_id': project_id,
                    'project_revision': parent['revision'], 'comparison': comparison,
                    'comparison_validation': summary}
        for key in ('id', 'revision', 'updated_at'):
            document.pop(key, None)
        return jobs.submit(document)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(409 if 'Revision conflict' in str(exc) else 422, str(exc)) from exc


@router.get('/runs/{run_id}/comparison.csv')
def comparison_csv(run_id: str):
    import csv
    import io
    import json

    from fastapi import Response

    from nova.application.comparisons import comparison_rows
    from nova.transport.api import run
    record = run(run_id)
    if not record.get('comparison'):
        raise HTTPException(422, 'This run is not a solver comparison')
    rows = comparison_rows(record)
    output = io.StringIO()
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows({k: json.dumps(v, sort_keys=True) if isinstance(v, dict) else v for k, v in row.items()} for row in rows)
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="solver-comparison.csv"'})
