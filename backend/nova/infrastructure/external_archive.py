"""Portable completed external runs, without executable or environment settings.

The archive is a data interchange format, never an execution request. Inputs,
normalized results and historical states survive; all restored files are private
and nonexecutable. Filesystem staging precedes the SQLite transaction.
"""
import copy
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import database
from nova.core.data import canonical_json
from nova.infrastructure import library

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_FILES = 2048
COMPLETED = {'succeeded', 'failed', 'cancelled', 'interrupted'}
ADAPTERS = {'pywake', 'openfast'}
LOCAL_KEYS = {'configuration', 'executable', 'environment', 'environment_kind', 'integration_id',
              'artifact_root', 'working_directory', 'case_directory', 'source_case_directory',
              'python_executable', 'command'}
SECRET_KEY = re.compile(r'(secret|password|passwd|token|api[_-]?key|authorization|credential|private[_-]?key)', re.I)


def _json(data):
    if len(data) > MAX_JSON_BYTES:
        raise ValueError('Archive JSON exceeds 20 MiB')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON member')
            result[key] = value
        return result
    try:
        result = json.loads(data, object_pairs_hook=pairs)
        canonical_json(result)
    except RecursionError as exc:
        raise ValueError('Archive JSON nesting exceeds supported depth') from exc
    return result


def _relative(name):
    if not isinstance(name, str) or not name or len(name) > 1024 or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('Invalid archive artifact path')
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Escaping or noncanonical archive path')
    if any(part in ('.env', '.ssh', 'id_rsa', 'id_ed25519') for part in path.parts) or path.suffix.lower() in ('.pem', '.key'):
        raise ValueError('Credential files cannot be included in portable runs')
    return path


def _owned_file(directory, relative):
    _relative(relative)
    path = directory
    for part in PurePosixPath(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Archive sources cannot contain symlinks')
    if not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Missing or escaping archive artifact')
    return path


def _redactions(record):
    """Known machine paths and configuration values must not leak through logs."""
    values = set()
    def walk(value, sensitive=False, path_value=False):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, sensitive or key == 'environment' or bool(SECRET_KEY.search(key)), key in LOCAL_KEYS)
        elif isinstance(value, list):
            for child in value:
                walk(child, sensitive, path_value)
        elif isinstance(value, str) and value and (sensitive or (path_value and value.startswith('/'))):
            values.add(value)
    walk(record)
    return sorted(values, key=len, reverse=True)


def _sanitize(value, replacements):
    if isinstance(value, dict):
        return {key: _sanitize(child, replacements) for key, child in value.items()
                if key not in LOCAL_KEYS and not SECRET_KEY.search(key)}
    if isinstance(value, list):
        return [_sanitize(child, replacements) for child in value]
    if isinstance(value, str):
        for text in replacements:
            value = value.replace(text, '[redacted]')
        return value
    return value


def _numeric_array(value, shape, label):
    """Require explicit JSON numeric arrays; never coerce booleans or broadcast."""
    if not shape:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'Invalid numeric value in {label}')
        return
    if not isinstance(value, list) or len(value) != shape[0]:
        raise ValueError(f'Invalid array shape for {label}')
    for child in value:
        _numeric_array(child, shape[1:], label)


