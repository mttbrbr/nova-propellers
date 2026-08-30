#!/usr/bin/env python3
"""Fail when a locked runtime dependency has unknown or unreviewed licensing."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_NPM_LICENSES = {
    "Apache-2.0",
    "Apache-2.0 OR MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC-BY-4.0",
    "ISC",
    "MIT",
    "Python-2.0",
}


def python_runtime_dependencies() -> set[str]:
    rows = set()
    for raw_line in (ROOT / "backend/requirements.lock").read_text().splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            rows.add(line)
    return rows


def check_python() -> list[str]:
    reviewed = json.loads(
        (ROOT / "compliance/python-runtime-licenses.json").read_text()
    )
    locked = python_runtime_dependencies()
    errors = []
    if locked != set(reviewed):
        errors.append(
            "Python license inventory mismatch: "
            f"missing={sorted(locked - set(reviewed))}, extra={sorted(set(reviewed) - locked)}"
        )
    for dependency, license_id in reviewed.items():
        if not license_id or license_id == "UNKNOWN":
            errors.append(f"Unresolved Python license: {dependency}")
    return errors


def check_npm() -> list[str]:
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    errors = []
    for path, package in lock["packages"].items():
        if not path:
            continue
        license_id = package.get("license", "UNKNOWN")
        if license_id not in ALLOWED_NPM_LICENSES:
            errors.append(
                f"Unreviewed npm license {license_id}: {path}@{package.get('version', 'UNKNOWN')}"
            )
    return errors


def main() -> int:
    errors = check_python() + check_npm()
    if errors:
        print("\n".join(errors))
        return 1
    print("Locked Python and npm licenses match the reviewed allowlist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
