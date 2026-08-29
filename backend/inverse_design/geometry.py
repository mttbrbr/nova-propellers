from __future__ import annotations

from dataclasses import dataclass
from math import comb
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class GeometryData:
    """Canonical blade geometry shared by all aerodynamic solvers."""

    radius_m: FloatArray
    chord_m: FloatArray
    twist_rad: FloatArray
    diameter_m: float
    blades: int
    airfoil: str = "NACA 4412"
    propeller_type: str = "traditional"

    def __post_init__(self) -> None:
        size = len(self.radius_m)
        if size < 4 or len(self.chord_m) != size or len(self.twist_rad) != size:
            raise ValueError("Geometry vectors must have the same length and at least four stations")
        if np.any(np.diff(self.radius_m) <= 0):
            raise ValueError("Radial stations must be strictly increasing")
        if np.any(self.chord_m <= 0) or self.diameter_m <= 0 or self.blades < 1:
            raise ValueError("Diameter, chord and blade count must be positive")

    @property
    def radial_fraction(self) -> FloatArray:
        return (self.radius_m - self.radius_m[0]) / (self.radius_m[-1] - self.radius_m[0])

    def to_dict(self) -> dict:
        return {
            "diameter_m": self.diameter_m,
            "blades": self.blades,
            "airfoil": self.airfoil,
            "propeller_type": self.propeller_type,
            "stations": [
                {
                    "r_over_R": float(fraction),
                    "radius_m": float(radius),
                    "chord_m": float(chord),
                    "twist_deg": float(np.degrees(twist)),
                }
                for fraction, radius, chord, twist in zip(
                    self.radial_fraction, self.radius_m, self.chord_m, self.twist_rad
                )
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GeometryData":
        stations = data.get("stations") or []
        if not stations:
            raise ValueError("Canonical geometry has no stations")
        return cls(
            radius_m=np.array([station["radius_m"] for station in stations], dtype=float),
            chord_m=np.array([station["chord_m"] for station in stations], dtype=float),
            twist_rad=np.radians([station["twist_deg"] for station in stations]),
            diameter_m=float(data["diameter_m"]),
            blades=int(data["blades"]),
            airfoil=data.get("airfoil", "NACA 4412"),
            propeller_type=data.get("propeller_type", "traditional"),
        )


@dataclass(frozen=True)
class BezierControlPoints:
    """The x coordinates are normalized radius; y stores chord [m] or twist [deg]."""

    chord: FloatArray
    twist: FloatArray

    def __post_init__(self) -> None:
        for name, points in (("chord", self.chord), ("twist", self.twist)):
            if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
                raise ValueError(f"{name} control points must have shape (n, 2)")
            if np.any(np.diff(points[:, 0]) <= 0) or points[0, 0] < 0 or points[-1, 0] > 1:
                raise ValueError(f"{name} control point abscissas must increase inside [0, 1]")


class GeometryParameterization(Protocol):
    @property
    def parameter_count(self) -> int: ...

    def encode(self, parameters: object) -> FloatArray: ...

    def decode(self, vector: FloatArray) -> object: ...

    def build(self, parameters: object) -> GeometryData: ...


class BezierBladeGeometry:
    """Maps editable Bézier ordinates to a canonical radial blade geometry."""

    def __init__(
        self,
        diameter_m: float,
        blades: int,
        airfoil: str = "NACA 4412",
        hub_radius_ratio: float = 0.14,
        station_count: int = 40,
    ) -> None:
        if not 0 < hub_radius_ratio < 1:
            raise ValueError("hub_radius_ratio must be inside (0, 1)")
        self.diameter_m = diameter_m
        self.blades = blades
        self.airfoil = airfoil
        self.hub_radius_ratio = hub_radius_ratio
        self.station_count = station_count
        self._chord_x: FloatArray | None = None
        self._twist_x: FloatArray | None = None

    @property
    def parameter_count(self) -> int:
        if self._chord_x is None or self._twist_x is None:
            raise RuntimeError("Call encode once to establish the control-point topology")
        return len(self._chord_x) + len(self._twist_x)

    def encode(self, parameters: object) -> FloatArray:
        if not isinstance(parameters, BezierControlPoints):
            raise TypeError("BezierBladeGeometry expects BezierControlPoints")
        self._chord_x = parameters.chord[:, 0].copy()
        self._twist_x = parameters.twist[:, 0].copy()
        return np.concatenate((parameters.chord[:, 1], parameters.twist[:, 1])).astype(float)

    def optimization_complexity(self, parameters: object) -> dict[str, int]:
        """Expose optimizer-relevant complexity without coupling the optimizer to Bézier types."""
        if not isinstance(parameters, BezierControlPoints):
            raise TypeError("BezierBladeGeometry expects BezierControlPoints")
        return {"chord": len(parameters.chord), "twist": len(parameters.twist)}

    def decode(self, vector: FloatArray) -> BezierControlPoints:
        if self._chord_x is None or self._twist_x is None:
            raise RuntimeError("Call encode before decode")
        split = len(self._chord_x)
        if len(vector) != split + len(self._twist_x):
            raise ValueError("Optimization vector has an unexpected size")
        return BezierControlPoints(
            chord=np.column_stack((self._chord_x, vector[:split])),
            twist=np.column_stack((self._twist_x, vector[split:])),
        )

    def build(self, parameters: object) -> GeometryData:
        if not isinstance(parameters, BezierControlPoints):
            raise TypeError("BezierBladeGeometry expects BezierControlPoints")
        fraction = np.linspace(0.0, 1.0, self.station_count)
        radius = self.diameter_m / 2.0
        hub_radius = radius * self.hub_radius_ratio
        return GeometryData(
            radius_m=hub_radius + fraction * (radius - hub_radius),
            chord_m=_sample_bezier_curve(parameters.chord, fraction),
            twist_rad=np.radians(_sample_bezier_curve(parameters.twist, fraction)),
            diameter_m=self.diameter_m,
            blades=self.blades,
            airfoil=self.airfoil,
        )


def _bezier_ordinates(control_values: FloatArray, parameter: FloatArray) -> FloatArray:
    degree = len(control_values) - 1
    return sum(
        comb(degree, index)
        * (1.0 - parameter) ** (degree - index)
        * parameter**index
        * value
        for index, value in enumerate(control_values)
    )


def _sample_bezier_curve(control_points: FloatArray, radial_fraction: FloatArray) -> FloatArray:
    """Evaluate parametric x(t), y(t), then resample y on the radial x grid."""
    parameter = np.linspace(0.0, 1.0, max(200, len(radial_fraction) * 5))
    curve_x = _bezier_ordinates(control_points[:, 0], parameter)
    curve_y = _bezier_ordinates(control_points[:, 1], parameter)
    if np.any(np.diff(curve_x) <= 0):
        raise ValueError("Bezier x(t) must be strictly increasing along the blade")
    return np.interp(radial_fraction, curve_x, curve_y)
