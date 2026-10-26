"""Bounded OpenFAST output import and execution of user supplied cases.

Binary layout derived from OpenFAST NWTC_IO.f90 WrBinFAST (IDs 1–4).
No external reader implementation or scientific solver is bundled.
"""

import hashlib
import math
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path

import numpy as np

from nova.adapters.base import (
    AdapterConfiguration,
    AdapterDescriptor,
    AdapterError,
    ExternalAdapter,
    PreparedCase,
    safe_artifact,
)
from nova.adapters.process import ProcessFailure, ProcessSpec, run_process
from nova.core.data import Port, content_hash

MAX_BYTES = 100 * 1024 * 1024
MAX_VALUES = 2_000_000
MAX_SAMPLES = 1_000_000
MAX_CHANNELS = 4096


def _result(names, units, time, values, description, data, filename, file_id):
    if not names or names[0].lower() != "time" or units[0] not in ("(s)", "s"):
        raise ValueError("OpenFAST output requires a Time channel explicitly in seconds")
    if len(set(names)) != len(names) or any(not n or not u for n, u in zip(names, units)):
        raise ValueError("Empty or duplicate output channel metadata")
    if not np.all(np.isfinite(time)) or not np.all(np.isfinite(values)):
        raise ValueError("Nonfinite OpenFAST time or channel values")
    if np.any(np.diff(time) <= 0):
        raise ValueError("OpenFAST output time must increase strictly")
    return {
        "kind": "time_series_result",
        "schema_version": 1,
        "channels": [
            {"name": n, "units": u, "frame": "unspecified", "sign_convention": "unspecified"}
            for n, u in zip(names[1:], units[1:])
        ],
        "time_s": time.tolist(),
        "values": values.tolist(),
        "description": description,
        "source": {
            "filename": Path(filename).name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "format": "openfast_ascii" if file_id is None else "openfast_binary",
            "file_id": file_id,
        },
    }


def _limits(samples, channels):
    if (
        not 1 <= samples <= MAX_SAMPLES
        or not 1 <= channels <= MAX_CHANNELS
        or samples * channels > MAX_VALUES
    ):
        raise ValueError("OpenFAST output exceeds bounded sample/channel limits")


def _ascii(data, filename):
    try:
        lines = data.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("OpenFAST ASCII output must be UTF-8 compatible") from exc
    header = next(
        (i for i, line in enumerate(lines) if line.split() and line.split()[0].lower() == "time"),
        None,
    )
    if header is None or header + 1 >= len(lines):
        raise ValueError("Missing OpenFAST channel names/units")
    names, units = lines[header].split(), lines[header + 1].split()
    if len(names) < 2 or len(units) != len(names):
        raise ValueError("OpenFAST channel names/units do not match")
    if len(names) - 1 > MAX_CHANNELS:
        raise ValueError("Too many OpenFAST channels")
    rows = []
    for number, line in enumerate(lines[header + 2 :], header + 3):
        if not line.strip():
            continue
        try:
            row = [float(v.replace("D", "E").replace("d", "e")) for v in line.split()]
        except ValueError as exc:
            raise ValueError(f"Malformed OpenFAST numeric row {number}") from exc
        if len(row) != len(names):
            raise ValueError(f"OpenFAST row {number} has the wrong channel count")
        rows.append(row)
        _limits(len(rows), len(names) - 1)
    _limits(len(rows), len(names) - 1)
    array = np.asarray(rows)
    return _result(
        names,
        units,
        array[:, 0],
        array[:, 1:],
        "\n".join(lines[:header]).strip(),
        data,
        filename,
        None,
    )


