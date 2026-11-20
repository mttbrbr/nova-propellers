"""Structure workspace API: structural data per simulation (version) and structural runs."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nova.application import structure as service
from nova.blocks.engine import BlockError
from nova.infrastructure import library

router = APIRouter(prefix='/api/v2/simulations/{simulation_id}/structure', tags=['structure'])


class StructureRequest(BaseModel):
    config: dict
    expected_revision: int | None = None


class StructureRunRequest(BaseModel):
    aero_run_id: str


def _simulation(simulation_id):
    try:
        stored = library.get('simulation', simulation_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Simulation not found') from exc
    if stored.get('kind') != 'rotor':
        raise HTTPException(422, 'The Structure workspace needs a rotor simulation (HAWT, air or marine propeller)')
    return stored


def _record(simulation_id):
    found = [r for r in library.list_records('structure') if r.get('simulation_id') == simulation_id]
    return found[0] if found else None


@router.get('')
def get_structure(simulation_id: str):
    stored = _simulation(simulation_id)
    spec = stored['configuration']['spec']
    try:
        record = _record(simulation_id)
        return record or {'simulation_id': simulation_id, 'config': service.default(spec), 'revision': None,
                          'materials': service.SOLID_MATERIALS}
    except service.StructureError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put('')
def save_structure(simulation_id: str, request: StructureRequest):
    stored = _simulation(simulation_id)
    try:
        service.family(stored['configuration']['spec'])
        existing = _record(simulation_id)
        document = {'project_id': stored.get('project_id'), 'simulation_id': simulation_id, 'version': stored.get('version'),
                    'config': request.config}
        return library.save('structure', document, existing['id'] if existing else None, request.expected_revision)
    except (service.StructureError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/runs')
def list_runs(simulation_id: str):
    return [r for r in library.list_records('structure_run') if r.get('simulation_id') == simulation_id]


@router.post('/runs')
def run_structure(simulation_id: str, request: StructureRunRequest):
    stored = _simulation(simulation_id)
    record = _record(simulation_id)
    config = record['config'] if record else service.default(stored['configuration']['spec'])
    try:
        aero = library.get('run', request.aero_run_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Aerodynamic run not found') from exc
    if aero.get('simulation_id') != simulation_id or aero.get('state') != 'succeeded':
        raise HTTPException(422, 'Choose a succeeded aerodynamic run of this version')
    try:
        result = service.run(stored['configuration']['spec'], config, aero)
    except (service.StructureError, BlockError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    document = {'project_id': stored.get('project_id'), 'simulation_id': simulation_id, 'version': stored.get('version'),
                'structure_revision': record['revision'] if record else None, 'config': config,
                'aero_run': {'id': aero['id'], 'created_at': aero.get('created_at'),
                             'method_label': ((aero.get('result') or {}).get('analysis') or {}).get('method_label')},
                'created_at': library.now(), 'state': 'succeeded', 'result': result}
    return library.save('structure_run', document)
