"""Quasi-static blade flexibility for performance curves.

The rotating 3-D beam of ``nova.physics.modal`` (with centrifugal stiffening) is loaded by the BEMT
distributed thrust (out of plane) and torque force (in plane) of one blade. The steady flapwise slope
cones the blade element by β(s) = precone + atan(dw/ds). A coned element sees the normal wind component
V cos β and moves at Ω s cos β: the local speed ratio is unchanged, the dynamic pressure scales with cos²β
and the torque arm (and the axial projection of the normal force) with cos β, so the element's power and
thrust contributions scale with cos³β. The loads are recomputed with the deflected shape until the cone
angles settle (fixed-point iteration). Elastic twist, prebend, sweep and the in-plane deflection's effect
on the aerodynamics are not modelled.
"""
import numpy as np

from . import modal


class FlexibilityError(ValueError):
    pass


def _load_vector(beam, positions, loads_out, loads_in):
    """Consistent nodal loads of distributed forces (N/m) given at `positions` (0–1) on the free degrees of freedom."""
    F = np.zeros(beam.size)
    xi, w = beam._full
    n, _ = modal._lagrange(beam.ref, xi)
    for e in range(beam.elements):
        a, b = beam.edges[e], beam.edges[e + 1]
        jac = (b - a) * beam.length / 2
        x = a + (xi + 1) / 2 * (b - a)
        f_out = np.interp(x, positions, loads_out, left=0.0, right=0.0)
        f_in = np.interp(x, positions, loads_in, left=0.0, right=0.0)
        dofs = beam._element_dofs(e)
        for g in range(len(xi)):
            F[dofs[2::6]] += n[g] * f_out[g] * w[g] * jac
            F[dofs[1::6]] += n[g] * f_in[g] * w[g] * jac
    return F


def deflection(beam, *, omega, hub_radius, positions, loads_out, loads_in, samples=101):
    """Steady out-of-plane and in-plane deflection (m) of the rotating clamped blade under distributed loads."""
    K = beam.K.copy()
    if omega:
        K += omega**2 * beam.rotating(hub_radius)[0]
    free = np.arange(6, beam.size)
    F = _load_vector(beam, np.asarray(positions), np.asarray(loads_out), np.asarray(loads_in))
    try:
        u = np.linalg.solve(K[np.ix_(free, free)], F[free])
    except np.linalg.LinAlgError as exc:
        raise FlexibilityError('The blade stiffness matrix is singular') from exc
    nodal = np.concatenate([np.zeros(6), u]).reshape(-1, 6)
    x = np.linspace(0.0, 1.0, samples)
    P = beam.interpolation(samples)
    return x, P @ nodal[:, 2], P @ nodal[:, 1]


def coned(result, beam, *, blades, hub_radius, omega, precone_deg=0.0, iterations=4, tolerance=1e-4):
    """Cone angles and the cos³β factors on power and thrust of a BEMT result for a flexible blade."""
    stations = result['stations']
    radius = np.array([s['radius_m'] for s in stations])
    thrust = np.array([s['d_thrust_n_m'] for s in stations]) / blades
    torque = np.array([s['d_torque_nm_m'] for s in stations]) / blades
    positions = (radius - hub_radius) / beam.length
    if np.any(positions < -1e-6) or np.any(positions > 1 + 1e-6):
        raise FlexibilityError('Blade structure length does not match the rotor (stations outside the blade)')
    in_plane = torque / np.maximum(radius, 1e-9)
    factor = np.ones_like(radius)
    load = np.ones_like(radius)  # normal force on a coned element scales with cos²β
    previous = None
    beta = np.full_like(radius, np.radians(precone_deg))
    for _ in range(iterations):
        x, w, v = deflection(beam, omega=omega, hub_radius=hub_radius, positions=positions, loads_out=thrust * load,
                             loads_in=in_plane * load)
        slope = np.gradient(w, x * beam.length)
        beta = np.radians(precone_deg) + np.arctan(np.interp(positions, x, slope))
        factor, load = np.cos(beta) ** 3, np.cos(beta) ** 2
        if previous is not None and np.max(np.abs(beta - previous)) < tolerance:
            break
        previous = beta
    weight_p = np.trapezoid(torque, radius)
    weight_t = np.trapezoid(thrust, radius)
    return {'power_factor': float(np.trapezoid(torque * factor, radius) / weight_p) if weight_p else 1.0,
            'thrust_factor': float(np.trapezoid(thrust * factor, radius) / weight_t) if weight_t else 1.0,
            'tip_flap_m': float(w[-1]), 'tip_edge_m': float(v[-1]), 'tip_cone_deg': float(np.degrees(beta[-1])),
            'mean_cone_deg': float(np.degrees(np.average(beta, weights=np.abs(torque) + 1e-12))),
            'shape': {'x': x.tolist(), 'flap_m': w.tolist(), 'edge_m': v.tolist()}}
