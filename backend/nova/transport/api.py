"""Versioned desktop interfaces over library and workflow services."""
import base64
import hashlib
import zipfile

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from nova.application.studies import (
    StudyDefinition,
    build_cases,
    comparison_rows,
    validate_study_result,
)
from nova.core.data import content_hash
from nova.core.polars import parse_polar, validate_points
from nova.infrastructure import jobs, library
from nova.workflow.engine import clone, registry, template, validate

router = APIRouter(prefix='/api/v1')


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ProjectRequest(Request):
    name: str = Field(min_length=1, max_length=120)
    inputs: dict
    workflow: dict
    polar_asset_id: str | None = None
    conditions: dict = Field(default_factory=dict)
    id: str | None = None
    expected_revision: int | None = None
    geometry_id: str | None = Field(None, min_length=1)
    geometry_revision: int | None = Field(None, ge=1, strict=True)


class ImportRequest(Request):
    content: str = Field(max_length=5_000_000)
    filename: str = Field(max_length=200)
    airfoil: str = Field(min_length=1, max_length=80)
    format: str = 'csv'
    reynolds: float | None = Field(None, gt=0)
    mach: float = Field(.03, ge=0, le=.8)
    ncrit: float = Field(9, gt=0, le=14)
    mapping: dict | None = None
    commit: bool = False


def checked_project(request, asset_lookup=None):
    # Share the constrained design contract with headless services.
    from nova.core.design import GeometryRequest
    inputs = GeometryRequest(**request.inputs).model_dump()
    # Freeze loft coordinates, rather than resolving mutable airfoils in a worker.
    from database import get_airfoil
    archive_mode = asset_lookup is not None
    asset_lookup = asset_lookup or (lambda id: library.get('asset', id))
    asset_ids = []
    for assignment in inputs.get('airfoil_assignments', []):
        if not assignment.get('coordinates'):
            assignment['coordinates'] = get_airfoil(assignment['airfoil'])['coordinates']
        if not assignment.get('coordinates'):
            raise ValueError('Airfoil assignment has no coordinates')
        import numpy as np
        coords = np.asarray(assignment['coordinates'], dtype=float)
        if coords.ndim != 2 or coords.shape[1] != 2 or len(coords) < 8 or not np.all(np.isfinite(coords)):
            raise ValueError('Airfoil coordinates must be finite Nx2 with at least 8 points')
        if not assignment.get('asset_id') and not archive_mode:
            source = next((a for a in library.list_records('asset') if a.get('kind') == 'airfoil_geometry'
                           and a['airfoil'] == assignment['airfoil'] and a['coordinates'] == assignment['coordinates']), None)
            if source:
                assignment['asset_id'] = source['id']
            else:
                assignment['source_unavailable'] = True
        if assignment.get('asset_id'):
            source = asset_lookup(assignment['asset_id'])
            if source.get('kind') != 'airfoil_geometry' or source['airfoil'] != assignment['airfoil'] or source['coordinates'] != assignment['coordinates']:
                raise ValueError('Airfoil source asset does not match frozen coordinates')
            asset_ids.append(source['id'])
    validate(request.workflow)
    if any(n['type'] in ('pywake_input', 'pywake', 'openfast_input', 'openfast') for n in request.workflow['nodes']):
        raise ValueError('External cases use an integration workflow, not propeller inputs')
    if request.polar_asset_id:
        polar = asset_lookup(request.polar_asset_id)
        if polar.get('kind') != 'polar_family' or polar['airfoil'] != inputs['airfoil']:
            raise ValueError('Selected asset is not a matching polar family')
        from nova.core.polars import PolarProvider
        PolarProvider(polar['points'], polar['mach'], polar['ncrit'])
    allowed = {'air_density_kg_m3', 'air_viscosity_pa_s'}
    if set(request.conditions) - allowed:
        raise ValueError('Unsupported operating conditions; static axial analysis only')
    import math
    if any(not isinstance(v, (float, int)) or not math.isfinite(v) or v <= 0 for v in request.conditions.values()):
        raise ValueError('Fluid properties must be finite and positive')
    result = {'schema_version': 1, 'asset_ids': asset_ids, 'name': request.name, 'inputs': inputs, 'workflow': request.workflow,
              'polar_asset_id': request.polar_asset_id, 'conditions': request.conditions}
    if request.geometry_id is not None or request.geometry_revision is not None:
        if request.geometry_id is None or request.geometry_revision is None:
            raise ValueError('Geometry ID and revision must be supplied together')
        result.update(geometry_id=request.geometry_id, geometry_revision=request.geometry_revision)
    return result


