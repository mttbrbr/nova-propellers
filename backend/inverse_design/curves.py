import numpy as np

from .geometry import GeometryData
from .solvers.base import SolverResult


def reconstruct_radial_curves(
    geometry: GeometryData,
    rpm: float,
    performance: SolverResult,
    air_density: float = 1.225,
    viscosity: float = 1.81e-5,
) -> list[dict]:
    """Reconstruct a smooth radial load shape from global solver outputs.

    This fallback is explicitly tagged ``reconstructed``. Solvers with native
    sectional outputs should override BaseSolver.evaluate_detailed.
    """
    omega = 2.0 * np.pi * rpm / 60.0
    radius = geometry.radius_m
    dr = np.gradient(radius)
    speed = np.maximum(omega * radius, 1e-6)
    disk_area = np.pi * (geometry.diameter_m / 2.0) ** 2
    induced = np.sqrt(max(performance["thrust"], 0.0) / max(2.0 * air_density * disk_area, 1e-9))
    phi = np.arctan2(induced, speed)
    alpha = geometry.twist_rad - phi
    cl = np.clip(2.0 * np.pi * alpha, -1.4, 1.4)
    cd = 0.012 + 0.018 * cl**2
    reynolds = air_density * np.hypot(speed, induced) * geometry.chord_m / viscosity
    circulation = 0.5 * np.hypot(speed, induced) * geometry.chord_m * cl

    thrust_shape = np.maximum(speed**2 * geometry.chord_m * np.maximum(cl, 0.02) * dr, 1e-12)
    torque_shape = np.maximum(radius * speed**2 * geometry.chord_m * cd * dr, 1e-12)
    d_thrust = performance["thrust"] * thrust_shape / np.sum(thrust_shape)
    d_torque = performance["torque"] * torque_shape / np.sum(torque_shape)

    return [
        {
            "r_over_R": round(float(fraction), 5),
            "radius_m": round(float(radius[index]), 7),
            "chord_mm": round(float(geometry.chord_m[index] * 1000.0), 4),
            "twist_deg": round(float(np.degrees(geometry.twist_rad[index])), 4),
            "alpha_deg": round(float(np.degrees(alpha[index])), 4),
            "cl": round(float(cl[index]), 5),
            "cd": round(float(cd[index]), 6),
            "reynolds": round(float(reynolds[index]), 1),
            "circulation": round(float(circulation[index]), 7),
            "d_thrust_n": round(float(d_thrust[index]), 7),
            "d_torque_nm": round(float(d_torque[index]), 8),
            "d_power_w": round(float(d_torque[index] * omega), 6),
            "source": "reconstructed",
        }
        for index, fraction in enumerate(geometry.radial_fraction)
    ]
