import numpy as np

from ..geometry import GeometryData
from .base import BaseSolver, SolverResult


class ActuatorDiskSolver(BaseSolver):
    """Ideal hover momentum model configured with an operating thrust."""

    def __init__(self, thrust_n: float, air_density: float = 1.225) -> None:
        if thrust_n <= 0:
            raise ValueError("thrust_n must be positive")
        self.thrust_n = thrust_n
        self.rho = air_density

    def evaluate(self, geometry_data: GeometryData, rpm: float) -> SolverResult:
        area = np.pi * (geometry_data.diameter_m / 2.0) ** 2
        induced_velocity = np.sqrt(self.thrust_n / (2.0 * self.rho * area))
        ideal_power = self.thrust_n * induced_velocity
        omega = 2.0 * np.pi * rpm / 60.0
        return {
            "thrust": float(self.thrust_n),
            "torque": float(ideal_power / max(omega, 1e-9)),
            "efficiency": 1.0,
        }
