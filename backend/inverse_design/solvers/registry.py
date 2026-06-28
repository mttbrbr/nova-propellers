from dataclasses import dataclass
from typing import Callable

from .actuator_disk import ActuatorDiskSolver
from .base import BaseSolver
from .bem import BoundaryElementSolver
from .bemt import BEMTSolver
from .llt import LLTSolver
from .vlm import VLMSolver


@dataclass(frozen=True)
class MethodDescriptor:
    id: str
    name: str
    fidelity: str
    suitable_for: tuple[str, ...]
    description: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "fidelity": self.fidelity,
            "suitable_for": self.suitable_for,
            "description": self.description,
        }


METHODS = {
    "actuator_disk": MethodDescriptor(
        "actuator_disk", "Actuator disk", "ideal",
        ("traditional", "toroidal"),
        "Ideal momentum-theory reference using the requested operating thrust.",
    ),
    "bemt": MethodDescriptor(
        "bemt", "Blade Element Momentum Theory", "preliminary",
        ("traditional",),
        "Iterative blade-element model with induction and tabulated section polars.",
    ),
    "llt": MethodDescriptor(
        "llt", "Lifting-Line Theory", "preliminary",
        ("traditional",),
        "Rotating lifting line with finite-span correction and Prandtl losses.",
    ),
    "vlm": MethodDescriptor(
        "vlm", "Vortex Lattice Method", "experimental",
        ("traditional", "toroidal"),
        "Horseshoe-vortex lattice with fixed wake; wake relaxation is not yet included.",
    ),
    "bem": MethodDescriptor(
        "bem", "Boundary Element Method", "experimental",
        ("traditional", "toroidal"),
        "Chordwise-refined constant-strength vortex boundary elements.",
    ),
}


def create_solver(method: str, target_thrust_n: float | None = None) -> BaseSolver:
    factories: dict[str, Callable[[], BaseSolver]] = {
        "actuator_disk": lambda: ActuatorDiskSolver(_require_target(target_thrust_n)),
        "bemt": lambda: BEMTSolver(reference_thrust_n=target_thrust_n or 10.0),
        "llt": LLTSolver,
        "vlm": VLMSolver,
        "bem": BoundaryElementSolver,
    }
    try:
        return factories[method]()
    except KeyError as exc:
        raise ValueError(f"Unknown computational method: {method}") from exc


def list_methods() -> list[dict]:
    return [descriptor.to_dict() for descriptor in METHODS.values()]


def _require_target(value: float | None) -> float:
    if value is None:
        raise ValueError("Actuator disk requires target_thrust_n")
    return value
