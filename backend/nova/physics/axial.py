"""Blade-element momentum theory for axial-flow rotors.

One formulation serves propellers (air and marine) and horizontal-axis wind or
tidal turbines. Each station is solved for its inflow angle φ through a 1-D
residual (Ning 2014), which always has a bracketed root, so the method does not
depend on fixed-point relaxation. Stations are solved simultaneously:
a vectorized scan finds the bracket and a vectorized bisection refines it.

Conventions
  turbine   : α = φ − θ, Vx = V∞(1 − a), Vy = Ωr(1 + a'), power extracted > 0
  propeller : α = θ − φ, Vx = V∞ + v,    Vy = Ωr − w,     thrust produced > 0
θ is the local twist plus collective pitch, measured from the rotor plane.
"""
import math
from dataclasses import dataclass

import numpy as np

from .corrections import (
    AxialCorrections,
    hub_loss,
    prandtl_glauert,
    snel_augmentation,
    tip_loss,
    turbine_axial_induction,
)
from .fluids import Fluid

EPS = 1e-6
# Largest k = σ'Cn/(4F sin²φ) handled by pure momentum, per high-induction model.
MOMENTUM_LIMIT = {'none': np.inf, 'glauert': 0.5, 'spera': 0.25, 'buhl': 2.0 / 3.0}
SCAN = 90


@dataclass
class AxialRotor:
    blades: int
    tip_radius_m: float
    hub_radius_m: float
    radius_m: np.ndarray
    chord_m: np.ndarray
    twist_deg: np.ndarray
    section: object
    pitch_deg: float = 0.0

    def __post_init__(self):
        self.radius_m = np.asarray(self.radius_m, dtype=float)
        self.chord_m = np.asarray(self.chord_m, dtype=float)
        self.twist_deg = np.asarray(self.twist_deg, dtype=float)
        if not (self.radius_m.shape == self.chord_m.shape == self.twist_deg.shape) or self.radius_m.size < 3:
            raise ValueError('Radius, chord and twist need the same length (at least 3 stations)')
        if int(self.blades) != self.blades or not 1 <= self.blades <= 12:
            raise ValueError('Blade count must be an integer between 1 and 12')
        if not 0 <= self.hub_radius_m < self.tip_radius_m:
            raise ValueError('Hub radius must be smaller than tip radius')
        if np.any(np.diff(self.radius_m) <= 0) or self.radius_m[0] < self.hub_radius_m - 1e-12 or self.radius_m[-1] > self.tip_radius_m + 1e-12:
            raise ValueError('Stations must increase strictly between hub and tip')
        if np.any(self.chord_m < 0):
            raise ValueError('Chord must be non-negative')

    @property
    def solidity(self):
        area = np.trapezoid(self.chord_m, self.radius_m) * self.blades
        return float(area / (math.pi * (self.tip_radius_m**2 - self.hub_radius_m**2)))


def _coefficients(rotor, fluid, corrections, alpha_deg, r, chord, speed, slope, alpha0):
    reynolds = fluid.density_kg_m3 * speed * chord / fluid.viscosity_pa_s
    cl, cd = rotor.section(alpha_deg, reynolds)
    if corrections.rotational_augmentation == 'snel':
        cl = snel_augmentation(cl, alpha_deg, chord, r, alpha0, slope, r / rotor.tip_radius_m)
    mach = speed / fluid.speed_of_sound_m_s
    if corrections.compressibility == 'prandtl_glauert':
        cl = prandtl_glauert(cl, mach)
    return cl, cd, reynolds, mach