def _binary(data, filename):
    position = 0

    def take(size):
        nonlocal position
        if size < 0 or position + size > len(data):
            raise ValueError("Truncated OpenFAST binary output")
        value = memoryview(data)[position : position + size]
        position += size
        return value

    def scalar(fmt):
        return struct.unpack("<" + fmt, take(struct.calcsize("<" + fmt)))[0]

    file_id = scalar("h")
    if file_id not in (1, 2, 3, 4):
        raise ValueError("Unsupported OpenFAST binary format ID")
    width = scalar("h") if file_id == 4 else 10
    if not 1 <= width <= 1024:
        raise ValueError("Invalid OpenFAST channel name width")
    channels, samples = scalar("i"), scalar("i")
    _limits(samples, channels)
    first, second = scalar("d"), scalar("d")
    if (
        not all(math.isfinite(v) for v in (first, second))
        or (file_id == 1 and first == 0)
        or (file_id != 1 and second <= 0)
    ):
        raise ValueError("Invalid OpenFAST time scaling")
    if file_id != 3:
        scales = np.frombuffer(take(4 * channels), dtype="<f4").astype(float)
        offsets = np.frombuffer(take(4 * channels), dtype="<f4").astype(float)
        if (
            not np.all(np.isfinite(scales))
            or not np.all(np.isfinite(offsets))
            or np.any(scales == 0)
        ):
            raise ValueError("Invalid OpenFAST channel scaling; values cannot be reconstructed")
    length = scalar("i")
    if not 0 <= length <= 1_000_000:
        raise ValueError("Invalid OpenFAST description length")
    try:
        description = bytes(take(length)).decode("utf-8")

        def labels():
            return [bytes(take(width)).decode("ascii").strip(" \x00") for _ in range(channels + 1)]

        names, units = labels(), labels()
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid OpenFAST binary text metadata") from exc
    if file_id == 1:
        time = (np.frombuffer(take(4 * samples), dtype="<i4").astype(float) - second) / first
    else:
        time = first + np.arange(samples, dtype=float) * second
    dtype, size = ("<f8", 8) if file_id == 3 else ("<i2", 2)
    values = (
        np.frombuffer(take(size * samples * channels), dtype=dtype)
        .astype(float)
        .reshape(samples, channels)
    )
    if file_id != 3:
        values = (values - offsets) / scales
    if position != len(data):
        raise ValueError("Unexpected trailing OpenFAST binary bytes")
    return _result(names, units, time, values, description, data, filename, file_id)


def read_openfast_bytes(data, filename):
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise ValueError("OpenFAST output requires nonempty bytes up to 100 MiB")
    suffix = Path(filename).suffix.lower()
    if suffix == ".out":
        return _ascii(data, filename)
    if suffix == ".outb":
        return _binary(data, filename)
    raise ValueError("Select an OpenFAST .out or .outb file")


