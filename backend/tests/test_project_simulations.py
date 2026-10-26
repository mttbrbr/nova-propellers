import base64
import copy
import hashlib
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_api_contract
from fastapi.testclient import TestClient

import database
from main import app
from nova.infrastructure import library
from nova.transport.simulation_api import router
from nova.workflow.engine import template

if not any(route.path == '/api/v1/simulations' for route in app.routes):
    app.include_router(router)


class ProjectSimulationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_patch = patch.object(database, 'DB_PATH', Path(self.directory.name) / 'nova.db')
        self.database_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.asset = self.client.post('/api/v1/assets/demonstration-polar', json={'airfoil': 'NACA 4412'}).json()
        self.payload = {'name': 'Propeller project', 'inputs': test_api_contract.ApiContractTests.geometry_payload(),
                        'workflow': template(), 'polar_asset_id': self.asset['id'], 'conditions': {}}
        self.project = self.client.post('/api/v1/projects', json=self.payload).json()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.database_patch.stop()
        self.directory.cleanup()

    def save(self, name='BEMT baseline', model='bemt'):
        payload = copy.deepcopy(self.payload)
        payload.update(name=name, project_id=self.project['id'])
        payload['workflow']['nodes'][3]['config']['model'] = model
        response = self.client.post('/api/v1/simulations', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def execute_simulation(self, simulation):
        response = self.client.post(f"/api/v1/simulations/{simulation['id']}/run", json={'expected_revision': simulation['revision']})
        self.assertEqual(response.status_code, 200, response.text)
        return self.wait_run(response.json())

    def wait_run(self, record):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            record = self.client.get(f"/api/v1/runs/{record['id']}").json()
            if record['state'] not in ('queued', 'running', 'cancelling'):
                self.assertEqual(record['state'], 'succeeded', record.get('error'))
                return record
            time.sleep(.05)
        self.fail('Small simulation exceeded test budget')

    def test_study_and_optimization_keep_saved_simulation_lineage(self):
        simulation = self.save('Saved LLT variant', 'llt')
        changed = copy.deepcopy(self.payload)
        changed.update(id=self.project['id'], expected_revision=1)
        changed['inputs']['rpm'] = 6000
        updated_project = self.client.post('/api/v1/projects', json=changed).json()
        study_response = self.client.post(f"/api/v1/simulations/{simulation['id']}/study", json={
            'expected_revision': 1, 'study': {'parameter': 'rpm', 'values': [3500, 4500]}})
        self.assertEqual(study_response.status_code, 200, study_response.text)
        study = self.wait_run(study_response.json())
        optimize_response = self.client.post(f"/api/v1/simulations/{simulation['id']}/optimize", json={
            'expected_revision': 1, 'solver': 'bemt', 'max_iterations': 10})
        self.assertEqual(optimize_response.status_code, 200, optimize_response.text)
        optimization = self.wait_run(optimize_response.json())
        for record in (study, optimization):
            self.assertEqual(record['simulation_id'], simulation['id'])
            self.assertEqual(record['simulation_name'], simulation['name'])
            self.assertEqual(record['simulation_revision'], 1)
            self.assertEqual(record['project_revision'], 2)
            self.assertEqual(record['inputs'], simulation['inputs'])
            self.assertEqual(record['workflow'], simulation['workflow'])
            self.assertEqual(record['inputs']['rpm'], 5000)
        self.assertEqual([c['inputs']['rpm'] for c in study['result']['cases']], [3500, 4500])
        self.assertTrue(all(c['result']['analyses'][0]['model'] == 'llt' for c in study['result']['cases']))
        self.assertEqual(optimization['optimization']['solver'], 'bemt')
        self.assertEqual(optimization['optimization']['rpm'], 5000)
        self.assertEqual(self.client.get(f"/api/v1/projects/{self.project['id']}").json(), updated_project)
        self.assertEqual(self.client.get(f"/api/v1/simulations/{simulation['id']}").json(), simulation)
        self.assertEqual(self.client.post(f"/api/v1/simulations/{simulation['id']}/study", json={
            'expected_revision': 2, 'study': {'parameter': 'rpm', 'values': [3500, 4500]}}).status_code, 409)
        self.assertEqual(self.client.post(f"/api/v1/simulations/{simulation['id']}/optimize", json={
            'expected_revision': 2, 'solver': 'bemt', 'max_iterations': 10}).status_code, 409)
        archive = library.export_project(self.project['id'])
        response = self.client.post('/api/v1/projects/import', json={
            'content_base64': base64.b64encode(archive).decode()})
        self.assertEqual(response.status_code, 200, response.text)
        imported_simulation = self.client.get(f"/api/v1/projects/{response.json()['id']}/simulations").json()[0]
        imported_runs = [r for r in library.list_records('run') if r.get('project_id') == response.json()['id']]
        self.assertEqual(len(imported_runs), 2)
        self.assertTrue(all(r['simulation_id'] == imported_simulation['id'] for r in imported_runs))

    def edit_payload(self, simulation):
        return {key: simulation[key] for key in ('name', 'inputs', 'workflow', 'polar_asset_id', 'conditions', 'project_id', 'id')} | {'expected_revision': simulation['revision']}

    def test_distinct_models_runs_clone_and_revision_isolation(self):
        bemt, llt = self.save(), self.save('LLT comparison', 'llt')
        self.assertNotEqual(bemt['id'], llt['id'])
        configs = self.client.get(f"/api/v1/projects/{self.project['id']}/simulations").json()
        self.assertEqual(len(configs), 2)
        first, repeated = self.execute_simulation(bemt), self.execute_simulation(bemt)
        llt_run = self.execute_simulation(llt)
        self.assertEqual(llt_run['result']['analyses'][0]['model'], 'llt')
        self.assertEqual(first['simulation_id'], repeated['simulation_id'])
        self.assertNotEqual(first['id'], repeated['id'])
        clone = self.client.post(f"/api/v1/simulations/{bemt['id']}/clone", json={}).json()
        self.assertEqual(clone['name'], 'BEMT baseline Copy')
        changed = self.edit_payload(clone)
        changed['inputs']['rpm'] = 4500
        response = self.client.post('/api/v1/simulations', json=changed)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['revision'], 2)
        self.assertEqual(self.client.get(f"/api/v1/simulations/{bemt['id']}").json(), bemt)
        self.assertEqual(self.client.get(f"/api/v1/runs/{first['id']}").json(), first)
        self.assertEqual(self.client.get(f"/api/v1/projects/{self.project['id']}").json(), self.project)
        self.assertEqual(self.client.post('/api/v1/simulations', json=changed).status_code, 409)
        self.assertEqual(self.client.post(f"/api/v1/simulations/{clone['id']}/run", json={'expected_revision': 1}).status_code, 409)
        other_project = self.client.post('/api/v1/projects', json={**self.payload, 'name': 'Other project'}).json()
        self.assertEqual(self.client.post('/api/v1/simulations', json={**changed, 'project_id': other_project['id'], 'expected_revision': 2}).status_code, 422)
        invalid = self.edit_payload(bemt)
        invalid['workflow'] = copy.deepcopy(invalid['workflow'])
        invalid['workflow']['edges'][0]['source'] = 'sizing'
        self.assertEqual(self.client.post('/api/v1/simulations', json=invalid).status_code, 422)

    def archive_request(self, records):
        data = json.dumps(records).encode()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as stream:
            stream.writestr('manifest.json', json.dumps({'schema_version': 1, 'sha256': hashlib.sha256(data).hexdigest()}))
            stream.writestr('project.json', data)
        return {'content_base64': base64.b64encode(archive.getvalue()).decode()}

    def test_archive_preserves_simulations_historical_revisions_and_assets(self):
        simulation = self.save()
        historical = self.execute_simulation(simulation)
        asset = self.client.post('/api/v1/assets/demonstration-polar', json={'airfoil': 'NACA 4412'}).json()
        edited = self.edit_payload(simulation)
        edited.update(polar_asset_id=asset['id'], name='Updated BEMT')
        edited['inputs']['rpm'] = 4500
        updated = self.client.post('/api/v1/simulations', json=edited).json()
        current = self.execute_simulation(updated)
        # Project adopts the new asset; the old asset is now referenced only by run/config history.
        project_edit = {**self.payload, 'id': self.project['id'], 'expected_revision': 1, 'polar_asset_id': asset['id']}
        self.assertEqual(self.client.post('/api/v1/projects', json=project_edit).status_code, 200)
        content = self.client.get(f"/api/v1/projects/{self.project['id']}/archive").content
        records = library.read_archive(content)
        self.assertEqual({a['id'] for a in records['assets']}, {self.asset['id'], asset['id']})
        response = self.client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(content).decode()})
        self.assertEqual(response.status_code, 200, response.text)
        imported = response.json()
        simulations = self.client.get(f"/api/v1/projects/{imported['id']}/simulations").json()
        self.assertEqual(len(simulations), 1)
        self.assertEqual(simulations[0]['revision'], 2)
        self.assertNotEqual(simulations[0]['id'], simulation['id'])
        runs = [r for r in library.list_records('run') if r.get('project_id') == imported['id']]
        self.assertEqual({r['simulation_revision'] for r in runs}, {1, 2})
        self.assertTrue(all(r['simulation_id'] == simulations[0]['id'] for r in runs))
        old = next(r for r in runs if r['simulation_revision'] == 1)
        self.assertEqual(old['simulation_name'], historical['simulation_name'])
        self.assertEqual(old['result'], historical['result'])
        self.assertNotEqual(old['polar_asset_id'], historical['polar_asset_id'])
        self.assertEqual(current['simulation_name'], 'Updated BEMT')
        second = self.client.get(f"/api/v1/projects/{imported['id']}/archive").content
        self.assertEqual(self.client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(second).decode()}).status_code, 200)

    def test_legacy_archive_and_invalid_links_are_atomic(self):
        simulation = self.save()
        self.execute_simulation(simulation)
        records = library.read_archive(library.export_project(self.project['id']))
        for mutation in ('ownership', 'dangling', 'revision', 'duplicate', 'graph'):
            invalid = copy.deepcopy(records)
            if mutation == 'ownership':
                invalid['simulations'][0]['project_id'] = 'other'
            elif mutation == 'dangling':
                invalid['runs'][0]['simulation_id'] = 'absent'
            elif mutation == 'revision':
                invalid['runs'][0]['simulation_revision'] = 99
            elif mutation == 'duplicate':
                invalid['simulations'].append(copy.deepcopy(invalid['simulations'][0]))
            else:
                invalid['simulations'][0]['workflow']['nodes'][3]['config']['model'] = 'missing'
            before = {k: len(library.list_records(k)) for k in ('project', 'simulation', 'asset', 'run')}
            with self.subTest(mutation=mutation):
                response = self.client.post('/api/v1/projects/import', json=self.archive_request(invalid))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(before, {k: len(library.list_records(k)) for k in before})
        legacy = copy.deepcopy(records)
        legacy.pop('simulations')
        legacy.pop('geometries')
        for record in [legacy['project'], *legacy['runs']]:
            for key in ('geometry_id', 'geometry_revision', 'geometry_content_hash', 'geometry_role'):
                record.pop(key, None)
        for run in legacy['runs']:
            for key in ('simulation_id', 'simulation_name', 'simulation_revision'):
                run.pop(key)
        imported = self.client.post('/api/v1/projects/import', json=self.archive_request(legacy))
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(self.client.get(f"/api/v1/projects/{imported.json()['id']}/simulations").json(), [])

    def test_shared_geometry_revision_adoption_history_and_archive(self):
        a, b = self.save(), self.save('LLT variant', 'llt')
        self.assertEqual((a['geometry_id'], a['geometry_revision']), (b['geometry_id'], 1))
        geometries = self.client.get(f"/api/v1/projects/{self.project['id']}/geometries").json()
        self.assertEqual(len(geometries), 1)
        self.assertNotIn('rpm', geometries[0]['definition'])
        self.assertNotIn('thrust_target', geometries[0]['definition'])
        old = self.execute_simulation(a)
        self.assertEqual(old['geometry_role'], 'baseline_input_geometry')
        self.assertEqual(old['geometry_id'], a['geometry_id'])
        self.assertEqual(old['result']['geometry'], geometries[0]['canonical_geometry'])
        draft = self.edit_payload(b)
        draft['inputs']['rpm'] = 5500
        draft['conditions'] = {'air_density_kg_m3': 1.1}
        b = self.client.post('/api/v1/simulations', json=draft).json()
        self.assertEqual(b['geometry_id'], a['geometry_id'])
        inputs = copy.deepcopy(a['inputs'])
        inputs['diameter'] = .27
        response = self.client.post(f"/api/v1/projects/{self.project['id']}/geometries", json={
            'name': 'Larger propeller', 'inputs': inputs, 'geometry_id': a['geometry_id'], 'expected_geometry_revision': 1})
        self.assertEqual(response.status_code, 200, response.text)
        geometry = response.json()
        self.assertEqual(geometry['geometry_revision'], 2)
        self.assertEqual(self.client.get(f"/api/v1/simulations/{a['id']}").json(), a)
        adopted = self.client.post(f"/api/v1/projects/{self.project['id']}/geometries/{a['geometry_id']}/adopt", json={
            'geometry_revision': 2, 'simulations': [{'id': a['id'], 'expected_revision': 1}, {'id': b['id'], 'expected_revision': b['revision']}]})
        self.assertEqual(adopted.status_code, 200, adopted.text)
        a, b = adopted.json()['simulations']
        self.assertEqual(a['geometry_revision'], 2)
        self.assertEqual(b['inputs']['rpm'], 5500)
        self.assertEqual(b['conditions'], {'air_density_kg_m3': 1.1})
        self.assertEqual(b['workflow']['nodes'][3]['config']['model'], 'llt')
        current = self.execute_simulation(b)
        self.assertEqual(current['result']['geometry'], geometry['canonical_geometry'])
        self.assertEqual(self.client.get(f"/api/v1/runs/{old['id']}").json(), old)
        self.assertEqual(old['geometry_revision'], 1)
        before = {k: library.list_records(k) for k in ('geometry', 'simulation')}
        inputs['diameter'] = .28
        conflict = self.client.post(f"/api/v1/projects/{self.project['id']}/geometries", json={
            'name': 'Atomic publish', 'inputs': inputs, 'geometry_id': a['geometry_id'], 'expected_geometry_revision': 2,
            'simulations': [{'id': a['id'], 'expected_revision': a['revision']}, {'id': b['id'], 'expected_revision': 99}]})
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(before, {k: library.list_records(k) for k in before})
        with self.assertRaises(ValueError):
            library.save('geometry', geometry, geometry['id'])
        archive = library.export_project(self.project['id'])
        imported = self.client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(archive).decode()})
        self.assertEqual(imported.status_code, 200, imported.text)
        new_project = imported.json()
        imported_geometries = self.client.get(f"/api/v1/projects/{new_project['id']}/geometries").json()
        self.assertEqual({g['geometry_revision'] for g in imported_geometries}, {1, 2})
        family = imported_geometries[0]['geometry_id']
        self.assertNotEqual(family, a['geometry_id'])
        runs = [r for r in library.list_records('run') if r.get('project_id') == new_project['id']]
        self.assertTrue(all(r['geometry_id'] == family for r in runs))
        self.assertEqual({r['geometry_revision'] for r in runs}, {1, 2})
        repeated = library.export_project(new_project['id'])
        self.assertEqual(self.client.post('/api/v1/projects/import', json={
            'content_base64': base64.b64encode(repeated).decode()}).status_code, 200)

    def test_geometry_ownership_conflicts_and_invalid_archive_are_atomic(self):
        simulation = self.save()
        other = self.client.post('/api/v1/projects', json={**self.payload, 'name': 'Other'}).json()
        invalid = self.edit_payload(simulation)
        invalid.update(geometry_id=other['geometry_id'], geometry_revision=other['geometry_revision'])
        self.assertEqual(self.client.post('/api/v1/simulations', json=invalid).status_code, 422)
        self.assertEqual(self.client.post(f"/api/v1/projects/{other['id']}/geometries/{simulation['geometry_id']}/adopt", json={
            'geometry_revision': 1, 'simulations': [{'id': simulation['id'], 'expected_revision': 1}]}).status_code, 422)
        self.assertEqual(self.client.post(f"/api/v1/projects/{self.project['id']}/geometries", json={
            'name': 'Stale', 'inputs': simulation['inputs'], 'geometry_id': simulation['geometry_id'],
            'expected_geometry_revision': 0}).status_code, 409)
        records = library.read_archive(library.export_project(self.project['id']))
        before = {k: len(library.list_records(k)) for k in ('project', 'geometry', 'simulation', 'asset', 'run')}
        for mutation in ('owner', 'canonical', 'reference', 'duplicate', 'namespace'):
            invalid = copy.deepcopy(records)
            if mutation == 'owner':
                invalid['geometries'][0]['project_id'] = other['id']
            elif mutation == 'canonical':
                invalid['geometries'][0]['canonical_geometry']['stations'][0]['chord_m'] += .001
            elif mutation == 'reference':
                invalid['simulations'][0]['geometry_revision'] = 99
            elif mutation == 'duplicate':
                item = copy.deepcopy(invalid['geometries'][0])
                item['id'] = 'different-record-id'
                invalid['geometries'].append(item)
            else:
                invalid['geometries'][0]['geometry_id'] = invalid['project']['id']
            with self.subTest(mutation=mutation):
                response = self.client.post('/api/v1/projects/import', json=self.archive_request(invalid))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(before, {k: len(library.list_records(k)) for k in before})

    def test_loft_geometry_snapshots_and_archive_remap_source_assets(self):
        from airfoil_management.example import _write_fake_dat
        assignments = []
        for name, fraction, thickness in [('root_profile', 0, .12), ('tip_profile', 1, .08)]:
            path = Path(self.directory.name) / (name + '.dat')
            _write_fake_dat(path, thickness)
            response = self.client.post('/api/airfoils/import-dat', json={'name': name, 'content': path.read_text()})
            self.assertEqual(response.status_code, 200, response.text)
            assignments.append({'airfoil': name, 'radial_fraction': fraction})
        payload = copy.deepcopy(self.payload)
        payload.update(project_id=self.project['id'], name='Loft geometry')
        payload['inputs']['airfoil_assignments'] = assignments
        response = self.client.post('/api/v1/simulations', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        simulation = response.json()
        geometry = library.get_geometry(self.project['id'], simulation['geometry_id'], simulation['geometry_revision'])
        original_ids = {a['asset_id'] for a in geometry['definition']['airfoil_assignments']}
        self.assertEqual(len(original_ids), 2)
        self.assertIn('airfoil_coordinates', geometry['canonical_geometry']['stations'][0])
        # Re-import a different mutable library profile; the revision remains frozen.
        path = Path(self.directory.name) / 'root_profile.dat'
        _write_fake_dat(path, .16)
        self.client.post('/api/airfoils/import-dat', json={'name': 'root_profile', 'content': path.read_text()})
        self.assertEqual(library.get_geometry(self.project['id'], simulation['geometry_id'], simulation['geometry_revision']), geometry)
        archive = library.export_project(self.project['id'])
        response = self.client.post('/api/v1/projects/import', json={'content_base64': base64.b64encode(archive).decode()})
        self.assertEqual(response.status_code, 200, response.text)
        imported = self.client.get(f"/api/v1/projects/{response.json()['id']}/simulations").json()[0]
        restored = library.get_geometry(response.json()['id'], imported['geometry_id'], imported['geometry_revision'])
        remapped_ids = {a['asset_id'] for a in restored['definition']['airfoil_assignments']}
        self.assertFalse(original_ids & remapped_ids)
        self.assertEqual(remapped_ids, {a['asset_id'] for a in restored['canonical_geometry']['airfoil_loft']})
        self.assertEqual(restored['canonical_geometry']['stations'], geometry['canonical_geometry']['stations'])
        self.assertEqual(restored['content_hash'], geometry['content_hash'])
        repeated = library.export_project(response.json()['id'])
        self.assertEqual(self.client.post('/api/v1/projects/import', json={
            'content_base64': base64.b64encode(repeated).decode()}).status_code, 200)

    def test_derived_sizing_and_diameter_study_use_baseline_provenance(self):
        payload = copy.deepcopy(self.payload)
        payload.update(project_id=self.project['id'], name='Automatic sizing')
        payload['workflow']['nodes'][1]['config'] = {'mode': 'actuator_disk', 'disk_loading': 220}
        payload['workflow']['nodes'][3]['config']['model'] = 'llt'
        response = self.client.post('/api/v1/simulations', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        automatic = response.json()
        record = self.execute_simulation(automatic)
        self.assertEqual(record['geometry_role'], 'baseline_input_geometry')
        self.assertNotEqual(record['result']['geometry']['diameter_m'], automatic['inputs']['diameter'])
        self.assertLessEqual(record['result']['geometry']['stations'][-1]['radius_m'], record['result']['geometry']['diameter_m'] / 2)
        manual = self.save('Diameter study', 'llt')
        response = self.client.post(f"/api/v1/simulations/{manual['id']}/study", json={
            'study': {'parameter': 'diameter', 'values': [.2, .3]}})
        self.assertEqual(response.status_code, 200, response.text)
        study = self.wait_run(response.json())
        self.assertEqual(study['geometry_id'], manual['geometry_id'])
        self.assertEqual(study['geometry_role'], 'baseline_input_geometry')
        self.assertEqual([c['result']['geometry']['diameter_m'] for c in study['result']['cases']], [.2, .3])
        archive = library.export_project(self.project['id'])
        self.assertEqual(self.client.post('/api/v1/projects/import', json={
            'content_base64': base64.b64encode(archive).decode()}).status_code, 200)

    def test_arbitrary_diameter_serialized_stations_stay_inside_rotor(self):
        from inverse_design import GeometryData
        from nova.application.geometry import create_propeller_geometry
        for diameter in (.10758293817, .2718281828459, .314159265):
            inputs = {**self.payload['inputs'], 'diameter': diameter}
            geometry = create_propeller_geometry(inputs)
            with self.subTest(diameter=diameter):
                self.assertLessEqual(geometry['stations'][-1]['radius_m'], diameter / 2)
                self.assertEqual(GeometryData.from_dict(geometry).diameter_m, diameter)


if __name__ == '__main__':
    unittest.main()
