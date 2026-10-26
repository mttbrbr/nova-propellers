"""Portable scientific inputs, independent of a source folder or installation."""
import base64
import copy
import hashlib
import tempfile
from pathlib import Path, PurePosixPath

from nova.adapters.base import AdapterConfiguration
from nova.adapters.openfast import _case_files
from nova.adapters.pywake import PyWakeAdapter
from nova.core.data import canonical_json, content_hash

MAX_BYTES = 100 * 1024 * 1024


def scientific_file(path, raw):
    relative = PurePosixPath(path)
    if (not isinstance(path, str) or not path or relative.is_absolute() or
            '..' in relative.parts or '\\' in path or ':' in path or str(relative) != path):
        raise ValueError('Case file requires a contained relative path')
    if (relative.suffix.lower() in {'.exe', '.dll', '.so', '.dylib', '.a', '.o', '.py', '.sh', '.bat', '.cmd'}
            or raw.startswith((b'\x7fELF', b'MZ', b'#!', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf'))):
        raise ValueError('Executable programs and controller libraries are external dependencies, not scientific assets')
    return relative


def freeze_case(kind, name, case, *, notes='', demonstration=False):
    if not isinstance(notes, str) or len(notes) > 800 or type(demonstration) is not bool:
        raise ValueError('Invalid case notes or demonstration label')
    payload = {'type': 'simulation_case', 'kind': kind, 'name': name,
               'notes': notes, 'demonstration': demonstration}
    if kind == 'pywake':
        if len(canonical_json(case).encode()) > 1_000_000:
            raise ValueError('PyWake case exceeds 1 MB')
        PyWakeAdapter().validate(case, AdapterConfiguration(Path('unused'), 'python_environment'))
        payload['case'] = copy.deepcopy(case)
    elif kind == 'openfast':
        root, paths = _case_files(case)
        files = []
        for source in sorted(paths):
            raw = source.read_bytes()
            path = source.relative_to(root).as_posix()
            scientific_file(path, raw)
            files.append({'path': path, 'content_base64': base64.b64encode(raw).decode(),
                          'sha256': hashlib.sha256(raw).hexdigest()})
        payload.update(case={key: case[key] for key in ('input_file', 'output_file', 'timeout_seconds') if key in case}, files=files)
    else:
        raise ValueError('Unknown scientific case kind')
    payload['case_hash'] = content_hash({key: payload[key] for key in ('kind', 'case', 'files') if key in payload})
    validate_asset(payload)
    return payload


def validate_asset(asset):
    if asset.get('type') != 'simulation_case':
        raise ValueError('Expected a scientific simulation case asset')
    if not isinstance(asset.get('notes', ''), str) or len(asset.get('notes', '')) > 800 or type(asset.get('demonstration', False)) is not bool:
        raise ValueError('Invalid case notes or demonstration label')
    if asset.get('case_hash') != content_hash({key: asset[key] for key in ('kind', 'case', 'files') if key in asset}):
        raise ValueError('Scientific case hash mismatch')
    if asset['kind'] == 'pywake':
        if 'files' in asset or len(canonical_json(asset['case']).encode()) > 1_000_000:
            raise ValueError('Invalid PyWake case asset')
        PyWakeAdapter().validate(asset['case'], AdapterConfiguration(Path('unused'), 'python_environment'))
        return
    if asset['kind'] != 'openfast' or set(asset['case']) - {'input_file', 'output_file', 'timeout_seconds'}:
        raise ValueError('Invalid portable OpenFAST case')
    files = asset.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= 1000:
        raise ValueError('OpenFAST asset requires 1–1000 files')
    total, seen = 0, set()
    for entry in files:
        if set(entry) != {'path', 'content_base64', 'sha256'}:
            raise ValueError('Invalid scientific file entry')
        if len(entry['content_base64']) > MAX_BYTES * 4 // 3 + 4:
            raise ValueError('Scientific case exceeds 100 MiB')
        raw = base64.b64decode(entry['content_base64'], validate=True)
        scientific_file(entry['path'], raw)
        total += len(raw)
        if total > MAX_BYTES or entry['path'] in seen:
            raise ValueError('Case exceeds 100 MiB or contains duplicate paths')
        seen.add(entry['path'])
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Scientific file checksum mismatch')
    # Validate the same reference containment rules used by the execution adapter.
    with tempfile.TemporaryDirectory(prefix='nova-case-check-') as directory:
        _materialize(asset, Path(directory))
        _case_files({**asset['case'], 'case_directory': directory})


def revise_case(asset, case, *, notes, demonstration):
    """Derive immutable scientific inputs while retaining the original asset."""
    validate_asset(asset)
    payload = {key: copy.deepcopy(value) for key, value in asset.items()
               if key not in {'id', 'revision', 'updated_at', 'content_hash'}}
    payload.update(case=copy.deepcopy(case), notes=notes, demonstration=demonstration)
    payload['case_hash'] = content_hash({key: payload[key] for key in ('kind', 'case', 'files') if key in payload})
    validate_asset(payload)
    return payload


def _materialize(asset, destination):
    for entry in asset['files']:
        path = destination / entry['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(entry['content_base64'], validate=True))
        path.chmod(0o600)


def materialize_asset(asset, destination):
    validate_asset(asset)
    if asset['kind'] == 'pywake':
        return copy.deepcopy(asset['case'])
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    _materialize(asset, destination)
    return {**asset['case'], 'case_directory': str(destination),
            'input_files': [entry['path'] for entry in asset['files']],
            'input_hashes': {entry['path']: entry['sha256'] for entry in asset['files']}}
