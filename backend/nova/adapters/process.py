"""Bounded, shell-free execution of independently installed programs."""
import codecs
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from nova.infrastructure.proc import group_kwargs, stop_group


class ProcessFailure(RuntimeError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


class ProcessCancelled(InterruptedError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class ProcessSpec:
    executable: Path
    arguments: tuple[str, ...] = ()
    timeout_seconds: float = 60.
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int
    elapsed_seconds: float
    log: str
    log_truncated: bool


def external_environment(overrides=None):
    """Restore host libraries; never pass the private desktop API token."""
    environment = dict(os.environ)
    original = environment.pop('LD_LIBRARY_PATH_ORIG', None)
    if original is not None:
        environment['LD_LIBRARY_PATH'] = original
    elif getattr(sys, 'frozen', False) or '_PYI_APPLICATION_HOME_DIR' in environment:
        environment.pop('LD_LIBRARY_PATH', None)
    for key in list(environment):
        if key.startswith('_PYI') or key in ('NOVA_SESSION_TOKEN', 'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
            environment.pop(key, None)
    overrides = overrides or {}
    if any(not isinstance(k, str) or not isinstance(v, str) or '\0' in k + v or '=' in k
           or k == 'NOVA_SESSION_TOKEN' or k.startswith('_PYI') for k, v in overrides.items()):
        raise ValueError('Invalid external process environment')
    environment.update(overrides)
    return environment


def run_process(spec: ProcessSpec, working_directory: Path, *, cancelled: Callable | None = None,
                on_log: Callable | None = None, max_log_characters=256_000):
    # Preserve the selected symlink path: resolving a venv interpreter to its
    # base Python would silently discard the user's scientific environment.
    executable = Path(os.path.abspath(Path(spec.executable).expanduser()))
    executable.resolve(strict=True)
    directory = Path(working_directory).resolve(strict=True)
    if not executable.is_file() or not os.access(executable, os.X_OK) or not directory.is_dir():
        raise ValueError('Select an executable file and existing working directory')
    if not 0 < spec.timeout_seconds <= 3600 or type(max_log_characters) is not int or not 1 <= max_log_characters <= 1_000_000:
        raise ValueError('Invalid process timeout or log limit')
    if any(not isinstance(arg, str) or '\0' in arg for arg in spec.arguments):
        raise ValueError('Arguments must be separate strings')
    if cancelled and cancelled():
        raise ProcessCancelled('External process cancelled before start')
    command = (str(executable), *spec.arguments)
    start = time.monotonic()
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    log, truncated = '', False
    def append(chunk):
        nonlocal log, truncated
        log += chunk
        if len(log) > max_log_characters:
            log = log[-max_log_characters:]
            truncated = True
        if on_log and chunk:
            on_log(chunk)
    def result(code):
        return ProcessResult(command, code, time.monotonic() - start, log, truncated)
    process = subprocess.Popen(command, cwd=directory, env=external_environment(spec.environment),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, **group_kwargs())
    chunks = queue.Queue()
    def pump():
        # A reader thread keeps pipe reading portable (select() on pipes is POSIX-only).
        descriptor = process.stdout.fileno()
        while True:
            try:
                data = os.read(descriptor, 4096)
            except OSError:
                data = b''
            chunks.put(data)
            if not data:
                return
    reader = None
    try:
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        eof = False
        while not eof:
            if cancelled and cancelled():
                raise ProcessCancelled('External process cancelled', result(process.poll() if process.poll() is not None else -1))
            if time.monotonic() - start >= spec.timeout_seconds:
                raise ProcessFailure('External process exceeded its timeout', result(process.poll() if process.poll() is not None else -1))
            try:
                data = chunks.get(timeout=.05)
            except queue.Empty:
                continue
            if data:
                append(decoder.decode(data))
            else:
                eof = True
                append(decoder.decode(b'', final=True))
        while process.poll() is None:
            if cancelled and cancelled():
                raise ProcessCancelled('External process cancelled', result(process.poll() if process.poll() is not None else -1))
            if time.monotonic() - start >= spec.timeout_seconds:
                raise ProcessFailure('External process exceeded its timeout', result(-1))
            time.sleep(.05)
        code = process.returncode
        completed = result(code)
        if code != 0:
            raise ProcessFailure(f'External process exited with code {code}', completed)
        return completed
    finally:
        # Also stop descendants holding pipes or surviving their launcher.
        stop_group(process)
        try:
            process.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            stop_group(process, force=True)
            process.wait()
        # A launcher can exit while a descendant ignores TERM in its group.
        stop_group(process, force=True)
        if reader is not None and reader.is_alive():
            reader.join(timeout=2)
        process.stdout.close()
