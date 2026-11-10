"""Streamtube momentum models for vertical-axis (Darrieus / H-rotor) turbines.

Four classical formulations share one blade-element kernel and differ only in
how the momentum balance is grouped:

  single_streamtube           one actuator disk for the whole rotor (Templin 1974)
  double_streamtube           one disk upwind, one downwind in tandem (Lissaman/Loth)
  multiple_streamtube         one disk per streamtube, both passages (Strickland 1975)
  double_multiple_streamtube  two disks per streamtube (Paraschivoiu 1981, DMST)

Geometry: blade at azimuth θ sits at r(−cos θ, sin θ) with the wind along +x;
θ ∈ (−90°, 90°) is the upwind half, θ = 0 the most upstream point. Reported
azimuths are shifted by +90° so 0–180° is upwind and 180–360° downwind.
Positive α produces lift toward the rotor axis (upwind half).
"""
import math
from dataclasses import dataclass

import numpy as np

from .corrections import (
    VerticalCorrections,
    finite_aspect_ratio_alpha,
    flow_curvature_deg,
    gormont_berg,
    induced_drag,
    shaft_wake_deficit,
    strut_torque,
)
from .fluids import Fluid

WAKE_FLOOR = 0.2
METHODS = ('single_streamtube', 'double_streamtube', 'multiple_streamtube', 'double_multiple_streamtube')
METHOD_LABELS = {
    'single_streamtube': 'Single streamtube (Templin)',
    'double_streamtube': 'Double streamtube (tandem actuator disks)',
    'multiple_streamtube': 'Multiple streamtube (Strickland)',
    'double_multiple_streamtube': 'Double-multiple streamtube (Paraschivoiu)',
}


@dataclass
class VerticalRotor:
    blades: int
    radius_m: float
    height_m: float
    chord_m: float
    section: object
    shape: str = 'straight'
    pitch_axis_fraction: float = 0.25
    blade_pitch_deg: float = 0.0
    struts_per_blade: int = 2
    strut_chord_m: float = 0.0
    strut_cd: float = 0.02
    shaft_diameter_m: float = 0.0
    shaft_cd: float = 1.2

    def __post_init__(self):
        if int(self.blades) != self.blades or not 1 <= self.blades <= 8:
            raise ValueError('Blade count must be an integer between 1 and 8')
        for key in ('radius_m', 'height_m', 'chord_m'):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) <= 0:
                raise ValueError(f'{key} must be positive')
        if self.chord_m >= self.radius_m:
            raise ValueError('Chord must be smaller than rotor radius')
        if self.shape not in ('straight', 'troposkien'):
            raise ValueError('Blade shape must be straight or troposkien')
        if not 0 <= self.pitch_axis_fraction <= 1:
            raise ValueError('Pitch axis must lie on the chord (0–1)')
        if self.shaft_diameter_m < 0 or self.shaft_diameter_m >= self.radius_m:
            raise ValueError('Shaft diameter must be smaller than rotor radius')

    @property
    def solidity(self):
        """σ = N c / R (Paraschivoiu's definition)."""
        return self.blades * self.chord_m / self.radius_m

    @property
    def aspect_ratio(self):
        return self.blade_length_m / self.chord_m

    @property
    def blade_length_m(self):
        if self.shape == 'straight':
            return self.height_m
        z = np.linspace(-self.height_m / 2, self.height_m / 2, 401)
        r = self.radius_at(z)
        return float(np.sum(np.hypot(np.diff(z), np.diff(r))))

    def radius_at(self, z):
        if self.shape == 'straight':
            return np.full_like(np.asarray(z, dtype=float), self.radius_m)
        # Parabolic approximation of the troposkien; ends kept off the axis.
        return np.maximum(self.radius_m * (1 - (2 * np.asarray(z) / self.height_m) ** 2), 0.02 * self.radius_m)

    def slope_at(self, z):
        if self.shape == 'straight':
            return np.zeros_like(np.asarray(z, dtype=float))
        return np.arctan(np.abs(8 * self.radius_m * np.asarray(z) / self.height_m**2))

    def swept_area(self):
        if self.shape == 'straight':
            return 2 * self.radius_m * self.height_m
        z = np.linspace(-self.height_m / 2, self.height_m / 2, 401)
        return float(np.trapezoid(2 * self.radius_at(z), z))


