"""Portable external result exchange; importing never launches a solver."""
import base64
import binascii

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field

from nova.infrastructure import library
from nova.infrastructure.external_archive import export_external_run, import_external_archive
from nova.transport.api import Request

router = APIRouter(prefix='/api/v1')


class ExternalArchiveImport(Request):
    content_base64: str = Field(min_length=1, max_length=180_000_000)


@router.get('/external-runs/{id}')
def external_run(id: str):
    try:
        record = library.get('run', id)
    except KeyError as exc:
        raise HTTPException(404, 'External run not found') from exc
    if not record.get('external_job'):
        raise HTTPException(404, 'External run not found')
    return record


@router.get('/external-runs/{id}/archive')
def export_archive(id: str):
    try:
        content = export_external_run(id)
    except KeyError as exc:
        raise HTTPException(404, 'External run not found') from exc
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(content, media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="external-run.nova-run"'})


@router.post('/external-runs/import')
def import_archive(request: ExternalArchiveImport):
    try:
        return import_external_archive(base64.b64decode(request.content_base64, validate=True))
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, binascii.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
