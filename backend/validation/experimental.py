"""Solver-independent experimental-validation domain models and metrics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Protocol

import numpy as np

from inverse_design.geometry import GeometryData
from inverse_design.solvers.base import BaseSolver


@dataclass(frozen=True)
class ExperimentalPoint:
    advance_ratio: float
    thrust_coefficient: float
    power_coefficient: float
    efficiency: float
    rpm: float
    reynolds_75: float | None = None


@dataclass(frozen=True)
class ExperimentalSeries:
    dataset: str
    case_id: str
    propeller_id: str
    points: tuple[ExperimentalPoint, ...]
    provenance: dict


class DatasetAdapter(Protocol):
    def parse_dynamic(self, path, *, rpm: float, provenance: dict) -> ExperimentalSeries: ...


@dataclass(frozen=True)
class Prediction:
    advance_ratio: float
    rpm: float
    thrust_coefficient: float | None
    power_coefficient: float | None
    efficiency: float | None
    converged: bool
    error: str | None = None
    iterations: int | None = None
    residual: float | None = None
    termination_reason: str | None = None


def evaluate_series(
    solver_factory,
    geometry: GeometryData,
    series: ExperimentalSeries,
    *,
    density_kg_m3: float = 1.225,
) -> list[Prediction]:
    """Evaluate through the public solver API at the experimental J/RPM points."""
    predictions = []
    for point in series.points:
        n = point.rpm / 60.0
        velocity = point.advance_ratio * n * geometry.diameter_m
        try:
            solver: BaseSolver = solver_factory(velocity, density_kg_m3)
            result = solver.evaluate_detailed(geometry, point.rpm)
            coefficients = result.get("coefficients")
            if coefficients is None:
                performance = result["performance"]
                ct = performance["thrust"] / (density_kg_m3 * n**2 * geometry.diameter_m**4)
                power = performance["torque"] * 2 * math.pi * n
                cp = power / (density_kg_m3 * n**3 * geometry.diameter_m**5)
            else:
                ct, cp = coefficients["thrust"], coefficients["power"]
            eta = point.advance_ratio * ct / cp if abs(cp) > 1e-12 else None
            convergence = result.get("convergence")
            converged = convergence is None or bool(convergence.get("converged"))
            predictions.append(
                Prediction(
                    point.advance_ratio,
                    point.rpm,
                    ct,
                    cp,
                    eta,
                    converged,
                    iterations=convergence.get("iterations") if convergence else None,
                    residual=convergence.get("residual") if convergence else None,
                    termination_reason=(
                        convergence.get("termination_reason") if convergence else None
                    ),
                )
            )
        except Exception as exc:  # retain every failed operating point in the report
            predictions.append(Prediction(point.advance_ratio, point.rpm, None, None, None, False, str(exc)))
    return predictions


def metric_summary(reference: list[float], predicted: list[float], *, zero_floor: float = 1e-3) -> dict:
    """Metrics with percentage errors excluded when |reference| < zero_floor."""
    ref = np.asarray(reference, dtype=float)
    pred = np.asarray(predicted, dtype=float)
    absolute = np.abs(pred - ref)
    signed = pred - ref
    valid_relative = np.abs(ref) >= zero_floor
    relative = np.abs(signed[valid_relative] / ref[valid_relative])
    return {
        "count": int(ref.size),
        "mae": float(np.mean(absolute)),
        "rmse": float(np.sqrt(np.mean(signed**2))),
        "mean_relative_error": float(np.mean(signed[valid_relative] / ref[valid_relative])) if np.any(valid_relative) else None,
        "mape": float(100 * np.mean(relative)) if np.any(valid_relative) else None,
        "maximum_absolute_error": float(np.max(absolute)),
        "maximum_relative_error": float(np.max(relative)) if np.any(valid_relative) else None,
        "relative_count": int(np.sum(valid_relative)),
        "relative_excluded_near_zero": int(np.sum(~valid_relative)),
        "relative_zero_floor": zero_floor,
    }


def compare(series: ExperimentalSeries, predictions: list[Prediction]) -> dict:
    successful = [(e, p) for e, p in zip(series.points, predictions) if p.converged and p.thrust_coefficient is not None]
    metrics = {}
    fields = {
        "ct": ("thrust_coefficient", "thrust_coefficient"),
        "cp": ("power_coefficient", "power_coefficient"),
        "eta": ("efficiency", "efficiency"),
    }
    for name, (experimental_field, predicted_field) in fields.items():
        values = [(getattr(e, experimental_field), getattr(p, predicted_field)) for e, p in successful]
        values = [(a, b) for a, b in values if b is not None and math.isfinite(a) and math.isfinite(b)]
        metrics[name] = metric_summary([a for a, _ in values], [b for _, b in values]) if values else None
    return {
        "experimental_points": len(series.points),
        "successful_points": len(successful),
        "failed_points": len(series.points) - len(successful),
        "metrics": metrics,
        "predictions": [asdict(value) for value in predictions],
    }


def compare_grouped(series: ExperimentalSeries, predictions: list[Prediction]) -> dict:
    """Return overall evidence plus independently inspectable RPM groups."""
    result = compare(series, predictions)
    result["by_rpm"] = {}
    for rpm in sorted({point.rpm for point in series.points}):
        indices = [index for index, point in enumerate(series.points) if point.rpm == rpm]
        subset = ExperimentalSeries(
            series.dataset,
            series.case_id,
            series.propeller_id,
            tuple(series.points[index] for index in indices),
            series.provenance,
        )
        result["by_rpm"][str(rpm)] = compare(
            subset, [predictions[index] for index in indices]
        )
    return result


def resample_geometry(geometry: GeometryData, station_count: int) -> GeometryData:
    """Resample measured radial geometry without changing its physical span."""
    if station_count < 4:
        raise ValueError("A convergence geometry needs at least four stations")
    radius = np.linspace(geometry.radius_m[0], geometry.radius_m[-1], station_count)
    return GeometryData(
        radius_m=radius,
        chord_m=np.interp(radius, geometry.radius_m, geometry.chord_m),
        twist_rad=np.interp(radius, geometry.radius_m, geometry.twist_rad),
        diameter_m=geometry.diameter_m,
        blades=geometry.blades,
        airfoil=geometry.airfoil,
        propeller_type=geometry.propeller_type,
    )
