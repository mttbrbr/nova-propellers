"""DUST adapter: runs dust_pre, dust and dust_post on a Nova-written case and returns the integral loads.

DUST (MIT licence) is installed independently by the user; the configured executable is the ``dust``
solver and ``dust_pre`` / ``dust_post`` are expected next to it.
"""
import re
import shutil
from pathlib import Path

from nova.adapters.base import (
    AdapterDescriptor,
    AdapterError,
    ExternalAdapter,
    PreparedCase,
    safe_artifact,
)
from nova.core.data import Port

STAGES = ('dust_pre', 'dust', 'dust_post')
NAME = re.compile(r'^[A-Za-z0-9_.-]+$')


def _case(case):
    root = Path(case.get('case_directory', ''))
    if not root.is_absolute() or not root.is_dir():
        raise AdapterError('DUST case directory must be an existing absolute path')
    files = sorted(p for p in root.iterdir() if p.is_file())
    names = {p.name for p in files}
    if not {'dust_pre.in', 'dust.in', 'dust_post.in'} <= names or any(not NAME.match(n) for n in names):
        raise AdapterError('A DUST case needs dust_pre.in, dust.in and dust_post.in (plain file names)')
    output = case.get('loads_file', '')
    if not re.fullmatch(r'Postpro/[A-Za-z0-9_.-]+\.dat', output):
        raise AdapterError('loads_file must be a .dat file in Postpro/')
    return root, files


def _executables(configuration):
    solver = Path(configuration.executable)
    return {name: solver.with_name(name) for name in STAGES}


class DustAdapter(ExternalAdapter):
    def describe(self):
        return AdapterDescriptor('dust', 'DUST', '1.0', 'Runs a Nova-written DUST vortex-particle rotor case (pre, solver, post); reads the '
                                 'integral loads.', 'MIT (external solver, installed independently)', ('local_executable',),
                                 {'case': Port('dust_case', 'native', shape='record')},
                                 {'result': Port('integral_loads', 'native', shape='record', time_domain='time_series')})

    def probe(self, configuration):
        paths = _executables(configuration)
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing:
            return {'available': False, 'compatible': False, 'version': None,
                    'message': f'Missing next to the solver: {", ".join(missing)}'}
        return {'available': True, 'compatible': True, 'version': None,
                'message': 'dust, dust_pre and dust_post found; the version is not reported by the executables'}

    def validate(self, case, configuration):
        if configuration.environment_kind != 'local_executable' or configuration.options:
            raise AdapterError('DUST accepts a local executable without adapter options')
        _case(case)

    def prepare(self, case, configuration, directory):
        from nova.adapters.process import ProcessSpec
        root, files = _case(case)
        for path in files:
            shutil.copy2(path, directory / path.name)
        (directory / 'Output').mkdir(exist_ok=True)
        (directory / 'Postpro').mkdir(exist_ok=True)
        paths = _executables(configuration)
        timeout = case.get('timeout_seconds', 3600.0)
        environment = {'OMP_NUM_THREADS': '2'}
        stages = tuple(ProcessSpec(paths[name], (f'{name}.in',), timeout, environment) for name in STAGES)
        return PreparedCase(stages, tuple(p.name for p in files), (case['loads_file'],))

    def collect(self, directory, prepared):
        return {'loads_text': safe_artifact(directory, prepared.expected_outputs[0]).read_text(errors='replace')}

    def normalize(self, output):
        return output
