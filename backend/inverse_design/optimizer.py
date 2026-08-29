from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import OptimizeResult, minimize

from .geometry import GeometryData, GeometryParameterization
from .solvers import BaseSolver, SolverResult

FloatArray = NDArray[np.float64]


class OptimizationSafetyError(ValueError):
    """Raised before optimization when a parameterization is too complex."""


@dataclass(frozen=True)
class GeometryConstraints:
    """Bounds for optimizer variables plus sampled STL-printability limits."""

    parameter_bounds: tuple[tuple[float, float], ...]
    min_chord_m: float
    max_chord_m: float
    min_twist_deg: float = 0.0
    max_twist_deg: float = 45.0
    max_chord_slope: float = 1.5
    penalty_weight: float = 100.0

    def penalty(self, vector: FloatArray, geometry: GeometryData) -> float:
        violation = 0.0
        for value, (lower, upper) in zip(vector, self.parameter_bounds):
            scale = max(upper - lower, 1e-12)
            violation += max(lower - value, 0.0) ** 2 / scale**2
            violation += max(value - upper, 0.0) ** 2 / scale**2
        twist_deg = np.degrees(geometry.twist_rad)
        violation += float(np.sum(np.maximum(self.min_chord_m - geometry.chord_m, 0.0) ** 2))
        violation += float(np.sum(np.maximum(geometry.chord_m - self.max_chord_m, 0.0) ** 2))
        violation += float(np.sum(np.maximum(self.min_twist_deg - twist_deg, 0.0) ** 2)) / 45.0**2
        violation += float(np.sum(np.maximum(twist_deg - self.max_twist_deg, 0.0) ** 2)) / 45.0**2
        chord_slope = np.abs(np.gradient(geometry.chord_m, geometry.radius_m))
        violation += float(np.sum(np.maximum(chord_slope - self.max_chord_slope, 0.0) ** 2))
        return self.penalty_weight * violation


@dataclass(frozen=True)
class OptimizationResult:
    success: bool
    message: str
    iterations: int
    loss: float
    parameters: object
    geometry: GeometryData
    performance: SolverResult


class InverseDesignOptimizer:
    """Solver- and geometry-agnostic inverse design loop."""

    def __init__(
        self,
        solver: BaseSolver,
        parameterization: GeometryParameterization,
        initial_parameters: object,
        constraints: GeometryConstraints,
        method: str = "Nelder-Mead",
        options: dict | None = None,
        progress_callback: Callable[[int, float], None] | None = None,
        max_control_points: int = 4,
    ) -> None:
        self.solver = solver
        self.parameterization = parameterization
        self.initial_parameters = initial_parameters
        self.constraints = constraints
        self.method = method
        self.options = {"maxiter": 350, "xatol": 1e-5, "fatol": 1e-6, **(options or {})}
        self.progress_callback = progress_callback
        self.max_control_points = max_control_points
        self._evaluations = 0

        initial_vector = self.parameterization.encode(initial_parameters)
        if len(initial_vector) != len(constraints.parameter_bounds):
            raise ValueError("A parameter bound is required for every optimization variable")

    def optimize(self, target_thrust: float, rpm: float) -> OptimizationResult:
        if target_thrust <= 0 or rpm <= 0:
            raise ValueError("target_thrust and rpm must be positive")
        self._enforce_complexity_guard()
        initial_vector = self.parameterization.encode(self.initial_parameters)
        self._evaluations = 0

        def objective(vector: FloatArray) -> float:
            parameters = self.parameterization.decode(np.asarray(vector, dtype=float))
            geometry = self.parameterization.build(parameters)
            try:
                performance = self.solver.evaluate(geometry, rpm)
                thrust_error = (performance["thrust"] - target_thrust) / target_thrust
                loss = thrust_error**2 + self.constraints.penalty(vector, geometry)
            except (RuntimeError, ValueError, FloatingPointError):
                # A non-convergent aerodynamic state is outside the feasible
                # design domain, not a valid objective sample.
                loss = 1e6 + self.constraints.penalty(vector, geometry)
            self._evaluations += 1
            if self.progress_callback is not None:
                self.progress_callback(self._evaluations, float(loss))
            return float(loss)

        scipy_result: OptimizeResult = minimize(
            objective,
            initial_vector,
            method=self.method,
            bounds=self.constraints.parameter_bounds,
            options=self.options,
        )
        parameters = self.parameterization.decode(np.asarray(scipy_result.x, dtype=float))
        geometry = self.parameterization.build(parameters)
        performance = self.solver.evaluate(geometry, rpm)
        return OptimizationResult(
            success=bool(scipy_result.success),
            message=str(scipy_result.message),
            iterations=int(scipy_result.nit),
            loss=float(scipy_result.fun),
            parameters=parameters,
            geometry=geometry,
            performance=performance,
        )

    def _enforce_complexity_guard(self) -> None:
        complexity_reader = getattr(self.parameterization, "optimization_complexity", None)
        if complexity_reader is None:
            return
        complexity = complexity_reader(self.initial_parameters)
        violations = {
            name: count
            for name, count in complexity.items()
            if count > self.max_control_points
        }
        if violations:
            details = ", ".join(f"{name}={count}" for name, count in violations.items())
            raise OptimizationSafetyError(
                "Inverse optimization refused by safety guard: "
                f"{details}; maximum allowed is {self.max_control_points} control points "
                "per curve. Manual geometry remains available. Reduce or fit the curves "
                "to four control points before retrying."
            )
