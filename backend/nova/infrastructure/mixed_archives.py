"""Portable mixed projects; validate everything before a single atomic restore."""
import base64
import hashlib
import io
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid
import zipfile

import database
from nova.core.data import canonical_json, content_hash
from nova.infrastructure import library, external_archive as external

GROUPS = {'assets': 'asset', 'simulations': 'simulation', 'geometries': 'geometry',
          'runs': 'run', 'run_links': 'run_link'}
REFS = {'project_id', 'simulation_id', 'baseline_simulation_id', 'run_id', 'asset_id',
        'polar_asset_id', 'geometry_id'}
FORBIDDEN = external.LOCAL_KEYS - {'configuration'}
BINARY = {'.exe', '.dll', '.so', '.dylib', '.bat', '.cmd', '.sh', '.py', '.ps1'}
LINEAGE = {'project_id', 'project_revision', 'simulation_id', 'simulation_revision',
           'simulation_name', 'simulation_kind', 'asset_id', 'asset_ids', 'input_hash'}


def _portable(value):
    if isinstance(value, dict):
        return {k: _portable(v) for k, v in value.items()
                if k not in FORBIDDEN and not external.SECRET_KEY.search(k)}
    if isinstance(value, list):
        return [_portable(v) for v in value]
    return value


def _file(name, data):
    from nova.application.simulation_cases import scientific_file
    scientific_file(name, data)
    path = external._relative(name)
    if path.suffix.lower() in BINARY or data.startswith((b'\x7fELF', b'MZ', b'#!')):
        raise ValueError('Executable and controller binaries are not portable')


def _asset(asset):
    payload = {k: v for k, v in asset.items() if k not in ('id', 'revision', 'updated_at', 'content_hash')}
    if asset.get('content_hash') != content_hash(payload):
        raise ValueError('Asset content hash mismatch')
    if asset.get('type') == 'simulation_case':
        from nova.application.simulation_cases import validate_asset
        validate_asset(asset)
    names = set()
    for entry in asset.get('files', []):
        name = entry['path']
        if name in names:
            raise ValueError('Duplicate case file')
        names.add(name)
        data = base64.b64decode(entry['content_base64'], validate=True)
        _file(name, data)
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Case file checksum mismatch')


