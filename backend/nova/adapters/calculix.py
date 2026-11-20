"""CalculiX (ccx) adapter: runs a self-contained .inp deck written by Nova and reads the eigenvalue table.

CalculiX is GPL-2.0 software installed independently by the user; Nova only writes the input deck and
reads the text output, it does not link to or bundle the solver.
"""
import re
import shutil
import tempfile
from pathlib import Path

from nova.adapters.base import (
    AdapterDescriptor,
    AdapterError,
    ExternalAdapter,
    PreparedCase,
    safe_artifact,
)
from nova.adapters.process import ProcessFailure, ProcessSpec, run_process
from nova.core.data import Port

THREADS = '2'  # the solver stays on two cores


def _case(case):
    root = Path(case.get('case_directory', ''))
    name = case.get('input_file', '')
    if not root.is_absolute() or not root.is_dir():
        raise AdapterError('CalculiX case directory must be an existing absolute path')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.inp', name or '') or not (root / name).is_file():
        raise AdapterError('CalculiX input must be a .inp file inside the case directory')
    return root, name


class CalculiXAdapter(ExternalAdapter):
    def describe(self):
        return AdapterDescriptor('calculix', 'CalculiX', '1.0', 'Runs a Nova-written CalculiX deck (shell blade modes); reads the .dat eigenvalues.',
                                 'GPL-2.0 (external solver, installed independently)', ('local_executable',),
                                 {'case': Port('calculix_case', 'native', shape='record')},
                                 {'result': Port('eigenvalues', 'native', shape='record')})

    def probe(self, configuration):
        try:
            with tempfile.TemporaryDirectory(prefix='nova-ccx-probe-') as temporary:
                result = run_process(ProcessSpec(configuration.executable, ('-v',), 10.0, {'OMP_NUM_THREADS': THREADS}), Path(temporary))
            match = re.search(r'Version\s+(\d+\.\d+)', result.log)
            return {'available': True, 'compatible': match is not None, 'version': match[1] if match else None,
                    'message': result.log[-4000:], 'version_flag': '-v'}
        except (OSError, ValueError, ProcessFailure) as exc:
            return {'available': False, 'compatible': False, 'version': None, 'message': str(exc)}

    def validate(self, case, configuration):
        if configuration.environment_kind != 'local_executable' or configuration.options:
            raise AdapterError('CalculiX accepts a local executable without adapter options')
        _case(case)

    def prepare(self, case, configuration, directory):
        root, name = _case(case)
        target = directory / 'case'
        target.mkdir()
        shutil.copy2(root / name, target / name)
        job = str(Path('case') / name[:-4])
        return PreparedCase((ProcessSpec(configuration.executable, ('-i', job), case.get('timeout_seconds', 600.0),
                                         {'OMP_NUM_THREADS': THREADS, 'CCX_NPROC_EQUATION_SOLVER': THREADS}),),
                            (str(Path('case') / name),), (job + '.dat',))

    def collect(self, directory, prepared):
        from nova.physics.blade_shell import ShellError, frequencies
        text = safe_artifact(directory, prepared.expected_outputs[0]).read_text(errors='replace')
        try:
            return {'modes': frequencies(text)}
        except ShellError as exc:
            raise AdapterError(str(exc)) from exc

    def normalize(self, output):
        return output
