"""Run deterministic BEMT regression and physics-consistency checks.

This suite detects software regressions. It does not establish agreement with
experimental measurements and must not be described as solver qualification.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from inverse_design import BEMTSolver, BezierBladeGeometry, BezierControlPoints


CASES_DIRECTORY = Path(__file__).with_name("cases")


def _load_case(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _geometry(case: dict, *, diameter_m: float | None = None):
    definition = case["geometry"]
    points = BezierControlPoints(
        chord=np.asarray(definition["chord_points"], dtype=float),
        twist=np.asarray(definition["twist_points_deg"], dtype=float),
    )
    return BezierBladeGeometry(
        diameter_m or definition["diameter_m"],
        definition["blades"],
        station_count=definition["stations"],
    ).build(points)


def evaluate_case(case: dict) -> dict:
    operating_point = case["operating_point"]
    solver = BEMTSolver(
        axial_velocity_m_s=operating_point["axial_velocity_m_s"],
        air_density=operating_point["air_density_kg_m3"],
    )
    return solver.evaluate_detailed(_geometry(case), operating_point["rpm"])


def _assert_close(label: str, actual: float, expected: float, tolerances: dict) -> None:
    if not math.isclose(
        actual,
        expected,
        rel_tol=tolerances["relative"],
        abs_tol=tolerances["absolute"],
    ):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def validate_case(case: dict) -> list[str]:
    detailed = evaluate_case(case)
    performance = detailed["performance"]
    convergence = detailed["convergence"]
    curves = detailed["curves"]
    rpm = case["operating_point"]["rpm"]
    omega = 2.0 * math.pi * rpm / 60.0
    checks: list[str] = []

    values = list(performance.values())
    if not all(math.isfinite(value) for value in values):
        raise AssertionError("performance contains NaN or infinity")
    checks.append("finite performance")

    if not convergence["converged"] or convergence["residual"] >= convergence["tolerance"]:
        raise AssertionError(f"BEMT did not converge: {convergence}")
    checks.append("declared convergence")

    station_thrust = sum(row["d_thrust_n"] for row in curves)
    strict_tolerance = {"relative": 1e-5, "absolute": 1e-6}
    _assert_close("station thrust sum", station_thrust, performance["thrust"], strict_tolerance)
    checks.append("station-to-total thrust conservation")

    station_power = sum(row["d_power_w"] for row in curves)
    expected_power = performance["torque"] * omega
    _assert_close("station power sum", station_power, expected_power, strict_tolerance)
    checks.append("power identity P = Q omega")

    low_rpm = BEMTSolver().evaluate(_geometry(case), rpm * 0.7)["thrust"]
    if performance["thrust"] <= low_rpm:
        raise AssertionError("thrust did not increase with RPM")
    checks.append("RPM monotonicity")

    for field, expected in case["expected"].items():
        performance_field = {
            "thrust_n": "thrust",
            "torque_nm": "torque",
            "efficiency": "efficiency",
        }[field]
        _assert_close(field, performance[performance_field], expected, case["tolerances"])
    checks.append("golden regression values")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", type=Path)
    arguments = parser.parse_args()
    paths = arguments.cases or sorted(CASES_DIRECTORY.glob("*.json"))
    if not paths:
        raise SystemExit("No validation cases found")
    executed = 0
    for path in paths:
        case = _load_case(path)
        if case.get("purpose") != "deterministic_regression":
            continue
        checks = validate_case(case)
        print(f"PASS {case['case_id']}: {', '.join(checks)}")
        executed += 1
    if executed == 0:
        raise SystemExit("No deterministic regression cases found")


if __name__ == "__main__":
    main()