def _validate_data(data, adapter):
    if data is None:
        return
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('Invalid normalized external result')
    if adapter == 'openfast':
        if data.get('kind') != 'time_series_result':
            raise ValueError('OpenFAST archive requires time series data')
        channels, times, values = data['channels'], data['time_s'], data['values']
        if not isinstance(channels, list) or not 1 <= len(channels) <= 4096 or not isinstance(times, list) or not 1 <= len(times) <= 1_000_000 or len(times) * len(channels) > 2_000_000 or len(values) != len(times):
            raise ValueError('Invalid time series shape')
        source = data.get('source', {})
        if not isinstance(source, dict) or not isinstance(source.get('filename'), str) or Path(source['filename']).name != source['filename'] or not re.fullmatch(r'[0-9a-f]{64}', source.get('sha256', '')):
            raise ValueError('Invalid OpenFAST source provenance')
        names = []
        for channel in channels:
            if not isinstance(channel, dict) or not isinstance(channel.get('name'), str) or not isinstance(channel.get('units'), str):
                raise ValueError('Invalid channel metadata')
            names.append(channel['name'])
        if len(set(names)) != len(names):
            raise ValueError('Duplicate channels')
        previous = None
        for time, row in zip(times, values, strict=True):
            if type(time) not in (float, int) or not math.isfinite(time) or (previous is not None and time <= previous) or not isinstance(row, list) or len(row) != len(channels) or any(type(v) not in (float, int) or not math.isfinite(v) for v in row):
                raise ValueError('Invalid time series sample')
            previous = time
    else:
        import numpy as np
        if data.get('kind') != 'wind_farm_result' or data.get('axis_order') != ['turbine', 'direction', 'speed']:
            raise ValueError('Invalid wind farm result')
        shape = (len(data['layout']['x_m']), len(data['directions_deg']), len(data['speeds_m_s']))
        if any(not 1 <= n <= 4096 for n in shape) or math.prod(shape) > 2_000_000 or len(data['layout']['y_m']) != shape[0]:
            raise ValueError('Invalid wind farm dimensions')
        for vector in (data['layout']['x_m'], data['layout']['y_m'], data['directions_deg'], data['speeds_m_s']):
            if not isinstance(vector, list) or any(type(v) not in (float, int) or not math.isfinite(v) for v in vector):
                raise ValueError('Invalid wind farm coordinates or conditions')
        if any(v < 0 for v in data['speeds_m_s']) or any(not 0 <= v < 360 for v in data['directions_deg']):
            raise ValueError('Invalid wind directions or speeds')
        for key in ('power_w', 'effective_speed_m_s', 'power_without_wakes_w'):
            _numeric_array(data[key], shape, key)
            array = np.asarray(data[key], dtype=float)
            if array.shape != shape or not np.all(np.isfinite(array)) or np.any(array < 0):
                raise ValueError('Invalid wind farm field')
        _numeric_array(data['probabilities'], shape[1:], 'probabilities')
        weights = np.asarray(data['probabilities'], dtype=float)
        if weights.shape != shape[1:] or not np.all(np.isfinite(weights)) or np.any(weights < 0) or not np.isclose(weights.sum(), 1., rtol=0, atol=1e-8):
            raise ValueError('Invalid wind probabilities')
        for field, total, power in [('aep_gwh', 'total_aep_gwh', 'power_w'), ('aep_without_wakes_gwh', 'total_aep_without_wakes_gwh', 'power_without_wakes_w')]:
            _numeric_array(data[field], (shape[0],), field)
            _numeric_array(data[total], (), total)
            if any(v < 0 for v in data[field]) or data[total] < 0:
                raise ValueError('Negative wind farm energy totals')
            expected = (np.asarray(data[power]) * weights).sum(axis=(1, 2)) * 8760 / 1e9
            if not np.allclose(data[field], expected, rtol=1e-9, atol=1e-12) or not math.isclose(data[total], float(expected.sum()), rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError('Inconsistent wind farm energy totals')
        reference = data['total_aep_without_wakes_gwh']
        loss = data.get('wake_loss_fraction')
        if reference == 0:
            if loss is not None:
                raise ValueError('Wake loss is undefined for zero baseline AEP')
        else:
            _numeric_array(loss, (), 'wake_loss_fraction')
            expected_loss = (reference - data['total_aep_gwh']) / reference
            if not math.isclose(loss, expected_loss, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError('Wake loss is inconsistent with energy totals')



def _validate_record(record):
    if not isinstance(record, dict) or record.get('schema_version') != 1 or record.get('state') not in COMPLETED or not isinstance(record.get('id'), str) or not isinstance(record.get('name'), str):
        raise ValueError('Only completed external runs can be archived')
    result = record.get('result')
    job = record.get('external_job')
    if not isinstance(result, dict) or result.get('schema_version') != 1 or result.get('kind') != 'external' or not isinstance(job, dict) or result.get('adapter_id') not in ADAPTERS or result['adapter_id'] != job.get('adapter_id'):
        raise ValueError('Archive requires an OpenFAST or PyWake external result')
    if record['state'] == 'succeeded' and result.get('data') is None:
        raise ValueError('Successful external runs require normalized data')
    _validate_data(result.get('data'), result['adapter_id'])
    artifacts = result.get('artifacts')
    if not isinstance(artifacts, list) or len(artifacts) > MAX_FILES - 2 or len(set(artifacts)) != len(artifacts):
        raise ValueError('Invalid or duplicate artifact list')
    for name in artifacts:
        _relative(name)
    if record.get('workflow'):
        from nova.workflow.engine import validate
        validate(record['workflow'])
        types = {n['type'] for n in record['workflow']['nodes']}
        if types != {result['adapter_id'], result['adapter_id'] + '_input'}:
            raise ValueError('Workflow and external adapter do not match')
    canonical_json(record)


def export_external_run(run_id):
    record = library.get('run', run_id)
    _validate_record(record)
    result = record['result']
    base = (database.DB_PATH.parent / 'external-runs').resolve()
    root = Path(record['external_job']['artifact_root'])
    directory = Path(result['working_directory'])
    if root.is_symlink() or directory.is_symlink() or root.resolve().parent != base or not root.is_dir() or not directory.resolve().is_relative_to(root.resolve()):
        raise ValueError('External run does not own this artifact directory')
    for path in [directory, *directory.parents]:
        if path.is_symlink():
            raise ValueError('External artifact directory contains symlinks')
        if path == root:
            break
    replacements = _redactions(record)
    portable = {key: copy.deepcopy(record[key]) for key in ('id', 'schema_version', 'name', 'state', 'progress', 'created_at', 'started_at', 'finished_at', 'logs', 'error', 'inputs', 'workflow', 'archive_origin_run') if key in record}
    portable['external_job'] = {'adapter_id': result['adapter_id'], 'operation': 'portable_import'}
    portable['result'] = {key: copy.deepcopy(result[key]) for key in ('kind', 'schema_version', 'adapter_id', 'data', 'provenance', 'artifacts') if key in result}
    portable = _sanitize(portable, replacements)
    # Redaction applies to execution metadata, never channel names, scientific
    # quantities or relative artifact names that happen to resemble a secret.
    portable['inputs'] = _sanitize(record.get('inputs', {}), [])
    if record.get('workflow') is not None:
        portable['workflow'] = _sanitize(record['workflow'], [])
    portable['result']['data'] = copy.deepcopy(result.get('data'))
    portable['result']['artifacts'] = list(result['artifacts'])
    payloads = {'run.json': canonical_json(portable).encode()}
    total = len(payloads['run.json'])
    if total > MAX_JSON_BYTES:
        raise ValueError('Run metadata exceeds archive limit')
    for name in result['artifacts']:
        source = _owned_file(directory, name)
        if source.stat().st_size > MAX_EXPANDED_BYTES:
            raise ValueError('Artifact exceeds archive limit')
        with source.open('rb') as stream:
            data = stream.read(MAX_EXPANDED_BYTES + 1)
        if len(data) > MAX_EXPANDED_BYTES:
            raise ValueError('Artifact exceeds archive limit')
        if source.suffix.lower() == '.json':
            original = _json(data)
            metadata = source.name in ('case.json', 'execution.json', 'failure.json', 'workflow.json')
            cleaned = _sanitize(original, replacements if metadata else [])
            if cleaned != original:
                data = canonical_json(cleaned).encode()
        elif source.suffix.lower() in ('.log',):
            try:
                text = data.decode('utf-8')
                for value in replacements:
                    text = text.replace(value, '[redacted]')
                data = text.encode()
            except UnicodeDecodeError:
                pass
        payloads['artifacts/' + name] = data
        total += len(data)
        if total > MAX_EXPANDED_BYTES:
            raise ValueError('Expanded archive exceeds 100 MiB')
    manifest = {'format': 'nova-external-run', 'schema_version': 1,
                'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in payloads.items()}}
    manifest_bytes = canonical_json(manifest).encode()
    if total + len(manifest_bytes) > MAX_EXPANDED_BYTES:
        raise ValueError('Expanded archive including manifest exceeds 100 MiB')
    output = io.BytesIO()
    # Stored entries avoid pathological compression ratios for legitimate
    # constant time series and bound decompression work during future imports.
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', manifest_bytes)
        for name, data in payloads.items():
            archive.writestr(name, data)
    if output.tell() > MAX_ARCHIVE_BYTES:
        raise ValueError('Archive exceeds 128 MiB')
    return output.getvalue()


def read_external_archive(content):
    """Fully validate structure, bytes and scientific data before any writes."""
    if not isinstance(content, bytes) or not content or len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError('Archive exceeds 128 MiB or is empty')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            names = [info.filename for info in members]
            if len(members) > MAX_FILES or len(names) != len(set(names)) or not {'manifest.json', 'run.json'} <= set(names):
                raise ValueError('Missing or duplicate archive entries')
            if sum(info.file_size for info in members) > MAX_EXPANDED_BYTES:
                raise ValueError('Expanded archive exceeds 100 MiB')
            for info in members:
                _relative(info.filename)
                mode = info.external_attr >> 16
                if info.is_dir() or info.flag_bits & 1 or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or info.file_size > 200 * max(info.compress_size, 1):
                    raise ValueError('Unsupported, special or excessive-compression ZIP entry')
                if info.filename not in ('manifest.json', 'run.json') and not info.filename.startswith('artifacts/'):
                    raise ValueError('Unexpected archive entry')
            for name in names:
                if any(str(parent) in set(names) for parent in PurePosixPath(name).parents if str(parent) != '.'):
                    raise ValueError('Conflicting archive file paths')
            manifest = _json(archive.read('manifest.json'))
            if not isinstance(manifest, dict) or manifest.get('format') != 'nova-external-run' or manifest.get('schema_version') != 1 or set(manifest.get('files', {})) != set(names) - {'manifest.json'}:
                raise ValueError('Invalid external archive manifest')
            payloads = {}
            for name, spec in manifest['files'].items():
                data = archive.read(name)
                if spec != {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}:
                    raise ValueError('External archive checksum mismatch')
                payloads[name] = data
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError('Invalid external archive ZIP') from exc
    record = _json(payloads.pop('run.json'))
    _validate_record(record)
    # Imported metadata cannot introduce executable configuration or local paths.
    clean = _sanitize(record, [])
    if clean != record:
        raise ValueError('Portable archive contains machine-local configuration or secrets')
    expected = {'artifacts/' + name for name in record['result']['artifacts']}
    if set(payloads) != expected:
        raise ValueError('Archive artifacts differ from the run manifest')
    normalized = record['result'].get('data')
    if record['result']['adapter_id'] == 'openfast' and normalized is not None:
        source = normalized['source']
        candidates = [data for name, data in payloads.items() if PurePosixPath(name).name == source['filename']]
        if not any(hashlib.sha256(data).hexdigest() == source['sha256'] for data in candidates):
            raise ValueError('OpenFAST raw source does not match normalized result provenance')
    for name, data in payloads.items():
        if name.lower().endswith('.json'):
            value = _json(data)
            if _sanitize(value, []) != value:
                raise ValueError('Artifact metadata contains local configuration or secrets')
    return record, {name.removeprefix('artifacts/'): data for name, data in payloads.items()}


def import_external_archive(content):
    record, files = read_external_archive(content)
    new_id = str(uuid.uuid4())
    base = database.DB_PATH.parent / 'external-runs'
    base.mkdir(parents=True, exist_ok=True)
    if base.is_symlink():
        raise ValueError('External run store cannot be a symlink')
    staging = Path(tempfile.mkdtemp(prefix='.import-', dir=base))
    destination = base / new_id
    committed = False
    if destination.exists():
        shutil.rmtree(staging)
        raise ValueError('External archive destination already exists')
    try:
        for name, data in files.items():
            path = staging.joinpath(*PurePosixPath(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
            path.chmod(0o600)
        restored = {**record, 'id': new_id, 'revision': 1, 'updated_at': library.now(),
                    'project_id': None, 'imported_from_run': record['id'],
                    'archive_origin_run': record.get('archive_origin_run', record['id']), 'portable_import': True,
                    'external_job': {'adapter_id': record['result']['adapter_id'], 'operation': 'portable_import',
                                     'artifact_root': str(destination.resolve())},
                    'result': {**record['result'], 'working_directory': str(destination.resolve())}}
        serialized = canonical_json(restored)
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO nova_records VALUES (?,?,?,?,?)',
                       (new_id, 'run', 1, serialized, restored['updated_at']))
            os.replace(staging, destination)
        committed = True
        return restored
    finally:
        if not committed:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(destination, ignore_errors=True)
