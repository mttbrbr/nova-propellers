"""Compare root-region caps on tangential induction."""

import argparse
import json
import statistics
from pathlib import Path

from inverse_design import BEMTSolver

from .relaxation_study import PERFORMANCE_FIELDS, _case_key, _failure_diagnostics
from .sensitivity import _geometry, _relative_error


DEFAULT_CONFIG = Path(__file__).with_name("cases") / "bemt_root_induction_study.json"


def run_study(config: dict) -> dict:
    rows = []
    for ratio in config["ratios"]:
        strategy_id = f"cap-{ratio:.2f}"
        for definition in config["geometries"]:
            for rpm in config["rpm_values"]:
                for stations in config["station_counts"]:
                    geometry = _geometry(definition, stations)
                    for tolerance in config["solver_tolerances"]:
                        detailed = BEMTSolver(
                            tolerance=tolerance,
                            max_iterations=config["max_iterations"],
                            max_tangential_induction_ratio=ratio,
                        ).evaluate_detailed(geometry, rpm)
                        convergence = detailed["convergence"]
                        rows.append(
                            {
                                "strategy_id": strategy_id,
                                "ratio": ratio,
                                "geometry_id": definition["id"],
                                "rpm": rpm,
                                "station_count": stations,
                                "solver_tolerance": tolerance,
                                "performance": detailed["performance"],
                                "converged": convergence["converged"],
                                "iterations": convergence["iterations"],
                                "residual": convergence["residual"],
                                "diagnostics": convergence["diagnostics"],
                            }
                        )
    baseline_id = f"cap-{config['baseline_ratio']:.2f}"
    baseline = {_case_key(row): row for row in rows if row["strategy_id"] == baseline_id}
    assessments = []
    for ratio in config["ratios"]:
        strategy_id = f"cap-{ratio:.2f}"
        candidates = [row for row in rows if row["strategy_id"] == strategy_id]
        deltas = [
            _relative_error(
                row["performance"][field], baseline[_case_key(row)]["performance"][field]
            )
            for row in candidates
            for field in PERFORMANCE_FIELDS
        ]
        converged = sum(row["converged"] for row in candidates)
        all_converged = converged == len(candidates)
        maximum_delta = max(deltas)
        passed = (
            (all_converged or not config["acceptance"]["require_all_converged"])
            and maximum_delta <= config["acceptance"]["max_relative_performance_delta"]
        )
        assessments.append(
            {
                "strategy_id": strategy_id,
                "ratio": ratio,
                "passed": passed,
                "converged": converged,
                "evaluations": len(candidates),
                "median_iterations": statistics.median(
                    row["iterations"] for row in candidates
                ),
                "max_relative_performance_delta": maximum_delta,
                "failure_diagnostics": _failure_diagnostics(candidates),
            }
        )
    eligible = [item for item in assessments if item["passed"]]
    recommended = (
        min(eligible, key=lambda item: item["median_iterations"])["ratio"]
        if eligible
        else None
    )
    return {
        "schema_version": "1.0",
        "study_id": config["study_id"],
        "configuration": config,
        "assessments": assessments,
        "recommended_ratio": recommended,
        "results": rows,
    }


def render_markdown(report: dict) -> str:
    lines = [
        f"# {report['study_id']}",
        "",
        "This is a numerical root-model study, not experimental validation.",
        "",
        "| Cap | Pass | Converged | Median iterations | Max performance delta |",
        "| ---: | --- | ---: | ---: | ---: |",
    ]
    for item in report["assessments"]:
        lines.append(
            f"| {item['ratio']:.2f} | {item['passed']} | "
            f"{item['converged']}/{item['evaluations']} | {item['median_iterations']} | "
            f"{item['max_relative_performance_delta']:.3%} |"
        )
    lines.extend(["", f"Recommended ratio: **{report['recommended_ratio']}**.", ""])
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
            f"cap={item['ratio']:.2f}: converged={item['converged']}/{item['evaluations']}, "
            f"median_iterations={item['median_iterations']}, "
            f"max_delta={item['max_relative_performance_delta']:.3%}, "
            f"failures={item['failure_diagnostics']}"
        )
    print(f"recommended={report['recommended_ratio']}")
    print(json_path)
    print(markdown_path)
    if report["recommended_ratio"] is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
