import numpy as np

from ..geometry import GeometryData
from .base import BaseSolver, SolverResult


class LLTSolver(BaseSolver):
    """Rotating lifting-line model with Prandtl root/tip losses."""

    def __init__(
        self,
        air_density: float = 1.225,
        axial_velocity_m_s: float = 0.1,
        lift_curve_slope: float = 2.0 * np.pi,
        zero_lift_angle_deg: float = -2.0,
        profile_drag_coefficient: float = 0.012,
    ) -> None:
        self.rho = air_density
        self.axial_velocity = axial_velocity_m_s
        self.a0 = lift_curve_slope
        self.alpha0 = np.radians(zero_lift_angle_deg)
        self.cd0 = profile_drag_coefficient

    def evaluate(self, geometry_data: GeometryData, rpm: float) -> SolverResult:
        omega = 2.0 * np.pi * rpm / 60.0
        radius = geometry_data.radius_m
        dr = np.gradient(radius)
        axial_induced = np.full_like(radius, max(self.axial_velocity, 0.2))
        circulation = np.zeros_like(radius)
        loss = np.ones_like(radius)

        for _ in range(80):
            tangential = np.maximum(omega * radius, 1e-9)
            axial = self.axial_velocity + axial_induced
            speed = np.hypot(tangential, axial)
            phi = np.arctan2(axial, tangential)
            alpha = geometry_data.twist_rad - phi - self.alpha0
            loss = _prandtl_loss(geometry_data.blades, radius, radius[-1], radius[0], phi)
            aspect_ratio = (radius[-1] - radius[0]) ** 2 / max(
                np.trapezoid(geometry_data.chord_m, radius), 1e-9
            )
            lift_slope = self.a0 / (1.0 + self.a0 / (np.pi * 0.85 * aspect_ratio))
            cl = np.clip(lift_slope * alpha, -1.4, 1.4)
            next_circulation = 0.5 * speed * geometry_data.chord_m * cl * loss
            next_induced = (
                geometry_data.blades * np.abs(next_circulation)
                / np.maximum(4.0 * np.pi * radius * loss, 1e-8)
            )
            if np.max(np.abs(next_induced - axial_induced)) < 1e-5:
                circulation = next_circulation
                axial_induced = next_induced
                break
            circulation = 0.7 * circulation + 0.3 * next_circulation
            axial_induced = 0.7 * axial_induced + 0.3 * next_induced

        speed = np.hypot(omega * radius, self.axial_velocity + axial_induced)
        phi = np.arctan2(self.axial_velocity + axial_induced, np.maximum(omega * radius, 1e-9))
        lift = self.rho * speed * circulation
        drag = 0.5 * self.rho * speed**2 * geometry_data.chord_m * self.cd0
        d_thrust = geometry_data.blades * (lift * np.cos(phi) - drag * np.sin(phi)) * dr
        d_torque = geometry_data.blades * radius * (lift * np.sin(phi) + drag * np.cos(phi)) * dr
        thrust = max(float(np.sum(d_thrust)), 0.0)
        torque = max(float(np.sum(d_torque)), 0.0)
        disk_area = np.pi * (geometry_data.diameter_m / 2.0) ** 2
        ideal_power = thrust * np.sqrt(thrust / max(2.0 * self.rho * disk_area, 1e-9))
        torque = max(torque, ideal_power / max(0.90 * omega, 1e-9))
        return {
            "thrust": thrust,
            "torque": torque,
            "efficiency": float(np.clip(ideal_power / max(torque * omega, 1e-9), 0.0, 1.0)),
        }


def _prandtl_loss(
    blades: int,
    radius: np.ndarray,
    tip_radius: float,
    root_radius: float,
    phi: np.ndarray,
) -> np.ndarray:
    sin_phi = np.maximum(np.abs(np.sin(phi)), 1e-4)
    tip = np.exp(-blades * (tip_radius - radius) / np.maximum(2.0 * radius * sin_phi, 1e-8))
    root = np.exp(-blades * (radius - root_radius) / np.maximum(2.0 * root_radius * sin_phi, 1e-8))
    return np.clip((2.0 / np.pi * np.arccos(np.clip(tip, 0, 1))) * (2.0 / np.pi * np.arccos(np.clip(root, 0, 1))), 0.08, 1.0)
