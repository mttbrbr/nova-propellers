"""Transport-independent analysis; preserve the legacy numerical/JSON contract."""

import numpy as np

from geometry_engine import AIR_DENSITY
from inverse_design import GeometryData, create_solver, list_methods
from nova.core.contracts import CanonicalSolverResult


def run_propeller_analysis(
    *, model: str, geometry_data: dict, rpm: float, target_thrust_n: float,
    propeller_type: str = "traditional", solver_version: str = "0.1.0-alpha.2",
    solver=None,
) -> dict:
    descriptor = next(item for item in list_methods() if item["id"] == model)
    if propeller_type not in descriptor["suitable_for"]:
        raise ValueError(
            f"{descriptor['name']} does not support {propeller_type} geometry"
        )
    geometry = GeometryData.from_dict(geometry_data)
    solver = solver or create_solver(model, target_thrust_n=target_thrust_n)
    detailed = solver.evaluate_detailed(geometry, rpm)
    performance = detailed["performance"]
    convergence = detailed.get("convergence")
    warnings = list(descriptor["warnings"])
    if convergence and not convergence.get("converged", False):
        warnings.append(
            f"Solver did not converge: {convergence.get('termination_reason', 'unknown')} "
            f"after {convergence.get('iterations', 'unknown')} iterations "
            f"(residual={convergence.get('residual', 'unknown')})."
        )
    omega = 2.0 * np.pi * rpm / 60.0
    power_w = performance["torque"] * omega
    result = CanonicalSolverResult(
        schema_version="1.0",
        model=model,
        method=descriptor["name"],
        role=descriptor["role"],
        fidelity=descriptor["fidelity"],
        description=descriptor["description"],
        solver={
            "id": model,
            "version": solver_version,
            "fidelity": descriptor["fidelity"],
        },
        operating_point={
            "rpm": rpm,
            "angular_velocity_rad_s": omega,
            "air_density_kg_m3": getattr(solver, "rho", AIR_DENSITY),
            "axial_velocity_m_s": getattr(solver, "axial_velocity", 0.0),
        },
        performance={
            "thrust_n": performance["thrust"],
            "torque_nm": performance["torque"],
            "power_w": power_w,
            "efficiency": performance["efficiency"],
        },
        units={
            "thrust": "N",
            "torque": "N*m",
            "power": "W",
            "efficiency": "dimensionless",
        },
        warnings=warnings,
        convergence=convergence,
        curve_source=detailed["curve_source"],
        summary={
            "target_thrust_n": round(target_thrust_n, 4),
            "estimated_thrust_n": round(performance["thrust"], 4),
            "thrust_error_pct": round(
                100.0
                * (performance["thrust"] - target_thrust_n)
                / target_thrust_n,
                3,
            ),
            "torque_nm": round(performance["torque"], 6),
            "power_w": round(performance["torque"] * omega, 4),
            "efficiency": round(performance["efficiency"], 4),
        },
        stations=detailed["curves"],
    )
    return result.model_dump()
