from abc import ABC, abstractmethod
from typing import TypedDict

from ..geometry import GeometryData


class SolverResult(TypedDict):
    thrust: float
    torque: float
    efficiency: float


class BaseSolver(ABC):
    """Stable aerodynamic interface consumed by the inverse optimizer."""

    @abstractmethod
    def evaluate(self, geometry_data: GeometryData, rpm: float) -> SolverResult:
        raise NotImplementedError

    def evaluate_detailed(self, geometry_data: GeometryData, rpm: float) -> dict:
        from ..curves import reconstruct_radial_curves

        performance = self.evaluate(geometry_data, rpm)
        return {
            "performance": performance,
            "curves": reconstruct_radial_curves(geometry_data, rpm, performance),
            "curve_source": "reconstructed",
            "convergence": None,
        }
