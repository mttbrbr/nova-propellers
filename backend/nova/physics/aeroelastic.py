"""Steady aeroelastic rotor: BEMT on the deformed blade, iterated with the rotating 3-D beam.

At a fixed operating point the blade deflects under its own aerodynamic loads; the deflected blade
changes those loads. Each iteration

1. solves the BEMT on the deformed geometry: every element at span s has a cone angle β(s) =
   precone + atan(dw/ds) from the flapwise deflection w, sits at the in-plane radius
   r(s) = r_hub + ∫ cos β ds, sees the normal wind V cos β and the speed Ω r, and has its twist reduced
   by the elastic nose-up torsion θ_e(s);
2. turns the element forces into loads per unit span: the normal force f_n (out of plane, flapwise),
   the tangential force f_t (in plane, edgewise) and the torsional moment f_n' d, where f_n' is the force
   normal to the chord acting at the quarter chord and d the distance of the elastic axis behind it;
3. solves the rotating beam (centrifugal stiffening included) for w(s) and the statically determinate
   torsion θ_e(s) = ∫₀ˢ T/GJ, T(s) = ∫ₛᴸ m_t;

until the cone and twist angles settle (under-relaxed fixed point). Thrust is ∫ f_n cos β ds, torque
∫ f_t r ds, both over the blade length; coefficients refer to the undeformed rotor area.

Not modelled: prebend, sweep, in-plane (edgewise) deflection in the aerodynamics, the propeller moment and
bend–twist coupling in the torsion, gravity, unsteady effects.
"""
import math

import numpy as np

from . import flexible, modal, rotors
from .axial import _flow, _solve_points
from .sections import lift_slope, zero_lift_angle


class AeroelasticError(ValueError):
    pass


def _torsion(s, moment, gj):
    """Elastic rotation of a cantilever under a distributed torque (s from the root)."""
    inner = np.concatenate([[0.0], np.cumsum((moment[1:] + moment[:-1]) / 2 * np.diff(s))])
    T = inner[-1] - inner
    rate = T / gj
    return np.concatenate([[0.0], np.cumsum((rate[1:] + rate[:-1]) / 2 * np.diff(s))])


def _bemt(rotor, fluid, corrections, *, V, omega, r, s, chord, theta):
    """BEMT at per-station radius r, normal wind V (arrays) and twist θ; forces per unit blade length."""
    R = rotor.tip_radius_m
    tsr = omega * R / max(float(np.max(V)), 1e-9)
    slope = lift_slope(rotor.section, r) if corrections.rotational_augmentation != 'none' else 2 * math.pi
    alpha0 = zero_lift_angle(rotor.section, r) if corrections.rotational_augmentation != 'none' else 0.0
    phi, st, solved = _solve_points('turbine', ('turbine', rotor, fluid, corrections), (r, chord, theta, V, omega, slope, alpha0, tsr))
    axial, tangential, a, ap = _flow('turbine', st, phi, V, omega, r)
    W = np.hypot(axial, tangential)
    q = 0.5 * fluid.density_kg_m3 * W**2
    alpha = np.radians(st['alpha'])
    return {'fn': q * chord * st['cn'], 'ft': q * chord * st['ct'], 'chord_normal': q * chord * (st['cl'] * np.cos(alpha) + st['cd'] * np.sin(alpha)),
            'alpha_deg': st['alpha'], 'a': a, 'phi': phi, 'solved': solved}


