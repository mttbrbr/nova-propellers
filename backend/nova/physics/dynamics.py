"""Aeroelastic time-domain model of a horizontal-axis wind turbine.

Structure: the rotor–tower model of ``nova.physics.coupled`` (tower modes; every blade's modes in its rotating
frame; second-order hub kinematics for the mass, Coriolis, centrifugal and gyroscopic coupling), with the blade
basis taken at a reference speed Ω_ref and its stiffness and gyroscopic terms updated with the actual speed:
K_b(Ω) = diag(ω_ref²) + (Ω² − Ω_ref²) Φᵀ S Φ, G_b(Ω) = (Ω/Ω_ref) G_ref. The rotor speed is a degree of freedom:
J Ω̇ = Q_aero − N T_gen (rigid drivetrain). The structure is integrated with the Newmark average-acceleration
scheme; the aerodynamic loads are evaluated at the start of each step (loose coupling).

Aerodynamics, per blade element: the local wind (power-law shear with the element height) minus the structural
velocity of the element (tower top and blade modes) gives the axial and tangential flow; the equilibrium BEMT
induction for that flow (warm-started from the previous step) drives N.O. Øye's dynamic-inflow filter on the
axial induced velocity (Hansen, *Aerodynamics of Wind Turbines*), the tangential induction stays quasi-steady;
the element loads follow from the polar at the resulting angle of attack. Collective pitch from the controller
rotates every section.

Not modelled: tower shadow, yaw, skewed wake, dynamic stall, gravity, drivetrain torsion, blade torsion and
the flap–edge geometric coupling of large deflections; turbulence enters only through the wind signal.
"""
import math

import numpy as np

from . import coupled, modal, rotors
from .axial import _state
from .sections import lift_slope, zero_lift_angle


class DynamicsError(ValueError):
    pass


def _skew(v):
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


