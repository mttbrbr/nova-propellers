"""Generate local radial diagnostics for representative experimental points."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from inverse_design import BEMTSolver
from polar_database import ALPHA_GRID, REYNOLDS_GRID
from validation.experimental import resample_geometry
from validation.experimental_report import GENERATED_ROOT, REFERENCE_ROOT, ROOT, load_case
from validation.uiuc import UIUCVolume1Adapter

TARGET_ADVANCE_RATIOS = (0.15, 0.35, 0.55, 0.67)
RADIAL_ZONES = ((0.15, 0.40, "root"), (0.40, 0.75, "mid"), (0.75, 1.001, "tip"))


def _available_points(case: dict, local: Path, adapter: UIUCVolume1Adapter) -> list[tuple]:
    available = []
    for item in case["measurement_series"]:
        series = adapter.parse_dynamic(
            local / item["file"],
            rpm=item["rpm"],
            provenance={"case_id": case["case_id"], "propeller_id": case["propeller_id"]},
        )
        available.extend(
            (point.advance_ratio, point.rpm, point.thrust_coefficient, point.power_coefficient)
            for point in series.points
        )
    return available


def _select_representative_points(available: list[tuple]) -> list[tuple]:
    selected = []
    remaining = list(available)
    for target in TARGET_ADVANCE_RATIOS:
        point = min(remaining, key=lambda item: (abs(item[0] - target), abs(item[1] - 5000)))
        selected.append(point)
        remaining.remove(point)
    return selected


def _zone_contributions(stations: list[dict]) -> dict:
    total_thrust = sum(row["d_thrust_n"] for row in stations)
    total_power = sum(row["d_power_w"] for row in stations)
    thrust_scale = sum(abs(row["d_thrust_n"]) for row in stations)
    power_scale = sum(abs(row["d_power_w"]) for row in stations)
    thrust_fraction_meaningful = abs(total_thrust) >= 0.01 * max(thrust_scale, 1e-12)
    power_fraction_meaningful = abs(total_power) >= 0.01 * max(power_scale, 1e-12)
    zones = {}
    for lower, upper, name in RADIAL_ZONES:
        rows = [row for row in stations if lower <= row["radius_over_tip_radius"] < upper]
        thrust = sum(row["d_thrust_n"] for row in rows)
        power = sum(row["d_power_w"] for row in rows)
        zones[name] = {
            "range_r_over_R": [lower, min(upper, 1.0)],
            "thrust_n": thrust,
            "thrust_fraction": thrust / total_thrust if thrust_fraction_meaningful else None,
            "power_w": power,
            "power_fraction": power / total_power if power_fraction_meaningful else None,
        }
    return zones


def _plot(record: dict, destination: Path) -> None:
    stations = record["stations"]
    radius = [row["radius_over_tip_radius"] for row in stations]
    figure, axes = plt.subplots(3, 2, figsize=(10, 11), constrained_layout=True)
    panels = (
        ("alpha_deg", "Angle of attack", "α [deg]"),
        ("reynolds", "Section Reynolds number", "Re"),
        ("cl", "Lift coefficient", "CL"),
        ("cd", "Drag coefficient", "CD"),
        ("d_thrust_n", "Radial thrust contribution", "dT [N]"),
        ("d_power_w", "Radial power contribution", "dP [W]"),
    )
    for axis, (field, title, ylabel) in zip(axes.flat, panels):
        axis.plot(radius, [row[field] for row in stations], marker="o", markersize=2)
        axis.set(title=title, xlabel="r/R", ylabel=ylabel)
        axis.grid(True, alpha=0.25)
        axis.axvline(0.4, color="grey", linewidth=0.8, linestyle=":")
        axis.axvline(0.75, color="grey", linewidth=0.8, linestyle=":")
    figure.suptitle(
        f"Radial diagnostics — J={record['advance_ratio']:.3f}, {record['rpm']:.0f} rpm"
    )
    figure.savefig(destination, dpi=180, metadata={"Software": "Nova Propellers"})
    plt.close(figure)


def run(case_path: Path, station_count: int = 36) -> Path:
    case = load_case(case_path)
    local = REFERENCE_ROOT / "uiuc" / case["case_id"]
    adapter = UIUCVolume1Adapter()
    geometry = resample_geometry(
        adapter.parse_geometry(
            local / case["geometry_file"],
            diameter_m=case["diameter_m"],
            blades=case["blades"],
            airfoil=case["solver"]["airfoil"],
        ),
        station_count,
    )
    points = _select_representative_points(_available_points(case, local, adapter))
    config = case["solver"]
    records = []
    output = GENERATED_ROOT / case["case_id"] / "radial"
    output.mkdir(parents=True, exist_ok=True)
    for advance_ratio, rpm, experimental_ct, experimental_cp in points:
        n = rpm / 60.0
        velocity = advance_ratio * n * geometry.diameter_m
        solver = BEMTSolver(
            axial_velocity_m_s=velocity,
            air_density=case["environment"]["air_density_kg_m3"],
            air_viscosity=case["environment"]["air_viscosity_pa_s"],
            max_iterations=config["max_iterations"],
            tolerance=config["tolerance"],
            relaxation_factor=config["relaxation_factor"],
            low_re_strategy=config["low_re_strategy"],
        )
        result = solver.evaluate_detailed(geometry, rpm)
        stations = result["curves"]
        alpha_outside = sum(
            not ALPHA_GRID[0] <= row["alpha_deg"] <= ALPHA_GRID[-1] for row in stations
        )
        reynolds_outside = sum(
            not REYNOLDS_GRID[0] <= row["reynolds"] <= REYNOLDS_GRID[-1]
            for row in stations
        )
        predicted_ct = result["coefficients"]["thrust"]
        predicted_cp = result["coefficients"]["power"]
        record = {
            "advance_ratio": advance_ratio,
            "rpm": rpm,
            "experimental": {"ct": experimental_ct, "cp": experimental_cp},
            "predicted": {
                "ct": predicted_ct,
                "cp": predicted_cp,
                "eta": advance_ratio * predicted_ct / predicted_cp
                if abs(predicted_cp) > 1e-12
                else None,
            },
            "convergence": result["convergence"],
            "polar_domain": {
                "alpha_range_deg": [float(ALPHA_GRID[0]), float(ALPHA_GRID[-1])],
                "reynolds_range": [float(REYNOLDS_GRID[0]), float(REYNOLDS_GRID[-1])],
                "stations_outside_alpha": alpha_outside,
                "stations_outside_reynolds": reynolds_outside,
                "total_stations": len(stations),
            },
            "radial_zones": _zone_contributions(stations),
            "stations": stations,
        }
        records.append(record)
        _plot(record, output / f"j-{advance_ratio:.3f}-rpm-{rpm:.0f}.png")
    destination = output / "radial-diagnostics.json"
    destination.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "case_id": case["case_id"],
                "station_count": station_count,
                "selection_targets_J": TARGET_ADVANCE_RATIOS,
                "note": (
                    "Diagnostics use UIUC planform/twist and Nova's declared synthetic polar; "
                    "out-of-domain counts identify model exposure, not experimental error cause."
                ),
                "operating_points": records,
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report_lines = [
        f"# Radial diagnostics: {case['case_id']}",
        "",
        "> Local-only diagnostic derived from UIUC reference data. Not calibration.",
        "",
        "| J | RPM | CT experimental | CT Nova | α range | stations outside α | stations outside Re |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for record in records:
        alpha_values = [row["alpha_deg"] for row in record["stations"]]
        domain = record["polar_domain"]
        report_lines.append(
            f"| {record['advance_ratio']:.3f} | {record['rpm']:.0f} "
            f"| {record['experimental']['ct']:.5g} | {record['predicted']['ct']:.5g} "
            f"| {min(alpha_values):.2f}…{max(alpha_values):.2f} "
            f"| {domain['stations_outside_alpha']}/{domain['total_stations']} "
            f"| {domain['stations_outside_reynolds']}/{domain['total_stations']} |"
        )
        report_lines += [
            "",
            f"![Radial diagnostics J={record['advance_ratio']:.3f}]"
            f"(j-{record['advance_ratio']:.3f}-rpm-{record['rpm']:.0f}.png)",
        ]
    report_lines += [
        "",
        "Near zero total thrust, signed regional fractions are omitted when cancellation "
        "makes their normalization misleading. Absolute station loads remain in JSON.",
    ]
    (output / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=ROOT / "cases" / "uiuc_apce_10x5.json")
    parser.add_argument("--stations", type=int, default=36)
    arguments = parser.parse_args()
    print(run(arguments.case, arguments.stations))


if __name__ == "__main__":
    main()
