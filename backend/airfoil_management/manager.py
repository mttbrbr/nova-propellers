from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import CubicSpline, splprep, splev


FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class AirfoilProfile:
    name: str
    coordinates: FloatArray

    def __post_init__(self) -> None:
        if self.coordinates.ndim != 2 or self.coordinates.shape[1] != 2:
            raise ValueError("Airfoil coordinates must have shape (n, 2)")
        if len(self.coordinates) < 8 or not np.all(np.isfinite(self.coordinates)):
            raise ValueError("Airfoil coordinates must contain at least eight finite points")


class AirfoilManager:
    """Import, normalize and blend UIUC/XFOIL airfoil coordinate files."""

    def __init__(self, normalized_point_count: int = 100) -> None:
        if normalized_point_count < 20:
            raise ValueError("normalized_point_count must be at least 20")
        self.normalized_point_count = normalized_point_count

    def read_dat(self, path: str | Path, normalize: bool = True) -> AirfoilProfile:
        path = Path(path)
        return self.parse_dat(path.read_text(encoding="utf-8", errors="ignore"), path.stem, normalize)

    def parse_dat(
        self,
        content: str,
        name: str = "Imported airfoil",
        normalize: bool = True,
    ) -> AirfoilProfile:
        coordinates: list[tuple[float, float]] = []
        for line in content.splitlines():
            fields = line.replace(",", " ").replace("D", "E").split()
            if len(fields) < 2:
                continue
            try:
                coordinates.append((float(fields[0]), float(fields[1])))
            except ValueError:
                continue
        if len(coordinates) < 8:
            raise ValueError(f"{name} does not contain a valid UIUC/XFOIL coordinate set")
        raw = np.asarray(coordinates, dtype=float)
        clean = self.normalize(raw) if normalize else _remove_consecutive_duplicates(raw)
        return AirfoilProfile(name, clean)

    def normalize(
        self,
        coordinates: FloatArray,
        point_count: int | None = None,
    ) -> FloatArray:
        """Return TE-upper → LE → TE-lower spline coordinates.

        Each side uses cosine-spaced spline parameters, concentrating samples
        around both the leading and trailing edges.
        """
        count = point_count or self.normalized_point_count
        if count < 20:
            raise ValueError("point_count must be at least 20")
        points = _canonicalize(coordinates)
        chord = float(np.max(points[:, 0]) - np.min(points[:, 0]))
        if chord <= 1e-10:
            raise ValueError("Airfoil chord is zero")
        points = points.copy()
        points[:, 0] = (points[:, 0] - np.min(points[:, 0])) / chord
        points[:, 1] /= chord

        distance = np.linalg.norm(np.diff(points, axis=0), axis=1)
        parameter = np.concatenate(([0.0], np.cumsum(distance)))
        parameter /= parameter[-1]
        degree = min(3, len(points) - 1)
        spline, fitted_parameter = splprep(
            [points[:, 0], points[:, 1]],
            u=parameter,
            s=0.0,
            k=degree,
            per=False,
        )
        leading_edge = int(np.argmin(points[:, 0]))
        leading_parameter = float(fitted_parameter[leading_edge])

        upper_count = count // 2
        lower_count = count - upper_count + 1
        upper_phase = np.linspace(0.0, np.pi, upper_count)
        lower_phase = np.linspace(0.0, np.pi, lower_count)
        upper_parameter = leading_parameter * (1.0 - np.cos(upper_phase)) / 2.0
        lower_parameter = leading_parameter + (1.0 - leading_parameter) * (
            1.0 - np.cos(lower_phase)
        ) / 2.0
        sample_parameter = np.concatenate((upper_parameter, lower_parameter[1:]))
        x, y = splev(sample_parameter, spline)
        normalized = np.column_stack((np.clip(x, 0.0, 1.0), y))
        normalized[0, 0] = 1.0
        normalized[upper_count - 1, 0] = 0.0
        normalized[-1, 0] = 1.0
        if len(normalized) != count:
            raise RuntimeError("Airfoil resampling produced an unexpected point count")
        return normalized

    def create_loft(
        self,
        profiles_by_radius: Mapping[float, AirfoilProfile | FloatArray],
    ) -> "AirfoilLoft":
        return AirfoilLoft(profiles_by_radius, self)

    def blend(
        self,
        profiles_by_radius: Mapping[float, AirfoilProfile | FloatArray],
        radial_fraction: float,
        method: str = "linear",
    ) -> FloatArray:
        return self.create_loft(profiles_by_radius).section(radial_fraction, method)


