"""Rotor physics and block-workflow endpoints."""
import copy

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from nova.blocks import catalog as block_catalog
from nova.blocks import engine, templates
from nova.blocks.constraints import normalise, report
from nova.infrastructure import library
from nova.physics import rotors
from nova.physics.vawt import METHODS as VAWT_METHODS

router = APIRouter(prefix='/api/v1')


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class RotorRequest(Request):
    spec: dict


class CurveRequest(Request):
    spec: dict
    variable: str | None = None
    values: list[float] | None = Field(None, min_length=2, max_length=200)
    points: int | None = Field(None, ge=2, le=200)


class SweepRequest(Request):
    spec: dict
    path: str = Field(min_length=3, max_length=80)
    values: list[float] = Field(min_length=1, max_length=41)
    method: str | None = None
    checks: list[dict] = Field(default_factory=list, max_length=20)


class BlockWorkflowRequest(Request):
    workflow: dict


class SaveBlockWorkflowRequest(Request):
    name: str = Field(min_length=1, max_length=120)
    workflow: dict
    id: str | None = None
    expected_revision: int | None = None


def _guard(call):
    try:
        return call()
    except InterruptedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/rotors/catalog')
def rotor_catalog():
    return rotors.catalog()


@router.post('/rotors/analyze')
def analyze_rotor(request: RotorRequest):
    return _guard(lambda: rotors.analyze(request.spec))


@router.post('/rotors/curve')
def rotor_curve(request: CurveRequest):
    return _guard(lambda: rotors.performance_curve(request.spec, variable=request.variable,
                                                   values=request.values, points=request.points))


@router.post('/rotors/sweep')
def rotor_sweep(request: SweepRequest):
    """Vary one specification field; optionally evaluate every point with another model."""
    def sweep():
        # Complete the specification first so a swept field never replaces a whole group.
        base = {k: v for k, v in rotors.merged(copy.deepcopy(request.spec)).items() if k not in ('curve', 'requirements')}
        engine.set_path({}, request.path, 0)
        if request.method:
            if base.get('kind') == 'vawt':
                if request.method not in VAWT_METHODS:
                    raise ValueError(f'Unknown VAWT method {request.method!r}')
            elif request.method != 'bemt':
                raise ValueError('Axial rotors use the BEMT method')
        for check in request.checks:
            normalise(check)
        rows = []
        for value in request.values:
            point = engine.set_path(copy.deepcopy(base), request.path, value)
            if request.method:
                point['method'] = request.method
            try:
                result = rotors.analyze(point)
                values = rotors.scalar_outputs(result)
                row = {'value': value, 'state': 'succeeded', 'converged': result['converged'], **values}
                if request.checks:
                    checked = report(request.checks, values)
                    row['feasible'] = checked['feasible']
                    row['violations'] = [c['label'] for c in checked['checks'] if not c['satisfied']]
            except ValueError as exc:
                row = {'value': value, 'state': 'failed', 'error': str(exc)}
            rows.append(row)
        return {'path': request.path, 'method': request.method or base.get('method', 'bemt'), 'rows': rows}
    return _guard(sweep)


@router.get('/blocks/catalog')
def blocks_catalog():
    return block_catalog.catalog()


@router.get('/blocks/templates')
def block_templates():
    return templates.templates()


@router.get('/blocks/templates/{key}')
def block_template(key: str):
    try:
        return templates.template(key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post('/blocks/validate')
def validate_blocks(request: BlockWorkflowRequest):
    checked = _guard(lambda: engine.validate(request.workflow))
    return {'valid': True, 'order': checked['order']}


@router.post('/blocks/run')
def run_blocks(request: BlockWorkflowRequest):
    return _guard(lambda: engine.execute(request.workflow))


@router.get('/blocks/workflows')
def list_block_workflows():
    return sorted(library.list_records('block_workflow'), key=lambda r: r.get('updated_at', ''), reverse=True)


@router.post('/blocks/workflows')
def save_block_workflow(request: SaveBlockWorkflowRequest):
    _guard(lambda: engine.validate(request.workflow))
    document = {'name': request.name, 'workflow': request.workflow}
    return _guard(lambda: library.save('block_workflow', document, request.id, request.expected_revision))


@router.get('/blocks/workflows/{id}')
def get_block_workflow(id: str):
    try:
        return library.get('block_workflow', id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, 'Block workflow not found') from exc
