import numpy as np

from geometry_engine import PropellerSpec, _evaluate_bemt_arrays

from ..geometry import GeometryData
from .base import BaseSolver, SolverResult


class BEMTSolver(BaseSolver):
    """Adapter around Nova's iterative blade-element/momentum implementation."""

    def __init__(self, reference_thrust_n: float = 10.0) -> None:
        self.reference_thrust_n = reference_thrust_n

    def evaluate(self, geometry_data: GeometryData, rpm: float) -> SolverResult:
        return self.evaluate_detailed(geometry_data, rpm)["performance"]

    def evaluate_detailed(self, geometry_data: GeometryData, rpm: float) -> dict:
        spec = PropellerSpec(
            thrust_target=self.reference_thrust_n,
            rpm=rpm,
            diameter=geometry_data.diameter_m,
            blades=geometry_data.blades,
            airfoil=geometry_data.airfoil,
            design_mode="preliminary",
        )
        result = _evaluate_bemt_arrays(
            spec, geometry_data.radius_m, geometry_data.chord_m, geometry_data.twist_rad
        )
        omega = 2.0 * np.pi * rpm / 60.0
        useful_power = max(result["thrust"], 0.0) * max(
            np.sqrt(max(result["thrust"], 0.0) / (2 * 1.225 * np.pi * (geometry_data.diameter_m / 2) ** 2)),
            0.0,
        )
        shaft_power = max(result["torque"] * omega, 1e-9)
        performance = {
            "thrust": float(result["thrust"]),
            "torque": float(result["torque"]),
            "efficiency": float(np.clip(useful_power / shaft_power, 0.0, 1.0)),
        }
        dr = np.gradient(geometry_data.radius_m)
        d_torque = result["d_power"] / max(omega, 1e-9)
        curves = [
            {
                "r_over_R": round(float(fraction), 5),
                "radius_m": round(float(geometry_data.radius_m[index]), 7),
                "chord_mm": round(float(geometry_data.chord_m[index] * 1000), 4),
                "twist_deg": round(float(np.degrees(geometry_data.twist_rad[index])), 4),
                "alpha_deg": round(float(result["alpha_deg"][index]), 4),
                "cl": round(float(result["cl"][index]), 5),
                "cd": round(float(result["cd"][index]), 6),
                "reynolds": round(float(result["reynolds"][index]), 1),
                "circulation": round(float(result["circulation"][index]), 7),
                "d_thrust_n": round(float(result["d_thrust"][index]), 7),
                "d_torque_nm": round(float(d_torque[index]), 8),
                "d_power_w": round(float(result["d_power"][index]), 6),
                "source": "native",
                "dr_m": round(float(dr[index]), 7),
            }
            for index, fraction in enumerate(geometry_data.radial_fraction)
        ]
        return {"performance": performance, "curves": curves, "curve_source": "native"}