def solve(spec, blade, *, precone_deg=0.0, relaxation=0.5, iterations=40, tolerance=1e-5, twist=None, attachments=()):
    """Steady aeroelastic operating point of a HAWT; returns coefficients, deflections and the rigid reference."""
    built, rotor, fluid = rotors.build(rotors.merged(spec))
    if built['kind'] != 'hawt':
        raise AeroelasticError('The steady aeroelastic model applies to horizontal-axis turbines')
    V, rpm = rotors.resolve_operating(built, rotor)
    corrections = rotors.checked_corrections('hawt', built.get('corrections'))
    omega = rpm * math.pi / 30
    hub, R = float(rotor.hub_radius_m), float(rotor.tip_radius_m)
    L = R - hub
    inner = (rotor.radius_m > hub + 1e-9) & (rotor.radius_m < R - 1e-9) & (rotor.chord_m > 0)
    r0, chord = rotor.radius_m[inner], rotor.chord_m[inner]
    theta0 = np.radians(rotor.twist_deg[inner] + rotor.pitch_deg)
    s = r0 - hub
    x = s / L
    beam = modal.blade_beam(blade, L, twist, attachments)
    extended = blade.get('extended') or {}
    fraction = np.array([row[0] for row in blade['stations']])
    gj = np.interp(x, fraction, extended['torsional_stiffness_nm2']) if 'torsional_stiffness_nm2' in extended else None
    offset = np.interp(x, fraction, extended['elastic_axis_offset_m']) if 'elastic_axis_offset_m' in extended else np.zeros_like(x)
    beta = np.full_like(s, math.radians(precone_deg))
    twist_e = np.zeros_like(s)
    history = []
    for step in range(iterations):
        grid = np.concatenate([[0.0], s])
        cos_grid = np.concatenate([[math.cos(beta[0])], np.cos(beta)])
        r = hub + np.concatenate([[0.0], np.cumsum((cos_grid[1:] + cos_grid[:-1]) / 2 * np.diff(grid))])[1:]
        f = _bemt(rotor, fluid, corrections, V=V * np.cos(beta), omega=omega, r=r, s=s, chord=chord, theta=theta0 - twist_e)
        positions = np.concatenate([[0.0], x, [1.0]])
        pad = lambda v: np.concatenate([[v[0]], v, [0.0]])  # noqa: E731
        xs, w, v = flexible.deflection(beam, omega=omega, hub_radius=hub, positions=positions, loads_out=pad(f['fn']), loads_in=pad(f['ft']))
        slope = np.gradient(w, xs * L)
        new_beta = math.radians(precone_deg) + np.arctan(np.interp(x, xs, slope))
        new_twist = twist_e
        if gj is not None:
            moment = f['chord_normal'] * offset
            new_twist = _torsion(np.concatenate([[0.0], s]), np.concatenate([[moment[0]], moment]), np.concatenate([[gj[0]], gj]))[1:]
        change = max(float(np.max(np.abs(new_beta - beta))), float(np.max(np.abs(new_twist - twist_e))))
        beta = beta + relaxation * (new_beta - beta) if step else new_beta
        twist_e = twist_e + relaxation * (new_twist - twist_e) if step else new_twist
        history.append(change)
        if change < tolerance:
            break
    nodes = np.concatenate([[0.0], s, [L]])
    thrust = int(rotor.blades) * float(np.trapezoid(np.concatenate([[0.0], f['fn'] * np.cos(beta), [0.0]]), nodes))
    torque = int(rotor.blades) * float(np.trapezoid(np.concatenate([[0.0], f['ft'] * r, [0.0]]), nodes))
    area = math.pi * R**2
    rho = fluid.density_kg_m3
    rigid = rotors.analyze(built)
    return {'CP': torque * omega / (0.5 * rho * area * V**3), 'CT': thrust / (0.5 * rho * area * V**2), 'power_w': torque * omega,
            'thrust_n': thrust, 'torque_nm': torque, 'CP_rigid': rigid['coefficients']['CP'], 'CT_rigid': rigid['coefficients']['CT'],
            'tip_flap_m': float(w[-1]), 'tip_edge_m': float(v[-1]), 'tip_twist_deg': float(np.degrees(twist_e[-1])),
            'tip_cone_deg': float(np.degrees(beta[-1])), 'iterations': len(history), 'converged': bool(history and history[-1] < tolerance),
            'stations': {'span_m': s.tolist(), 'radius_m': r.tolist(), 'cone_deg': np.degrees(beta).tolist(),
                         'elastic_twist_deg': np.degrees(twist_e).tolist(), 'alpha_deg': np.asarray(f['alpha_deg']).tolist()},
            'velocity_m_s': V, 'rpm': rpm, 'torsion': gj is not None}
