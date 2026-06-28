import numpy as np

from ..geometry import GeometryData
from .base import BaseSolver, SolverResult
from .vlm import _vortex_segment


class BoundaryElementSolver(BaseSolver):
    """Low-order constant-strength vortex boundary-element model.

    Three chordwise elements resolve the mean blade surface. This is deliberately
    isolated so a production source/doublet formulation can replace it without
    changing API, optimizer or UI code.
    """

    def __init__(
        self,
        air_density: float = 1.225,
        axial_velocity_m_s: float = 0.1,
        chordwise_elements: int = 3,
        max_radial_elements: int = 14,
        core_radius_m: float = 2e-4,
        profile_drag_coefficient: float = 0.01,
    ) -> None:
        self.rho = air_density
        self.axial_velocity = axial_velocity_m_s
        self.chordwise_elements = chordwise_elements
        self.max_radial_elements = max_radial_elements
        self.core_radius = core_radius_m
        self.cd0 = profile_drag_coefficient

    def evaluate(self, geometry_data: GeometryData, rpm: float) -> SolverResult:
        omega = 2.0 * np.pi * rpm / 60.0
        sample_count = min(len(geometry_data.radius_m), self.max_radial_elements + 1)
        radius = np.linspace(geometry_data.radius_m[0], geometry_data.radius_m[-1], sample_count)
        chord_at_edge = np.interp(radius, geometry_data.radius_m, geometry_data.chord_m)
        twist_at_edge = np.interp(radius, geometry_data.radius_m, geometry_data.twist_rad)
        radial_mid = 0.5 * (radius[:-1] + radius[1:])
        chord = np.interp(radial_mid, radius, chord_at_edge)
        twist = np.interp(radial_mid, radius, twist_at_edge)
        dr = np.diff(radius)
        chord_fractions = (np.arange(self.chordwise_elements) + 0.75) / self.chordwise_elements
        controls, normals, vortices = [], [], []
        wake = geometry_data.diameter_m * 4.0

        for radial_index, radial_control in enumerate(radial_mid):
            for fraction in chord_fractions:
                offset = (fraction - 0.35) * chord[radial_index]
                controls.append([
                    radial_control,
                    offset * np.cos(twist[radial_index]),
                    offset * np.sin(twist[radial_index]),
                ])
                normals.append([0.0, -np.sin(twist[radial_index]), np.cos(twist[radial_index])])

        for radial_index in range(len(radial_mid)):
            for fraction in chord_fractions:
                left_offset = (fraction - 0.60) * chord_at_edge[radial_index]
                right_offset = (fraction - 0.60) * chord_at_edge[radial_index + 1]
                start = np.array([
                    radius[radial_index],
                    left_offset * np.cos(twist_at_edge[radial_index]),
                    left_offset * np.sin(twist_at_edge[radial_index]),
                ])
                end = np.array([
                    radius[radial_index + 1],
                    right_offset * np.cos(twist_at_edge[radial_index + 1]),
                    right_offset * np.sin(twist_at_edge[radial_index + 1]),
                ])
                vortices.append((start, end))

        controls = np.asarray(controls)
        normals = np.asarray(normals)
        matrix = np.empty((len(controls), len(vortices)))
        downstream = np.array([0.0, 0.0, -wake])
        for row, (control, normal) in enumerate(zip(controls, normals)):
            for column, (start, end) in enumerate(vortices):
                velocity = (
                    _vortex_segment(control, start + downstream, start, self.core_radius)
                    + _vortex_segment(control, start, end, self.core_radius)
                    + _vortex_segment(control, end, end + downstream, self.core_radius)
                )
                matrix[row, column] = np.dot(velocity, normal)

        local_radius = np.repeat(radial_mid, self.chordwise_elements)
        freestream = np.column_stack((
            np.zeros_like(local_radius),
            omega * local_radius,
            np.full_like(local_radius, self.axial_velocity),
        ))
        rhs = -np.einsum("ij,ij->i", freestream, normals)
        strengths = np.linalg.lstsq(matrix + np.eye(len(matrix)) * 1e-7, rhs, rcond=1e-8)[0]
        circulation = np.sum(np.abs(strengths.reshape(-1, self.chordwise_elements)), axis=1)
        speed = np.hypot(omega * radial_mid, self.axial_velocity)
        lift = self.rho * speed * circulation
        drag = 0.5 * self.rho * speed**2 * chord * self.cd0
        phi = np.arctan2(self.axial_velocity, np.maximum(omega * radial_mid, 1e-9))
        thrust = geometry_data.blades * np.sum(np.maximum(lift * np.cos(phi) - drag * np.sin(phi), 0.0) * dr)
        torque = geometry_data.blades * np.sum(radial_mid * (lift * np.sin(phi) + drag * np.cos(phi)) * dr)
        disk_area = np.pi * (geometry_data.diameter_m / 2.0) ** 2
        ideal_power = thrust * np.sqrt(max(thrust, 0.0) / max(2.0 * self.rho * disk_area, 1e-9))
        torque = max(float(torque), ideal_power / max(0.78 * omega, 1e-9))
        return {
            "thrust": float(thrust),
            "torque": torque,
            "efficiency": float(np.clip(ideal_power / max(torque * omega, 1e-9), 0.0, 1.0)),
        }
