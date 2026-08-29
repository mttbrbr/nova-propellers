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
    role: str
    fidelity: str
    suitable_for: tuple[str, ...]
    description: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "fidelity": self.fidelity,
            "suitable_for": self.suitable_for,
            "description": self.description,
            "warnings": self.warnings,
        }


METHODS = {
    "actuator_disk": MethodDescriptor(
        "actuator_disk", "Actuator disk", "sizing_reference", "ideal_reference",
        ("traditional",),
        "Ideal momentum-theory sizing reference; it is not a blade-performance prediction.",
        ("The returned thrust is the requested target, not a prediction from blade geometry.",),
    ),
    "bemt": MethodDescriptor(
        "bemt", "Blade Element Momentum Theory", "analysis", "preliminary",
        ("traditional",),
        "Iterative blade-element model with induction and tabulated section polars.",
        ("Not yet qualified against an experimental propeller dataset.",),
    ),
    "llt": MethodDescriptor(
        "llt", "Lifting-Line Theory", "analysis", "preliminary",
        ("traditional",),
        "Rotating lifting line with finite-span correction and Prandtl losses.",
        ("Not yet qualified against an experimental propeller dataset.",),
    ),
    "vlm": MethodDescriptor(
        "vlm", "Vortex Lattice Method", "analysis", "experimental",
        ("traditional",),
        "Horseshoe-vortex lattice with fixed wake; wake relaxation is not yet included.",
        ("Architecture prototype only; do not use for engineering decisions.",),
    ),
    "bem": MethodDescriptor(
        "bem", "Boundary Element Method", "analysis", "experimental",
        ("traditional",),
        "Chordwise-refined constant-strength vortex boundary elements.",
        ("Architecture prototype only; do not use for engineering decisions.",),
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
