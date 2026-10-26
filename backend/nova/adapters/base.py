"""Explicit adapter contracts; external software is installed by the user."""
import copy
import hashlib
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nova.adapters.process import ProcessSpec, run_process
from nova.core.data import Port, canonical_json, content_hash


@dataclass(frozen=True)
class AdapterDescriptor:
    id: str
    name: str
    version: str
    description: str
    license: str
    environments: tuple[str, ...]
    inputs: dict[str, Port]
    outputs: dict[str, Port]


@dataclass(frozen=True)
class AdapterConfiguration:
    executable: Path
    environment_kind: str = 'local_executable'
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedCase:
    stages: tuple[ProcessSpec, ...]
    input_files: tuple[str, ...]
    expected_outputs: tuple[str, ...]


class AdapterError(RuntimeError):
    pass


class ExternalAdapter(ABC):
    @abstractmethod
    def describe(self) -> AdapterDescriptor: ...

    @abstractmethod
    def probe(self, configuration: AdapterConfiguration) -> dict: ...

    @abstractmethod
    def validate(self, case: dict, configuration: AdapterConfiguration) -> None: ...

    @abstractmethod
    def prepare(self, case: dict, configuration: AdapterConfiguration, directory: Path) -> PreparedCase: ...

    @abstractmethod
    def collect(self, directory: Path, prepared: PreparedCase) -> dict: ...

    @abstractmethod
    def normalize(self, output: dict) -> dict: ...


def safe_artifact(directory, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise AdapterError('Adapter artifacts must use relative paths')
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise AdapterError(f'Missing or escaping adapter artifact: {relative}')
    return path


def execute_adapter(adapter, configuration, case, root, *, cancelled=None, on_log=None):
    """Keep raw inputs, outputs and execution manifest in an isolated case folder."""
    case = copy.deepcopy(case)
    configuration = AdapterConfiguration(configuration.executable, configuration.environment_kind,
                                         copy.deepcopy(configuration.options))
    descriptor = adapter.describe()
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', descriptor.id):
        raise AdapterError('Invalid adapter ID')
    if configuration.environment_kind not in descriptor.environments:
        raise AdapterError('Adapter does not support this execution environment')
    canonical_json(configuration.options)
    canonical_json(case)
    adapter.validate(case, configuration)
    if cancelled and cancelled():
        raise InterruptedError('Adapter cancelled')
    probe = adapter.probe(configuration)
    if not probe.get('available') or not probe.get('compatible'):
        raise AdapterError(probe.get('message', 'External program is unavailable or incompatible'))
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=descriptor.id + '-', dir=root))
    (directory / 'case.json').write_text(canonical_json(case))
    manifest = {'adapter': asdict(descriptor), 'program': probe, 'input_hash': content_hash(case),
                'configuration': {'executable': str(Path(configuration.executable).expanduser().absolute()),
                                  'environment_kind': configuration.environment_kind, 'options': configuration.options},
                'state': 'preparing', 'stages': []}
    (directory / 'execution.json').write_text(canonical_json(manifest))
    stage = None
    try:
        prepared = adapter.prepare(case, configuration, directory)
        input_hashes = {}
        for file in prepared.input_files:
            with safe_artifact(directory, file).open('rb') as stream:
                input_hashes[file] = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest['input_files'] = input_hashes
        if not 1 <= len(prepared.stages) <= 8:
            raise AdapterError('Adapters require 1–8 execution stages')
        processes = []
        for index, spec in enumerate(prepared.stages):
            stage = index + 1
            manifest.update(state='running', active_stage=stage)
            (directory / 'execution.json').write_text(canonical_json(manifest))
            if on_log:
                on_log(f'Stage {stage}/{len(prepared.stages)}: {spec.executable.name}\n')
            if cancelled and cancelled():
                raise InterruptedError('Adapter cancelled')
            process = run_process(spec, directory, cancelled=cancelled, on_log=on_log)
            processes.append(process)
            manifest['stages'].append({'command': process.command, 'returncode': process.returncode,
                                       'elapsed_seconds': process.elapsed_seconds, 'log_truncated': process.log_truncated})
            with (directory / 'process.log').open('a') as log:
                log.write(f'Stage {index + 1}\n{process.log}\n')
        for file in prepared.expected_outputs:
            safe_artifact(directory, file)
        output = adapter.normalize(adapter.collect(directory, prepared))
        canonical_json(output)
        output_hashes = {}
        for file in prepared.expected_outputs:
            with safe_artifact(directory, file).open('rb') as stream:
                output_hashes[file] = hashlib.file_digest(stream, 'sha256').hexdigest()
        provenance = {**manifest, 'state': 'succeeded', 'output_files': output_hashes,
                      'returncode': 0, 'elapsed_seconds': sum(p.elapsed_seconds for p in processes),
                      'log_truncated': any(p.log_truncated for p in processes)}
        (directory / 'result.json').write_text(canonical_json(output))
        (directory / 'execution.json').write_text(canonical_json(provenance))
        return {'data': output, 'provenance': provenance, 'working_directory': str(directory),
                'artifacts': [*prepared.input_files, *prepared.expected_outputs, 'case.json', 'result.json', 'execution.json', 'process.log']}
    except Exception as exc:
        manifest.update(state='cancelled' if isinstance(exc, InterruptedError) or getattr(exc, 'cancelled', False) else 'failed', error=str(exc), active_stage=stage)
        if getattr(exc, 'result', None):
            manifest['failed_process'] = asdict(exc.result)
        (directory / 'execution.json').write_text(canonical_json(manifest))
        (directory / 'failure.json').write_text(canonical_json({'error': str(exc), 'input_hash': content_hash(case)}))
        if getattr(exc, 'result', None):
            with (directory / 'process.log').open('a') as log:
                log.write(exc.result.log)
        exc.working_directory = str(directory)
        raise