def read_openfast_output(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Missing or oversized OpenFAST output")
    with path.open("rb") as stream:
        return read_openfast_bytes(stream.read(MAX_BYTES + 1), path.name)


def _relative(value, suffixes):
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise AdapterError("Case paths must be relative POSIX paths")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() not in suffixes:
        raise AdapterError("Invalid or escaping OpenFAST case path")
    return path


def _case_files(case):
    if set(case) - {
        "case_directory",
        "input_file",
        "output_file",
        "timeout_seconds",
        "source_case_directory",
        "input_files",
        "input_hashes",
    }:
        raise AdapterError("Unsupported OpenFAST case option")
    selected = Path(case.get("case_directory", ""))
    if not selected.is_absolute() or selected.is_symlink() or not selected.is_dir():
        raise AdapterError("Select an absolute self-contained case directory")
    root = selected.resolve()
    input_path = _relative(case.get("input_file"), (".fst",))
    _relative(case.get("output_file"), (".out", ".outb"))
    timeout = case.get("timeout_seconds", 60.0)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise AdapterError("OpenFAST timeout must be positive and at most 3600 seconds")
    files, total, entries, file_count = [], 0, 0, 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            entries += 1
            path = Path(directory) / name
            if entries > 2000 or path.is_symlink() or not path.resolve().is_relative_to(root):
                raise AdapterError("Case contains symlink, escaping path or too many entries")
        for name in names:
            path = Path(directory) / name
            if not path.is_file():
                raise AdapterError("Case contains a nonregular file")
            file_count += 1
            total += path.stat().st_size
            if file_count > 1000 or total > MAX_BYTES:
                raise AdapterError("Case permits at most 1000 files and 100 MiB")
            if path.suffix.lower() in (".out", ".outb"):
                continue
            files.append(path)
            # Conservatively inspect text inputs. Quoted filenames and standalone
            # path tokens must remain inside the selected case, without rewriting.
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                if path.suffix.lower() in (".fst", ".dat", ".txt", ".inp", ".yaml", ".csv"):
                    raise AdapterError("Text case inputs must be UTF-8 compatible")
                continue
            for line in text.splitlines():
                line = line.split("!")[0]
                quoted = re.findall(r'"([^"\n]*)"|\x27([^\x27\n]*)\x27', line)
                candidates = [a or b for a, b in quoted]
                candidates.extend(re.findall(r'[^\s"\x27]+', line))
                for token in candidates:
                    if not token or token.lower() in ("unused", "default", "none"):
                        continue
                    if (
                        "/" not in token
                        and "\\" not in token
                        and not re.search(r"\.(fst|dat|txt|bts|dll|so|inp|yaml|csv)$", token, re.I)
                    ):
                        continue
                    normalized = token.replace("\\", "/")
                    reference = Path(normalized)
                    resolved = (path.parent / reference).resolve()
                    if (
                        reference.is_absolute()
                        or re.match(r"^[A-Za-z]:", normalized)
                        or not resolved.is_relative_to(root)
                    ):
                        raise AdapterError(f"Case input references outside its folder: {path.name}")
    if not (root / input_path).is_file() or root / input_path not in files:
        raise AdapterError("Missing OpenFAST primary input")
    if "input_hashes" in case:
        actual = {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        }
        if actual != case["input_hashes"] or set(actual) != set(case.get("input_files", [])):
            raise AdapterError("Frozen OpenFAST case inputs changed after submission")
    return root, files


def copy_openfast_case(case, destination):
    """Freeze selected source inputs before queueing; preserve hashes and originals."""
    root, files = _case_files(case)
    destination = Path(destination).absolute()
    if destination.exists():
        raise AdapterError("Case snapshot destination must not exist")
    if destination.resolve().is_relative_to(root):
        raise AdapterError("Case snapshot must be outside its source folder")
    destination.mkdir(parents=True)
    names, hashes = [], {}
    try:
        for source in files:
            relative = source.relative_to(root)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            name = str(relative)
            names.append(name)
            hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        frozen = {
            **case,
            "case_directory": str(destination),
            "source_case_directory": case.get("source_case_directory", str(root)),
            "input_files": names,
            "input_hashes": hashes,
        }
        _case_files(frozen)
        return frozen
    except Exception:
        shutil.rmtree(destination)
        raise


def inspect_openfast_case(case):
    """Inspect the same contained inputs used by execution, without a solver.

    Hashes cover raw input bytes and relative names; source locations and old
    result files do not contribute to scientific case identity.
    """
    root, files = _case_files(case)
    inventory, total = [], 0
    for path in sorted(files, key=lambda value: value.relative_to(root).as_posix()):
        with path.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        total += len(data)
        if total > MAX_BYTES:
            raise AdapterError('Case inputs changed or exceed the 100 MiB limit')
        inventory.append({'path': path.relative_to(root).as_posix(), 'bytes': len(data),
                          'sha256': hashlib.sha256(data).hexdigest()})
    warnings = ['Preflight does not execute OpenFAST or validate version-specific model settings.']
    if (root / case['output_file']).exists():
        warnings.append('Existing output is excluded from the input snapshot; execution must produce a new result.')
    return {'input_file': case['input_file'], 'output_file': case['output_file'],
            'file_count': len(inventory), 'total_bytes': total,
            'case_hash': content_hash({'input_file': case['input_file'], 'output_file': case['output_file'],
                                       'input_files': inventory}),
            'input_files': inventory, 'warnings': warnings}


class OpenFASTAdapter(ExternalAdapter):
    def describe(self):
        return AdapterDescriptor(
            "openfast",
            "OpenFAST",
            "1.0",
            "Runs a supplied self-contained case; imports ASCII/binary time series.",
            "Apache-2.0 (external solver, installed independently)",
            ("local_executable",),
            {"case": Port("openfast_case", "native", shape="record")},
            {
                "result": Port(
                    "time_series_result", "native", shape="record", time_domain="time_series"
                )
            },
        )

    def probe(self, configuration: AdapterConfiguration):
        try:
            with tempfile.TemporaryDirectory(prefix="nova-openfast-probe-") as temporary:
                result = run_process(
                    ProcessSpec(configuration.executable, ("-v",), 10.0), Path(temporary)
                )
            match = re.search(
                r"\bOpenFAST(?:[-_ ]v?|\s+version\s+)(\d+\.\d+(?:\.\d+)?)", result.log, re.I
            )
            version = match[1] if match else None
            return {
                "available": True,
                "compatible": version is not None,
                "version": version,
                "message": result.log[-4000:],
                "version_flag": "-v",
            }
        except (OSError, ValueError, ProcessFailure) as exc:
            return {"available": False, "compatible": False, "version": None, "message": str(exc)}

    def validate(self, case, configuration):
        if configuration.environment_kind != "local_executable" or configuration.options:
            raise AdapterError(
                "OpenFAST currently accepts a local executable without adapter options"
            )
        _case_files(case)

    def prepare(self, case, configuration, directory):
        root, files = _case_files(case)
        target = directory / "case"
        target.mkdir()
        copied = []
        for source in files:
            relative = source.relative_to(root)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(str(Path("case") / relative))
        return PreparedCase(
            (
                ProcessSpec(
                    configuration.executable,
                    (str(Path("case") / case["input_file"]),),
                    case.get("timeout_seconds", 60.0),
                ),
            ),
            tuple(copied),
            (str(Path("case") / case["output_file"]),),
        )

    def collect(self, directory, prepared):
        return read_openfast_output(safe_artifact(directory, prepared.expected_outputs[0]))

    def normalize(self, output):
        return output
