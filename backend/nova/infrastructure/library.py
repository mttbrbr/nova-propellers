"""Additive SQLite library; immutable JSON records and portable archives."""
import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone

from database import connect
from nova.core.data import canonical_json, content_hash
from nova.core.geometry_assets import geometry_definition, geometry_hash

KINDS = {'project', 'asset', 'workflow', 'run', 'integration', 'simulation', 'geometry', 'run_link'}


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS nova_migrations (version INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS nova_records (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, revision INTEGER NOT NULL,
            document TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT OR IGNORE INTO nova_migrations VALUES (1);
        ''')
        rows = db.execute("SELECT id, document FROM nova_records WHERE kind='run'").fetchall()
        for row in rows:
            document = json.loads(row['document'])
            if document['state'] in ('queued', 'running', 'cancelling'):
                document.update(state='interrupted', finished_at=now())
                if (document.get('result') or {}).get('kind') == 'study':
                    document['result']['study_status'] = 'interrupted'
                if (document.get('result') or {}).get('kind') == 'comparison':
                    from nova.application.comparisons import comparison_rows
                    document['result']['comparison_status'] = 'interrupted'
                    document['result']['rows'] = comparison_rows(document)
                db.execute('UPDATE nova_records SET document=? WHERE id=?', (canonical_json(document), row['id']))


def save(kind, document, id=None, expected_revision=None, new_asset=None):
    if kind not in KINDS:
        raise ValueError('Unknown record kind')
    id = id or str(uuid.uuid4())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM nova_records WHERE id=?', (id,)).fetchone()
        if row and row['kind'] != kind:
            raise ValueError('Record kind mismatch')
        if kind == 'simulation':
            parent = db.execute("SELECT id FROM nova_records WHERE id=? AND kind='project'", (document.get('project_id'),)).fetchone()
            if not parent:
                raise ValueError('Simulation requires an existing project')
            if row and json.loads(row['document'])['project_id'] != document['project_id']:
                raise ValueError('Simulation cannot move to another project')
            if row and json.loads(row['document']).get('kind', 'propeller') != document.get('kind', 'propeller'):
                raise ValueError('Simulation kind cannot change')
        if row and kind == 'run' and json.loads(row['document']).get('state') in ('succeeded', 'failed', 'cancelled', 'interrupted'):
            raise ValueError('Completed runs are immutable')
        if row and kind in ('asset', 'geometry', 'run_link'):
            raise ValueError('Assets and geometry revisions are immutable')
        if expected_revision is not None and (row['revision'] if row else 0) != expected_revision:
            raise ValueError('Revision conflict; reload before saving')
        if not row and kind == 'run' and document.get('simulation_id'):
            current_row = db.execute("SELECT document FROM nova_records WHERE id=? AND kind='simulation'",
                                     (document['simulation_id'],)).fetchone()
            current = json.loads(current_row['document']) if current_row else {}
            if current.get('project_id') != document.get('project_id') or current.get('revision') != document.get('simulation_revision'):
                raise ValueError('Revision conflict; simulation changed before queueing')
        if not row and kind == 'run' and document.get('comparison'):
            for source in document['comparison']['simulations']:
                existing = db.execute("SELECT document FROM nova_records WHERE id=? AND kind='simulation'", (source['id'],)).fetchone()
                current = json.loads(existing['document']) if existing else {}
                if current.get('project_id') != document['project_id'] or current.get('revision') != source['revision'] or any(current.get(k) != source.get(k) for k in ('name', 'inputs', 'workflow', 'conditions', 'polar_asset_id', 'geometry_id', 'geometry_revision')):
                    raise ValueError('Revision conflict; selected simulation changed before queueing')
        revision = row['revision'] + 1 if row else 1
        if new_asset is not None:
            if kind != 'simulation' or document.get('asset_id') != new_asset['id']:
                raise ValueError('New case asset must belong to the saved simulation')
            db.execute('INSERT INTO nova_records VALUES (?, ?, ?, ?, ?)',
                       (new_asset['id'], 'asset', 1, canonical_json(new_asset), new_asset['updated_at']))
        result = {**document, 'id': id, 'revision': revision, 'updated_at': now()}
        if kind in ('project', 'simulation') and 'inputs' in document and all(key in document['inputs'] for key in ('geometry_method', 'airfoil_assignments')):
            owner = id if kind == 'project' else document['project_id']
            previous = json.loads(row['document']) if row else None
            geometry = _link_geometry(db, result, owner, previous)
            result.update(geometry_id=geometry['geometry_id'], geometry_revision=geometry['geometry_revision'])
        if kind == 'simulation' and result.get('kind') == 'propeller' and 'configuration' in result:
            result['configuration'] = {key: result[key] for key in
                ('inputs', 'workflow', 'conditions', 'polar_asset_id', 'geometry_id', 'geometry_revision') if key in result}
        db.execute('INSERT INTO nova_records VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, document=excluded.document, updated_at=excluded.updated_at',
                   (id, kind, revision, canonical_json(result), result['updated_at']))
    return result


def _geometries(db, project_id):
    return [value for row in db.execute("SELECT document FROM nova_records WHERE kind='geometry'").fetchall()
            if (value := json.loads(row['document']))['project_id'] == project_id]


def _insert_geometry(db, project_id, name, definition, geometry_id=None):
    from nova.application.geometry import create_propeller_geometry
    canonical = create_propeller_geometry({**definition, 'rpm': 5000., 'thrust_target': 1.})
    family = geometry_id or str(uuid.uuid4())
    revisions = [g['geometry_revision'] for g in _geometries(db, project_id) if g['geometry_id'] == family]
    value = {'schema_version': 1, 'id': str(uuid.uuid4()), 'revision': 1, 'updated_at': now(),
             'project_id': project_id, 'geometry_id': family, 'geometry_revision': max(revisions, default=0) + 1,
             'name': name, 'definition': definition, 'content_hash': geometry_hash(definition),
             'canonical_geometry': canonical, 'canonical_geometry_hash': content_hash(canonical),
             'role': 'baseline_input_geometry'}
    db.execute('INSERT INTO nova_records VALUES (?,?,?,?,?)',
               (value['id'], 'geometry', 1, canonical_json(value), value['updated_at']))
    return value


def _link_geometry(db, document, owner, previous=None):
    definition = geometry_definition(document['inputs'])
    geometries = _geometries(db, owner)
    family, revision = document.get('geometry_id'), document.get('geometry_revision')
    if family is not None or revision is not None:
        selected = next((g for g in geometries if g['geometry_id'] == family and g['geometry_revision'] == revision), None)
        if not selected or selected['content_hash'] != geometry_hash(definition):
            raise ValueError('Geometry reference is absent, owned by another project, or differs from inputs')
        return selected
    matches = [g for g in geometries if g['content_hash'] == geometry_hash(definition)]
    if matches:
        previous_family = (previous or {}).get('geometry_id')
        return next((g for g in reversed(matches) if g['geometry_id'] == previous_family), matches[-1])
    return _insert_geometry(db, owner, document['name'] + ' geometry', definition,
                            (previous or {}).get('geometry_id'))


def get_geometry(project_id, geometry_id, geometry_revision):
    with connect() as db:
        value = next((g for g in _geometries(db, project_id) if g['geometry_id'] == geometry_id and g['geometry_revision'] == geometry_revision), None)
    if value is None:
        raise KeyError('Geometry revision not found for this project')
    return value


def publish_geometry(project_id, name, inputs, geometry_id=None, expected_geometry_revision=None, updates=None):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT id FROM nova_records WHERE id=? AND kind='project'", (project_id,)).fetchone():
            raise KeyError('Project not found')
        existing = [g for g in _geometries(db, project_id) if g['geometry_id'] == geometry_id]
        if geometry_id is not None and not existing:
            raise ValueError('Geometry family is absent or owned by another project')
        latest = max((g['geometry_revision'] for g in existing), default=0)
        if expected_geometry_revision is not None and expected_geometry_revision != latest:
            raise ValueError('Revision conflict; reload geometry before publishing')
        geometry = _insert_geometry(db, project_id, name, geometry_definition(inputs), geometry_id)
        if updates is not None:
            updates = [({**document, 'geometry_id': geometry['geometry_id'], 'geometry_revision': geometry['geometry_revision']}, revision) for document, revision in updates]
            return {'geometry': geometry, 'simulations': _adopt_geometries(db, project_id, geometry, updates)}
        return geometry


def adopt_geometry(project_id, geometry, updates):
    """Optimistic checks and all selected simulation writes share one transaction."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return _adopt_geometries(db, project_id, geometry, updates)


def _adopt_geometries(db, project_id, geometry, updates):
    pending = []
    for document, expected_revision in updates:
        row = db.execute("SELECT * FROM nova_records WHERE id=? AND kind='simulation'", (document['id'],)).fetchone()
        if not row or json.loads(row['document'])['project_id'] != project_id:
            raise ValueError('Simulation is absent or owned by another project')
        if row['revision'] != expected_revision:
            raise ValueError('Revision conflict; reload simulation before adopting geometry')
        linked = _link_geometry(db, document, project_id)
        if linked['id'] != geometry['id']:
            raise ValueError('Adoption geometry mismatch')
        value = {**document, 'revision': row['revision'] + 1, 'updated_at': now()}
        pending.append(value)
    for value in pending:
        db.execute('UPDATE nova_records SET revision=?,document=?,updated_at=? WHERE id=?',
                   (value['revision'], canonical_json(value), value['updated_at'], value['id']))
    return pending


def get(kind, id):
    with connect() as db:
        row = db.execute('SELECT document FROM nova_records WHERE id=? AND kind=?', (id, kind)).fetchone()
    if row is None:
        raise KeyError(id)
    return json.loads(row['document'])


def list_records(kind):
    with connect() as db:
        rows = db.execute('SELECT document FROM nova_records WHERE kind=? ORDER BY updated_at DESC', (kind,)).fetchall()
    return [json.loads(row['document']) for row in rows]


def make_asset(document):
    payload = {**document, 'schema_version': 1}
    return save('asset', {**payload, 'content_hash': content_hash(payload)})


def export_project(id):
    project = get('project', id)
    records = {'project': project, 'assets': [], 'runs': [],
               'simulations': [s for s in list_records('simulation') if s['project_id'] == id],
               'geometries': [g for g in list_records('geometry') if g['project_id'] == id]}
    asset_ids = set(project.get('asset_ids', []))
    if project.get('polar_asset_id'):
        asset_ids.add(project['polar_asset_id'])
    for assignment in project.get('inputs', {}).get('airfoil_assignments', []):
        if assignment.get('asset_id'):
            asset_ids.add(assignment['asset_id'])
    records['runs'] = [r for r in list_records('run') if r.get('project_id') == id and r['state'] not in ('queued', 'running', 'cancelling')]
    comparison_sources = [s for run in records['runs'] for s in run.get('comparison', {}).get('simulations', [])]
    for run in [*records['runs'], *records['simulations'], *comparison_sources]:
        asset_ids.update(run.get('asset_ids', []))
        if run.get('polar_asset_id'):
            asset_ids.add(run['polar_asset_id'])
        for assignment in run.get('inputs', {}).get('airfoil_assignments', []):
            if assignment.get('asset_id'):
                asset_ids.add(assignment['asset_id'])
    for geometry in records['geometries']:
        for assignment in geometry['definition'].get('airfoil_assignments', []):
            if assignment.get('asset_id'):
                asset_ids.add(assignment['asset_id'])
    records['assets'] = [get('asset', aid) for aid in sorted(asset_ids)]
    data = canonical_json(records).encode()
    manifest = canonical_json({'schema_version': 1, 'sha256': hashlib.sha256(data).hexdigest()})
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', manifest)
        archive.writestr('project.json', data)
    return output.getvalue()


def read_archive(content):
    if len(content) > 20 * 1024 * 1024:
        raise ValueError('Archive exceeds 20 MiB')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if sorted(archive.namelist()) != ['manifest.json', 'project.json']:
            raise ValueError('Unexpected archive entries')
        if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError('Expanded archive exceeds 100 MiB')
        manifest = json.loads(archive.read('manifest.json'))
        data = archive.read('project.json')
    if manifest.get('schema_version') != 1 or hashlib.sha256(data).hexdigest() != manifest.get('sha256'):
        raise ValueError('Invalid archive version or checksum')
    records = json.loads(data)
    canonical_json(records)  # reject NaN/Inf before any mutation
    return records


def import_records(document, records):
    """All references were validated before entering this atomic transaction."""
    remap = {asset['id']: str(uuid.uuid4()) for asset in records['assets']}
    simulation_ids = {s['id']: str(uuid.uuid4()) for s in records.get('simulations', [])}
    geometry_ids = {g['geometry_id']: str(uuid.uuid4()) for g in records.get('geometries', [])}
    def remapped(value):
        result = dict(value)
        result['polar_asset_id'] = remap.get(value.get('polar_asset_id'))
        result['asset_ids'] = [remap[id] for id in value.get('asset_ids', [])]
        result['inputs'] = json.loads(canonical_json(value['inputs']))
        if value.get('geometry_id'):
            result['geometry_id'] = geometry_ids[value['geometry_id']]
        for item in result['inputs'].get('airfoil_assignments', []):
            if item.get('asset_id'):
                item['asset_id'] = remap[item['asset_id']]
        return result
    project = {**remapped(document), 'id': str(uuid.uuid4()), 'revision': 1, 'updated_at': now()}
    pending = [('project', project)]
    for geometry in records.get('geometries', []):
        definition = json.loads(canonical_json(geometry['definition']))
        for assignment in definition['airfoil_assignments']:
            if assignment.get('asset_id'):
                assignment['asset_id'] = remap[assignment['asset_id']]
        canonical = json.loads(canonical_json(geometry['canonical_geometry']))
        for assignment in canonical.get('airfoil_loft', []):
            if assignment.get('asset_id'):
                assignment['asset_id'] = remap[assignment['asset_id']]
        pending.append(('geometry', {**geometry, 'id': str(uuid.uuid4()), 'project_id': project['id'],
                                     'geometry_id': geometry_ids[geometry['geometry_id']], 'definition': definition,
                                     'canonical_geometry': canonical, 'canonical_geometry_hash': content_hash(canonical),
                                     'updated_at': now()}))
    for simulation in records.get('simulations', []):
        pending.append(('simulation', {**remapped(simulation), 'id': simulation_ids[simulation['id']],
                                       'project_id': project['id'], 'updated_at': now()}))
    for asset in records['assets']:
        payload = {k: v for k, v in asset.items() if k not in ('id', 'revision', 'updated_at', 'content_hash')}
        pending.append(('asset', {**payload, 'content_hash': content_hash(payload),
                                  'id': remap[asset['id']], 'revision': 1, 'updated_at': now()}))
    for run in records.get('runs', []):
        imported_run = {**remapped(run), 'project_id': project['id'],
                                'imported_from_run': run['id'], 'id': str(uuid.uuid4()),
                                'revision': 1, 'updated_at': now()}
        if run.get('simulation_id'):
            imported_run['simulation_id'] = simulation_ids[run['simulation_id']]
        if run.get('comparison'):
            from nova.application.comparisons import comparison_rows, validate_comparison
            sources = []
            for source in run['comparison']['simulations']:
                value = {**remapped(source), 'id': simulation_ids[source['id']], 'project_id': project['id']}
                if source.get('polar_asset'):
                    value['polar_asset'] = next(asset for kind, asset in pending if kind == 'asset' and asset['id'] == remap[source['polar_asset']['id']])
                sources.append(value)
            imported_run['comparison'] = {**run['comparison'], 'simulations': sources}
            imported_run['comparison_validation'] = validate_comparison(imported_run['comparison'])
            if run.get('result'):
                output = json.loads(canonical_json(run['result']))
                output['baseline_simulation_id'] = sources[0]['id']
                for case in output['cases']:
                    source = sources[case['index']]
                    case.update(simulation_id=source['id'], snapshot=source)
                imported_run['result'] = output
                output['rows'] = comparison_rows(imported_run)
        pending.append(('run', imported_run))
    # Serialization failures also happen before any database mutation.
    serialized = [(kind, value, canonical_json(value)) for kind, value in pending]
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for kind, value, json_value in serialized:
            db.execute('INSERT INTO nova_records VALUES (?, ?, ?, ?, ?)',
                       (value['id'], kind, value['revision'], json_value, value['updated_at']))
    return project
