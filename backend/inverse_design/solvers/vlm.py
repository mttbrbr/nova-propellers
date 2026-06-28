import numpy as np

from ..geometry import GeometryData
from .base import BaseSolver, SolverResult


class VLMSolver(BaseSolver):
    """Preliminary rotating horseshoe-vortex lattice.

    This low-order implementation is suitable for architecture work and early
    comparisons. Toroidal production analysis still requires a closed-surface,
    wake-relaxed VLM and independent validation.
    """

    def __init__(
        self,
        air_density: float = 1.225,
        axial_velocity_m_s: float = 0.1,
        core_radius_m: float = 1e-4,
        wake_length_radii: float = 8.0,
        profile_drag_coefficient: float = 0.012,
    ) -> None:
        self.rho = air_density
        self.axial_velocity = axial_velocity_m_s
        self.core_radius = core_radius_m
        self.wake_length_radii = wake_length_radii
        self.cd0 = profile_drag_coefficient

    def evaluate(self, geometry_data: GeometryData, rpm: float) -> SolverResult:
        omega = 2.0 * np.pi * rpm / 60.0
        radius = geometry_data.radius_m
        panel_radius = 0.5 * (radius[:-1] + radius[1:])
        dr = np.diff(radius)
        chord = np.interp(panel_radius, radius, geometry_data.chord_m)
        twist = np.interp(panel_radius, radius, geometry_data.twist_rad)
        controls = np.column_stack(
            (panel_radius, 0.5 * chord * np.cos(twist), 0.5 * chord * np.sin(twist))
        )
        normals = np.column_stack(
            (np.zeros_like(twist), -np.sin(twist), np.cos(twist))
        )
        freestream = np.column_stack(
            (np.zeros_like(panel_radius), omega * panel_radius, np.full_like(panel_radius, self.axial_velocity))
        )
        matrix = np.empty((len(panel_radius), len(panel_radius)))
        wake = self.wake_length_radii * geometry_data.diameter_m / 2.0
        for row, (control, normal) in enumerate(zip(controls, normals)):
            for column in range(len(panel_radius)):
                start = np.array([radius[column], 0.0, 0.0])
                end = np.array([radius[column + 1], 0.0, 0.0])
                downstream = np.array([0.0, 0.0, -wake])
                induced = (
                    _vortex_segment(control, start + downstream, start, self.core_radius)
                    + _vortex_segment(control, start, end, self.core_radius)
                    + _vortex_segment(control, end, end + downstream, self.core_radius)
                )
                matrix[row, column] = np.dot(induced, normal)
        rhs = -np.einsum("ij,ij->i", freestream, normals)
        circulation = np.linalg.solve(matrix + np.eye(len(matrix)) * 1e-8, rhs)

        relative_speed = np.linalg.norm(freestream, axis=1)
        lift_axial = self.rho * np.abs(circulation) * omega * panel_radius * dr
        profile_drag = 0.5 * self.rho * relative_speed**2 * chord * self.cd0 * dr
        thrust = geometry_data.blades * np.sum(np.maximum(lift_axial - profile_drag * np.sin(twist), 0.0))
        induced_tangential = self.rho * np.abs(circulation) * self.axial_velocity * dr
        torque = geometry_data.blades * np.sum(
            panel_radius * (induced_tangential + profile_drag * np.cos(twist))
        )
        disk_area = np.pi * (geometry_data.diameter_m / 2.0) ** 2
        ideal_power = thrust * np.sqrt(max(thrust, 0.0) / (2.0 * self.rho * disk_area))
        # A fixed-wake horseshoe lattice under-resolves induced torque. Enforce
        # the actuator-disk lower power bound instead of reporting η > 1.
        torque = max(torque, ideal_power / max(0.85 * omega, 1e-9))
        shaft_power = max(torque * omega, 1e-9)
        return {
            "thrust": float(thrust),
            "torque": float(torque),
            "efficiency": float(np.clip(ideal_power / shaft_power, 0.0, 1.0)),
        }


def _vortex_segment(
    point: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    core_radius: float,
) -> np.ndarray:
    """Regularized finite-segment Biot-Savart velocity for unit circulation."""
    r1 = point - start
    r2 = point - end
    segment = end - start
    cross = np.cross(r1, r2)
    denominator = np.dot(cross, cross) + core_radius**2 * np.dot(segment, segment)
    if denominator < 1e-20:
        return np.zeros(3)
    direction = r1 / max(np.linalg.norm(r1), 1e-12) - r2 / max(np.linalg.norm(r2), 1e-12)
    return cross * np.dot(segment, direction) / (4.0 * np.pi * denominator)
