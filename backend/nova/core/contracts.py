"""Versioned result models shared by the API, persistence and validation suite."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SolverIdentity(StrictModel):
    id: str
    version: str
    fidelity: Literal["ideal_reference", "preliminary", "experimental", "qualified"]


class OperatingPoint(StrictModel):
    rpm: float = Field(gt=0)
    angular_velocity_rad_s: float = Field(gt=0)
    air_density_kg_m3: float = Field(gt=0)
    axial_velocity_m_s: float = Field(ge=0)


class PerformanceSummary(StrictModel):
    thrust_n: float
    torque_nm: float
    power_w: float = Field(ge=0)
    efficiency: float = Field(ge=0, le=1)


class ConvergenceDiagnostics(StrictModel):
    classification: Literal[
        "converged", "stagnation", "oscillation", "slow_convergence", "divergence"
    ]
    relaxation_strategy: Literal["fixed", "adaptive"]
    initial_relaxation_factor: float = Field(gt=0, le=1)
    final_relaxation_factor: float = Field(gt=0, le=1)
    minimum_relaxation_factor: float = Field(gt=0, le=1)
    maximum_relaxation_factor: float = Field(gt=0, le=1)
    initial_residual: float = Field(ge=0)
    final_residual: float = Field(ge=0)
    total_reduction_ratio: float = Field(ge=0)
    recent_reduction_ratio: float = Field(ge=0)
    tail_variation_ratio: float = Field(ge=1)
    target_tolerance: float = Field(gt=0)
    history_sampling: str
    history: list[dict[str, Any]]


class ConvergenceInfo(StrictModel):
    converged: bool
    iterations: int = Field(ge=0)
    residual: float = Field(ge=0)
    tolerance: float = Field(gt=0)
    termination_reason: str
    diagnostics: ConvergenceDiagnostics | None = None

    @model_validator(mode="after")
    def convergence_state_is_consistent(self) -> "ConvergenceInfo":
        if self.converged and self.residual >= self.tolerance:
            raise ValueError("a converged result must have residual below tolerance")
        return self


class CanonicalSolverResult(StrictModel):
    """Canonical API contract introduced by the v0.2 validation work.

    Presentation fields remain during the alpha so existing saved projects and
    the React client continue to work while consumers migrate to performance.
    """

    schema_version: Literal["1.0"] = "1.0"
    model: str
    method: str
    role: str
    fidelity: str
    description: str
    solver: SolverIdentity
    operating_point: OperatingPoint
    performance: PerformanceSummary
    units: dict[str, str]
    warnings: list[str]
    convergence: ConvergenceInfo | None
    curve_source: Literal["native", "reconstructed"]
    summary: dict[str, float]
    stations: list[dict[str, Any]]

    @model_validator(mode="after")
    def summary_matches_performance(self) -> "CanonicalSolverResult":
        mappings = {
            "estimated_thrust_n": self.performance.thrust_n,
            "torque_nm": self.performance.torque_nm,
            "power_w": self.performance.power_w,
            "efficiency": self.performance.efficiency,
        }
        for field, expected in mappings.items():
            actual = self.summary.get(field)
            if actual is None:
                raise ValueError(f"summary is missing {field}")
            tolerance = max(1e-6, abs(expected) * 1e-3)
            if abs(actual - expected) > tolerance:
                raise ValueError(f"summary {field} does not match canonical performance")
        return self
