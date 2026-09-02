"""Compare declared low-Re polar treatments without selecting or tuning one."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from inverse_design import BEMTSolver
from validation.experimental import (
    ExperimentalSeries,
    compare_grouped,
    evaluate_series,
    resample_geometry,
)
from validation.experimental_report import GENERATED_ROOT, REFERENCE_ROOT, ROOT, load_case
from validation.uiuc import UIUCVolume1Adapter

STRATEGIES = ("clip", "linear_extrapolation", "smooth_transition")


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
    geometry = resample_geometry(
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
    for strategy in STRATEGIES:

        def factory(velocity, density):
            return BEMTSolver(
                axial_velocity_m_s=velocity,
                air_density=density,
                air_viscosity=case["environment"]["air_viscosity_pa_s"],
                max_iterations=config["max_iterations"],
                tolerance=config["tolerance"],
                relaxation_factor=config["relaxation_factor"],
                low_re_strategy=strategy,
            )

        predictions = evaluate_series(
            factory,
            geometry,
            series,
            density_kg_m3=case["environment"]["air_density_kg_m3"],
        )
        results[strategy] = compare_grouped(series, predictions)
    output = GENERATED_ROOT / case["case_id"]
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "polar-study.json"
    destination.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "claim": (
                    "Controlled sensitivity study, not calibration. No strategy is selected "
                    "from agreement with this benchmark alone."
                ),
                "case_id": case["case_id"],
                "station_count": station_count,
                "strategies": results,
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
    parser.add_argument("--stations", type=int, default=36)
    arguments = parser.parse_args()
    print(run(arguments.case, arguments.stations))


if __name__ == "__main__":
    main()
