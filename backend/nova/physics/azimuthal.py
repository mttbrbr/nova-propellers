"""Blade-element momentum for axial rotors with inflow that varies around the disk.

The axisymmetric solver (``axial.solve_axial``) gives one state per radius. Here
every radius is solved at ``azimuth_steps`` blade positions, each with its own
inflow, by running the same bracketed 1-D residual over all (radius, azimuth)
points at once:

  * yaw / inclination γ: normal velocity V cos γ and an in-plane component
    V sin γ cos ψ added to the blade speed (Hansen 2015); for turbines the
    Glauert skewed-wake correction a(ψ) = a (1 + 15π/32 · r/R · tan(χ/2) · sin ψ)
    with χ = γ (1 + 0.6 a) at a ≈ 0.25 (Burton et al. 2011)
  * vertical wind shear (power law) with hub height
  * tower shadow below the hub: potential flow for an upwind rotor, a Gaussian
    bluff-body wake for a downwind rotor
  * an upstream rotor or body wake resolved point by point (see ``wake``)
  * Øye dynamic stall (Hansen 2015): attached-flow fraction f relaxes towards its
    steady value with τ = 4 c / W and corrects the section lift

Limits, stated in every result: annuli stay independent (no radial or azimuthal
coupling of the induced velocity beyond the skew correction), and dynamic stall
acts on the loads after the induction is solved.

Azimuth ψ = 0 is the blade pointing up; the blade moves towards +y at ψ = 0 and
the yaw component of the wind points to +y.
"""
import math

import numpy as np

from . import wake as upstream
from .axial import EPS, _flow, _solve_points
from .corrections import AxialCorrections

KEYS = {'resolved', 'yaw_deg', 'shear_exponent', 'hub_height_m', 'tower', 'azimuth_steps'}
TOWER_KEYS = {'kind', 'radius_m', 'distance_m'}
SKEW_INDUCTION = 0.25
REVOLUTIONS = 3


def _number(config, key, default, low, high):
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Inflow {key.replace("_", " ")} must be a number between {low:g} and {high:g}')
    return float(value)


def validate(config):
    """Normalised resolved-inflow description, or None when the axisymmetric solver applies."""
    if not config or not config.get('resolved'):
        return None
    unknown = set(config) - KEYS
    if unknown:
        raise ValueError(f'Unsupported inflow fields: {", ".join(sorted(unknown))}')
    steps = config.get('azimuth_steps', 36)
    if type(steps) is not int or not 12 <= steps <= 144:
        raise ValueError('Azimuth steps must be an integer between 12 and 144')
    tower = dict(config.get('tower') or {'kind': 'none'})
    if set(tower) - TOWER_KEYS or tower.get('kind', 'none') not in ('none', 'upwind', 'downwind'):
        raise ValueError('Tower needs kind none, upwind or downwind with radius and distance')
    if tower.get('kind', 'none') != 'none':
        tower = {'kind': tower['kind'], 'radius_m': _number(tower, 'radius_m', None, 1e-3, 100.0),
                 'distance_m': _number(tower, 'distance_m', None, 1e-3, 1000.0)}
        if tower['distance_m'] <= tower['radius_m']:
            raise ValueError('The tower axis must lie farther from the rotor plane than the tower radius')
    shear = _number(config, 'shear_exponent', 0.0, 0.0, 1.0)
    hub = _number(config, 'hub_height_m', 0.0, 0.0, 1000.0)
    if (shear > 0 or tower['kind'] != 'none') and hub <= 0:
        raise ValueError('Wind shear and tower shadow need the hub height')
    return {'resolved': True, 'yaw_deg': _number(config, 'yaw_deg', 0.0, -60.0, 60.0), 'shear_exponent': shear,
            'hub_height_m': hub, 'tower': tower, 'azimuth_steps': steps}


