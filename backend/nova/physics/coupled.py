"""Rotor–tower coupled modal analysis in multi-blade coordinates (no aerodynamics, no gravity).

Model
-----
Generalised coordinates: the modal coordinates η of the tower (clamped at the base, nacelle as a rigid
body at the top, *without* the rotor) and, for every blade b, the modal coordinates q_b of the rotating
blade at the current speed Ω (real undamped modes of the 3-D beam with centrifugal stiffening and spin
softening; their Coriolis matrix is kept). The rotor is not reduced to a rigid disc: every blade mass
point moves with the tower top. A material point of blade b at radius r is at

    P = top + u(η) + R(θ(η)) · (d + r e_r(ψ_b) + u_b e_r + v_b e_t + w_b e_z),

where u, θ are the tower-top translation and rotation, d the hub centre from the tower top (shaft height,
overhang), ψ_b = ψ + 2πb/B the blade azimuth, e_r, e_t, e_z the radial, in-plane and shaft directions,
and R(θ) ≈ I + [θ×] + ½[θ×]². The kinetic energy is expanded to second order in the coordinates; the
first-order velocities give mass, Coriolis and centrifugal terms between tower and blades, the
second-order positions give the centrifugal (and gyroscopic) terms of the tower rotations. The
blade–blade block is replaced by the 3-D beam's own rotating-frame matrices, which already include
those effects with the full section model. A rotating hub is represented by a ring of point masses
with the hub inertia about the shaft.

The equations M(ψ) ẍ + D(ψ) ẋ + K(ψ) x = 0 are periodic in ψ = Ωt. They are transformed to
multi-blade coordinates (collective, cosine and sine cyclic, and the differential mode for an even blade
count), x = T(ψ) z, and the transformed first-order system matrix is averaged over azimuth — the MBC3
approach of Bir (2008). For an isotropic rotor with three or more blades the averaged system is exact for
the 0P/1P coupling and drops only the higher-harmonic (BP) residuals.
"""
import numpy as np
from scipy.linalg import eig
from scipy.optimize import linear_sum_assignment

from . import modal

AZIMUTHS = 36
SAMPLES = 81
HUB_RING = 6
EPS = 1e-4


class CoupledError(ValueError):
    pass


def _sample(beam, positions):
    """Interpolation of nodal values at positions (0–1)."""
    P = np.zeros((len(positions), len(beam.nodes)))
    for k, position in enumerate(positions):
        e = min(int(np.searchsorted(beam.edges, position, side='right')) - 1, beam.elements - 1)
        a, b = beam.edges[e], beam.edges[e + 1]
        n, _ = modal._lagrange(beam.ref, 2 * (position - a) / (b - a) - 1)
        P[k, e * beam.order:e * beam.order + beam.order + 1] = n[0]
    return P


def _classify(q, weights, names):
    energy = np.zeros(4)
    for dof in range(6):
        energy[modal.DOF_FAMILY[dof]] += np.sum(np.abs(q[dof::6]) ** 2 * weights[dof::6])
    energy = energy / max(energy.sum(), 1e-300)
    return names[int(np.argmax(energy))]


def _mass_points(beam):
    """Lumped mass points (position 0–1, mass) representing the blade's translational inertia."""
    x = np.linspace(0.0, 1.0, SAMPLES)
    m = beam.sections.at('mass', x) * beam.length
    w = np.full(SAMPLES, 1.0 / (SAMPLES - 1))
    w[0] = w[-1] = 0.5 / (SAMPLES - 1)
    positions, masses = list(x), list(m * w)
    for position, mass, _, _ in beam.bodies:
        if mass:
            positions.append(position)
            masses.append(mass)
    return np.array(positions), np.array(masses)