def _state(phi, mode, rotor, fluid, corrections, r, chord, theta, V, omega, slope, alpha0, tsr):
    """All station quantities for a candidate inflow angle (arrays broadcast)."""
    B = rotor.blades
    sigma = B * chord / (2 * math.pi * r)
    s, c = np.sin(phi), np.cos(phi)
    s = np.where(np.abs(s) < EPS, EPS, s)
    c = np.where(np.abs(c) < EPS, EPS, c)
    F = tip_loss(corrections.tip_loss, B, r, rotor.tip_radius_m, phi, tsr) * \
        hub_loss(corrections.hub_loss, B, r, rotor.hub_radius_m, phi)
    nominal = np.hypot(V, omega * r)
    if mode == 'turbine':
        alpha = np.degrees(phi - theta)
        cl, cd, re, mach = _coefficients(rotor, fluid, corrections, alpha, r, chord, nominal, slope, alpha0)
        cn, ct = cl * c + cd * s, cl * s - cd * c
        k = sigma * cn / (4 * F * s * s)
        kp = sigma * ct / (4 * F * s * c)
        a = np.where(phi > 0, turbine_axial_induction(k, F, corrections.high_induction),
                     np.where(k > 1, k / (k - 1), 0.0))
        ap = kp / np.where(np.abs(1 - kp) < EPS, EPS, 1 - kp)
        # In the momentum region 1/(1 − a) = 1 + k exactly; using it avoids the
        # spurious pole at k = −1 (a → ∞) that would masquerade as a root.
        # Propeller-brake branch (φ < 0): a = k/(k − 1) gives 1/(1 − a) = 1 − k.
        windmill = np.where(k <= MOMENTUM_LIMIT[corrections.high_induction], 1 + k,
                            1 / np.where(np.abs(1 - a) < EPS, EPS, 1 - a))
        inverse = np.where(phi > 0, windmill, np.where(k > 1, 1 - k, 1.0))
        residual = s * inverse - V / (omega * r) * c * (1 - kp)
        return dict(alpha=alpha, cl=cl, cd=cd, cn=cn, ct=ct, F=F, a=a, ap=ap, re=re, mach=mach, residual=residual)
    alpha = np.degrees(theta - phi)
    cl, cd, re, mach = _coefficients(rotor, fluid, corrections, alpha, r, chord, nominal, slope, alpha0)
    cn, ct = cl * c - cd * s, cl * s + cd * c
    k = sigma * cn / (4 * F * s * s)
    kp = sigma * ct / (4 * F * s * c)
    residual = omega * r * s * (1 - k) - V * c * (1 + kp)
    return dict(alpha=alpha, cl=cl, cd=cd, cn=cn, ct=ct, F=F, k=k, kp=kp, re=re, mach=mach, residual=residual)


def _bracket(residual_grid, phi_grid, windows):
    """Bracket per station, searching windows in order.

    The physical root is where the residual rises through zero (Ning 2014);
    a falling crossing near φ → 0 appears when the local twist is ≤ 0 and is
    used only if no rising crossing exists in any window.
    """
    n = residual_grid.shape[1]
    low, high = np.full(n, np.nan), np.full(n, np.nan)
    for rising_only in (True, False):
        for start, stop in windows:
            idx = np.flatnonzero((phi_grid >= start) & (phi_grid <= stop))
            values = residual_grid[idx]
            if rising_only:
                change = (values[:-1] < 0) & (values[1:] >= 0)
            else:
                change = np.signbit(values[:-1]) != np.signbit(values[1:])
            for station in np.flatnonzero(np.isnan(low)):
                hits = np.flatnonzero(change[:, station])
                if hits.size:
                    low[station], high[station] = phi_grid[idx[hits[0]]], phi_grid[idx[hits[0] + 1]]
    return low, high


