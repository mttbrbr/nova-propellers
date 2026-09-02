"""Compare fixed and adaptive BEMT relaxation strategies."""

import argparse
import json
import statistics
from pathlib import Path

from inverse_design import BEMTSolver

from .sensitivity import _geometry, _relative_error


DEFAULT_CONFIG = Path(__file__).with_name("cases") / "bemt_relaxation_study.json"
PERFORMANCE_FIELDS = ("thrust", "torque", "efficiency")


def _case_key(row: dict) -> tuple:
    return (
        row["geometry_id"],
        row["rpm"],
        row["station_count"],
        row["solver_tolerance"],
    )


def _failure_diagnostics(rows: list[dict]) -> dict:
    failed = [row for row in rows if not row["converged"]]
    if not failed:
        return {
            "components": {},
            "alpha_clipped": 0,
            "reynolds_clipped": 0,
            "limiting_r_over_R_range": None,
        }
    final_samples = [row["diagnostics"]["history"][-1] for row in failed]
    components: dict[str, int] = {}
    for sample in final_samples:
        component = sample["limiting_component"]
        components[component] = components.get(component, 0) + 1
    radial_positions = [sample["limiting_r_over_R"] for sample in final_samples]
    alphas = [sample["limiting_alpha_deg"] for sample in final_samples]
    reynolds_values = [sample["limiting_reynolds"] for sample in final_samples]
    loss_factors = [sample["limiting_loss_factor"] for sample in final_samples]
    return {
        "components": components,
        "alpha_clipped": sum(sample["polar_context"]["alpha_clipped"] for sample in final_samples),
        "reynolds_clipped": sum(
            sample["polar_context"]["reynolds_clipped"] for sample in final_samples
        ),
        "limiting_r_over_R_range": [min(radial_positions), max(radial_positions)],
        "limiting_alpha_deg_range": [min(alphas), max(alphas)],
        "limiting_reynolds_range": [min(reynolds_values), max(reynolds_values)],
        "limiting_loss_factor_range": [min(loss_factors), max(loss_factors)],
    }


def run_study(config: dict) -> dict:
    rows = []
    for strategy in config["strategies"]:
        for geometry_definition in config["geometries"]:
            for rpm in config["rpm_values"]:
                for stations in config["station_counts"]:
                    geometry = _geometry(geometry_definition, stations)
                    for tolerance in config["solver_tolerances"]:
                        solver = BEMTSolver(
                            tolerance=tolerance,
                            max_iterations=config["max_iterations"],
                            relaxation_factor=strategy["initial_factor"],
                            relaxation_strategy=strategy["strategy"],
                            max_tangential_induction_ratio=config.get(
                                "max_tangential_induction_ratio", 0.75
                            ),
                        )
                        detailed = solver.evaluate_detailed(geometry, rpm)
                        convergence = detailed["convergence"]
                        rows.append(
                            {
                                "strategy_id": strategy["id"],
                                "geometry_id": geometry_definition["id"],
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

    baseline_rows = {
        _case_key(row): row
        for row in rows
        if row["strategy_id"] == config["baseline_strategy_id"]
    }
    acceptance = config["acceptance"]
    assessments = []
    for strategy in config["strategies"]:
        strategy_rows = [row for row in rows if row["strategy_id"] == strategy["id"]]
        deltas = []
        for row in strategy_rows:
            baseline = baseline_rows[_case_key(row)]
            deltas.extend(
                _relative_error(
                    row["performance"][field], baseline["performance"][field]
                )
                for field in PERFORMANCE_FIELDS
            )
        converged_count = sum(row["converged"] for row in strategy_rows)
        all_converged = converged_count == len(strategy_rows)
        max_delta = max(deltas)
        passed = (
            (all_converged or not acceptance["require_all_converged"])
            and max_delta <= acceptance["max_relative_performance_delta"]
        )
        assessments.append(
            {
                "strategy_id": strategy["id"],
                "passed": passed,
                "converged": converged_count,
                "evaluations": len(strategy_rows),
                "median_iterations": statistics.median(
                    row["iterations"] for row in strategy_rows
                ),
                "maximum_iterations": max(row["iterations"] for row in strategy_rows),
                "max_relative_performance_delta": max_delta,
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
        "recommended_strategy_id": recommended,
        "results": rows,
    }


def render_markdown(report: dict) -> str:
    lines = [
        f"# {report['study_id']}",
        "",
        "This study compares numerical convergence strategies; it is not experimental validation.",
        "",
        "| Strategy | Pass | Converged | Median iterations | "
        "Maximum iterations | Max performance delta | Limiting component |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["assessments"]:
        lines.append(
            f"| {item['strategy_id']} | {item['passed']} | "
            f"{item['converged']}/{item['evaluations']} | {item['median_iterations']} | "
            f"{item['maximum_iterations']} | {item['max_relative_performance_delta']:.3%} | "
            f"{item['failure_diagnostics']['components'] or 'none'} |"
        )
    lines.extend(
        [
            "",
            f"Recommended strategy: **{report['recommended_strategy_id'] or 'none'}**.",
            "",
            "A strategy is eligible only when it satisfies every predeclared acceptance criterion.",
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
    for assessment in report["assessments"]:
        print(
            f"{assessment['strategy_id']}: converged="
            f"{assessment['converged']}/{assessment['evaluations']}, "
            f"median_iterations={assessment['median_iterations']}, "
            f"max_delta={assessment['max_relative_performance_delta']:.3%}, "
            f"failures={assessment['failure_diagnostics']}"
        )
    print(f"recommended={report['recommended_strategy_id']}")
    print(json_path)
    print(markdown_path)
    if report["recommended_strategy_id"] is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
