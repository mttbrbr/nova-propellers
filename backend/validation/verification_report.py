"""Build the consolidated pre-experimental BEMT verification report."""

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .root_induction_study import run_study as run_root_study
from .runner import CASES_DIRECTORY, _load_case, validate_case
from .sensitivity import DEFAULT_CONFIG as SENSITIVITY_CONFIG
from .sensitivity import run_study as run_sensitivity_study


ROOT_CONFIG = Path(__file__).with_name("cases") / "bemt_root_induction_study.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _configuration_hash(configuration: dict) -> str:
    payload = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_report() -> dict:
    regression_cases = []
    for path in sorted(CASES_DIRECTORY.glob("*.json")):
        case = _load_case(path)
        if case.get("purpose") != "deterministic_regression":
            continue
        checks = validate_case(case)
        regression_cases.append(
            {
                "case_id": case["case_id"],
                "passed": True,
                "checks": checks,
                "configuration_sha256": _configuration_hash(case),
            }
        )

    sensitivity_config = _read_json(SENSITIVITY_CONFIG)
    sensitivity = run_sensitivity_study(sensitivity_config)
    root_config = _read_json(ROOT_CONFIG)
    root = run_root_study(root_config)
    sensitivity_passed = sensitivity["assessment"]["passed"]
    root_passed = root["recommended_ratio"] == 0.75
    passed = (
        bool(regression_cases)
        and all(case["passed"] for case in regression_cases)
        and sensitivity_passed
        and root_passed
    )
    return {
        "schema_version": "1.0",
        "report_id": "bemt-pre-experimental-verification",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "nova_version": os.getenv("NOVA_VERSION", "0.1.0-alpha.2"),
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "claim": (
            "Software and numerical verification in the declared domain; "
            "not validation against experimental measurements."
        ),
        "supported_domain": {
            "solver": "bemt",
            "operation": "static axial",
            "minimum_tolerance": 1e-5,
            "maximum_tangential_induction_ratio": 0.75,
            "relaxation_strategy": "fixed",
            "relaxation_factor": 0.08,
            "low_reynolds_strategy": "clip",
            "validated_station_counts": [12, 18, 24, 36, 48, 72],
        },
        "regression": {"passed": bool(regression_cases), "cases": regression_cases},
        "sensitivity": {
            "passed": sensitivity_passed,
            "assessment": sensitivity["assessment"],
            "configuration_sha256": _configuration_hash(sensitivity_config),
        },
        "root_induction": {
            "passed": root_passed,
            "recommended_ratio": root["recommended_ratio"],
            "assessments": root["assessments"],
            "configuration_sha256": _configuration_hash(root_config),
        },
        "passed": passed,
    }


def render_markdown(report: dict) -> str:
    sensitivity = report["sensitivity"]["assessment"]
    lines = [
        "# BEMT pre-experimental verification report",
        "",
        f"Overall status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"> {report['claim']}",
        "",
        "## Supported numerical domain",
        "",
    ]
    lines.extend(
        f"- {key.replace('_', ' ')}: `{value}`"
        for key, value in report["supported_domain"].items()
    )
    lines.extend(
        [
            "",
            "## Evidence summary",
            "",
            f"- Golden regression: {'PASS' if report['regression']['passed'] else 'FAIL'}",
            f"- Numerical sensitivity: {'PASS' if report['sensitivity']['passed'] else 'FAIL'}",
            "- Root-induction selection: "
            f"{'PASS' if report['root_induction']['passed'] else 'FAIL'}",
            f"- Sensitivity evaluations: {sensitivity['evaluations']} matrix cases",
            f"- All sensitivity cases converged: {sensitivity['all_converged']}",
            "- Maximum finest-grid relative error: "
            f"{sensitivity['max_relative_error_at_finest_grid']:.6%}",
            "- Selected maximum tangential-induction ratio: "
            f"{report['root_induction']['recommended_ratio']}",
            "",
            "## Claim boundary",
            "",
            "This report establishes deterministic behavior, internal physical consistency, "
            "declared convergence and numerical sensitivity. It does not establish predictive "
            "accuracy, certify a design or replace comparison with independent measurements.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_report()
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = arguments.output_dir / "bemt-pre-experimental-verification.json"
    markdown_path = arguments.output_dir / "bemt-pre-experimental-verification.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"{'PASS' if report['passed'] else 'FAIL'} {report['report_id']}")
    print(json_path)
    print(markdown_path)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
