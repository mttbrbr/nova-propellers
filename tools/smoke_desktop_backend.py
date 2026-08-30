#!/usr/bin/env python3
"""Smoke-test a bundled Nova backend without importing project Python code."""

from __future__ import annotations

import argparse
import json
import selectors
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ENDPOINT_PREFIX = "NOVA_BACKEND_ENDPOINT="


def wait_for_endpoint(process: subprocess.Popen[str], timeout: float = 25) -> str:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    output = []
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        for key, _ in selector.select(timeout=0.2):
            line = key.fileobj.readline()
            output.append(line)
            if line.startswith(ENDPOINT_PREFIX):
                return line.removeprefix(ENDPOINT_PREFIX).strip()
    raise RuntimeError(f"backend did not report an endpoint: {''.join(output)}")


def request(url: str, payload: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers), timeout=20
    ) as response:
        return response.status, response.read()


def smoke(executable: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="nova-desktop-smoke-") as data_dir:
        process = subprocess.Popen(
            [str(executable), "--port", "0", "--data-dir", data_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            endpoint = wait_for_endpoint(process)
            status, body = request(f"{endpoint}/health")
            assert status == 200 and json.loads(body) == {"status": "ok"}

            geometry_payload = {
                "project_name": "Desktop smoke test",
                "propeller_type": "traditional",
                "thrust_target": 10,
                "rpm": 5000,
                "diameter": 0.25,
                "blades": 2,
                "airfoil": "NACA 4412",
                "geometry_method": "bezier",
                "geometry_parameters": {
                    "chord_points": [
                        {"x": 0, "y": 0.026},
                        {"x": 0.5, "y": 0.022},
                        {"x": 1, "y": 0.005},
                    ],
                    "twist_points": [
                        {"x": 0, "y": 34},
                        {"x": 0.5, "y": 20},
                        {"x": 1, "y": 7},
                    ],
                },
                "airfoil_assignments": [],
            }
            status, body = request(f"{endpoint}/geometries", geometry_payload)
            assert status == 200 and json.loads(body)["geometry"]["stations"]
            status, body = request(f"{endpoint}/geometries/stl", geometry_payload)
            assert status == 200 and len(body) > 1000
            assert (Path(data_dir) / "nova.db").is_file()
        finally:
            process.terminate()
            process.wait(timeout=10)
        assert process.returncode is not None
        print(f"Desktop backend smoke test passed: {executable}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    if not args.executable.is_file():
        parser.error(f"sidecar not found: {args.executable}")
    smoke(args.executable.resolve())


if __name__ == "__main__":
    main()
