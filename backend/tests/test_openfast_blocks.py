"""OpenFAST blocks in block workflows, run with a fixture program instead of OpenFAST."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
from main import app
from nova.blocks import engine, templates

OUTPUT = b"fixture\nTime GenPwr RotSpeed\n(s) (kW) (rpm)\n0 0 10\n1 100 20\n2 200 30\n3 300 40\n"


class OpenFASTBlockTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.db = patch.object(database, 'DB_PATH', self.root / 'library.sqlite')
        self.db.start()
        self.client = TestClient(app)
        self.client.__enter__()
        case = self.root / 'case'
        case.mkdir()
        (case / 'main.fst').write_text('input')
        self.case = {'case_directory': str(case), 'input_file': 'main.fst', 'output_file': 'main.out', 'timeout_seconds': 5}
        program = self.root / 'solver'
        program.write_text("#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n"
                           "if sys.argv[1:] == ['-v']:\n print('OpenFAST-v4.1.1')\n raise SystemExit(0)\n"
                           f"Path('case/main.out').write_bytes({OUTPUT!r})\n")
        program.chmod(0o755)
        self.program = program

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db.stop()
        self.directory.cleanup()

    def workflow(self, **run):
        config = {'start_time_s': 1.0, 'statistics': [{'channel': 'GenPwr', 'stat': 'mean', 'name': 'power_kw', 'unit': 'kW'},
                                                      {'channel': 'RotSpeed', 'stat': 'max', 'name': 'speed_max', 'unit': 'rpm'}], **run}
        nodes = [{'id': 'case', 'type': 'openfast_case', 'config': self.case},
                 {'id': 'run', 'type': 'openfast_run', 'config': config},
                 {'id': 'limits', 'type': 'constraint', 'config': {'checks': [
                     {'quantity': 'speed_max', 'operator': '<=', 'value': 35, 'severity': 'hard', 'label': 'Speed', 'unit': 'rpm'}]}}]
        edges = [{'source': 'case', 'source_port': 'case', 'target': 'run', 'target_port': 'case'},
                 {'source': 'run', 'source_port': 'values', 'target': 'limits', 'target_port': 'values'}]
        return {'schema_version': 2, 'kind': 'blocks', 'name': 't', 'nodes': nodes, 'edges': edges}

    def configure(self):
        response = self.client.post('/api/v1/adapters/openfast/configure', json={'executable': str(self.program), 'environment_kind': 'local_executable'})
        self.assertEqual(response.status_code, 200, response.text)

    def test_statistics_feed_constraints(self):
        self.configure()
        result = engine.execute(self.workflow())
        self.assertEqual(result['blocks']['run']['status'], 'succeeded', result['blocks']['run'])
        values = result['blocks']['run']['outputs']['values']
        self.assertAlmostEqual(values['power_kw'], 200.0)
        self.assertEqual(values['speed_max'], 40.0)
        table = result['blocks']['run']['outputs']['table']
        self.assertEqual(table['samples'], 3)
        self.assertEqual({r['channel'] for r in table['rows']}, {'GenPwr', 'RotSpeed'})
        self.assertFalse(result['feasible'])

    def test_missing_integration_and_bad_inputs(self):
        result = engine.execute(self.workflow())
        self.assertEqual(result['blocks']['run']['status'], 'failed')
        self.assertIn('Settings', result['blocks']['run']['error'])
        self.configure()
        self.assertIn('after the last', engine.execute(self.workflow(start_time_s=99))['blocks']['run']['error'])
        bad = self.workflow(statistics=[{'channel': 'Nope', 'stat': 'mean', 'name': 'x'}])
        self.assertIn('not in the OpenFAST output', engine.execute(bad)['blocks']['run']['error'])
        bad = self.workflow(statistics=[{'channel': 'GenPwr', 'stat': 'median', 'name': 'x'}])
        self.assertEqual(engine.execute(bad)['blocks']['run']['status'], 'failed')
        self.case['case_directory'] = str(self.root / 'missing')
        self.assertEqual(engine.execute(self.workflow())['blocks']['case']['status'], 'failed')

    def test_template_is_valid(self):
        self.assertTrue(engine.validate(templates.template('openfast_limits'))['valid'])


if __name__ == '__main__':
    unittest.main()
