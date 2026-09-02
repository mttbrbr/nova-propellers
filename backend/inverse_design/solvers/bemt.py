import numpy as np

from geometry_engine import PropellerSpec, _evaluate_bemt_arrays

from ..geometry import GeometryData
from .base import BaseSolver, SolverResult


class BEMTSolver(BaseSolver):
    """Axial-flow blade-element/momentum solver."""

    def __init__(
        self,
        reference_thrust_n: float | None = None,
        *,
        axial_velocity_m_s: float = 0.0,
        air_density: float = 1.225,
        air_viscosity: float = 1.81e-5,
        max_iterations: int = 200,
        tolerance: float = 1e-5,
        relaxation_factor: float = 0.08,
        relaxation_strategy: str = "fixed",
        low_re_strategy: str = "clip",
        max_tangential_induction_ratio: float = 0.75,
    ) -> None:
        # Retained only for API compatibility. Analysis must not depend on a
        # requested thrust value.
        self.reference_thrust_n = reference_thrust_n
        self.axial_velocity = axial_velocity_m_s
        self.rho = air_density
        self.viscosity = air_viscosity
        self.max_iterations = max_iterations
        self.tolerance = tolerance
        self.relaxation_factor = relaxation_factor
        self.relaxation_strategy = relaxation_strategy
        self.low_re_strategy = low_re_strategy
        self.max_tangential_induction_ratio = max_tangential_induction_ratio

    def evaluate(self, geometry_data: GeometryData, rpm: float) -> SolverResult:
        return self.evaluate_detailed(geometry_data, rpm)["performance"]

    def evaluate_detailed(self, geometry_data: GeometryData, rpm: float) -> dict:
        spec = PropellerSpec(
            thrust_target=self.reference_thrust_n or 1.0,
            rpm=rpm,
            diameter=geometry_data.diameter_m,
            blades=geometry_data.blades,
            airfoil=geometry_data.airfoil,
            design_mode="preliminary",
        )
        result = _evaluate_bemt_arrays(
            spec,
            geometry_data.radius_m,
            geometry_data.chord_m,
            geometry_data.twist_rad,
            axial_velocity=self.axial_velocity,
            air_density=self.rho,
            air_viscosity=self.viscosity,
            max_iterations=self.max_iterations,
            tolerance=self.tolerance,
            relaxation_factor=self.relaxation_factor,
            relaxation_strategy=self.relaxation_strategy,
            low_re_strategy=self.low_re_strategy,
            max_tangential_induction_ratio=self.max_tangential_induction_ratio,
        )
        omega = 2.0 * np.pi * rpm / 60.0
        performance = {
            "thrust": float(result["thrust"]),
            "torque": float(result["torque"]),
            "efficiency": float(result["figure_of_merit"]),
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
        revolutions_per_second = rpm / 60.0
        diameter = geometry_data.diameter_m
        coefficients = {
            "thrust": result["thrust"] / max(self.rho * revolutions_per_second**2 * diameter**4, 1e-12),
            "power": result["power"] / max(self.rho * revolutions_per_second**3 * diameter**5, 1e-12),
            "torque": result["torque"] / max(self.rho * revolutions_per_second**2 * diameter**5, 1e-12),
        }
        return {
            "performance": performance,
            "curves": curves,
            "curve_source": "native",
            "coefficients": coefficients,
            "convergence": {
                "converged": result["converged"],
                "iterations": result["iterations"],
                "residual": result["residual"],
                "tolerance": result["tolerance"],
                "termination_reason": result["termination_reason"],
                "diagnostics": result["diagnostics"],
            },
        }
