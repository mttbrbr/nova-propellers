import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app
from nova.blocks import engine, templates
from nova.blocks.constraints import evaluate_check, report
from nova.blocks.expressions import ExpressionError, evaluate, names


def workflow(nodes, edges):
    return {'schema_version': 2, 'kind': 'blocks', 'nodes': nodes, 'edges': edges}


def edge(a, ap, b, bp):
    return {'source': a, 'source_port': ap, 'target': b, 'target_port': bp}


class ExpressionTests(unittest.TestCase):
    def test_arithmetic_functions_and_conditions(self):
        self.assertAlmostEqual(evaluate('sqrt(a**2 + b**2) + pi * 0', {'a': 3, 'b': 4}), 5.0)
        self.assertEqual(evaluate('1 if x > 2 else 0', {'x': 3}), 1.0)
        self.assertEqual(names('power_w / 1000 + max(a, b)'), ['a', 'b', 'power_w'])

    def test_unsafe_constructs_are_rejected(self):
        for text in ('__import__("os")', 'x.real', 'x[0]', '(lambda: 1)()', '"text"', '2 ** 1000'):
            with self.assertRaises(ExpressionError):
                evaluate(text, {'x': 1})
        with self.assertRaises(ExpressionError):
            evaluate('missing + 1', {})


class ConstraintTests(unittest.TestCase):
    def test_margins_and_presets(self):
        check = evaluate_check({'quantity': 'power_w', 'operator': '<=', 'value': 100}, {'power_w': 80})
        self.assertTrue(check['satisfied'])
        self.assertAlmostEqual(check['margin'], 0.2)
        result = report([{'preset': 'keller'}, {'quantity': 'x', 'operator': 'between', 'value': 1, 'upper': 2, 'severity': 'soft'}],
                        {'keller_margin': -0.1, 'x': 3})
        self.assertFalse(result['feasible'])
        self.assertEqual((result['hard_violations'], result['soft_violations']), (1, 1))

    def test_invalid_constraints_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_check({'quantity': 'x', 'operator': '~', 'value': 1}, {'x': 1})
        with self.assertRaises(ValueError):
            evaluate_check({'preset': 'nonexistent'}, {})


class EngineTests(unittest.TestCase):
    def test_every_template_validates_and_runs(self):
        for item in templates.templates():
            result = engine.execute(templates.template(item['id']))
            self.assertEqual(result['status'], 'succeeded', (item['id'], {k: v.get('error') for k, v in result['blocks'].items()}))

    def test_structural_errors(self):
        rotor = {'id': 'r', 'type': 'rotor_hawt', 'config': {}}
        solver = {'id': 's', 'type': 'solver', 'config': {}}
        with self.assertRaisesRegex(ValueError, 'Unconnected required input'):
            engine.validate(workflow([rotor, solver], []))
        with self.assertRaisesRegex(ValueError, 'cannot feed'):
            engine.validate(workflow([rotor, {'id': 'c', 'type': 'constraint', 'config': {}}], [edge('r', 'spec', 'c', 'values')]))
        a = {'id': 'a', 'type': 'expression', 'config': {}}
        b = {'id': 'b', 'type': 'expression', 'config': {}}
        with self.assertRaisesRegex(ValueError, 'cycle'):
            engine.validate(workflow([a, b], [edge('a', 'values', 'b', 'values'), edge('b', 'values', 'a', 'values')]))
        with self.assertRaisesRegex(ValueError, 'unsupported settings'):
            engine.validate(workflow([{'id': 'p', 'type': 'parameter', 'config': {'evil': 1}}], []))

    def test_parameter_limits_fail_and_block_downstream(self):
        graph = workflow([
            {'id': 'p', 'type': 'parameter', 'config': {'name': 'radius', 'value': 80, 'min': 1, 'max': 60}},
            {'id': 'r', 'type': 'rotor_hawt', 'config': {'bindings': {'geometry.radius_m': 'radius'}}},
        ], [edge('p', 'value', 'r', 'parameters')])
        result = engine.execute(graph)
        self.assertEqual(result['blocks']['p']['status'], 'failed')
        self.assertIn('above its maximum', result['blocks']['p']['error'])
        self.assertEqual(result['blocks']['r']['status'], 'blocked')

    def test_bindings_drive_the_specification(self):
        graph = workflow([
            {'id': 'p', 'type': 'parameter', 'config': {'name': 'D', 'value': 12}},
            {'id': 'r', 'type': 'rotor_hawt', 'config': {'bindings': {'geometry.radius_m': 'D / 2', 'geometry.hub_radius_m': 'D / 20'}}},
            {'id': 'o', 'type': 'operating_point', 'config': {'operating': {'velocity_m_s': 9, 'tip_speed_ratio': 7}}},
            {'id': 's', 'type': 'solver', 'config': {}},
        ], [edge('p', 'value', 'r', 'parameters'), edge('r', 'spec', 'o', 'spec'), edge('o', 'spec', 's', 'spec')])
        result = engine.execute(graph)
        self.assertEqual(result['status'], 'succeeded')
        self.assertAlmostEqual(result['blocks']['s']['outputs']['result']['blade']['tip_radius_m'], 6.0)

    def test_stop_on_violation_blocks_downstream(self):
        graph = templates.template('hawt_rated_design')
        checks = next(n for n in graph['nodes'] if n['id'] == 'checks')
        checks['config'] = {'checks': [{'preset': 'rated_power', 'value': 100}], 'on_violation': 'stop'}
        result = engine.execute(graph)
        self.assertEqual(result['blocks']['checks']['status'], 'violated')
        self.assertEqual(result['blocks']['report']['status'], 'blocked')
        self.assertFalse(result['feasible'])
        self.assertEqual(result['status'], 'stopped')

    def test_wrong_corrections_for_rotor_family_fail(self):
        graph = workflow([{'id': 'r', 'type': 'rotor_vawt', 'config': {}},
                          {'id': 'c', 'type': 'corrections_axial', 'config': {}}], [edge('r', 'spec', 'c', 'spec')])
        result = engine.execute(graph)
        self.assertEqual(result['blocks']['c']['status'], 'failed')

    def test_optimizer_respects_hard_constraint(self):
        graph = templates.template('hawt_constrained_optimization')
        optimizer = next(n for n in graph['nodes'] if n['id'] == 'optimizer')
        for method in ('cobyla', 'nelder_mead', 'grid'):
            node = copy.deepcopy(optimizer)
            node['config']['method'] = method
            node['config']['max_evaluations'] = 40
            graph['nodes'] = [n if n['id'] != 'optimizer' else node for n in graph['nodes']]
            result = engine.execute(graph)
            values = result['blocks']['optimizer']['outputs']['values']
            self.assertLessEqual(values['thrust_n'], 2500 * 1.001, method)
            self.assertLessEqual(values['evaluations'], 40)
            self.assertGreater(values['CP'], 0.3, method)

    def test_sweep_filter_select(self):
        result = engine.execute(templates.template('propeller_sweep'))
        rows = result['blocks']['sweep']['outputs']['table']['rows']
        feasible = result['blocks']['feasible']['outputs']['table']['rows']
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(r['thrust_n'] >= 5 and r['max_section_mach'] <= 0.6 for r in feasible))
        best = result['blocks']['best']['outputs']['values']
        self.assertEqual(best['efficiency'], max(r['efficiency'] for r in feasible))


class BlockApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = patch.object(database, 'DB_PATH', Path(self.directory.name) / 'library.sqlite')
        self.db.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db.stop()
        self.directory.cleanup()

    def test_rotor_and_block_endpoints(self):
        catalog = self.client.get('/api/v1/rotors/catalog').json()
        self.assertEqual(set(catalog['kinds']), {'hawt', 'vawt', 'propeller', 'marine'})
        analysis = self.client.post('/api/v1/rotors/analyze', json={'spec': {'kind': 'vawt'}})
        self.assertEqual(analysis.status_code, 200, analysis.text)
        self.assertIn('azimuth', analysis.json())
        curve = self.client.post('/api/v1/rotors/curve', json={'spec': {'kind': 'hawt'}, 'points': 5}).json()
        self.assertEqual(len(curve['rows']), 5)
        bad = self.client.post('/api/v1/rotors/analyze', json={'spec': {'kind': 'helicopter'}})
        self.assertEqual(bad.status_code, 422)

        blocks = self.client.get('/api/v1/blocks/catalog').json()
        families = {b['family'] for b in blocks['blocks']}
        self.assertEqual(families, {'general', 'specific'})
        graph = self.client.get('/api/v1/blocks/templates/vawt_dmst_study').json()
        self.assertTrue(self.client.post('/api/v1/blocks/validate', json={'workflow': graph}).json()['valid'])
        saved = self.client.post('/api/v1/blocks/workflows', json={'name': 'Mine', 'workflow': graph}).json()
        self.assertEqual(saved['revision'], 1)
        listed = self.client.get('/api/v1/blocks/workflows').json()
        self.assertEqual([r['id'] for r in listed], [saved['id']])
        self.assertEqual(self.client.get(f'/api/v1/blocks/workflows/{saved["id"]}').json()['name'], 'Mine')
        invalid = self.client.post('/api/v1/blocks/workflows', json={'name': 'Bad', 'workflow': {'schema_version': 2, 'kind': 'blocks', 'nodes': []}})
        self.assertEqual(invalid.status_code, 422)
        run = self.client.post('/api/v1/blocks/run', json={'workflow': self.client.get('/api/v1/blocks/templates/marine_cavitation').json()}).json()
        self.assertEqual(run['status'], 'succeeded')


if __name__ == '__main__':
    unittest.main()
