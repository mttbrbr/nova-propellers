"""Characterize BEMT sensitivity to radial discretization and solver tolerance."""

import argparse
import json
import math
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from inverse_design import BEMTSolver, BezierBladeGeometry, BezierControlPoints


DEFAULT_CONFIG = Path(__file__).with_name("cases") / "bemt_sensitivity.json"


def _geometry(definition: dict, station_count: int):
    control_points = BezierControlPoints(
        chord=np.asarray(definition["chord_points"], dtype=float),
        twist=np.asarray(definition["twist_points_deg"], dtype=float),
    )
    return BezierBladeGeometry(
        definition["diameter_m"],
        definition["blades"],
        station_count=station_count,
    ).build(control_points)


def _evaluate(
    definition: dict,
    rpm: float,
    station_count: int,
    tolerance: float,
    max_iterations: int,
) -> dict:
    solver = BEMTSolver(tolerance=tolerance, max_iterations=max_iterations)
    started = time.perf_counter()
    detailed = solver.evaluate_detailed(_geometry(definition, station_count), rpm)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    performance = detailed["performance"]
    convergence = detailed["convergence"]
    omega = 2.0 * math.pi * rpm / 60.0
    return {
        "thrust_n": performance["thrust"],
        "torque_nm": performance["torque"],
        "power_w": performance["torque"] * omega,
        "efficiency": performance["efficiency"],
        "converged": convergence["converged"],
        "iterations": convergence["iterations"],
        "residual": convergence["residual"],
        "convergence_diagnostics": convergence["diagnostics"],
        "elapsed_ms": elapsed_ms,
    }


def _relative_error(actual: float, reference: float) -> float:
    return abs(actual - reference) / max(abs(reference), 1e-12)


def run_study(config: dict) -> dict:
    references: dict[tuple[str, float], dict] = {}
    reference_config = config["reference"]
    for geometry in config["geometries"]:
        for rpm in config["rpm_values"]:
            references[(geometry["id"], rpm)] = _evaluate(
                geometry,
                rpm,
                reference_config["station_count"],
                reference_config["solver_tolerance"],
                reference_config["max_iterations"],
            )

    rows = []
    for geometry in config["geometries"]:
        for rpm in config["rpm_values"]:
            reference = references[(geometry["id"], rpm)]
            for stations in config["station_counts"]:
                for tolerance in config["solver_tolerances"]:
                    result = _evaluate(
                        geometry, rpm, stations, tolerance, config["max_iterations"]
                    )
                    rows.append(
                        {
                            "geometry_id": geometry["id"],
                            "rpm": rpm,
                            "station_count": stations,
                            "solver_tolerance": tolerance,
                            **result,
                            "relative_error": {
                                field: _relative_error(result[field], reference[field])
                                for field in ("thrust_n", "torque_nm", "power_w")
                            },
                        }
                    )

    finest = max(config["station_counts"])
    finest_rows = [row for row in rows if row["station_count"] == finest]
    max_finest_error = max(
        error
        for row in finest_rows
        for error in row["relative_error"].values()
    )
    all_converged = all(row["converged"] for row in rows) and all(
        reference["converged"] for reference in references.values()
    )
    nonconverged_evaluations = sum(not row["converged"] for row in rows) + sum(
        not reference["converged"] for reference in references.values()
    )
    classifications: dict[str, int] = {}
    for evaluation in [*rows, *references.values()]:
        classification = evaluation["convergence_diagnostics"]["classification"]
        classifications[classification] = classifications.get(classification, 0) + 1
    acceptance = config["acceptance"]
    passed = (
        (all_converged or not acceptance["require_convergence"])
        and max_finest_error <= acceptance["max_relative_error_at_finest_grid"]
    )
    return {
        "schema_version": "1.0",
        "study_id": config["study_id"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
        "configuration": config,
        "references": [
            {"geometry_id": geometry_id, "rpm": rpm, **result}
            for (geometry_id, rpm), result in references.items()
        ],
        "results": rows,
        "assessment": {
            "passed": passed,
            "all_converged": all_converged,
            "nonconverged_evaluations": nonconverged_evaluations,
            "classifications": classifications,
            "max_relative_error_at_finest_grid": max_finest_error,
            "evaluations": len(rows),
        },
    }


def render_markdown(report: dict) -> str:
    assessment = report["assessment"]
    config = report["configuration"]
    lines = [
        f"# {report['study_id']}",
        "",
        "This is a numerical-sensitivity report, not experimental validation.",
        "",
        "## Assessment",
        "",
        f"- Status: **{'PASS' if assessment['passed'] else 'FAIL'}**",
        f"- Evaluations: {assessment['evaluations']}",
        f"- All cases converged: {assessment['all_converged']}",
        f"- Non-converged evaluations: {assessment['nonconverged_evaluations']}",
        "- Classifications: "
        + ", ".join(
            f"{name}={count}" for name, count in sorted(assessment["classifications"].items())
        ),
        "- Maximum relative error on finest tested grid: "
        f"{assessment['max_relative_error_at_finest_grid']:.4%}",
        "",
        "## Study matrix",
        "",
        f"- Geometries: {', '.join(item['id'] for item in config['geometries'])}",
        f"- RPM: {', '.join(str(value) for value in config['rpm_values'])}",
        f"- Stations: {', '.join(str(value) for value in config['station_counts'])}",
        "- Solver tolerances: "
        f"{', '.join(format(value, '.0e') for value in config['solver_tolerances'])}",
        "",
        "## Finest-grid results",
        "",
        "| Geometry | RPM | Tolerance | Thrust [N] | Power [W] | Max error | Iterations |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    finest = max(config["station_counts"])
    for row in report["results"]:
        if row["station_count"] != finest:
            continue
        max_error = max(row["relative_error"].values())
        lines.append(
            f"| {row['geometry_id']} | {row['rpm']:.0f} | {row['solver_tolerance']:.0e} "
            f"| {row['thrust_n']:.5f} | {row['power_w']:.5f} | {max_error:.3%} "
            f"| {row['iterations']} |"
        )
    lines.extend(
        [
            "",
            "The reference uses the station count and tolerance declared in the JSON report. "
            "Timing is diagnostic only and is not an acceptance criterion.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    report = run_study(config)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = arguments.output_dir / f"{config['study_id']}.json"
    markdown_path = arguments.output_dir / f"{config['study_id']}.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"{'PASS' if report['assessment']['passed'] else 'FAIL'} {config['study_id']}")
    print(f"all_converged={report['assessment']['all_converged']}")
    print(
        "nonconverged_evaluations="
        f"{report['assessment']['nonconverged_evaluations']}"
    )
    print(f"classifications={report['assessment']['classifications']}")
    for reference in report["references"]:
        if not reference["converged"]:
            print(
                "nonconverged_reference="
                f"{reference['geometry_id']}@{reference['rpm']:.0f}rpm, "
                f"residual={reference['residual']:.6e}, "
                f"classification={reference['convergence_diagnostics']['classification']}"
            )
    for row in report["results"]:
        if not row["converged"]:
            print(
                "nonconverged_matrix_case="
                f"{row['geometry_id']}@{row['rpm']:.0f}rpm, "
                f"stations={row['station_count']}, tolerance={row['solver_tolerance']:.0e}, "
                f"residual={row['residual']:.6e}, "
                f"classification={row['convergence_diagnostics']['classification']}"
            )
    print(
        "max_relative_error_at_finest_grid="
        f"{report['assessment']['max_relative_error_at_finest_grid']:.6%}"
    )
    print(json_path)
    print(markdown_path)
    if not report["assessment"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
