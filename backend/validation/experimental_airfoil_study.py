"""Measure sensitivity to Nova's synthetic airfoil families without calibration."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from inverse_design import BEMTSolver
from inverse_design.geometry import GeometryData
from polar_database import SYNTHETIC_POLAR_PARAMETERS
from validation.experimental import (
    ExperimentalSeries,
    compare_grouped,
    evaluate_series,
    resample_geometry,
)
from validation.experimental_report import GENERATED_ROOT, REFERENCE_ROOT, ROOT, load_case
from validation.uiuc import UIUCVolume1Adapter


def _geometry_with_airfoil(geometry: GeometryData, airfoil: str) -> GeometryData:
    return GeometryData(
        radius_m=geometry.radius_m.copy(),
        chord_m=geometry.chord_m.copy(),
        twist_rad=geometry.twist_rad.copy(),
        diameter_m=geometry.diameter_m,
        blades=geometry.blades,
        airfoil=airfoil,
        propeller_type=geometry.propeller_type,
    )


def run(case_path: Path, station_count: int = 36) -> Path:
    case = load_case(case_path)
    local = REFERENCE_ROOT / "uiuc" / case["case_id"]
    adapter = UIUCVolume1Adapter()
    parsed = [
        adapter.parse_dynamic(
            local / item["file"],
            rpm=item["rpm"],
            provenance={"case_id": case["case_id"], "propeller_id": case["propeller_id"]},
        )
        for item in case["measurement_series"]
    ]
    series = ExperimentalSeries(
        parsed[0].dataset,
        parsed[0].case_id,
        parsed[0].propeller_id,
        tuple(point for item in parsed for point in item.points),
        parsed[0].provenance,
    )
    base_geometry = resample_geometry(
        adapter.parse_geometry(
            local / case["geometry_file"],
            diameter_m=case["diameter_m"],
            blades=case["blades"],
            airfoil=case["solver"]["airfoil"],
        ),
        station_count,
    )
    config = case["solver"]
    results = {}
    for airfoil in sorted(SYNTHETIC_POLAR_PARAMETERS):
        geometry = _geometry_with_airfoil(base_geometry, airfoil)

        def factory(velocity, density):
            return BEMTSolver(
                axial_velocity_m_s=velocity,
                air_density=density,
                air_viscosity=case["environment"]["air_viscosity_pa_s"],
                max_iterations=config["max_iterations"],
                tolerance=config["tolerance"],
                relaxation_factor=config["relaxation_factor"],
                low_re_strategy=config["low_re_strategy"],
            )

        predictions = evaluate_series(
            factory,
            geometry,
            series,
            density_kg_m3=case["environment"]["air_density_kg_m3"],
        )
        results[airfoil] = {
            "synthetic_seed_parameters": SYNTHETIC_POLAR_PARAMETERS[airfoil],
            "comparison": compare_grouped(series, predictions),
        }
    output = GENERATED_ROOT / case["case_id"]
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "airfoil-study.json"
    payload = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim": (
            "Sensitivity to Nova synthetic polar families; not airfoil identification, "
            "calibration, or evidence that any family represents the APC blade."
        ),
        "case_id": case["case_id"],
        "station_count": station_count,
        "fixed_geometry": "UIUC r/R, c/R and beta; only the synthetic polar family changes",
        "airfoils": results,
    }
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    figure, axes = plt.subplots(1, 3, figsize=(11, 4), constrained_layout=True)
    names = list(results)
    for axis, quantity, title in zip(
        axes,
        ("ct", "cp", "eta"),
        ("CT mean absolute error", "CP mean absolute error", "Efficiency MAE"),
    ):
        values = [results[name]["comparison"]["metrics"][quantity]["mae"] for name in names]
        axis.bar(names, values, color="#376996")
        axis.set_title(title)
        axis.set_ylabel("MAE")
        if quantity == "eta":
            axis.set_yscale("log")
            axis.set_ylabel("MAE (log scale)")
        axis.tick_params(axis="x", rotation=35)
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle("Synthetic polar sensitivity — diagnostic only")
    figure.savefig(
        output / "airfoil-study.png",
        dpi=180,
        metadata={"Software": "Nova Propellers"},
    )
    plt.close(figure)
    report = [
        f"# Synthetic-airfoil sensitivity: {case['case_id']}",
        "",
        "> Diagnostic only. None of these families is asserted to be the APC section.",
        "",
        "| synthetic family | converged | CT MAE | CP MAE | eta MAE | CT MAPE |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for airfoil, item in results.items():
        comparison = item["comparison"]
        report.append(
            f"| {airfoil} | {comparison['successful_points']}/"
            f"{comparison['experimental_points']} | {comparison['metrics']['ct']['mae']:.6g} "
            f"| {comparison['metrics']['cp']['mae']:.6g} "
            f"| {comparison['metrics']['eta']['mae']:.6g} "
            f"| {comparison['metrics']['ct']['mape']:.3f}% |"
        )
    report += [
        "",
        "![Synthetic polar sensitivity](airfoil-study.png)",
        "",
        "A lower error in this table is not a selection criterion. Any model change requires "
        "independent section evidence and evaluation on a held-out propeller.",
    ]
    (output / "airfoil-study.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=ROOT / "cases" / "uiuc_apce_10x5.json")
    parser.add_argument("--stations", type=int, default=36)
    arguments = parser.parse_args()
    print(run(arguments.case, arguments.stations))


if __name__ == "__main__":
    main()
