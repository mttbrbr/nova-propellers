"""Rotor physics and block-workflow endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from nova.blocks import catalog as block_catalog
from nova.blocks import engine, templates
from nova.infrastructure import library
from nova.physics import rotors

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
