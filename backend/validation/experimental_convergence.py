"""Measure radial-discretization sensitivity over an experimental corpus."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from inverse_design import BEMTSolver
from validation.experimental import (
    ExperimentalSeries,
    evaluate_series,
    metric_summary,
    resample_geometry,
)
from validation.experimental_report import GENERATED_ROOT, REFERENCE_ROOT, ROOT, load_case
from validation.uiuc import UIUCVolume1Adapter


def run(case_path: Path, station_counts: tuple[int, ...]) -> Path:
    case = load_case(case_path)
    if tuple(sorted(set(station_counts))) != station_counts:
        raise ValueError("Station counts must be unique and strictly increasing")
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
    source_geometry = adapter.parse_geometry(
        local / case["geometry_file"],
        diameter_m=case["diameter_m"],
        blades=case["blades"],
        airfoil=case["solver"]["airfoil"],
    )
    config = case["solver"]

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

    predictions = {}
    for count in station_counts:
        predictions[count] = evaluate_series(
            factory,
            resample_geometry(source_geometry, count),
            series,
            density_kg_m3=case["environment"]["air_density_kg_m3"],
        )
    reference = predictions[station_counts[-1]]
    summaries = []
    for count in station_counts:
        values = predictions[count]
        successful = [
            (candidate, finest)
            for candidate, finest in zip(values, reference)
            if candidate.converged and finest.converged
        ]
        coefficient_deltas = {}
        for field in ("thrust_coefficient", "power_coefficient", "efficiency"):
            pairs = [
                (getattr(finest, field), getattr(candidate, field))
                for candidate, finest in successful
                if getattr(candidate, field) is not None
                and getattr(finest, field) is not None
            ]
            coefficient_deltas[field] = (
                metric_summary(
                    [reference_value for reference_value, _ in pairs],
                    [candidate_value for _, candidate_value in pairs],
                )
                if pairs
                else None
            )
        summaries.append(
            {
                "station_count": count,
                "successful_pairs": len(successful),
                "failed_or_unpaired": len(series.points) - len(successful),
                "relative_to_station_count": station_counts[-1],
                "coefficient_deltas": coefficient_deltas,
            }
        )
    output = GENERATED_ROOT / case["case_id"]
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "convergence.json"
    destination.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "claim": "Numerical sensitivity only; the finest grid is not physical truth.",
                "case_id": case["case_id"],
                "operating_points": len(series.points),
                "station_counts": station_counts,
                "summaries": summaries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=ROOT / "cases" / "uiuc_apce_10x5.json")
    parser.add_argument("--stations", type=int, nargs="+", default=[18, 36, 72])
    arguments = parser.parse_args()
    print(run(arguments.case, tuple(arguments.stations)))


if __name__ == "__main__":
    main()
