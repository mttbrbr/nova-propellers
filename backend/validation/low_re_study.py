"""Compare low-Reynolds polar treatments without changing production defaults."""

import argparse
import json
import statistics
from pathlib import Path

from inverse_design import BEMTSolver

from .relaxation_study import PERFORMANCE_FIELDS, _case_key, _failure_diagnostics
from .sensitivity import _geometry, _relative_error


DEFAULT_CONFIG = Path(__file__).with_name("cases") / "bemt_low_re_study.json"


def run_study(config: dict) -> dict:
    rows = []
    for strategy in config["strategies"]:
        for geometry_definition in config["geometries"]:
            for rpm in config["rpm_values"]:
                for stations in config["station_counts"]:
                    geometry = _geometry(geometry_definition, stations)
                    for tolerance in config["solver_tolerances"]:
                        detailed = BEMTSolver(
                            tolerance=tolerance,
                            max_iterations=config["max_iterations"],
                            relaxation_factor=config["relaxation_factor"],
                            low_re_strategy=strategy,
                            max_tangential_induction_ratio=config.get(
                                "max_tangential_induction_ratio", 0.95
                            ),
                        ).evaluate_detailed(geometry, rpm)
                        convergence = detailed["convergence"]
                        rows.append(
                            {
                                "strategy_id": strategy,
                                "geometry_id": geometry_definition["id"],
                                "rpm": rpm,
                                "station_count": stations,
                                "solver_tolerance": tolerance,
                                "performance": detailed["performance"],
                                "converged": convergence["converged"],
                                "iterations": convergence["iterations"],
                                "residual": convergence["residual"],
                                "diagnostics": convergence["diagnostics"],
                                "coefficient_range": {
                                    "min_cl": min(row["cl"] for row in detailed["curves"]),
                                    "max_cl": max(row["cl"] for row in detailed["curves"]),
                                    "min_cd": min(row["cd"] for row in detailed["curves"]),
                                    "max_cd": max(row["cd"] for row in detailed["curves"]),
                                },
                            }
                        )

    baseline = {
        _case_key(row): row
        for row in rows
        if row["strategy_id"] == config["baseline_strategy"]
    }
    acceptance = config["acceptance"]
    assessments = []
    for strategy in config["strategies"]:
        strategy_rows = [row for row in rows if row["strategy_id"] == strategy]
        deltas = [
            _relative_error(
                row["performance"][field],
                baseline[_case_key(row)]["performance"][field],
            )
            for row in strategy_rows
            for field in PERFORMANCE_FIELDS
        ]
        coefficient_bounds_ok = all(
            abs(row["coefficient_range"][limit]) <= acceptance["max_absolute_cl"]
            for row in strategy_rows
            for limit in ("min_cl", "max_cl")
        ) and all(
            acceptance["min_cd"] <= row["coefficient_range"][limit] <= acceptance["max_cd"]
            for row in strategy_rows
            for limit in ("min_cd", "max_cd")
        )
        converged_count = sum(row["converged"] for row in strategy_rows)
        all_converged = converged_count == len(strategy_rows)
        max_delta = max(deltas)
        passed = (
            (all_converged or not acceptance["require_all_converged"])
            and max_delta <= acceptance["max_relative_performance_delta"]
            and coefficient_bounds_ok
        )
        assessments.append(
            {
                "strategy_id": strategy,
                "passed": passed,
                "converged": converged_count,
                "evaluations": len(strategy_rows),
                "median_iterations": statistics.median(
                    row["iterations"] for row in strategy_rows
                ),
                "max_relative_performance_delta": max_delta,
                "coefficient_bounds_ok": coefficient_bounds_ok,
                "failure_diagnostics": _failure_diagnostics(strategy_rows),
            }
        )
    eligible = [item for item in assessments if item["passed"]]
    recommended = (
        min(eligible, key=lambda item: item["median_iterations"])["strategy_id"]
        if eligible
        else None
    )
    return {
        "schema_version": "1.0",
        "study_id": config["study_id"],
        "configuration": config,
        "assessments": assessments,
        "recommended_strategy": recommended,
        "results": rows,
    }


def render_markdown(report: dict) -> str:
    lines = [
        f"# {report['study_id']}",
        "",
        "This is a numerical treatment study, not experimental validation.",
        "",
        "| Strategy | Pass | Converged | Median iterations | "
        "Max performance delta | Coefficients valid |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for item in report["assessments"]:
        lines.append(
            f"| {item['strategy_id']} | {item['passed']} | "
            f"{item['converged']}/{item['evaluations']} | {item['median_iterations']} | "
            f"{item['max_relative_performance_delta']:.3%} | "
            f"{item['coefficient_bounds_ok']} |"
        )
    lines.extend(
        [
            "",
            f"Recommended strategy: **{report['recommended_strategy'] or 'none'}**.",
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
    for item in report["assessments"]:
        print(
            f"{item['strategy_id']}: converged={item['converged']}/{item['evaluations']}, "
            f"median_iterations={item['median_iterations']}, "
            f"max_delta={item['max_relative_performance_delta']:.3%}, "
            f"coefficients_valid={item['coefficient_bounds_ok']}, "
            f"failures={item['failure_diagnostics']}"
        )
    print(f"recommended={report['recommended_strategy']}")
    print(json_path)
    print(markdown_path)
    if report["recommended_strategy"] is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