@router.get('/registry')
def get_registry():
    return registry()


@router.get('/workflow-template')
def get_template():
    return template()


@router.post('/workflows/validate')
def validate_workflow(document: dict):
    try:
        return validate(document)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/workflows/clone')
def clone_workflow(document: dict):
    validate_workflow(document)
    return clone(document)


@router.get('/projects')
def projects():
    return [p for p in library.list_records('project') if 'inputs' in p and 'workflow' in p]


@router.post('/projects')
def save_project(request: ProjectRequest):
    try:
        if request.id and 'inputs' not in project(request.id):
            raise ValueError('Neutral projects use the v2 project API')
        return library.save('project', checked_project(request), request.id, request.expected_revision)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/projects/{id}')
def project(id: str):
    try:
        return library.get('project', id)
    except KeyError as exc:
        raise HTTPException(404, 'Project not found') from exc


@router.get('/projects/{id}/archive')
def archive(id: str):
    stored = project(id)
    if stored.get('schema_version') == 2 or any(s.get('kind') in ('pywake', 'openfast')
            for s in library.list_records('simulation') if s['project_id'] == id):
        raise HTTPException(422, 'Mixed projects require the v2 archive API')
    return Response(library.export_project(id), media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="project.nova"'})


class ArchiveImport(Request):
    content_base64: str = Field(max_length=30_000_000)


@router.post('/projects/import')
def import_archive(request: ArchiveImport):
    try:
        records = library.read_archive(base64.b64decode(request.content_base64, validate=True))
        document = validate_archive_records(records)
        document['workflow'] = clone(document['workflow'])
        return library.import_records(document, records)
    except (ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile) as exc:
        raise HTTPException(422, str(exc)) from exc


def validate_archive_records(records):
    # Validate the entire graph and asset set before writing anything.
    old = records['project']
    assets = {asset['id']: asset for asset in records['assets']}
    if len(assets) != len(records['assets']):
        raise ValueError('Duplicate archive asset IDs')
    def lookup(id):
        return assets[id]
    project_request = ProjectRequest(name=old['name'], inputs=old['inputs'], workflow=old['workflow'],
                                     conditions=old.get('conditions', {}), polar_asset_id=old.get('polar_asset_id'),
                                     geometry_id=old.get('geometry_id'), geometry_revision=old.get('geometry_revision'))
    document = checked_project(project_request, lookup)
    document['asset_ids'] = old.get('asset_ids', [])
    simulations = records.get('simulations', [])
    if not isinstance(simulations, list) or any(not isinstance(s, dict) for s in simulations):
        raise ValueError('Archive simulations must be a list of objects')
    geometries = records.get('geometries', [])
    if not isinstance(geometries, list) or any(not isinstance(g, dict) for g in geometries):
        raise ValueError('Archive geometries must be a list of objects')
    all_records = [old, *records['assets'], *simulations, *geometries, *records.get('runs', [])]
    identifiers = [r.get('id') for r in all_records]
    if any(not isinstance(i, str) or not i for i in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError('Archive record IDs must be unique nonempty strings')
    simulation_lookup = {s['id']: s for s in simulations}
    comparison_sources = [source for r in records.get('runs', []) for source in r.get('comparison', {}).get('simulations', [])]
    from nova.application.geometry import create_propeller_geometry
    from nova.core.data import content_hash
    from nova.core.geometry_assets import geometry_definition, geometry_hash
    geometry_lookup = {}
    for geometry in geometries:
        if geometry.get('project_id') != old['id'] or geometry.get('schema_version') != 1 or geometry.get('revision') != 1 or not isinstance(geometry.get('geometry_id'), str) or not geometry['geometry_id'] or type(geometry.get('geometry_revision')) is not int or geometry['geometry_revision'] < 1:
            raise ValueError('Invalid geometry ownership, ID or revision')
        key = (geometry['geometry_id'], geometry['geometry_revision'])
        if key in geometry_lookup or geometry['geometry_id'] in identifiers:
            raise ValueError('Duplicate geometry revision or colliding geometry family ID')
        definition = geometry['definition']
        normalized = checked_project(ProjectRequest(name=geometry['name'], inputs={**definition, 'rpm': 5000., 'thrust_target': 1.},
                                                     workflow=template()), lookup)['inputs']
        if geometry_definition(normalized) != definition or geometry_hash(definition) != geometry['content_hash']:
            raise ValueError('Geometry definition or content hash differs')
        canonical = create_propeller_geometry({**definition, 'rpm': 5000., 'thrust_target': 1.})
        if canonical != geometry['canonical_geometry'] or content_hash(canonical) != geometry['canonical_geometry_hash']:
            raise ValueError('Canonical geometry snapshot differs from its definition')
        geometry_lookup[key] = geometry
    for linked in [old, *simulations, *records.get('runs', []), *comparison_sources]:
        if linked.get('geometry_id') is not None or linked.get('geometry_revision') is not None:
            if type(linked.get('geometry_revision')) is not int or linked['geometry_revision'] < 1:
                raise ValueError('Invalid geometry reference revision')
            geometry = geometry_lookup[(linked['geometry_id'], linked['geometry_revision'])]
            if geometry_hash(geometry_definition(linked['inputs'])) != geometry['content_hash']:
                raise ValueError('Linked baseline geometry differs from frozen inputs')
            if linked.get('geometry_content_hash') and linked['geometry_content_hash'] != geometry['content_hash']:
                raise ValueError('Historical baseline geometry hash differs')
    for simulation in simulations:
        if simulation.get('project_id') != old['id'] or simulation.get('schema_version') != 1 or type(simulation.get('revision')) is not int or simulation['revision'] < 1:
            raise ValueError('Invalid simulation ownership, schema or revision')
        checked_project(ProjectRequest(name=simulation['name'], inputs=simulation['inputs'], workflow=simulation['workflow'],
                                       conditions=simulation.get('conditions', {}), polar_asset_id=simulation.get('polar_asset_id')), lookup)
    for asset in assets.values():
        if asset.get('kind') == 'airfoil_geometry':
            from airfoil_management import AirfoilManager
            AirfoilManager().parse_dat(asset['source'], asset['airfoil'])
        elif asset.get('kind') == 'polar_family':
            validate_points(asset['points'])
        else:
            raise ValueError('Unsupported asset type')
    for record in [old, *simulations, *records.get('runs', []), *comparison_sources]:
        for id in record.get('asset_ids', []):
            lookup(id)
        if record.get('polar_asset_id'):
            lookup(record['polar_asset_id'])
        for item in record['inputs'].get('airfoil_assignments', []):
            if item.get('asset_id'):
                lookup(item['asset_id'])
    for source in comparison_sources:
        current = simulation_lookup[source['id']]
        if source.get('project_id') != old['id'] or type(source.get('revision')) is not int or not 1 <= source['revision'] <= current['revision']:
            raise ValueError('Invalid comparison simulation ownership or historical revision')
        checked_project(ProjectRequest(name=source['name'], inputs=source['inputs'], workflow=source['workflow'],
                                       conditions=source.get('conditions', {}), polar_asset_id=source.get('polar_asset_id')), lookup)
        if source['revision'] == current['revision'] and any(source.get(k) != current.get(k) for k in ('name', 'inputs', 'workflow', 'conditions', 'geometry_id', 'geometry_revision', 'polar_asset_id')):
            raise ValueError('Comparison source differs from declared saved revision')
        if source.get('polar_asset_id'):
            if source.get('polar_asset') != lookup(source['polar_asset_id']):
                raise ValueError('Frozen comparison polar differs from archived asset')
        elif source.get('polar_asset') is not None:
            raise ValueError('Unreferenced frozen comparison polar')
    for record in records.get('runs', []):
        if record.get('project_id') != old['id']:
            raise ValueError('Archived run belongs to a different project')
        if any(key in record for key in ('simulation_id', 'simulation_revision', 'simulation_name')) and not record.get('simulation_id'):
            raise ValueError('Historical simulation metadata requires a simulation ID')
        if record.get('simulation_id'):
            simulation = simulation_lookup[record['simulation_id']]
            if type(record.get('simulation_revision')) is not int or not 1 <= record['simulation_revision'] <= simulation['revision'] or not isinstance(record.get('simulation_name'), str) or type(record.get('project_revision')) is not int or record['project_revision'] < 1:
                raise ValueError('Invalid historical simulation reference')
            if record['simulation_revision'] == simulation['revision'] and (record['simulation_name'] != simulation['name'] or any(record.get(key, {}) != simulation.get(key, {}) for key in ('inputs', 'workflow', 'polar_asset_id', 'conditions'))):
                raise ValueError('Historical run differs from its declared simulation revision')
        if not isinstance(record.get('id'), str) or record.get('state') not in ('succeeded', 'failed', 'cancelled', 'interrupted'):
            raise ValueError('Only well-formed completed runs can be imported')
        checked_project(ProjectRequest(name=record['name'], inputs=record['inputs'], workflow=record['workflow'],
                                       conditions=record.get('conditions', {}), polar_asset_id=record.get('polar_asset_id')), lookup)
        if record.get('study'):
            build_cases(record, record['study'])
        if record.get('comparison'):
            from nova.application.comparisons import validate_comparison, validate_result
            validate_comparison(record['comparison'])
            if record.get('result'):
                if record['result'].get('kind') != 'comparison':
                    raise ValueError('Comparison run has an incompatible result')
                validate_result(record['result'], record)
        elif record.get('result') and record['result'].get('kind') == 'study':
            validate_study_result(record['result'], record)
        elif record.get('result') and record['result'].get('kind') == 'optimization':
            from inverse_design import GeometryData
            from nova.core.design import InverseDesignRequest
            InverseDesignRequest.model_validate(record['optimization'])
            GeometryData.from_dict(record['result']['candidate']['geometry'])
        elif record.get('result'):
            from inverse_design import GeometryData
            if record['result'].get('geometry'):
                GeometryData.from_dict(record['result']['geometry'])
            from nova.core.contracts import CanonicalSolverResult
            for result in record['result']['analyses']:
                CanonicalSolverResult.model_validate({k: v for k, v in result.items() if k in CanonicalSolverResult.model_fields})
    return document


@router.get('/assets')
def assets():
    return library.list_records('asset')


@router.post('/assets/import-polar')
def import_polar(request: ImportRequest):
    try:
        points = parse_polar(request.content, request.format, reynolds=request.reynolds,
                             mach=request.mach, ncrit=request.ncrit, mapping=request.mapping)
        conditions = sorted({(p['mach'], p['ncrit']) for p in points})
        if len(conditions) != 1:
            raise ValueError('Import one Mach/Ncrit condition at a time')
        document = {'kind': 'polar_family', 'airfoil': request.airfoil, 'filename': request.filename,
                    'source': request.content, 'source_sha256': hashlib.sha256(request.content.encode()).hexdigest(),
                    'format': request.format, 'points': points, 'mach': conditions[0][0], 'ncrit': conditions[0][1],
                    'policy': 'endpoint_clipping', 'demonstration': False}
        return library.make_asset(document) if request.commit else {**document, 'preview': True}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/assets/demonstration-polar')
def demo_polar(document: dict):
    from polar_database import (
        ALPHA_GRID,
        REYNOLDS_GRID,
        SYNTHETIC_POLAR_PARAMETERS,
        build_seed_table,
    )
    name = document.get('airfoil', 'NACA 4412')
    if name not in SYNTHETIC_POLAR_PARAMETERS:
        raise HTTPException(422, 'No demonstration data for this airfoil')
    table = build_seed_table(name)
    points = [{'reynolds': float(re), 'mach': .03, 'ncrit': 9., 'alpha_deg': float(alpha),
               'cl': float(table['cl'][i, j]), 'cd': float(table['cd'][i, j]), 'cm': float(table['cm'][i, j])}
              for i, re in enumerate(REYNOLDS_GRID) for j, alpha in enumerate(ALPHA_GRID)]
    return library.make_asset({'kind': 'polar_family', 'airfoil': name, 'filename': 'synthetic-demo',
                               'source': 'NOVA synthetic formula; not measurements', 'format': 'synthetic',
                               'points': points, 'mach': .03, 'ncrit': 9., 'demonstration': True})


@router.post('/runs')
def submit_run(request: ProjectRequest):
    return submit_project_job(request)


def submit_project_job(request, study=None, optimization=None, simulation_metadata=None):
    try:
        document = checked_project(request)
        asset = library.get('asset', request.polar_asset_id) if request.polar_asset_id else None
        if asset and asset['airfoil'] != document['inputs']['airfoil']:
            raise ValueError('Selected polar asset belongs to a different airfoil')
        needs_bemt = optimization.get('solver') == 'bemt' if optimization is not None else any(n['type'] == 'analysis' and n.get('config', {}).get('model', 'bemt') == 'bemt' for n in document['workflow']['nodes'])
        if not asset and needs_bemt:
            raise ValueError('BEMT requires an explicitly selected polar asset')
        parent = project(request.id) if request.id else None
        snapshot = {**document, 'project_id': request.id, 'polar_asset': asset,
                    'input_hash': content_hash(document), 'solver_version': '0.1.0-alpha.2'}
        if parent:
            snapshot['project_revision'] = parent['revision']
            # References identify the frozen baseline, not a derived sizing/study/optimization output.
            from nova.core.geometry_assets import geometry_definition, geometry_hash
            family, revision = document.get('geometry_id'), document.get('geometry_revision')
            if family is None and parent.get('geometry_id'):
                candidate = library.get_geometry(parent['id'], parent['geometry_id'], parent['geometry_revision'])
                if candidate['content_hash'] == geometry_hash(geometry_definition(document['inputs'])):
                    family, revision = candidate['geometry_id'], candidate['geometry_revision']
            if family is not None:
                geometry = library.get_geometry(parent['id'], family, revision)
                if geometry['content_hash'] != geometry_hash(geometry_definition(document['inputs'])):
                    raise ValueError('Baseline geometry differs from run inputs')
                snapshot.update(geometry_id=family, geometry_revision=revision,
                                geometry_content_hash=geometry['content_hash'], geometry_role='baseline_input_geometry')
        if simulation_metadata is not None:
            simulation = library.get('simulation', simulation_metadata['simulation_id'])
            if simulation['project_id'] != request.id or simulation_metadata != {
                'simulation_id': simulation['id'], 'simulation_name': simulation['name'],
                'simulation_revision': simulation['revision']}:
                raise ValueError('Simulation metadata differs from its saved configuration')
            if any(document[key] != simulation[key] for key in ('name', 'inputs', 'workflow', 'polar_asset_id', 'conditions')):
                raise ValueError('Run inputs differ from its saved simulation')
            snapshot.update(simulation_metadata)
        if study is not None:
            build_cases(snapshot, study)
            snapshot['study'] = study
        if optimization is not None:
            from nova.core.design import InverseDesignRequest
            settings = InverseDesignRequest.model_validate(optimization).model_dump()
            if document['inputs']['geometry_method'] != 'bezier':
                raise ValueError('Inverse optimization currently requires Bezier geometry')
            if any(len(settings[key]) > 4 for key in ('chord_points', 'twist_points')):
                raise ValueError('Use at most four control points for inverse optimization')
            if settings['solver'] == 'bemt' and not asset:
                raise ValueError('BEMT optimization requires an explicitly selected polar asset')
            snapshot['optimization'] = settings
        return jobs.submit(snapshot)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/runs')
def runs():
    return library.list_records('run')


@router.get('/runs/{id}')
def run(id: str):
    try:
        return library.get('run', id)
    except KeyError as exc:
        raise HTTPException(404, 'Run not found') from exc


@router.post('/runs/{id}/cancel')
def cancel(id: str):
    run(id)
    return jobs.cancel(id)


@router.get('/runs/{id}/stl')
def run_stl(id: str):
    from io import BytesIO

    from geometry_engine import generate_mesh_from_geometry
    record = run(id)
    geometry = (record.get('result') or {}).get('geometry')
    if not geometry:
        raise HTTPException(404, 'Run has no geometry artifact')
    mesh = generate_mesh_from_geometry(geometry)
    output = BytesIO()
    mesh.export(output, file_type='stl')
    return Response(output.getvalue(), media_type='model/stl',
                    headers={'Content-Disposition': 'attachment; filename="propeller.stl"'})


@router.get('/runs/{id}/results.csv')
def run_csv(id: str):
    import csv
    import io
    record = run(id)
    analyses = (record.get('result') or {}).get('analyses', [])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['model', 'thrust_N', 'torque_Nm', 'power_W', 'figure_of_merit'])
    for result in analyses:
        p = result['performance']
        writer.writerow([result['model'], p['thrust_n'], p['torque_nm'], p['power_w'], p['efficiency']])
    return Response(output.getvalue(), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="results.csv"'})


class StudyRequest(ProjectRequest):
    study: StudyDefinition


@router.get('/studies/parameters')
def study_parameters():
    from nova.application.studies import PARAMETERS
    return PARAMETERS


@router.post('/studies')
def submit_study(request: StudyRequest):
    return submit_project_job(request, request.study.model_dump(exclude_none=True))


class ComparisonRequest(Request):
    run_ids: list[str] = Field(min_length=2, max_length=8)


@router.post('/runs/compare')
def compare_runs(request: ComparisonRequest):
    try:
        if len(set(request.run_ids)) != len(request.run_ids):
            raise ValueError('Select distinct runs')
        rows = []
        for id in request.run_ids:
            rows.extend(comparison_rows(run(id)))
        return {'rows': rows, 'frame': 'rotor', 'time_domain': 'static',
                'units': {'thrust_n': 'N', 'torque_nm': 'N*m', 'power_w': 'W', 'figure_of_merit': 'dimensionless'}}
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/runs/{id}/study.csv')
def study_csv(id: str):
    import csv
    import io
    record = run(id)
    if not record.get('study'):
        raise HTTPException(422, 'This run is not a study')
    rows = comparison_rows(record)
    output = io.StringIO()
    fields = ['run_id', 'case_index', 'value', 'parameter', 'parameter_units', 'state', 'run_state', 'airfoil', 'viscosity_pa_s', 'node_id', 'model', 'fidelity', 'polar_data', 'rpm',
              'density_kg_m3', 'diameter_m', 'thrust_n', 'torque_nm', 'power_w', 'figure_of_merit', 'error']
    if record['study'].get('secondary'):
        fields.extend(['secondary_parameter', 'secondary_units', 'secondary_value'])
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return Response(output.getvalue(), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="study.csv"'})


@router.get('/runs/{id}/study.rows')
def study_rows(id: str):
    from nova.application.studies import PARAMETERS
    record = run(id)
    if not record.get('study'):
        raise HTTPException(422, 'This run is not a study')
    definition = StudyDefinition.model_validate(record['study'])
    axes = [definition, *([definition.secondary] if definition.secondary else [])]
    return {'rows': comparison_rows(record) if record.get('result') else [],
            'axes': [{'parameter': axis.parameter, 'values': axis.values, 'units': PARAMETERS[axis.parameter]['units']} for axis in axes]}


@router.get('/runs/{id}/cases/{index}/stl')
def study_case_stl(id: str, index: int):
    from io import BytesIO

    from geometry_engine import generate_mesh_from_geometry
    record = run(id)
    cases = (record.get('result') or {}).get('cases', [])
    if not 0 <= index < len(cases) or cases[index]['state'] != 'succeeded':
        raise HTTPException(404, 'Successful study case not found')
    mesh = generate_mesh_from_geometry(cases[index]['result']['geometry'])
    output = BytesIO()
    mesh.export(output, file_type='stl')
    return Response(output.getvalue(), media_type='model/stl',
                    headers={'Content-Disposition': 'attachment; filename="study-case.stl"'})


class AdapterConfigurationRequest(Request):
    executable: str = Field(min_length=1, max_length=4096)
    environment_kind: str = 'local_executable'
    options: dict = Field(default_factory=dict)


@router.get('/adapters')
def adapters():
    from nova.adapters.registry import descriptors
    return descriptors()


@router.get('/integrations')
def integrations():
    return library.list_records('integration')


@router.post('/adapters/{id}/probe')
def probe_adapter(id: str, request: AdapterConfigurationRequest):
    from pathlib import Path

    from nova.adapters.base import AdapterConfiguration, AdapterError
    from nova.adapters.process import ProcessFailure
    from nova.adapters.registry import get
    from nova.core.data import canonical_json
    try:
        adapter = get(id)
    except KeyError as exc:
        raise HTTPException(404, 'Adapter is not registered') from exc
    configuration = AdapterConfiguration(Path(request.executable), request.environment_kind, request.options)
    try:
        if configuration.environment_kind not in adapter.describe().environments:
            raise ValueError('Unsupported adapter environment')
        canonical_json(request.options)
        return adapter.probe(configuration)
    except (ValueError, OSError, ProcessFailure, AdapterError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/adapters/{id}/configure')
def configure_adapter(id: str, request: AdapterConfigurationRequest):
    result = probe_adapter(id, request)
    if not result.get('available') or not result.get('compatible'):
        raise HTTPException(422, result.get('message', 'Program unavailable or incompatible'))
    return library.save('integration', {'schema_version': 1, 'adapter_id': id,
                                        **request.model_dump(), 'probe': result})


class OptimizationRequest(ProjectRequest):
    solver: str = 'bemt'
    max_iterations: int = Field(180, ge=10, le=1000)


@router.post('/optimizations')
def submit_optimization(request: OptimizationRequest):
    return submit_project_job(request, optimization=build_optimization_settings(request.inputs, request.solver, request.max_iterations))


def build_optimization_settings(inputs, solver, max_iterations):
    """Use the same geometry controls for project and saved-simulation optimization."""
    from nova.core.design import GeometryRequest
    try:
        inputs = GeometryRequest.model_validate(inputs).model_dump()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    params = inputs.get('geometry_parameters', {})
    settings = {'target_thrust': inputs.get('thrust_target'), 'rpm': inputs.get('rpm'),
                'diameter': inputs.get('diameter'), 'blades': inputs.get('blades'),
                'airfoil': inputs.get('airfoil'), 'solver': solver,
                'chord_points': params.get('chord_points', []), 'twist_points': params.get('twist_points', []),
                'min_chord_m': max(.003, inputs.get('diameter', .25) * .012),
                'max_chord_m': inputs.get('diameter', .25) * .16,
                'max_iterations': max_iterations}
    return settings