class Tower:
    """Tower modal basis with the top motion (translation, rotation) of every mode."""

    def __init__(self, beam, counts, damping_ratio):
        natural, phi, (_, M, _, _) = modal.basis(beam, count=modal.BASIS)
        weights = np.diag(M)
        families = [_classify(phi[:, k], weights, modal.FAMILIES['tower']) for k in range(len(natural))]
        keep, seen = [], {f: 0 for f in counts}
        for k, family in enumerate(families):
            if family in seen and seen[family] < counts[family]:
                keep.append(k)
                seen[family] += 1
        if not keep:
            raise CoupledError('No tower modes selected')
        self.natural = natural[keep]
        self.families = [families[k] for k in keep]
        top = phi[-6:, keep]  # last node: (u_x up, u_y lateral, u_z downwind, θ_x, θ_y, θ_z)
        self.A_u, self.A_theta = top[:3], top[3:]
        self.ratio = damping_ratio
        self.beam = beam
        self.phi = phi[:, keep]
        counts_found = {f: self.families.count(f) for f in counts}
        self.short = {f: (counts_found[f], n) for f, n in counts.items() if counts_found[f] < n}


class Blade:
    """Rotating-frame basis of one blade at a rotor speed."""

    def __init__(self, beam, omega, hub_radius, counts, ratios):
        natural, phi, (_, M, _, G) = modal.basis(beam, omega=omega, hub_radius=hub_radius, count=modal.BASIS)
        weights = np.diag(M)
        families = [_classify(phi[:, k], weights, modal.FAMILIES['blade']) for k in range(len(natural))]
        keep, seen = [], {f: 0 for f in counts}
        for k, family in enumerate(families):
            if family in seen and seen[family] < counts[family]:
                keep.append(k)
                seen[family] += 1
        if not keep:
            raise CoupledError('No blade modes selected')
        self.natural = natural[keep]
        self.families = [families[k] for k in keep]
        self.phi = phi[:, keep]
        self.gyro = self.phi.T @ G @ self.phi
        self.ratio = np.array([ratios.get(f, 0.0) for f in self.families])
        positions, self.masses = _mass_points(beam)
        self.radius = hub_radius + positions * beam.length
        full = np.vstack([np.zeros((6, len(keep))), self.phi]).reshape(-1, 6, len(keep))
        S = _sample(beam, positions)
        self.u = S @ full[:, 0, :]  # radial (axial along the blade)
        self.v = S @ full[:, 1, :]  # in-plane
        self.w = S @ full[:, 2, :]  # out-of-plane (along the shaft)
        m, r = self.masses, self.radius
        Y = np.stack([self.u, self.v, self.w])  # 3 × points × modes
        self.moments = (float(m.sum()), float(m @ r), float(m @ r**2), np.einsum('p,cpk->ck', m, Y), np.einsum('p,cpk->ck', m * r, Y))


def _skew(v):
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def _directions(psi):
    e_r = np.array([np.cos(psi), np.sin(psi), 0.0])   # tower frame: x up, y lateral, z downwind (shaft)
    e_t = np.array([-np.sin(psi), np.cos(psi), 0.0])
    return e_r, e_t