class Turbine:
    def __init__(self, spec, blade, *, tower=None, nacelle=None, hub=None, rpm_ref=None, blade_counts=None, tower_counts=None,
                 hub_height_m=None, shear_exponent=0.0, dynamic_inflow=True, rotor_inertia_kg_m2=None, generator_inertia_kg_m2=0.0,
                 gearbox_ratio=1.0):
        built, rotor, fluid = rotors.build(rotors.merged(spec))
        if built['kind'] != 'hawt':
            raise DynamicsError('The aeroelastic turbine model applies to horizontal-axis wind turbines')
        self.rotor, self.fluid = rotor, fluid
        self.corrections = rotors.checked_corrections('hawt', built.get('corrections'))
        V0, rpm0 = rotors.resolve_operating(built, rotor)
        self.rpm_ref = float(rpm_ref or rpm0)
        omega_ref = self.rpm_ref * math.pi / 30
        self.B = int(rotor.blades)
        if self.B < 3:
            raise DynamicsError('The rotor model needs three or more blades')
        hub_r, R = float(rotor.hub_radius_m), float(rotor.tip_radius_m)
        self.R, self.hub_r = R, hub_r
        L = R - hub_r
        twist_fraction = (np.asarray(rotor.radius_m) - hub_r) / L
        aero_twist = np.asarray(rotor.twist_deg) + float(rotor.pitch_deg)
        self.beam = modal.blade_beam(blade, L, lambda x: np.interp(x, twist_fraction, aero_twist))
        self.blade = coupled.Blade(self.beam, omega_ref, hub_r, blade_counts or {'flap': 2, 'edge': 1},
                                   modal.blade_damping(blade))
        # modal stiffening per Ω² in the fixed reference basis
        stiffening, _ = self.beam.rotating(hub_r)
        free = np.arange(6, self.beam.size)
        self.S_modal = self.blade.phi.T @ stiffening[np.ix_(free, free)] @ self.blade.phi
        self.omega_ref = omega_ref
        if tower is not None:
            if nacelle is None:
                raise DynamicsError('The tower needs the nacelle (overhang, shaft height, mass)')
            bodies = [(nacelle['mass_kg'], (nacelle['cm_up_m'], nacelle['cm_lateral_m'], nacelle['cm_downwind_m']),
                       np.diag([nacelle['yaw_inertia_kg_m2'], 0.0, 0.0]))]
            self.tower = coupled.Tower(modal.tower_beam(tower, bodies), tower_counts or {'fa': 1, 'ss': 1}, tower['damping_pct'] / 100)
            offset = (nacelle['tower_top_to_shaft_m'], 0.0, nacelle['overhang_m'])
            self.tower_height = tower['height_m'] + tower.get('base_height_m', 0.0)
        else:
            self.tower = _RigidTower()
            offset = (0.0, 0.0, 0.0)
            self.tower_height = 0.0
        ring = ()
        if hub and hub.get('mass_kg'):
            radius = math.sqrt(max(hub.get('inertia_kg_m2', 0.0), 0.0) / hub['mass_kg'])
            ring = tuple((hub['mass_kg'] / coupled.HUB_RING, radius) for _ in range(coupled.HUB_RING))
        self.system = coupled.System(self.tower, self.blade, self.B, omega_ref, offset, ring)
        self.offset = np.asarray(offset, float)
        self.hub_height = hub_height_m if hub_height_m is not None else (self.tower_height + offset[0] if tower is not None else None)
        self.shear = float(shear_exponent)
        if self.shear > 0 and not self.hub_height:
            raise DynamicsError('Wind shear needs the hub height')
        # aerodynamic elements
        inner = (rotor.radius_m > hub_r + 1e-9) & (rotor.radius_m < R - 1e-9) & (rotor.chord_m > 0)
        self.r = np.asarray(rotor.radius_m)[inner]
        self.chord = np.asarray(rotor.chord_m)[inner]
        self.twist = np.radians(np.asarray(rotor.twist_deg)[inner] + float(rotor.pitch_deg))
        nodes = np.concatenate([[hub_r], self.r, [R]])
        self.ds = (nodes[2:] - nodes[:-2]) / 2
        S = coupled._sample(self.beam, (self.r - hub_r) / L)
        full = np.vstack([np.zeros((6, len(self.blade.natural))), self.blade.phi]).reshape(-1, 6, len(self.blade.natural))
        self.phi_w, self.phi_v = S @ full[:, 2, :], S @ full[:, 1, :]
        tip = coupled._sample(self.beam, [1.0])
        self.tip_w = (tip @ full[:, 2, :])[0]
        # elastic root flap moment per modal coordinate: ω² ∫ m φ_w s ds (mass-normalised modes)
        self.root_moment = self.blade.natural**2 * ((self.blade.masses * (self.blade.radius - hub_r)) @ self.blade.w)
        self.slope = lift_slope(rotor.section, np.tile(self.r, self.B)) if self.corrections.rotational_augmentation != 'none' else 2 * math.pi
        self.alpha0 = zero_lift_angle(rotor.section, np.tile(self.r, self.B)) if self.corrections.rotational_augmentation != 'none' else 0.0
        self.dynamic_inflow = dynamic_inflow
        blade_inertia = self.B * float(self.blade.masses @ self.blade.radius**2)
        hub_inertia = (hub or {}).get('inertia_kg_m2', 0.0) or 0.0
        self.inertia = rotor_inertia_kg_m2 if rotor_inertia_kg_m2 is not None else blade_inertia + hub_inertia
        self.inertia += generator_inertia_kg_m2 * gearbox_ratio**2
        self.gear = gearbox_ratio
        n = self.system.n
        self.x, self.v, self.a = np.zeros(n), np.zeros(n), np.zeros(n)
        self.psi, self.omega = 0.0, rpm0 * math.pi / 30
        count = self.B * len(self.r)
        self.phi = None
        self.W_qs = self.W_int = self.W = np.zeros(count)
        self.V0 = V0

    # ------------------------------------------------------------------ structure
    def matrices(self, psi, omega):
        sys = self.system
        sys.omega = omega
        M, N, R = sys._quadratic(psi)
        if omega:
            h = 1e-4
            Mp, Np, _ = sys._quadratic(psi + h)
            Mm, Nm, _ = sys._quadratic(psi - h)
            dM, dN = omega * (Mp - Mm) / (2 * h), omega * (Np - Nm) / (2 * h)
        else:
            dM = dN = np.zeros_like(M)
        D, K = dM + N - N.T, dN - R
        nt, nb = sys.nt, sys.nb
        t = self.tower
        M[:nt, :nt] += np.eye(nt)
        K[:nt, :nt] += np.diag(t.natural**2)
        D[:nt, :nt] += np.diag(2 * t.ratio * t.natural)
        bl = self.blade
        Kb = np.diag(bl.natural**2) + (omega**2 - self.omega_ref**2) * self.S_modal
        Gb = bl.gyro * (omega / self.omega_ref)
        Db = np.diag(2 * bl.ratio * bl.natural)
        for b in range(self.B):
            cols = slice(nt + b * nb, nt + (b + 1) * nb)
            M[cols, cols] += np.eye(nb)
            K[cols, cols] += Kb
            D[cols, cols] += Gb + Db
        return M, D, K

    def _kinematics(self, psi):
        """Per element: azimuth, radial and tangential directions, and the tower-motion map L_η (3 × nt)."""
        out = []
        Au, At = self.tower.A_u, self.tower.A_theta
        for b in range(self.B):
            a = psi + 2 * math.pi * b / self.B
            e_r = np.array([math.cos(a), math.sin(a), 0.0])
            e_t = np.array([-math.sin(a), math.cos(a), 0.0])
            maps = [Au - _skew(self.offset + r * e_r) @ At for r in self.r]
            out.append((a, e_r, e_t, maps))
        return out

    # ------------------------------------------------------------------ aerodynamics
    def _solve_inflow(self, V, omega_eff, theta):
        """Equilibrium inflow angle and inductions per element, warm-started from the previous step."""
        r = np.tile(self.r, self.B)
        chord = np.tile(self.chord, self.B)
        args = ('turbine', self.rotor, self.fluid, self.corrections)
        tsr = float(np.mean(omega_eff) * self.R / max(np.mean(V), 1e-6))
        station = (r, chord, theta, V, omega_eff, self.slope, self.alpha0, tsr)
        if self.phi is not None:
            lo, hi = np.maximum(self.phi - 0.15, 1e-6), np.minimum(self.phi + 0.15, math.pi / 2)
            f_lo, f_hi = _state(lo, *args, *station)['residual'], _state(hi, *args, *station)['residual']
            bracketed = (f_lo < 0) & (f_hi >= 0)
            if bracketed.all():
                for _ in range(22):
                    mid = 0.5 * (lo + hi)
                    f_mid = _state(mid, *args, *station)['residual']
                    below = f_mid < 0
                    lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
                phi = 0.5 * (lo + hi)
                return phi, _state(phi, *args, *station)
        from .axial import _solve_points
        phi, st, _ = _solve_points('turbine', args, station)
        return phi, st

    def loads(self, wind, pitch_deg, dt):
        """Element loads (per unit length) in the current state; updates the dynamic-inflow states by dt."""
        kin = self._kinematics(self.psi)
        nt, nb = self.system.nt, self.system.nb
        eta_dot = self.v[:nt]
        V, omega_eff, axial_v, tang_v, z = [], [], [], [], []
        for b, (a, e_r, e_t, maps) in enumerate(kin):
            qd = self.v[nt + b * nb: nt + (b + 1) * nb]
            for j, r in enumerate(self.r):
                vel = maps[j] @ eta_dot
                ax = vel[2] + self.phi_w[j] @ qd
                tg = vel @ e_t + self.phi_v[j] @ qd
                height = (self.hub_height or 0.0) + r * math.cos(a)
                local = wind * (max(height, 0.1) / self.hub_height) ** self.shear if self.shear else wind
                axial_v.append(ax)
                tang_v.append(tg)
                V.append(max(local - ax, 0.1))
                omega_eff.append(max((self.omega * r + tg) / r, 1e-3))
                z.append(height)
        V, omega_eff = np.array(V), np.array(omega_eff)
        theta = np.tile(self.twist, self.B) + math.radians(pitch_deg)
        phi, st = self._solve_inflow(V, omega_eff, theta)
        self.phi = phi
        a_qs = np.clip(st['a'], -0.5, 0.95)
        W_qs = a_qs * V
        if self.dynamic_inflow and dt > 0 and np.any(self.W):
            r = np.tile(self.r, self.B)
            tau1 = 1.1 / (1 - 1.3 * np.minimum(a_qs, 0.5)) * self.R / max(wind, 0.5)
            tau2 = (0.39 - 0.26 * (r / self.R) ** 2) * tau1
            H = W_qs + 0.6 * tau1 * (W_qs - self.W_qs) / dt
            self.W_int = H + (self.W_int - H) * np.exp(-dt / tau1)
            self.W = self.W_int + (self.W - self.W_int) * np.exp(-dt / tau2)
        else:
            self.W_int = self.W = W_qs
        self.W_qs = W_qs
        r = np.tile(self.r, self.B)
        axial = V - self.W
        tangential = omega_eff * r * (1 + st['ap'])
        flow = np.arctan2(axial, tangential)
        alpha = np.degrees(flow - theta)
        Wrel = np.hypot(axial, tangential)
        re = self.fluid.density_kg_m3 * Wrel * np.tile(self.chord, self.B) / self.fluid.viscosity_pa_s
        cl, cd = self.rotor.section(alpha, re, r)
        q = 0.5 * self.fluid.density_kg_m3 * Wrel**2 * np.tile(self.chord, self.B)
        fn = q * (cl * np.cos(flow) + cd * np.sin(flow))
        ft = q * (cl * np.sin(flow) - cd * np.cos(flow))
        return kin, fn.reshape(self.B, -1), ft.reshape(self.B, -1), alpha.reshape(self.B, -1)

    def forces(self, kin, fn, ft):
        nt, nb = self.system.nt, self.system.nb
        Q = np.zeros(self.system.n)
        torque = thrust = 0.0
        for b, (_, _, e_t, maps) in enumerate(kin):
            f_n, f_t = fn[b] * self.ds, ft[b] * self.ds
            for j in range(len(self.r)):
                F = np.array([0.0, 0.0, f_n[j]]) + f_t[j] * e_t
                Q[:nt] += maps[j].T @ F
            Q[nt + b * nb: nt + (b + 1) * nb] += self.phi_w.T @ f_n + self.phi_v.T @ f_t
            torque += float(f_t @ self.r)
            thrust += float(f_n.sum())
        return Q, torque, thrust

    # ------------------------------------------------------------------ time step
    def step(self, dt, wind, pitch_deg, generator_torque, fixed_speed=None, aero=True):
        if aero:
            kin, fn, ft, alpha = self.loads(wind, pitch_deg, dt)
            Q, torque, thrust = self.forces(kin, fn, ft)
        else:
            Q, torque, thrust, alpha = np.zeros(self.system.n), 0.0, 0.0, None
        M, D, K = self.matrices(self.psi, self.omega)
        # Newmark, average acceleration (β = 1/4, γ = 1/2)
        Keff = K + 2 / dt * D + 4 / dt**2 * M
        rhs = Q + M @ (4 / dt**2 * self.x + 4 / dt * self.v + self.a) + D @ (2 / dt * self.x + self.v)
        x_new = np.linalg.solve(Keff, rhs)
        v_new = 2 / dt * (x_new - self.x) - self.v
        a_new = 4 / dt**2 * (x_new - self.x) - 4 / dt * self.v - self.a
        self.x, self.v, self.a = x_new, v_new, a_new
        if fixed_speed is not None:
            self.omega = fixed_speed
        else:
            self.omega = max(self.omega + dt * (torque - self.gear * generator_torque) / self.inertia, 0.0)
        self.psi = (self.psi + self.omega * dt) % (2 * math.pi)
        nt, nb = self.system.nt, self.system.nb
        top = self.tower.A_u @ self.x[:nt]
        q1 = self.x[nt:nt + nb]
        return {'aero_torque': torque, 'thrust': thrust, 'aero_power': torque * self.omega,
                'tower_top_fa': float(top[2]), 'tower_top_ss': float(top[1]), 'tip_flap_b1': float(self.tip_w @ q1),
                'root_flap_moment_b1': float(self.root_moment @ q1),
                'alpha_tip_b1': float(alpha[0, -1]) if alpha is not None else None}


class _RigidTower:
    """Tower without degrees of freedom (blade-only rotor on a fixed hub)."""
    natural = np.zeros(0)
    ratio = 0.0
    families = []
    A_u = np.zeros((3, 0))
    A_theta = np.zeros((3, 0))