def _inverse_thrust(ct, model):
    """Induction a from a streamtube thrust coefficient CT = 4a(1−a) (+ empirical branch)."""
    ct = np.asarray(ct, dtype=float)
    momentum = 0.5 * (1 - np.sqrt(np.maximum(1 - np.minimum(ct, 0.96 if model != 'none' else 1.0), 0)))
    if model == 'none':
        return np.minimum(momentum, 0.5)
    if model == 'spera':
        ac = 0.2
        return np.where(ct > 4 * ac * (1 - ac), (ct / 4 - ac**2) / (1 - 2 * ac), momentum)
    heavy = ct > 0.96
    if model == 'buhl':
        A, b = 50 / 9 - 4, 4 - 40 / 9
        buhl = (-b + np.sqrt(np.maximum(b * b - 4 * A * (8 / 9 - ct), 0))) / (2 * A)
        return np.where(heavy, np.minimum(buhl, 0.99), momentum)
    # Glauert empirical CT = 4a(1 − a(5 − 3a)/4), continuous with momentum at a = 1/3.
    glauert_heavy = ct > 8 / 9
    low, high = np.full_like(ct, 1 / 3), np.full_like(ct, 0.99)
    for _ in range(50):
        mid = 0.5 * (low + high)
        g = 4 * mid * (1 - 0.25 * (5 - 3 * mid) * mid) - ct
        low, high = np.where(g < 0, mid, low), np.where(g < 0, high, mid)
    exact = 0.5 * (1 - np.sqrt(np.maximum(1 - ct, 0)))
    return np.where(glauert_heavy, 0.5 * (low + high), exact)


class _Kernel:
    def __init__(self, rotor, fluid, corrections, omega):
        self.rotor, self.fluid, self.c, self.omega = rotor, fluid, corrections, omega
        self.section = rotor.section
        self.alpha0 = self.section.zero_lift_angle_deg()
        self.slope = self.section.lift_slope_per_rad()
        self.stall = self.section.static_stall_angle_deg()

    def forces(self, theta, v_local, r, delta, alpha_rate=None):
        X = self.omega * r / np.maximum(v_local, 1e-9)
        normal = np.cos(theta) * np.cos(delta)
        chordwise = X - np.sin(theta)
        w_over_v = np.sqrt(chordwise**2 + normal**2)
        W = v_local * w_over_v
        alpha_flow = np.degrees(np.arctan2(normal, chordwise))
        alpha = alpha_flow + self.rotor.blade_pitch_deg
        if self.c.flow_curvature:
            alpha = alpha + flow_curvature_deg(self.omega, self.rotor.chord_m, self.rotor.pitch_axis_fraction, W)
        ar = self.rotor.aspect_ratio
        if self.c.finite_aspect_ratio:
            alpha = finite_aspect_ratio_alpha(alpha, self.alpha0, self.slope, ar)
        reynolds = self.fluid.density_kg_m3 * W * self.rotor.chord_m / self.fluid.viscosity_pa_s
        if self.c.dynamic_stall == 'gormont_berg' and alpha_rate is not None:
            cl, cd = gormont_berg(alpha, alpha_rate, self.rotor.chord_m, W, self.section.thickness, self.section,
                                  reynolds, self.stall, self.alpha0, self.slope)
        else:
            cl, cd = self.section(alpha, reynolds)
        if self.c.finite_aspect_ratio:
            cd = cd + induced_drag(cl, ar)
        a = np.radians(alpha_flow)
        cn = cl * np.cos(a) + cd * np.sin(a)
        ct = cl * np.sin(a) - cd * np.cos(a)
        cx = cn * np.cos(theta) + ct * np.sin(theta) / np.cos(delta)
        return dict(W=W, alpha=alpha, alpha_flow=alpha_flow, cl=cl, cd=cd, cn=cn, ct=ct, cx=cx, re=reynolds)


