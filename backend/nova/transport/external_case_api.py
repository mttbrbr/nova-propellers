"""Save/load PyWake case data without selecting or launching an interpreter."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from nova.application.external_cases import get_case, list_cases, save_case

router = APIRouter(prefix='/api/v1')


class ExternalCaseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=120)
    case: dict
    notes: str = Field('', max_length=800)
    demonstration: bool = Field(False, strict=True)


@router.post('/external-cases')
def create_external_case(request: ExternalCaseRequest):
    try:
        return save_case(request.name, request.case, notes=request.notes, demonstration=request.demonstration)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/external-cases')
def external_cases():
    return list_cases()


@router.get('/external-cases/{id}')
def external_case(id: str):
    try:
        return get_case(id)
    except KeyError as exc:
        raise HTTPException(404, 'Saved external case not found') from exc