def solve_axial(rotor: AxialRotor, *, mode, velocity_m_s, rpm, fluid: Fluid, corrections: AxialCorrections):
    if mode not in ('turbine', 'propeller'):
        raise ValueError('Mode must be turbine or propeller')
    V = float(velocity_m_s)
    omega = 2 * math.pi * float(rpm) / 60.0
    if not math.isfinite(V) or not math.isfinite(omega) or omega <= 0:
        raise ValueError('Rotational speed must be positive and velocity finite')
    if mode == 'turbine' and V <= 0:
        raise ValueError('A turbine needs a positive free-stream velocity')
    if mode == 'propeller' and V < 0:
        raise ValueError('Propeller advance velocity must be non-negative')
    R = rotor.tip_radius_m
    inner = (rotor.radius_m > rotor.hub_radius_m + 1e-9) & (rotor.radius_m < R - 1e-9) & (rotor.chord_m > 0)
    r, chord = rotor.radius_m[inner], rotor.chord_m[inner]
    theta = np.radians(rotor.twist_deg[inner] + rotor.pitch_deg)
    tsr = omega * R / V if V > 0 else math.inf
    slope = rotor.section.lift_slope_per_rad() if corrections.rotational_augmentation == 'snel' else 2 * math.pi
    alpha0 = rotor.section.zero_lift_angle_deg() if corrections.rotational_augmentation == 'snel' else 0.0
    args = (mode, rotor, fluid, corrections)
    station = (r, chord, theta, V, omega, slope, alpha0, tsr)

    if mode == 'turbine':
        windows = [(EPS, math.pi / 2), (-math.pi / 4, -EPS), (math.pi / 2, math.pi - EPS)]
        grid = np.concatenate([np.linspace(EPS, math.pi / 2, SCAN), np.linspace(-math.pi / 4, -EPS, SCAN // 3),
                               np.linspace(math.pi / 2, math.pi - EPS, SCAN // 3)])
    else:
        windows = [(EPS, math.pi / 2 - EPS)]
        grid = np.linspace(EPS, math.pi / 2 - EPS, SCAN)
    order = np.argsort(grid, kind='stable')
    grid = grid[order]
    scan = _state(grid[:, None], *args, *station)
    low, high = _bracket(scan['residual'], grid, windows)
    solved = ~np.isnan(low)
    # Unbracketed stations (deep stall or windmill brake without a momentum
    # solution) take the scan point of minimum |residual| and are flagged.
    fallback = grid[np.argmin(np.abs(scan['residual']), axis=0)]
    low, high = np.where(solved, low, fallback), np.where(solved, high, fallback)
    f_low = _state(low, *args, *station)['residual']
    for _ in range(60):
        mid = 0.5 * (low + high)
        f_mid = _state(mid, *args, *station)['residual']
        same = np.signbit(f_mid) == np.signbit(f_low)
        low, f_low = np.where(same, mid, low), np.where(same, f_mid, f_low)
        high = np.where(same, high, mid)
    phi = 0.5 * (low + high)
    st = _state(phi, *args, *station)

    if mode == 'turbine':
        axial = V * (1 - st['a'])
        tangential = omega * r * (1 + st['ap'])
        a, ap = st['a'], st['ap']
    else:
        sin_phi, cos_phi = np.sin(phi), np.cos(phi)
        through = omega * r * sin_phi / (cos_phi * (1 + st['kp']))
        axial = through
        tangential = through * cos_phi / np.maximum(sin_phi, EPS)
        a = (through - V) / V if V > 0 else np.full_like(r, np.nan)
        ap = 1 - tangential / (omega * r)
    W = np.hypot(axial, tangential)
    q = 0.5 * fluid.density_kg_m3 * W**2
    dT = rotor.blades * q * chord * st['cn']
    dQ = rotor.blades * q * chord * st['ct'] * r
    # Loads vanish at the hub and tip ends of the blade.
    nodes = np.concatenate([[max(rotor.hub_radius_m, rotor.radius_m[0])], r, [R]])
    thrust = float(np.trapezoid(np.concatenate([[0], dT, [0]]), nodes))
    torque = float(np.trapezoid(np.concatenate([[0], dQ, [0]]), nodes))
    power = torque * omega
    area = math.pi * R**2
    rho = fluid.density_kg_m3
    n, D = rpm / 60.0, 2 * R
    coefficients = {'KT': thrust / (rho * n**2 * D**4), 'KQ': torque / (rho * n**2 * D**5),
                    'CP_prop': power / (rho * n**3 * D**5)}
    if V > 0:
        coefficients.update(J=V / (n * D), CP=power / (0.5 * rho * area * V**3), CT=thrust / (0.5 * rho * area * V**2),
                            CQ=torque / (0.5 * rho * area * R * V**2), TSR=tsr)
    if mode == 'propeller':
        coefficients['efficiency'] = (thrust * V / power) if V > 0 and power > 0 else None
        ideal = thrust * math.sqrt(max(thrust, 0) / (2 * rho * area)) if V == 0 else None
        coefficients['figure_of_merit'] = (ideal / power) if ideal is not None and power > 0 else None
    warnings = []
    if not solved.all():
        warnings.append(f'{int((~solved).sum())} station(s) without a momentum solution; minimum-residual state used')
    if np.any(st['mach'] > 0.7):
        warnings.append('Section Mach number above 0.7: compressibility outside model validity')
    if rotor.section.synthetic:
        warnings.append(f'Synthetic demonstration section polar ({rotor.section.name})')
    stations = [{
        'r_over_R': round(float(r[i] / R), 5), 'radius_m': float(r[i]), 'chord_m': float(chord[i]),
        'phi_deg': float(np.degrees(phi[i])), 'alpha_deg': float(st['alpha'][i]), 'cl': float(st['cl'][i]),
        'cd': float(st['cd'][i]), 'a': float(a[i]), 'a_prime': float(ap[i]), 'loss_factor': float(st['F'][i]),
        'reynolds': float(st['re'][i]), 'mach': float(st['mach'][i]), 'relative_velocity_m_s': float(W[i]),
        'd_thrust_n_m': float(dT[i]), 'd_torque_nm_m': float(dQ[i]), 'solved': bool(solved[i]),
    } for i in range(r.size)]
    return {
        'mode': mode, 'performance': {'thrust_n': thrust, 'torque_nm': torque, 'power_w': power},
        'operating': {'velocity_m_s': V, 'rpm': float(rpm), 'omega_rad_s': omega, 'tip_speed_m_s': omega * R,
                      'tip_speed_ratio': tsr if math.isfinite(tsr) else None},
        'coefficients': coefficients, 'stations': stations, 'converged': bool(solved.all()),
        'solidity': rotor.solidity, 'warnings': warnings,
    }