class System:
    """Periodic second-order system of the tower and B blades at a rotor speed."""

    def __init__(self, tower, blades, count, omega, hub_offset, hub_ring=()):
        self.tower, self.blade, self.B, self.omega = tower, blades, count, omega
        self.d = np.asarray(hub_offset, dtype=float)
        self.hub_ring = hub_ring  # (mass, radius) of each hub point
        self.nt, self.nb = len(tower.natural), len(blades.natural)
        self.n = self.nt + self.B * self.nb

    def _quadratic(self, psi):
        """M, N, R of the kinetic energy ½ẋᵀMẋ + ẋᵀNx + ½xᵀRx (blade–blade blocks excluded) at azimuth ψ.

        Every term is a mass moment of a blade (Σm, Σmr, Σmr², ΣmY, ΣmrY with Y the modal displacements),
        so the cost does not depend on the number of mass points."""
        nt, nb, n, Om = self.nt, self.nb, self.n, self.omega
        Au, At = self.tower.A_u, self.tower.A_theta
        M, N, R = np.zeros((n, n)), np.zeros((n, n)), np.zeros((n, n))
        bl = self.blade
        e_z = np.array([0.0, 0.0, 1.0])
        L0 = Au - _skew(self.d) @ At
        bodies = [(psi + 2 * np.pi * b / self.B, bl.moments, b) for b in range(self.B)]
        for k, (mass, radius) in enumerate(self.hub_ring):
            bodies.append((psi + 2 * np.pi * k / len(self.hub_ring), (mass, mass * radius, mass * radius**2, None, None), None))
        for angle, (m0, m1, m2, SY, SrY), b in bodies:
            e_r, e_t = _directions(angle)
            Ler, Let = _skew(e_r) @ At, _skew(e_t) @ At
            # tower–tower
            M[:nt, :nt] += m0 * L0.T @ L0 - m1 * (L0.T @ Ler + Ler.T @ L0) + m2 * Ler.T @ Ler
            N[:nt, :nt] += -Om * (m1 * L0.T @ Let - m2 * Ler.T @ Let)
            N[:nt, :nt] += Om * At.T @ (m1 * (0.5 * (np.outer(self.d, e_t) + np.outer(e_t, self.d)) - (self.d @ e_t) * np.eye(3))
                                       + m2 * 0.5 * (np.outer(e_r, e_t) + np.outer(e_t, e_r))) @ At
            R[:nt, :nt] += Om**2 * m2 * Let.T @ Let + Om**2 * m2 * At.T @ (np.outer(e_t, e_t) - np.eye(3)) @ At
            if b is None:
                continue
            cols = slice(nt + b * nb, nt + (b + 1) * nb)
            E = np.column_stack([e_r, e_t, e_z])
            dE = np.column_stack([e_t, -e_r, np.zeros(3)])
            ESY, ESrY, dESY, dESrY = E @ SY, E @ SrY, dE @ SY, dE @ SrY
            Mtq = L0.T @ ESY - Ler.T @ ESrY
            M[:nt, cols] += Mtq
            M[cols, :nt] += Mtq.T
            St = _skew(e_t)
            N[:nt, cols] += Om * (L0.T @ dESY - Ler.T @ dESrY) - Om * At.T @ St @ ESrY
            N[cols, :nt] += -Om * ESrY.T @ Let - Om * (At.T @ St @ ESrY).T
            Rtq = -Om**2 * Let.T @ dESrY - Om**2 * At.T @ St @ dESrY
            R[:nt, cols] += Rtq
            R[cols, :nt] += Rtq.T
        return M, N, R

    def matrices(self, psi):
        """M, D, K of M ẍ + D ẋ + K x = 0 at azimuth ψ (d/dt = Ω d/dψ)."""
        M, N, R = self._quadratic(psi)
        Om = self.omega
        if Om:
            Mp, Np, _ = self._quadratic(psi + EPS)
            Mm, Nm, _ = self._quadratic(psi - EPS)
            dM, dN = Om * (Mp - Mm) / (2 * EPS), Om * (Np - Nm) / (2 * EPS)
        else:
            dM = dN = np.zeros_like(M)
        D = dM + N - N.T
        K = dN - R
        nt, nb = self.nt, self.nb
        t = self.tower
        M[:nt, :nt] += np.eye(nt)
        K[:nt, :nt] += np.diag(t.natural**2)
        D[:nt, :nt] += np.diag(2 * t.ratio * t.natural)
        bl = self.blade
        for b in range(self.B):
            cols = slice(nt + b * nb, nt + (b + 1) * nb)
            M[cols, cols] += np.eye(nb)
            K[cols, cols] += np.diag(bl.natural**2)
            D[cols, cols] += bl.gyro + np.diag(2 * bl.ratio * bl.natural)
        return M, D, K

    # ------------------------------------------------------------------ multi-blade coordinates
    def harmonics(self):
        """Multi-blade coordinate labels: 0 (collective), 1c, 1s, …, and d (differential, even B)."""
        labels = ['0']
        for h in range(1, (self.B - 1) // 2 + 1):
            labels += [f'{h}c', f'{h}s']
        if self.B % 2 == 0:
            labels.append('d')
        return labels

    def _blade_rows(self, psi):
        """t[b, j] and its first two ψ-derivatives: q_b = Σ_j t[b, j] z_j for every blade mode."""
        labels = self.harmonics()
        t, t1, t2 = (np.zeros((self.B, len(labels))) for _ in range(3))
        for b in range(self.B):
            a = psi + 2 * np.pi * b / self.B
            for j, label in enumerate(labels):
                if label == '0':
                    t[b, j] = 1.0
                elif label == 'd':
                    t[b, j] = (-1.0) ** b
                else:
                    h = int(label[:-1])
                    if label.endswith('c'):
                        t[b, j], t1[b, j], t2[b, j] = np.cos(h * a), -h * np.sin(h * a), -h * h * np.cos(h * a)
                    else:
                        t[b, j], t1[b, j], t2[b, j] = np.sin(h * a), h * np.cos(h * a), -h * h * np.sin(h * a)
        return t, t1, t2

    def transform(self, psi):
        nt, nb = self.nt, self.nb
        t, t1, t2 = self._blade_rows(psi)
        T, T1, T2 = (np.zeros((self.n, self.n)) for _ in range(3))
        T[:nt, :nt] = np.eye(nt)
        for target, rows in ((T, t), (T1, t1), (T2, t2)):
            target[nt:, nt:] = np.kron(rows, np.eye(nb))
        return T, T1, T2

    def averaged(self, azimuths=AZIMUTHS):
        """Azimuth-averaged first-order system matrix in multi-blade coordinates."""
        Om = self.omega
        acc = np.zeros((2 * self.n, 2 * self.n))
        for psi in np.linspace(0.0, 2 * np.pi, azimuths, endpoint=False):
            M, D, K = self.matrices(psi)
            T, T1, T2 = self.transform(psi)
            Mz = M @ T
            Dz = 2 * Om * M @ T1 + D @ T
            Kz = Om**2 * M @ T2 + Om * D @ T1 + K @ T
            inv = np.linalg.solve(Mz, np.eye(self.n))
            acc[:self.n, self.n:] += np.eye(self.n)
            acc[self.n:, :self.n] -= inv @ Kz
            acc[self.n:, self.n:] -= inv @ Dz
        return acc / azimuths

    def labels(self):
        out = [('tower', f, k) for k, f in enumerate(self.tower.families)]
        for h in self.harmonics():
            for k, f in enumerate(self.blade.families):
                out.append(('blade', f, h))
        return out


def modes(system):
    """Eigen-solution of the averaged MBC system: list of modes with frequency, damping and participation."""
    A = system.averaged()
    lam, vec = eig(A)
    upper = lam.imag > 1e-7
    lam, vec = lam[upper], vec[:system.n, upper]
    order = np.argsort(lam.imag)
    out = []
    labels = system.labels()
    nt, nb = system.nt, system.nb
    harmonics = system.harmonics()
    for k in order:
        z = vec[:, k]
        energy = np.abs(z) ** 2
        energy = energy / max(energy.sum(), 1e-300)
        share = {}
        for weight, (component, family, h) in zip(energy, labels):
            key = f'tower_{family}' if component == 'tower' else f'blade_{family}'
            share[key] = share.get(key, 0.0) + float(weight)
        dominant = max(share, key=share.get)
        whirl = None
        if dominant.startswith('blade'):
            family = dominant.split('_', 1)[1]
            idx = [i for i, f in enumerate(system.blade.families) if f == family]
            group = {h: sum(float(energy[nt + j * nb + i]) for i in idx) for j, h in enumerate(harmonics)}
            cyclic = group.get('1c', 0.0) + group.get('1s', 0.0)
            if group['0'] >= cyclic and group['0'] >= group.get('d', 0.0):
                whirl = 'collective'
            elif group.get('d', 0.0) > cyclic:
                whirl = 'differential'
            else:
                j_c, j_s = harmonics.index('1c'), harmonics.index('1s')
                c = np.array([z[nt + j_c * nb + i] for i in idx])
                s = np.array([z[nt + j_s * nb + i] for i in idx])
                # q_c = Re(C e^{iωt}), q_s = Re(S e^{iωt}); S ≈ −iC is a pattern turning with the rotor
                whirl = 'forward' if np.imag(np.vdot(c, s)) < 0 else 'backward'
        out.append({'frequency_hz': float(lam[k].imag / (2 * np.pi)), 'natural_hz': float(abs(lam[k]) / (2 * np.pi)),
                    'damping_ratio': float(-lam[k].real / abs(lam[k])), 'dominant': dominant, 'whirl': whirl,
                    'participation': share, 'z': z})
    return out


WHIRL_LABEL = {'collective': 'collective', 'forward': 'FW', 'backward': 'BW', 'differential': 'differential'}


def _mode_id(mode):
    if mode['whirl'] is None:
        return mode['dominant']
    return f'{mode["dominant"]}_{mode["whirl"]}'


def _label(mode):
    component, family = mode['dominant'].split('_', 1)
    family = {'fa': 'fore-aft', 'ss': 'side-side'}.get(family, family)
    text = f'{component.capitalize()} {family}'
    if mode['whirl']:
        text += f' {WHIRL_LABEL[mode["whirl"]]}'
    return text


def campbell(blade_beam, tower_beam, *, blades, hub_radius, hub_offset, rpm, blade_counts, tower_counts,
             blade_damping, tower_damping, hub=None):
    """Coupled Campbell diagram in the fixed frame over `rpm`; modes tracked between speeds by MAC."""
    if blades < 3:
        raise CoupledError('The multi-blade-coordinate transformation needs at least three blades')
    rpm = np.asarray(rpm, dtype=float)
    tower = Tower(tower_beam, tower_counts, tower_damping)
    ring = ()
    if hub and hub.get('mass_kg'):
        radius = np.sqrt(max(hub.get('inertia_kg_m2', 0.0), 0.0) / hub['mass_kg'])
        ring = tuple((hub['mass_kg'] / HUB_RING, radius) for _ in range(HUB_RING))
    solutions = []
    for speed in rpm:
        omega = speed * np.pi / 30
        blade = Blade(blade_beam, omega, hub_radius, blade_counts, blade_damping)
        solutions.append(modes(System(tower, blade, blades, omega, hub_offset, ring)))
    # Track from the highest speed down: at standstill the whirl pairs are degenerate and their shapes arbitrary.
    tracks = [[m] for m in solutions[-1]]
    mac_min = [1.0] * len(tracks)
    for index in range(len(rpm) - 2, -1, -1):
        found = solutions[index]
        if len(found) != len(tracks):
            raise CoupledError('The number of coupled modes changed between rotor speeds')
        previous = [t[-1] for t in tracks]
        similarity = np.array([[modal.mac(p['z'], c['z']) for c in found] for p in previous])
        degenerate = rpm[index] == 0.0
        penalty = np.array([[0.0 if degenerate or _mode_id(p) == _mode_id(c) else 0.5 for c in found] for p in previous])
        if degenerate:  # same family, nearest frequency
            penalty = np.array([[(0.0 if p['dominant'] == c['dominant'] else 10.0) + abs(p['frequency_hz'] - c['frequency_hz'])
                                 / max(p['frequency_hz'], 1e-9) for c in found] for p in previous])
            rows, cols = linear_sum_assignment(penalty)
        else:
            rows, cols = linear_sum_assignment(1.0 - similarity + penalty)
        for r, c in zip(rows, cols):
            tracks[r].append(found[c])
            if not degenerate:
                mac_min[r] = min(mac_min[r], float(similarity[r, c]))
    tracks = [t[::-1] for t in tracks]
    curves, used = [], {}
    for track, similarity in zip(tracks, mac_min):
        first = track[-1]
        base = _mode_id(first)
        used[base] = used.get(base, 0) + 1
        ident = f'coupled_{base}{used[base]}'
        label = f'{_label(first)} {used[base]}'
        curves.append({'id': ident, 'label': label, 'component': 'coupled', 'direction': first['dominant'], 'whirl': first['whirl'],
                       'frame': 'fixed', 'frequency_hz': [m['frequency_hz'] for m in track],
                       'damping_ratio': [m['damping_ratio'] for m in track],
                       'participation': [m['participation'] for m in track], 'tracking_mac_min': float(similarity)})
    curves.sort(key=lambda c: c['frequency_hz'][0])
    short = {f'tower {f}': v for f, v in tower.short.items()}
    return curves, short
