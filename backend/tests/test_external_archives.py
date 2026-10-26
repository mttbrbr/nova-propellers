"""Portable external archives preserve scientific bytes, never local execution."""
import base64
import copy
import hashlib
import io
import json
import sqlite3
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
from nova.adapters.openfast import read_openfast_bytes
from nova.application.external import result_csv
from nova.core.data import canonical_json
from nova.infrastructure import library
from nova.infrastructure.external_archive import (
    export_external_run, import_external_archive, read_external_archive,
)
from nova.transport.external_archive_api import router
from nova.workflow.engine import external_template

SOURCE = b'NOVA original source\nTime GenPwr\n(s) (kW)\n0 10\n1 20\n'


class ExternalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(database, 'DB_PATH', self.root / 'library.db')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        library.initialize()

    def record(self, state='succeeded'):
        root = self.root / 'external-runs' / 'original-run'
        directory = root / 'openfast-case'
        directory.mkdir(parents=True)
        source = directory / 'source' / 'raw.out'
        source.parent.mkdir()
        source.write_bytes(SOURCE)
        data = read_openfast_bytes(SOURCE, 'raw.out')
        configuration = {'executable': '/private/bin/openfast', 'environment_kind': 'local_executable',
                         'options': {'api_token': 'private-token-value'}}
        provenance = {'state': state, 'configuration': configuration,
                      'program': {'version': '4.1.1'}, 'input_files': {'case/main.fst': 'abc123'},
                      'source_sha256': hashlib.sha256(SOURCE).hexdigest()}
        (directory / 'execution.json').write_text(canonical_json(provenance))
        (directory / 'result.json').write_text(json.dumps(data, indent=2))
        (directory / 'case.json').write_text(json.dumps({'case_directory': '/private/original', 'input_file': 'main.fst'}))
        (directory / 'process.log').write_text('Program /private/bin/openfast; credential private-token-value\n')
        result = {'kind': 'external', 'schema_version': 1, 'adapter_id': 'openfast', 'data': data,
                  'working_directory': str(directory), 'provenance': provenance,
                  'artifacts': ['source/raw.out', 'execution.json', 'result.json', 'case.json', 'process.log']}
        return library.save('run', {'schema_version': 1, 'project_id': None, 'name': 'Original result',
                                    'state': state, 'progress': 1., 'logs': ['/private/bin/openfast finished'],
                                    'inputs': {'case_directory': '/private/original', 'input_file': 'main.fst', 'output_file': 'main.out'},
                                    'workflow': external_template('openfast'), 'finished_at': '2026-10-16T12:00:00Z',
                                    'external_job': {'adapter_id': 'openfast', 'artifact_root': str(root),
                                                     'configuration': configuration, 'integration_id': 'local-only'},
                                    'result': result})

    def rewrite(self, content, *, changes=None, extra=None, rehash=False, compression=zipfile.ZIP_STORED):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries.update(changes or {})
        entries.update(extra or {})
        if rehash:
            manifest = json.loads(entries['manifest.json'])
            manifest['files'] = {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in entries.items() if name != 'manifest.json'}
            entries['manifest.json'] = canonical_json(manifest).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression) as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return output.getvalue()

    def test_round_trip_raw_bytes_csv_workflow_and_redaction(self):
        original = self.record()
        archive = export_external_run(original['id'])
        _record, files = read_external_archive(archive)
        self.assertEqual(files['source/raw.out'], SOURCE)
        self.assertNotIn(b'private-token-value', archive)
        self.assertNotIn(b'/private/', archive)
        self.assertNotIn(b'local-only', archive)
        self.assertEqual(files['result.json'], Path(original['result']['working_directory'], 'result.json').read_bytes())
        self.assertEqual(json.loads(files['execution.json'])['input_files'], {'case/main.fst': 'abc123'})
        imported = import_external_archive(archive)
        self.assertNotEqual(imported['id'], original['id'])
        self.assertEqual(imported['imported_from_run'], original['id'])
        self.assertEqual(imported['state'], original['state'])
        self.assertEqual(imported['workflow'], original['workflow'])
        self.assertEqual(result_csv(imported['result']['data']), result_csv(original['result']['data']))
        self.assertNotIn('configuration', imported['external_job'])
        self.assertNotIn('case_directory', imported['inputs'])
        restored = Path(imported['result']['working_directory'])
        self.assertEqual((restored / 'source/raw.out').read_bytes(), SOURCE)
        self.assertEqual((restored / 'source/raw.out').stat().st_mode & 0o777, 0o600)
        self.assertEqual(library.get('run', imported['id']), imported)
        with self.assertRaises(ValueError):
            library.save('run', imported, imported['id'])

    def test_completed_failure_states_preserved(self):
        record = self.record(state='cancelled')
        restored = import_external_archive(export_external_run(record['id']))
        self.assertEqual(restored['state'], 'cancelled')
        self.assertEqual(restored['finished_at'], record['finished_at'])

    def test_invalid_archives_never_write(self):
        record = self.record()
        content = export_external_run(record['id'])
        invalid = [self.rewrite(content, changes={'artifacts/source/raw.out': b'corrupted'}),
                   self.rewrite(content, extra={'../escaped': b'bad'}, rehash=True),
                   self.rewrite(content, extra={'artifacts/C:/escaped': b'bad'}, rehash=True),
                   self.rewrite(content, extra={'unlisted': b'bad'}, rehash=True),
                   self.rewrite(content, extra={'artifacts/bomb': b'0' * 2_000_000}, rehash=True,
                                compression=zipfile.ZIP_DEFLATED)]
        baseline = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        for archive in invalid:
            with self.subTest(size=len(archive)), self.assertRaises(ValueError):
                import_external_archive(archive)
            self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), baseline)
            self.assertEqual(len(library.list_records('run')), 1)

    def test_symlink_entries_and_sources_rejected(self):
        record = self.record()
        content = export_external_run(record['id'])
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(output, 'w') as target:
            for entry in source.infolist():
                if entry.filename == 'artifacts/source/raw.out':
                    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                target.writestr(entry, source.read(entry.filename))
        with self.assertRaises(ValueError):
            import_external_archive(output.getvalue())
        path = Path(record['result']['working_directory']) / 'source/raw.out'
        path.unlink()
        path.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            export_external_run(record['id'])

    def test_database_failure_removes_staged_files(self):
        record = self.record()
        content = export_external_run(record['id'])
        before = sorted(p.name for p in (self.root / 'external-runs').iterdir())
        with patch('nova.infrastructure.external_archive.database.connect', side_effect=sqlite3.OperationalError('fixture DB failure')):
            with self.assertRaises(sqlite3.OperationalError):
                import_external_archive(content)
        self.assertEqual(sorted(p.name for p in (self.root / 'external-runs').iterdir()), before)
        self.assertEqual(len(library.list_records('run')), 1)

    def test_api_import_export(self):
        record = self.record()
        from nova.transport.external_api import router as existing_router
        app = FastAPI()
        app.include_router(router)
        app.include_router(existing_router)
        with TestClient(app) as client:
            exported = client.get('/api/v1/external-runs/' + record['id'] + '/archive')
            self.assertEqual(exported.status_code, 200)
            self.assertIn('.nova-run', exported.headers['content-disposition'])
            imported = client.post('/api/v1/external-runs/import', json={'content_base64': base64.b64encode(exported.content).decode()})
            self.assertEqual(imported.status_code, 200, imported.text)
            self.assertNotEqual(imported.json()['id'], record['id'])
            restored_id = imported.json()['id']
            self.assertEqual(client.get(f'/api/v1/external-runs/{restored_id}').json()['id'], restored_id)
            self.assertEqual(client.get(f'/api/v1/external-runs/{restored_id}/artifacts/source/raw.out').content, SOURCE)
            self.assertIn('GenPwr [kW]', client.get(f'/api/v1/external-runs/{restored_id}/csv').text)
            self.assertEqual(client.post('/api/v1/external-runs/import', json={'content_base64': 'bad@@'}).status_code, 422)

    def test_pywake_scientific_result_round_trip(self):
        from nova.adapters.pywake import PyWakeAdapter
        from test_pywake_adapter import PyWakeTests, case
        inputs = case()
        data = PyWakeAdapter().normalize(PyWakeTests().fixture_output(inputs))
        root = self.root / 'external-runs' / 'wind-run'
        root.mkdir(parents=True)
        source = json.dumps(inputs, indent=2).encode()
        (root / 'input.json').write_bytes(source)
        result = {'kind': 'external', 'schema_version': 1, 'adapter_id': 'pywake', 'data': data,
                  'working_directory': str(root), 'provenance': {'program': {'version': 'fixture'}},
                  'artifacts': ['input.json']}
        record = library.save('run', {'schema_version': 1, 'name': 'Wind farm', 'state': 'succeeded',
                                     'inputs': inputs, 'workflow': external_template('pywake'),
                                     'external_job': {'adapter_id': 'pywake', 'artifact_root': str(root),
                                                      'configuration': {'executable': '/private/python'}},
                                     'result': result})
        restored = import_external_archive(export_external_run(record['id']))
        self.assertEqual(restored['result']['data'], data)
        self.assertEqual(result_csv(restored['result']['data']), result_csv(data))
        self.assertEqual(Path(restored['result']['working_directory'], 'input.json').read_bytes(), source)

    def test_rename_failure_rolls_back_database_and_files(self):
        record = self.record()
        content = export_external_run(record['id'])
        before = sorted(p.name for p in (self.root / 'external-runs').iterdir())
        with patch('nova.infrastructure.external_archive.os.replace', side_effect=OSError('fixture rename failure')):
            with self.assertRaises(OSError):
                import_external_archive(content)
        self.assertEqual(len(library.list_records('run')), 1)
        self.assertEqual(sorted(p.name for p in (self.root / 'external-runs').iterdir()), before)

    def test_tampered_metadata_and_duplicate_zip_names_rejected(self):
        content = export_external_run(self.record()['id'])
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            metadata = json.loads(archive.read('run.json'))
        metadata['external_job']['configuration'] = {'executable': '/other/machine/program'}
        bad = self.rewrite(content, changes={'run.json': canonical_json(metadata).encode()}, rehash=True)
        with self.assertRaises(ValueError):
            import_external_archive(bad)
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(output, 'w') as archive:
            for info in source.infolist():
                archive.writestr(info, source.read(info.filename))
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                archive.writestr('manifest.json', b'{}')
        with self.assertRaises(ValueError):
            import_external_archive(output.getvalue())
        self.assertEqual(len(library.list_records('run')), 1)

    def test_pywake_array_shapes_numeric_types_and_wake_loss(self):
        from nova.adapters.pywake import PyWakeAdapter
        from nova.infrastructure.external_archive import _validate_data
        from test_pywake_adapter import PyWakeTests, case
        valid = PyWakeAdapter().normalize(PyWakeTests().fixture_output(case()))
        _validate_data(valid, 'pywake')
        mutations = [lambda d: d.update(aep_gwh=d['aep_gwh'][0]),
                     lambda d: d.update(aep_gwh=[d['aep_gwh'][0]]),
                     lambda d: d.update(aep_without_wakes_gwh=[[v] for v in d['aep_without_wakes_gwh']]),
                     lambda d: d.update(aep_gwh=[True, False]),
                     lambda d: d.update(aep_gwh=[str(v) for v in d['aep_gwh']]),
                     lambda d: d.update(aep_gwh=[float('nan'), 0]),
                     lambda d: d.update(total_aep_gwh=True),
                     lambda d: d.update(total_aep_without_wakes_gwh=float('inf')),
                     lambda d: d.update(wake_loss_fraction=True),
                     lambda d: d.update(wake_loss_fraction=None),
                     lambda d: d.update(wake_loss_fraction=float('nan')),
                     lambda d: d.update(wake_loss_fraction=d['wake_loss_fraction'] + .1)]
        for mutate in mutations:
            bad = copy.deepcopy(valid)
            mutate(bad)
            with self.subTest(data=bad), self.assertRaises(ValueError):
                _validate_data(bad, 'pywake')
        zero = copy.deepcopy(valid)
        for key in ('power_w', 'power_without_wakes_w'):
            zero[key] = [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]
        zero.update(aep_gwh=[0, 0], aep_without_wakes_gwh=[0, 0],
                    total_aep_gwh=0, total_aep_without_wakes_gwh=0, wake_loss_fraction=None)
        # Zero wind is accepted by the adapter and must remain portable.
        zero['speeds_m_s'][0] = 0
        zero['effective_speed_m_s'] = [[[0, 10], [0, 10]], [[0, 10], [0, 10]]]
        _validate_data(zero, 'pywake')
        zero['wake_loss_fraction'] = 0
        with self.assertRaises(ValueError):
            _validate_data(zero, 'pywake')


if __name__ == '__main__':
    unittest.main()
