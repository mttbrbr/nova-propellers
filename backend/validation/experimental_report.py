"""Run a declared experimental case and create local JSON/Markdown/SVG evidence."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from inverse_design import BEMTSolver
from validation.experimental import ExperimentalSeries, compare_grouped, evaluate_series
from validation.uiuc import UIUCVolume1Adapter, acquire

ROOT = Path(__file__).parent
REFERENCE_ROOT = ROOT / "reference_data"
GENERATED_ROOT = ROOT / "generated"


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
            cwd=ROOT.parents[1],
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_case(path: Path) -> dict:
    case = json.loads(path.read_text(encoding="utf-8"))
    for required in ("case_id", "dataset", "propeller_id", "sources", "coefficient_definitions"):
        if required not in case:
            raise ValueError(f"Case metadata missing required field: {required}")
    for source_name, source in case["sources"].items():
        if "license" not in source:
            raise ValueError(f"Provenance source {source_name!r} has no license status")
    return case


def _svg(series, predictions, field: str, label: str) -> str:
    pairs = [
        (e.rpm, e.advance_ratio, getattr(e, field), getattr(p, field))
        for e, p in zip(series.points, predictions)
    ]
    all_y = [
        value
        for _, _, experimental, predicted in pairs
        for value in (experimental, predicted)
        if value is not None
    ]
    min_x = min(x for _, x, _, _ in pairs)
    max_x = max(x for _, x, _, _ in pairs)
    min_y, max_y = min(all_y), max(all_y)
    def xscale(value):
        return 70 + (value - min_x) / max(max_x - min_x, 1e-12) * 650

    def yscale(value):
        return 350 - (value - min_y) / max(max_y - min_y, 1e-12) * 290
    colors = ("#1565c0", "#00897b", "#7b1fa2", "#ef6c00", "#2e7d32", "#c62828", "#455a64")
    curves = []
    legends = []
    for index, rpm in enumerate(sorted({rpm for rpm, _, _, _ in pairs})):
        color = colors[index % len(colors)]
        group = [(x, exp, pred) for item_rpm, x, exp, pred in pairs if item_rpm == rpm]
        experimental = " ".join(
            f"{xscale(x):.1f},{yscale(value):.1f}" for x, value, _ in group
        )
        predicted = " ".join(
            f"{xscale(x):.1f},{yscale(value):.1f}"
            for x, _, value in group
            if value is not None
        )
        curves.append(
            f'<polyline points="{experimental}" fill="none" stroke="{color}" '
            f'stroke-width="2"/><polyline points="{predicted}" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-dasharray="7 4"/>'
        )
        legends.append(
            f'<text x="{90 + index * 95}" y="52" fill="{color}" '
            f'font-family="sans-serif" font-size="11">{rpm:g} rpm</text>'
        )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="420" viewBox="0 0 800 420">
<rect width="800" height="420" fill="white"/><text x="400" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">{html.escape(label)} vs J</text>
<line x1="70" y1="350" x2="720" y2="350" stroke="black"/><line x1="70" y1="60" x2="70" y2="350" stroke="black"/>
{''.join(curves)}{''.join(legends)}
<text x="395" y="395" text-anchor="middle" font-family="sans-serif">advance ratio J</text><text x="15" y="205" font-family="sans-serif" transform="rotate(-90 15 205)">{html.escape(label)}</text>
<text x="570" y="385" font-family="sans-serif" font-size="11">solid: experiment; dashed: Nova</text>
<text x="70" y="370" font-family="sans-serif" font-size="11">{min_x:.3g}</text><text x="700" y="370" font-family="sans-serif" font-size="11">{max_x:.3g}</text>
<text x="30" y="350" font-family="sans-serif" font-size="11">{min_y:.3g}</text><text x="30" y="65" font-family="sans-serif" font-size="11">{max_y:.3g}</text></svg>'''


def _png(series, predictions, field: str, label: str, destination: Path) -> None:
    figure, axis = plt.subplots(figsize=(9, 5.4), constrained_layout=True)
    rpms = sorted({point.rpm for point in series.points})
    color_map = plt.get_cmap("tab10")
    for index, rpm in enumerate(rpms):
        pairs = [
            (experimental, prediction)
            for experimental, prediction in zip(series.points, predictions)
            if experimental.rpm == rpm
        ]
        color = color_map(index % 10)
        axis.plot(
            [item.advance_ratio for item, _ in pairs],
            [getattr(item, field) for item, _ in pairs],
            color=color,
            marker="o",
            markersize=3,
            linewidth=1.5,
            label=f"UIUC {rpm:g} rpm",
        )
        converged = [pair for pair in pairs if pair[1].converged]
        axis.plot(
            [item.advance_ratio for item, _ in converged],
            [getattr(prediction, field) for _, prediction in converged],
            color=color,
            linestyle="--",
            linewidth=1.5,
            label=f"Nova {rpm:g} rpm",
        )
    axis.set(title=f"{label} vs advance ratio", xlabel="Advance ratio J", ylabel=label)
    axis.grid(True, alpha=0.25)
    axis.legend(ncols=2, fontsize=7)
    figure.savefig(destination, dpi=180, metadata={"Software": "Nova Propellers"})
    plt.close(figure)


def run(case_path: Path, output_root: Path = GENERATED_ROOT) -> Path:
    case = load_case(case_path)
    local = REFERENCE_ROOT / "uiuc" / case["case_id"]
    adapter = UIUCVolume1Adapter()
    parsed = [
        adapter.parse_dynamic(
            local / item["file"],
            rpm=item["rpm"],
            provenance={
                "case_id": case["case_id"],
                "propeller_id": case["propeller_id"],
                **case["sources"],
            },
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
    geometry = adapter.parse_geometry(local / case["geometry_file"], diameter_m=case["diameter_m"], blades=case["blades"], airfoil=case["solver"]["airfoil"])
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
    predictions = evaluate_series(factory, geometry, series, density_kg_m3=case["environment"]["air_density_kg_m3"])
    comparison = compare_grouped(series, predictions)
    output = output_root / case["case_id"]
    output.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": "1.0", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "nova_git_commit": _git_commit(), "case": case, "geometry": geometry.to_dict(), "comparison": comparison}
    (output / "results.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for field, label in (("thrust_coefficient", "CT"), ("power_coefficient", "CP"), ("efficiency", "eta")):
        (output / f"{label.lower()}.svg").write_text(_svg(series, predictions, field, label), encoding="utf-8")
        _png(series, predictions, field, label, output / f"{label.lower()}.png")
    lines = [f"# Validation report: {case['case_id']}", "", "> Local generated artifact: redistribution is not assumed because it derives from third-party measurements.", "", f"- Propeller: {case['propeller_id']}", f"- Dataset: {case['dataset']}", f"- Solver: {config['id']} (no calibration performed)", f"- Points: {comparison['successful_points']}/{comparison['experimental_points']} successful; {comparison['failed_points']} failed", f"- Git commit: `{record['nova_git_commit'] or 'unavailable'}`", "", "## Metrics", "", "| quantity | MAE | RMSE | MAPE | near-zero exclusions |", "| --- | ---: | ---: | ---: | ---: |"]
    for key in ("ct", "cp", "eta"):
        metric = comparison["metrics"][key]
        lines.append(f"| {key.upper()} | {metric['mae']:.6g} | {metric['rmse']:.6g} | {metric['mape']:.3g}% | {metric['relative_excluded_near_zero']} |" if metric else f"| {key.upper()} | n/a | n/a | n/a | n/a |")
    lines += ["", "## Breakdown by RPM", "", "| RPM | successful | CT MAE | CP MAE | eta MAE |", "| ---: | ---: | ---: | ---: | ---: |"]
    for rpm, group in comparison["by_rpm"].items():
        lines.append(
            f"| {rpm} | {group['successful_points']}/{group['experimental_points']} "
            f"| {group['metrics']['ct']['mae']:.6g} | {group['metrics']['cp']['mae']:.6g} "
            f"| {group['metrics']['eta']['mae']:.6g} |"
        )
    failed = [item for item in comparison["predictions"] if not item["converged"]]
    if failed:
        lines += [
            "",
            "## Solver failures",
            "",
            "| J | RPM | iterations | residual | termination | error |",
            "| ---: | ---: | ---: | ---: | --- | --- |",
        ]
        for item in failed:
            lines.append(
                f"| {item['advance_ratio']:.5g} | {item['rpm']:.5g} "
                f"| {item['iterations'] if item['iterations'] is not None else 'n/a'} "
                f"| {item['residual'] if item['residual'] is not None else 'n/a'} "
                f"| {item['termination_reason'] or 'n/a'} | {item['error'] or ''} |"
            )
    lines += ["", "## Plots", "", "![CT](ct.png)", "![CP](cp.png)", "![eta](eta.png)", "", "## Provenance and limitations", "", case["solver"]["airfoil_note"], "UIUC geometry is an approximate digitization. Source licenses are unspecified and redistribution is not assumed. Raw inputs and this report remain local-only by policy."]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=ROOT / "cases" / "uiuc_apce_10x5.json")
    parser.add_argument("--acquire", action="store_true", help="download only the two declared official UIUC files")
    args = parser.parse_args()
    case = load_case(args.case)
    local = REFERENCE_ROOT / "uiuc" / case["case_id"]
    if args.acquire:
        downloads = [(item["url"], item["file"]) for item in case["measurement_series"]]
        downloads.append((case["sources"]["geometry"]["file_url"], case["geometry_file"]))
        for source, filename in downloads:
            if (local / filename).exists():
                print(json.dumps({"path": str(local / filename), "status": "already present"}))
                continue
            print(json.dumps(acquire(source, local / filename)))
        return
    print(run(args.case))


if __name__ == "__main__":
    main()
