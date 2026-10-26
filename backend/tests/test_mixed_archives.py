"""Mixed projects preserve immutable cases and reject corrupt portable data."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import database
from nova.core.data import canonical_json
from nova.infrastructure import library, mixed_archives


class MixedArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = patch.object(database, 'DB_PATH', Path(self.tmp.name) / 'test.db')
        self.db.start()
        self.addCleanup(self.db.stop)
        library.initialize()

    def project(self):
        project = library.save('project', {'schema_version': 2, 'name': 'Mixed'})
        from nova.application.simulation_cases import freeze_case
        from test_pywake_adapter import case
        asset = library.make_asset(freeze_case('pywake', 'Farm', case()))
        simulation = library.save('simulation', {'schema_version': 2, 'project_id': project['id'],
            'kind': 'pywake', 'name': 'Wind farm', 'configuration': {'asset_id': asset['id']},
            'asset_id': asset['id'], 'asset_ids': [asset['id']]})
        return project, asset, simulation

    def rewrite(self, archive, edit):
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            entries = {name: source.read(name) for name in source.namelist()}
        records = json.loads(entries['project.json'])
        edit(records)
        entries['project.json'] = canonical_json(records).encode()
        manifest = json.loads(entries['manifest.json'])
        manifest['files']['project.json'] = {'bytes': len(entries['project.json']),
            'sha256': hashlib.sha256(entries['project.json']).hexdigest()}
        entries['manifest.json'] = canonical_json(manifest).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as target:
            for name, data in entries.items():
                target.writestr(name, data)
        return output.getvalue()

    def test_round_trip_remaps_nested_case_references(self):
        project, asset, simulation = self.project()
        restored = mixed_archives.import_project(mixed_archives.export_project(project['id']))
        self.assertNotEqual(project['id'], restored['id'])
        simulations = [s for s in library.list_records('simulation') if s['project_id'] == restored['id']]
        self.assertEqual(len(simulations), 1)
        saved = simulations[0]
        self.assertNotEqual(simulation['id'], saved['id'])
        self.assertNotEqual(asset['id'], saved['asset_id'])
        self.assertEqual(saved['asset_id'], saved['configuration']['asset_id'])
        self.assertEqual(saved['asset_ids'], [saved['asset_id']])
        self.assertEqual(library.get('asset', saved['asset_id'])['case'], asset['case'])

    def test_corrupt_hash_dangling_reference_and_local_settings_are_atomic(self):
        project, _, _ = self.project()
        archive = mixed_archives.export_project(project['id'])
        for edit in (lambda r: r['assets'][0].update(content_hash='bad'),
                     lambda r: r['simulations'][0].update(asset_id='missing'),
                     lambda r: r['simulations'][0]['configuration'].update(executable='/usr/bin/tool')):
            with self.subTest(edit=edit):
                damaged = self.rewrite(archive, edit)
                with self.assertRaises(ValueError):
                    mixed_archives.import_project(damaged)
                self.assertEqual(len(library.list_records('project')), 1)

    def test_reject_traversal_and_executable_inline_files(self):
        project, _, _ = self.project()
        archive = mixed_archives.export_project(project['id'])
        for path in ('../outside.fst', 'controller.dll'):
            def edit(records):
                asset = records['assets'][0]
                asset['files'] = [{'path': path, 'content_base64': 'YWJj', 'sha256': hashlib.sha256(b'abc').hexdigest()}]
                from nova.core.data import content_hash
                asset['content_hash'] = content_hash({k: v for k, v in asset.items() if k not in ('id', 'revision', 'updated_at', 'content_hash')})
            with self.assertRaises(ValueError):
                mixed_archives.import_project(self.rewrite(archive, edit))

    def test_external_association_restores_artifacts_without_local_configuration(self):
        SOURCE = b'OpenFAST scientific output\n'
        self.root = Path(self.tmp.name)
        project, _, simulation = self.project()
        directory = self.root / 'external-runs' / 'original'
        (directory / 'source').mkdir(parents=True)
        (directory / 'source/raw.out').write_bytes(SOURCE)
        run = library.save('run', {'schema_version': 1, 'name': 'External', 'state': 'failed',
            'inputs': {}, 'external_job': {'adapter_id': 'openfast', 'artifact_root': str(directory)},
            'result': {'schema_version': 1, 'kind': 'external', 'adapter_id': 'openfast',
                'data': None, 'artifacts': ['source/raw.out'], 'working_directory': str(directory)}})
        link = library.save('run_link', {'schema_version': 2, 'project_id': project['id'], 'run_id': run['id']})
        archive = mixed_archives.export_project(project['id'])
        self.assertNotIn(b'/private/bin/openfast', archive)
        restored = mixed_archives.import_project(archive)
        links = [r for r in library.list_records('run_link') if r['project_id'] == restored['id']]
        self.assertEqual(len(links), 1)
        imported = library.get('run', links[0]['run_id'])
        self.assertNotEqual(imported['id'], run['id'])
        directory = Path(imported['result']['working_directory'])
        self.assertEqual((directory / 'source/raw.out').read_bytes(), SOURCE)
        self.assertEqual((directory / 'source/raw.out').stat().st_mode & 0o777, 0o600)
        self.assertEqual(imported['external_job']['operation'], 'portable_import')

    def test_external_project_history_keeps_configuration_revision(self):
        project, asset, simulation = self.project()
        folder = Path(self.tmp.name) / 'external-runs' / 'owned'
        folder.mkdir(parents=True)
        run = library.save('run', {'schema_version': 1, 'name': 'Historical farm run',
            'project_id': project['id'], 'simulation_id': simulation['id'],
            'simulation_revision': simulation['revision'], 'simulation_name': 'Earlier farm name',
            'simulation_kind': 'pywake', 'asset_id': asset['id'], 'asset_ids': [asset['id']],
            'input_hash': asset['case_hash'], 'state': 'failed', 'inputs': {},
            'external_job': {'adapter_id': 'pywake', 'artifact_root': str(folder)},
            'result': {'schema_version': 1, 'kind': 'external', 'adapter_id': 'pywake',
                       'data': None, 'artifacts': [], 'working_directory': str(folder)}})
        restored = mixed_archives.import_project(mixed_archives.export_project(project['id']))
        historical = next(r for r in library.list_records('run') if r.get('project_id') == restored['id'])
        self.assertEqual(historical['simulation_revision'], simulation['revision'])
        self.assertEqual(historical['simulation_name'], 'Earlier farm name')
        self.assertNotEqual(historical['simulation_id'], simulation['id'])
        self.assertNotEqual(historical['asset_id'], asset['id'])
        self.assertEqual(historical['input_hash'], run['input_hash'])

    def test_case_configuration_cannot_disagree_with_asset(self):
        project, _, _ = self.project()
        archive = mixed_archives.export_project(project['id'])
        damaged = self.rewrite(archive, lambda r: r['simulations'][0]['configuration'].update(case={'unrelated': 1}))
        with self.assertRaisesRegex(ValueError, 'immutable case'):
            mixed_archives.import_project(damaged)

    def test_openfast_case_survives_deleted_source_directory(self):
        from nova.application.simulation_cases import freeze_case, materialize_asset
        project = library.save('project', {'schema_version': 2, 'name': 'OpenFAST'})
        source = Path(self.tmp.name) / 'original-case'
        source.mkdir()
        (source / 'main.fst').write_text('Scientific fixture\n')
        asset = library.make_asset(freeze_case('openfast', 'Turbine', {
            'case_directory': str(source), 'input_file': 'main.fst', 'output_file': 'main.out'}))
        library.save('simulation', {'schema_version': 2, 'name': 'Turbine', 'kind': 'openfast',
            'project_id': project['id'], 'asset_id': asset['id'], 'configuration': {'case': asset['case']}})
        import shutil
        shutil.rmtree(source)
        restored = mixed_archives.import_project(mixed_archives.export_project(project['id']))
        simulation = next(s for s in library.list_records('simulation') if s['project_id'] == restored['id'])
        case = materialize_asset(library.get('asset', simulation['asset_id']), Path(self.tmp.name) / 'materialized')
        self.assertEqual((Path(case['case_directory']) / 'main.fst').read_text(), 'Scientific fixture\n')

    def test_native_simulation_in_neutral_project_validates_and_round_trips(self):
        from test_api_contract import ApiContractTests
        from nova.transport.api import checked_project, ProjectRequest
        from nova.workflow.engine import template
        project = library.save('project', {'schema_version': 2, 'name': 'Native'})
        document = checked_project(ProjectRequest(name='Propeller', inputs=ApiContractTests.geometry_payload(), workflow=template()))
        simulation = library.save('simulation', {**document, 'schema_version': 2, 'kind': 'propeller',
            'project_id': project['id'], 'configuration': document})
        restored = mixed_archives.import_project(mixed_archives.export_project(project['id']))
        saved = next(s for s in library.list_records('simulation') if s['project_id'] == restored['id'])
        self.assertNotEqual(saved['geometry_id'], simulation['geometry_id'])
        self.assertEqual(saved['inputs'], simulation['inputs'])

    def test_sql_failure_rolls_back_all_records(self):
        project, _, _ = self.project()
        archive = mixed_archives.export_project(project['id'])
        with database.connect() as db:
            db.execute("CREATE TRIGGER reject_asset BEFORE INSERT ON nova_records WHEN NEW.kind = 'asset' BEGIN SELECT RAISE(ABORT, 'reject'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            mixed_archives.import_project(archive)
        self.assertEqual(len(library.list_records('project')), 1)