def _references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in REFS and child:
                yield child
            elif key == 'asset_ids':
                yield from child
            else:
                yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def export_project(id):
    project = library.get('project', id)
    records = {'project': project}
    for group, kind in GROUPS.items():
        records[group] = [] if kind == 'asset' else [r for r in library.list_records(kind) if r.get('project_id') == id]
    linked = {r['run_id'] for r in records['run_links']}
    records['runs'] = [r for r in library.list_records('run')
                       if (r.get('project_id') == id or r['id'] in linked) and r.get('state') in external.COMPLETED]
    run_ids = {r['id'] for r in records['runs']}
    records['run_links'] = [r for r in records['run_links'] if r['run_id'] in run_ids]
    refs = set(_references(records))
    records['assets'] = [a for a in library.list_records('asset') if a['id'] in refs]
    entries = {}
    for index, run in enumerate(records['runs']):
        if (run.get('result') or {}).get('kind') == 'external':
            archive = external.export_external_run(run['id'])
            portable, files = external.read_external_archive(archive)
            for name, data in files.items():
                _file(name, data)
            for key in LINEAGE:
                if key in run:
                    portable[key] = run[key]
            records['runs'][index] = portable
            entries['external/' + run['id'] + '.nova'] = archive
    records = _portable(records)
    for asset in records['assets']:
        payload = {k: v for k, v in asset.items() if k not in ('id', 'revision', 'updated_at', 'content_hash')}
        asset['content_hash'] = content_hash(payload)
        _asset(asset)
    entries['project.json'] = canonical_json(records).encode()
    manifest = {'format': 'nova-project', 'schema_version': 2,
                'files': {k: {'bytes': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for k, v in entries.items()}}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', canonical_json(manifest))
        for name, data in entries.items():
            archive.writestr(name, data)
    content = output.getvalue()
    read_archive(content)
    return content


def read_archive(content):
    if not isinstance(content, bytes) or not content or len(content) > external.MAX_ARCHIVE_BYTES:
        raise ValueError('Invalid archive size')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            names = {i.filename for i in members}
            if len(names) != len(members) or len(names) > external.MAX_FILES or not {'manifest.json', 'project.json'} <= names:
                raise ValueError('Missing or duplicate archive entries')
            if sum(i.file_size for i in members) > external.MAX_EXPANDED_BYTES:
                raise ValueError('Expanded archive exceeds limit')
            for info in members:
                external._relative(info.filename)
                if info.is_dir() or info.flag_bits & 1 or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG) or info.compress_type not in (0, 8) or info.file_size > 200 * max(1, info.compress_size):
                    raise ValueError('Unsafe archive entry')
            manifest = external._json(archive.read('manifest.json'))
            if manifest.get('format') != 'nova-project' or manifest.get('schema_version') != 2 or set(manifest.get('files', {})) != names - {'manifest.json'}:
                raise ValueError('Invalid mixed project manifest')
            entries = {name: archive.read(name) for name in names - {'manifest.json'}}
            for name, data in entries.items():
                if manifest['files'][name] != {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
                    raise ValueError('Archive checksum mismatch')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError('Invalid project archive') from exc
    records = external._json(entries.pop('project.json'))
    if set(records) != {'project', *GROUPS} or records != _portable(records):
        raise ValueError('Invalid or machine-local project records')
    project = records['project']
    if project.get('schema_version') not in (1, 2) or not isinstance(project.get('name'), str):
        raise ValueError('Invalid mixed project')
    values = [project] + [v for group in GROUPS for v in records[group]]
    ids = [v['id'] for v in values]
    if any(not isinstance(id, str) or not id for id in ids) or len(ids) != len(set(ids)):
        raise ValueError('Invalid or duplicate record IDs')
    known = set(ids) | {g['geometry_id'] for g in records['geometries']}
    if any(ref not in known for ref in _references(records)):
        raise ValueError('Dangling archive reference')
    for group in ('simulations', 'geometries', 'run_links'):
        if any(v.get('project_id') != project['id'] for v in records[group]):
            raise ValueError('Record belongs to another project')
    assets = {a['id']: a for a in records['assets']}
    for asset in assets.values():
        _asset(asset)
    from nova.core.geometry_assets import geometry_hash
    for geometry in records['geometries']:
        if geometry.get('content_hash') != geometry_hash(geometry['definition']) or geometry.get('canonical_geometry_hash') != content_hash(geometry['canonical_geometry']):
            raise ValueError('Geometry checksum mismatch')
    run_ids = {r['id'] for r in records['runs']}
    if any(link['run_id'] not in run_ids for link in records['run_links']):
        raise ValueError('Run association does not reference a run')
    for simulation in records['simulations']:
        kind = simulation.get('kind', 'propeller')
        if simulation.get('schema_version') not in (1, 2) or kind not in ('propeller', 'openfast', 'pywake'):
            raise ValueError('Invalid simulation kind or version')
        if kind != 'propeller':
            asset = assets.get(simulation.get('asset_id'), {})
            if asset.get('type') != 'simulation_case' or asset.get('kind') != kind:
                raise ValueError('Simulation case asset mismatch')
            config = simulation.get('configuration', {})
            if set(config) - {'case', 'asset_id', 'notes', 'demonstration'}:
                raise ValueError('Unsupported scientific configuration')
            if config.get('asset_id', asset['id']) != asset['id'] or config.get('case', asset['case']) != asset['case']:
                raise ValueError('Simulation configuration differs from its immutable case')
            if simulation.get('workflow'):
                from nova.workflow.engine import validate
                validate(simulation['workflow'])
                if {n['type'] for n in simulation['workflow']['nodes']} != {kind, kind + '_input'}:
                    raise ValueError('Simulation workflow differs from its scientific kind')
    external_files = {}
    for run in records['runs']:
        if run.get('state') not in external.COMPLETED:
            raise ValueError('Only completed runs can be restored')
        if (run.get('result') or {}).get('kind') == 'external':
            name = 'external/' + run['id'] + '.nova'
            portable, files = external.read_external_archive(entries.pop(name))
            if {k: v for k, v in run.items() if k not in LINEAGE} != portable:
                raise ValueError('External run metadata mismatch')
            for path, data in files.items():
                _file(path, data)
            external_files[run['id']] = files
    if entries:
        raise ValueError('Unexpected archive payloads')
    native_simulations = [s for s in records['simulations'] if s.get('kind', 'propeller') == 'propeller']
    native_runs = [r for r in records['runs'] if (r.get('result') or {}).get('kind') != 'external']
    if native_simulations or native_runs or 'inputs' in project or records['geometries']:
        # Reuse the established scientific/history validator on a native view of
        # the graph. External cases have their own adapter validation above.
        from nova.transport.api import validate_archive_records
        seed = project if 'inputs' in project else next(iter(native_simulations or native_runs), None)
        if seed is None:
            raise ValueError('Native geometry requires a native scientific definition')
        native_project = {**seed, 'id': project['id'], 'schema_version': 1, 'name': project['name']}
        native = {'project': native_project,
                  'simulations': [{**s, 'schema_version': 1} for s in native_simulations],
                  'runs': native_runs, 'geometries': records['geometries'],
                  'assets': [a for a in records['assets'] if a.get('type') != 'simulation_case']}
        validate_archive_records(native)
    return records, external_files


def import_project(content):
    records, files = read_archive(content)
    values = [('project', records['project'])] + [(kind, value) for group, kind in GROUPS.items() for value in records[group]]
    remap = {value['id']: str(uuid.uuid4()) for _, value in values}
    remap.update({g['geometry_id']: str(uuid.uuid4()) for g in records['geometries']})
    def rewrite(value, key=None):
        if isinstance(value, dict):
            return {k: rewrite(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v, 'asset_id' if key == 'asset_ids' else None) for v in value]
        if isinstance(value, str) and key in REFS | {'id'}:
            return remap.get(value, value)
        return value
    pending = [(kind, {**rewrite(value), 'updated_at': library.now()}) for kind, value in values]
    staging = None
    destinations = []
    committed = False
    try:
        if files:
            base = database.DB_PATH.parent / 'external-runs'
            base.mkdir(parents=True, exist_ok=True)
            if base.is_symlink():
                raise ValueError('External store cannot be a symlink')
            staging = Path(tempfile.mkdtemp(prefix='.project-import-', dir=base))
            for old_id, payloads in files.items():
                folder = staging / remap[old_id]
                folder.mkdir()
                for name, data in payloads.items():
                    path = folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    path.chmod(0o600)
                destination = base / remap[old_id]
                if destination.exists():
                    raise ValueError('Restore destination exists')
                destinations.append((folder, destination))
                run = next(v for k, v in pending if k == 'run' and v['id'] == remap[old_id])
                run.update(portable_import=True, imported_from_run=old_id)
                run['external_job']['artifact_root'] = str(destination.resolve())
                run['result']['working_directory'] = str(destination.resolve())
        for kind, value in pending:
            if kind == 'asset':
                value['content_hash'] = content_hash({k: v for k, v in value.items() if k not in ('id', 'revision', 'updated_at', 'content_hash')})
            if kind == 'geometry':
                value['canonical_geometry_hash'] = content_hash(value['canonical_geometry'])
            if kind == 'run' and value.get('comparison'):
                from nova.application.comparisons import comparison_rows, validate_comparison
                value['comparison_validation'] = validate_comparison(value['comparison'])
                if value.get('result'):
                    value['result']['rows'] = comparison_rows(value)
        serialized = [(kind, value, canonical_json(value)) for kind, value in pending]
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for kind, value, data in serialized:
                db.execute('INSERT INTO nova_records VALUES (?,?,?,?,?)', (value['id'], kind, value.get('revision', 1), data, value['updated_at']))
            for folder, destination in destinations:
                os.replace(folder, destination)
        committed = True
        return pending[0][1]
    finally:
        if staging:
            shutil.rmtree(staging, ignore_errors=True)
        if not committed:
            for _, destination in destinations:
                shutil.rmtree(destination, ignore_errors=True)