def solve_vertical(rotor: VerticalRotor, *, method, wind_speed_m_s, rpm, fluid: Fluid,
                   corrections: VerticalCorrections, azimuth_tubes=36, height_levels=None,
                   max_iterations=400, tolerance=1e-7):
    if method not in METHODS:
        raise ValueError(f'VAWT method must be one of {", ".join(METHODS)}')
    V = float(wind_speed_m_s)
    omega = 2 * math.pi * float(rpm) / 60
    if not (math.isfinite(V) and V > 0 and math.isfinite(omega) and omega > 0):
        raise ValueError('Wind speed and rotational speed must be positive')
    if not 6 <= azimuth_tubes <= 180:
        raise ValueError('Use between 6 and 180 streamtubes per half')
    kernel = _Kernel(rotor, fluid, corrections, omega)
    n = int(azimuth_tubes)
    dtheta = math.pi / n
    theta_u = -math.pi / 2 + (np.arange(n) + 0.5) * dtheta
    theta_d = math.pi - theta_u
    levels = height_levels or (1 if rotor.shape == 'straight' else 16)
    z_edges = np.linspace(-rotor.height_m / 2, rotor.height_m / 2, levels + 1)
    z_mid, dz = 0.5 * (z_edges[1:] + z_edges[:-1]), np.diff(z_edges)
    N, c, model = rotor.blades, rotor.chord_m, corrections.high_induction
    total_torque = total_fx = 0.0
    iterations_used, converged = 0, True
    level_results = []

    for z, h in zip(z_mid, dz):
        r = float(rotor.radius_at(z))
        delta = float(rotor.slope_at(z))
        y = r * np.sin(theta_u)
        deficit = shaft_wake_deficit(y, rotor.shaft_diameter_m, rotor.shaft_cd) if corrections.shaft_wake and rotor.shaft_diameter_m > 0 else 0.0
        width = 2 * math.pi * r * np.abs(np.cos(theta_u))  # per-tube CT denominator
        a_u, a_d = np.zeros(n), np.zeros(n)
        rate_u = rate_d = None
        relax, previous_change = 0.4, None
        for iteration in range(1, max_iterations + 1):
            if method in ('single_streamtube', 'multiple_streamtube'):
                v_u = V * (1 - a_u)
                v_d = v_u * (1 - deficit)
                v_ref_d = V
            else:
                v_u = V * (1 - a_u)
                # Equilibrium velocity between the disks; beyond a = 0.4 the far-wake
                # estimate V(1 − 2a) loses meaning (turbulent-wake state) and is floored.
                v_e = np.maximum(V * (1 - 2 * a_u), WAKE_FLOOR * V) * (1 - deficit)
                v_d = v_e * (1 - a_d)
                v_ref_d = v_e
            up = kernel.forces(theta_u, v_u, r, delta, rate_u)
            down = kernel.forces(theta_d, v_d, r, delta, rate_d)
            load_u = N * c * up['W'] ** 2 * up['cx']
            load_d = N * c * down['W'] ** 2 * down['cx']
            if method == 'double_multiple_streamtube':
                target_u = _inverse_thrust(load_u / (width * V**2), model)
                target_d = _inverse_thrust(load_d / (width * v_ref_d**2), model)
            elif method == 'multiple_streamtube':
                target_u = _inverse_thrust((load_u + load_d) / (width * V**2), model)
                target_d = target_u
            elif method == 'single_streamtube':
                ct = (np.sum(load_u) + np.sum(load_d)) * dtheta / (4 * math.pi * r * V**2)
                target_u = np.full(n, float(_inverse_thrust(ct, model)))
                target_d = target_u
            else:
                ct_u = np.sum(load_u) * dtheta / (4 * math.pi * r * V**2)
                a_up = float(_inverse_thrust(ct_u, model))
                ve = max(V * (1 - 2 * a_up), WAKE_FLOOR * V)
                ct_d = np.sum(load_d) * dtheta / (4 * math.pi * r * ve**2)
                target_u = np.full(n, a_up)
                target_d = np.full(n, float(_inverse_thrust(ct_d, model)))
            change = max(float(np.max(np.abs(target_u - a_u))), float(np.max(np.abs(target_d - a_d))))
            if previous_change is not None and change > previous_change * 1.02:
                relax = max(0.05, relax * 0.7)
            previous_change = change
            a_u += relax * (target_u - a_u)
            a_d += relax * (target_d - a_d)
            if corrections.dynamic_stall != 'none':
                # α̇ = Ω dα/dθ around the full revolution (upwind then downwind, ascending θ).
                ring = np.concatenate([up['alpha'], down['alpha'][::-1]])
                rate = omega * np.gradient(np.unwrap(np.radians(ring)), dtheta)  # rad/s
                rate_u, rate_d = rate[:n], rate[n:][::-1]
            if change < tolerance:
                break
        else:
            converged = False
        iterations_used = max(iterations_used, iteration)
        torque_u = N / (2 * math.pi) * 0.5 * fluid.density_kg_m3 * c * r / math.cos(delta) * up['W'] ** 2 * up['ct']
        torque_d = N / (2 * math.pi) * 0.5 * fluid.density_kg_m3 * c * r / math.cos(delta) * down['W'] ** 2 * down['ct']
        level_torque = float((np.sum(torque_u) + np.sum(torque_d)) * dtheta * h)
        fx = N / (2 * math.pi) * 0.5 * fluid.density_kg_m3 * c * (np.sum(up['W'] ** 2 * up['cx']) + np.sum(down['W'] ** 2 * down['cx'])) * dtheta * h
        total_torque += level_torque
        total_fx += float(fx)
        level_results.append(dict(z=float(z), r=r, up=up, down=down, a_u=a_u.copy(), a_d=a_d.copy(), v_u=v_u, v_d=v_d, h=float(h)))

    strut_loss = 0.0
    if corrections.strut_drag and rotor.strut_chord_m > 0:
        strut_loss = strut_torque(fluid.density_kg_m3, omega, N, rotor.struts_per_blade, rotor.strut_chord_m,
                                  rotor.strut_cd, rotor.radius_m)
    torque = total_torque - strut_loss
    power = torque * omega
    area = rotor.swept_area()
    rho = fluid.density_kg_m3
    tsr = omega * rotor.radius_m / V
    # Azimuthal distributions at the equator (largest radius level).
    mid = level_results[len(level_results) // 2]
    azimuth = np.degrees(np.concatenate([theta_u, theta_d[::-1]])) + 90.0
    order = lambda key: np.concatenate([mid['up'][key], mid['down'][key][::-1]])  # noqa: E731
    induction = np.concatenate([mid['a_u'], mid['a_d'][::-1]])
    local_v = np.concatenate([mid['v_u'], mid['v_d'][::-1]])
    blade_torque = 0.5 * rho * c * mid['r'] * order('W') ** 2 * order('ct') * rotor.height_m
    distributions = [{
        'azimuth_deg': float(azimuth[i]), 'half': 'upwind' if i < n else 'downwind',
        'alpha_deg': float(order('alpha')[i]), 'inflow_angle_deg': float(order('alpha_flow')[i]),
        'relative_velocity_ratio': float(order('W')[i] / V), 'local_velocity_ratio': float(local_v[i] / V),
        'induction': float(induction[i]), 'cl': float(order('cl')[i]), 'cd': float(order('cd')[i]),
        'cn': float(order('cn')[i]), 'ct': float(order('ct')[i]), 'reynolds': float(order('re')[i]),
        'blade_torque_nm': float(blade_torque[i]),
    } for i in range(2 * n)]
    warnings = []
    if not converged:
        warnings.append('Streamtube iteration reached the iteration limit; result retained with diagnostics')
    if rotor.section.synthetic:
        warnings.append(f'Synthetic demonstration section polar ({rotor.section.name})')
    if rotor.solidity > 0.5 and method in ('single_streamtube', 'double_streamtube'):
        warnings.append('High solidity: single/double streamtube models over-predict power; prefer DMST')
    if np.max(induction) > 0.5 and model == 'none':
        warnings.append('Induction above 0.5 without a high-induction correction: momentum theory invalid')
    return {
        'method': method, 'method_label': METHOD_LABELS[method],
        'performance': {'torque_nm': torque, 'power_w': power, 'streamwise_force_n': total_fx,
                        'strut_torque_loss_nm': strut_loss},
        'operating': {'wind_speed_m_s': V, 'rpm': float(rpm), 'omega_rad_s': omega, 'tip_speed_ratio': tsr,
                      'tip_speed_m_s': omega * rotor.radius_m},
        'coefficients': {'CP': power / (0.5 * rho * area * V**3), 'CT': total_fx / (0.5 * rho * area * V**2),
                         'CQ': torque / (0.5 * rho * area * rotor.radius_m * V**2), 'TSR': tsr},
        'geometry': {'solidity': rotor.solidity, 'aspect_ratio': rotor.aspect_ratio, 'swept_area_m2': area,
                     'shape': rotor.shape},
        'azimuth': distributions, 'converged': converged, 'iterations': iterations_used, 'warnings': warnings,
    }