class AirfoilLoft:
    """Coordinate-consistent spanwise interpolation of normalized profiles."""

    def __init__(
        self,
        profiles_by_radius: Mapping[float, AirfoilProfile | FloatArray],
        manager: AirfoilManager | None = None,
    ) -> None:
        if len(profiles_by_radius) < 2:
            raise ValueError("At least two radial airfoil assignments are required")
        self.manager = manager or AirfoilManager()
        self.stations = np.asarray(sorted(float(value) for value in profiles_by_radius), dtype=float)
        if self.stations[0] < 0 or self.stations[-1] > 1 or np.any(np.diff(self.stations) <= 0):
            raise ValueError("Radial assignments must be unique and inside [0, 1]")
        normalized = []
        for station in self.stations:
            profile = profiles_by_radius[station]
            coordinates = profile.coordinates if isinstance(profile, AirfoilProfile) else np.asarray(profile)
            normalized.append(
                coordinates
                if len(coordinates) == self.manager.normalized_point_count
                else self.manager.normalize(coordinates)
            )
        self.coordinates = np.stack(normalized)
        if len({len(profile) for profile in self.coordinates}) != 1:
            raise ValueError("All normalized profiles must have the same point count")

    def section(self, radial_fraction: float, method: str = "linear") -> FloatArray:
        radial_fraction = float(radial_fraction)
        if radial_fraction < self.stations[0] or radial_fraction > self.stations[-1]:
            raise ValueError("Requested radius is outside the assigned profile span")
        if method == "spline":
            if len(self.stations) < 3:
                method = "linear"
            else:
                return CubicSpline(self.stations, self.coordinates, axis=0)(radial_fraction)
        if method != "linear":
            raise ValueError("method must be 'linear' or 'spline'")
        right = int(np.searchsorted(self.stations, radial_fraction, side="right"))
        if right == 0:
            return self.coordinates[0].copy()
        if right == len(self.stations):
            return self.coordinates[-1].copy()
        left = right - 1
        weight = (radial_fraction - self.stations[left]) / (
            self.stations[right] - self.stations[left]
        )
        return (1.0 - weight) * self.coordinates[left] + weight * self.coordinates[right]


def _remove_consecutive_duplicates(points: FloatArray) -> FloatArray:
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("Coordinates must have shape (n, 2)")
    finite = points[np.all(np.isfinite(points), axis=1)]
    if len(finite) < 2:
        return finite
    keep = np.concatenate(([True], np.linalg.norm(np.diff(finite, axis=0), axis=1) > 1e-10))
    return finite[keep]


def _canonicalize(coordinates: FloatArray) -> FloatArray:
    points = _remove_consecutive_duplicates(coordinates)
    if len(points) < 8:
        raise ValueError("Too few unique airfoil coordinates")
    leading_edge = int(np.argmin(points[:, 0]))
    if leading_edge in {0, len(points) - 1}:
        trailing_edge = int(np.argmax(points[:, 0]))
        points = np.vstack((points[trailing_edge:], points[1 : trailing_edge + 1]))
        points = _remove_consecutive_duplicates(points)
        leading_edge = int(np.argmin(points[:, 0]))
    if leading_edge in {0, len(points) - 1}:
        raise ValueError("Unable to identify separate upper and lower airfoil surfaces")
    upper_mean = float(np.mean(points[: leading_edge + 1, 1]))
    lower_mean = float(np.mean(points[leading_edge:, 1]))
    if upper_mean < lower_mean:
        points = points[::-1]
    return _remove_consecutive_duplicates(points)