def _tower_deficit(tower, y, below_hub):
    if tower['kind'] == 'none':
        return np.zeros_like(y)
    a, d = tower['radius_m'], tower['distance_m']
    if tower['kind'] == 'upwind':
        # Potential flow past a cylinder: the stagnation flow ahead of the tower slows the blade as it passes.
        deficit = a**2 * (d**2 - y**2) / (d**2 + y**2) ** 2
    else:
        deficit = upstream.local_deficit({'model': 'gaussian', 'diameter_m': 2 * a, 'coefficient': 1.0,
                                          'distance_m': d, 'decay': upstream.DEFAULT_DECAY['body']}, np.abs(y))
    return np.where(below_hub, np.maximum(deficit, 0.0), 0.0)


def solve_azimuthal(rotor, *, mode, velocity_m_s, rpm, fluid, corrections: AxialCorrections, inflow, wake_config=None):
    inflow = validate(inflow)
    if inflow is None:
        raise ValueError('Resolved inflow is not enabled')
    wake = upstream.validate(wake_config)
    V, omega = float(velocity_m_s), 2 * math.pi * float(rpm) / 60.0
    if not math.isfinite(V) or not math.isfinite(omega) or omega <= 0:
        raise ValueError('Rotational speed must be positive and velocity finite')
    if (mode == 'turbine' and V <= 0) or (mode == 'propeller' and V < 0):
        raise ValueError('Free-stream velocity must be positive for a turbine and non-negative for a propeller')
    R, B = rotor.tip_radius_m, rotor.blades
    inner = (rotor.radius_m > rotor.hub_radius_m + 1e-9) & (rotor.radius_m < R - 1e-9) & (rotor.chord_m > 0)
    r, chord = rotor.radius_m[inner], rotor.chord_m[inner]
    theta = np.radians(rotor.twist_deg[inner] + rotor.pitch_deg)
    n, m = r.size, inflow['azimuth_steps']
    psi = np.arange(m) / m * 2 * math.pi
    rr, pp = np.meshgrid(r, psi, indexing='ij')
    y, z = rr * np.sin(pp), rr * np.cos(pp)
    below = z < 0

    # Local free-stream speed at every point of the disk.
    speed = np.full_like(rr, V)
    if inflow['shear_exponent'] > 0:
        height = np.maximum(inflow['hub_height_m'] + z, 0.01 * inflow['hub_height_m'])
        speed = speed * (height / inflow['hub_height_m']) ** inflow['shear_exponent']
    speed = speed * (1 - _tower_deficit(inflow['tower'], y, below))
    if wake is not None:
        speed = speed * (1 - upstream.local_deficit(wake, np.hypot(y - wake['offset_m'], z - wake['offset_z_m'])))
    gamma = math.radians(inflow['yaw_deg'])
    normal = speed * math.cos(gamma)
    in_plane = speed * math.sin(gamma) * np.cos(pp)
    blade_speed = omega * rr + in_plane
    if np.any(blade_speed <= 0):
        raise ValueError('The in-plane inflow exceeds the blade speed; lower the yaw angle or raise the rotation speed')
    if mode == 'turbine' and np.any(normal <= 0):
        raise ValueError('A turbine needs a positive normal inflow everywhere on the disk')
    omega_eff = blade_speed / rr
    skew = None
    if mode == 'turbine' and abs(gamma) > 1e-9:
        chi = min(abs(gamma) * (1 + 0.6 * SKEW_INDUCTION), math.radians(80))
        skew = 15 * math.pi / 32 * rr / R * math.tan(chi / 2) * np.sin(pp) * math.copysign(1.0, gamma)
    with np.errstate(divide='ignore'):
        tsr = np.where(normal > 0, omega * R / np.maximum(normal, 1e-12), np.inf)

    needs_slope = corrections.rotational_augmentation != 'none' or corrections.dynamic_stall != 'none'
    slope = rotor.section.lift_slope_per_rad() if needs_slope else 2 * math.pi
    alpha0 = rotor.section.zero_lift_angle_deg() if needs_slope else 0.0
    flat = lambda a: a.reshape(-1)  # noqa: E731
    station = (flat(rr), flat(np.broadcast_to(chord[:, None], rr.shape)), flat(np.broadcast_to(theta[:, None], rr.shape)),
               flat(normal), flat(omega_eff), slope, alpha0, flat(tsr), None if skew is None else flat(skew))
    phi, st, solved = _solve_points(mode, (mode, rotor, fluid, corrections), station)
    axial, tangential, a, ap = _flow(mode, st, phi, station[3], station[4], station[0])
    shape = lambda v: np.asarray(v).reshape(n, m)  # noqa: E731
    phi, alpha, cl, cd, F = (shape(v) for v in (phi, st['alpha'], st['cl'], st['cd'], st['F']))
    axial, tangential, a, ap, solved = (shape(v) for v in (axial, tangential, a, ap, solved))
    W = np.hypot(axial, tangential)
    c = chord[:, None]

    dynamic = None
    if corrections.dynamic_stall == 'oye':
        cl, dynamic = _oye(cl, alpha, W, c, slope, alpha0, omega, m)
    s, co = np.sin(phi), np.cos(phi)
    cn, ct = (cl * co + cd * s, cl * s - cd * co) if mode == 'turbine' else (cl * co - cd * s, cl * s + cd * co)
    q = 0.5 * fluid.density_kg_m3 * W**2
    dT, dQ = q * c * cn, q * c * ct * rr          # one blade, per metre of span
    nodes = np.concatenate([[max(rotor.hub_radius_m, rotor.radius_m[0])], r, [R]])
    pad = np.zeros((1, m))
    integrate = lambda f: np.trapezoid(np.vstack([pad, f, pad]), nodes, axis=0)  # noqa: E731
    blade_thrust, blade_torque, flap = integrate(dT), integrate(dQ), integrate(dT * rr)
    thrust, torque = float(B * blade_thrust.mean()), float(B * blade_torque.mean())
    power = torque * omega
    area, rho = math.pi * R**2, fluid.density_kg_m3
    rps, D = rpm / 60.0, 2 * R
    coefficients = {'KT': thrust / (rho * rps**2 * D**4), 'KQ': torque / (rho * rps**2 * D**5), 'CP_prop': power / (rho * rps**3 * D**5)}
    if V > 0:
        coefficients.update(J=V / (rps * D), CP=power / (0.5 * rho * area * V**3), CT=thrust / (0.5 * rho * area * V**2),
                            CQ=torque / (0.5 * rho * area * R * V**2), TSR=omega * R / V)
    if mode == 'propeller':
        coefficients['efficiency'] = (thrust * V / power) if V > 0 and power > 0 else None
        ideal = thrust * math.sqrt(max(thrust, 0) / (2 * rho * area)) if V == 0 else None
        coefficients['figure_of_merit'] = (ideal / power) if ideal is not None and power > 0 else None

    # Whole-rotor load against azimuth: the blades are spaced 2π/B apart.
    def rotor_total(values):
        return sum(np.interp((psi + 2 * math.pi * j / B) % (2 * math.pi), psi, values, period=2 * math.pi) for j in range(B))
    rotor_thrust, rotor_torque = rotor_total(blade_thrust), rotor_total(blade_torque)
    probe = int(np.argmin(np.abs(r / R - 0.7)))
    rotation = [{'azimuth_deg': float(np.degrees(psi[k])), 'blade_thrust_n': float(blade_thrust[k]), 'blade_torque_nm': float(blade_torque[k]),
                 'flap_moment_nm': float(flap[k]), 'rotor_thrust_n': float(rotor_thrust[k]), 'rotor_torque_nm': float(rotor_torque[k]),
                 'alpha_deg': float(alpha[probe, k]), 'inflow_ratio': float(speed[probe, k] / V) if V > 0 else None} for k in range(m)]
    mean = lambda f: f.mean(axis=1)  # noqa: E731
    stations = [{
        'r_over_R': round(float(r[i] / R), 5), 'radius_m': float(r[i]), 'chord_m': float(chord[i]),
        'phi_deg': float(np.degrees(mean(phi)[i])), 'alpha_deg': float(mean(alpha)[i]), 'alpha_min_deg': float(alpha[i].min()),
        'alpha_max_deg': float(alpha[i].max()), 'cl': float(mean(cl)[i]), 'cd': float(mean(cd)[i]), 'a': float(np.nanmean(a[i])),
        'a_prime': float(mean(ap)[i]), 'loss_factor': float(mean(F)[i]), 'reynolds': float(mean(shape(st['re']))[i]),
        'mach': float(shape(st['mach'])[i].max()), 'relative_velocity_m_s': float(mean(W)[i]),
        'd_thrust_n_m': float(B * mean(dT)[i]), 'd_torque_nm_m': float(B * mean(dQ)[i]), 'solved': bool(solved[i].all()),
    } for i in range(n)]
    warnings = ['Resolved inflow: each annulus is solved independently at every azimuth (no cross-coupling of the induced velocity beyond '
                'the skew correction)' + ('; Øye dynamic stall corrects the loads after the induction is solved' if dynamic else '')]
    if not solved.all():
        warnings.append(f'{int((~solved).sum())} of {solved.size} points without a momentum solution; minimum-residual state used')
    if np.any(shape(st['mach']) > 0.7):
        warnings.append('Section Mach number above 0.7: compressibility outside model validity')
    if rotor.section.synthetic:
        warnings.append(f'Synthetic demonstration section polar ({rotor.section.name})')
    swing = float((blade_thrust.max() - blade_thrust.min()) / abs(blade_thrust.mean())) if abs(blade_thrust.mean()) > 1e-12 else None
    return {
        'mode': mode, 'performance': {'thrust_n': thrust, 'torque_nm': torque, 'power_w': power,
                                      'blade_thrust_variation': swing, 'rotor_thrust_ripple': float((rotor_thrust.max() - rotor_thrust.min()) / abs(rotor_thrust.mean()))
                                      if abs(rotor_thrust.mean()) > 1e-12 else None},
        'operating': {'velocity_m_s': V, 'rpm': float(rpm), 'omega_rad_s': omega, 'tip_speed_m_s': omega * R,
                      'tip_speed_ratio': omega * R / V if V > 0 else None},
        'coefficients': coefficients, 'stations': stations, 'rotation': rotation, 'converged': bool(solved.all()),
        'inflow': {**{k: v for k, v in inflow.items() if k != 'resolved'}, 'speed_ratio_min': float(speed.min() / V) if V > 0 else None,
                   'speed_ratio_max': float(speed.max() / V) if V > 0 else None, 'dynamic_stall': 'oye' if dynamic else 'none',
                   'attached_fraction_min': dynamic['f_min'] if dynamic else None},
        'solidity': rotor.solidity, 'warnings': warnings,
    }


def _oye(cl_static, alpha_deg, W, chord, slope, alpha0_deg, omega, steps):
    """Øye (Hansen 2015): relax the attached-flow fraction f towards f_st with τ = 4 c / W, in steady-consistent difference form."""
    cl_inv = slope * np.radians(alpha_deg - alpha0_deg)
    cl_fs = 0.5 * cl_inv
    gap = cl_inv - cl_fs
    with np.errstate(divide='ignore', invalid='ignore'):
        f_st = np.where(np.abs(gap) > 1e-3, np.clip((cl_static - cl_fs) / gap, 0.0, 1.0), 1.0)
    decay = np.exp(-(2 * math.pi / steps / omega) / np.maximum(4 * chord / np.maximum(W, 1e-6), 1e-9))
    f = f_st[:, 0].copy()
    history = np.empty_like(f_st)
    for revolution in range(REVOLUTIONS):
        for k in range(steps):
            f = f_st[:, k] + (f - f_st[:, k]) * decay[:, k]
            if revolution == REVOLUTIONS - 1:
                history[:, k] = f
    return cl_static + (history - f_st) * gap, {'f_min': float(history.min())}
