"""Structural modal analysis without aerodynamics: clamped blade, rotating blade, tower and Campbell diagram.

Every component is an Euler–Bernoulli beam discretised with cubic Hermite elements (two degrees of freedom
per node: deflection and slope) and consistent mass matrices, clamped at the root (blade) or base (tower).

* Rotating blade: the centrifugal tension T(x) = Ω² ∫ₓᴸ m(s)(r_hub + s) ds adds the geometric stiffness
  Ω²K_G to both directions. In-plane (edgewise) bending also loses Ω²M from the centrifugal component
  along the deflection ("spin softening"). Flap and edge are uncoupled: structural twist, precone and
  Coriolis coupling are not modelled.
* Tower: top mass (nacelle + hub + blades) and optional rotary inertia lumped at the free end.
* Attachments: point masses, rotary inertias, grounded springs and dampers at any position, distributed
  with the Hermite shape functions so they need not sit on a node.
* Damping: modal structural damping ratio for every mode plus the discrete dampers. Without discrete
  dampers the undamped problem is solved with a symmetric eigensolver; with them the 2n state-space
  problem gives damped frequencies and damping ratios.

The matrices are small (≈ 160 degrees of freedom), so dense eigensolvers are exact and fast; iterative
(Arnoldi/Lanczos) solvers are not needed at this size.
"""
import numpy as np
from scipy.linalg import eig, eigh
from scipy.optimize import linear_sum_assignment

ELEMENTS = 80
MAX_MODES = 8
SHAPE_POINTS = 41


class ModalError(ValueError):
    pass


# ------------------------------------------------------------------ matrices

def _hermite(xi, h):
    """Translation and slope shape functions at local coordinate xi ∈ [0, 1] of an element of length h."""
    n = np.array([1 - 3 * xi**2 + 2 * xi**3, h * (xi - 2 * xi**2 + xi**3), 3 * xi**2 - 2 * xi**3, h * (xi**3 - xi**2)])
    dn = np.array([(-6 * xi + 6 * xi**2) / h, 1 - 4 * xi + 3 * xi**2, (6 * xi - 6 * xi**2) / h, 3 * xi**2 - 2 * xi])
    return n, dn


class Beam:
    """Clamped-free Hermite beam over the normalised length 0–1."""

    def __init__(self, fraction, mass_per_length, stiffness, length_m, elements=ELEMENTS):
        fraction = np.asarray(fraction, dtype=float)
        mass_per_length = np.asarray(mass_per_length, dtype=float)
        stiffness = np.asarray(stiffness, dtype=float)
        if not np.isfinite(length_m) or length_m <= 0:
            raise ModalError('Length must be positive')
        if fraction.ndim != 1 or len(fraction) < 2 or fraction.shape != mass_per_length.shape or fraction.shape != stiffness.shape:
            raise ModalError('Distributions need at least two stations of equal length')
        if np.any(mass_per_length <= 0) or np.any(stiffness <= 0):
            raise ModalError('Mass per length and stiffness must be positive')
        self.length = float(length_m)
        self.elements = int(elements)
        self.nodes = np.linspace(0.0, 1.0, self.elements + 1)
        middle = 0.5 * (self.nodes[:-1] + self.nodes[1:])
        self.m = np.interp(middle, fraction, mass_per_length)
        self.ei = np.interp(middle, fraction, stiffness)
        self.h = self.length / self.elements
        size = 2 * (self.elements + 1)
        h = self.h
        ke = np.array([[12, 6 * h, -12, 6 * h], [6 * h, 4 * h**2, -6 * h, 2 * h**2],
                       [-12, -6 * h, 12, -6 * h], [6 * h, 2 * h**2, -6 * h, 4 * h**2]])
        me = np.array([[156, 22 * h, 54, -13 * h], [22 * h, 4 * h**2, 13 * h, -3 * h**2],
                       [54, 13 * h, 156, -22 * h], [-13 * h, -3 * h**2, -22 * h, 4 * h**2]])
        self.K = np.zeros((size, size))
        self.M = np.zeros((size, size))
        self.C = np.zeros((size, size))
        for e in range(self.elements):
            at = slice(2 * e, 2 * e + 4)
            self.K[at, at] += self.ei[e] / h**3 * ke
            self.M[at, at] += self.m[e] * h / 420.0 * me
        self.tip_mass = 0.0
        self.point_masses = []  # (position fraction, mass) used by the centrifugal tension

    @property
    def mass_kg(self):
        return float(np.sum(self.m) * self.h + self.tip_mass + sum(m for _, m in self.point_masses))

    def _locate(self, position):
        if not 0.0 <= position <= 1.0:
            raise ModalError('Attachment position must be between 0 and 1')
        e = min(int(position * self.elements), self.elements - 1)
        xi = position * self.elements - e
        n, dn = _hermite(xi, self.h)
        return slice(2 * e, 2 * e + 4), n, dn

    def add_point(self, position, mass=0.0, inertia=0.0, stiffness=0.0, damping=0.0, rotational_stiffness=0.0,
                  rotational_damping=0.0):
        at, n, dn = self._locate(position)
        self.M[at, at] += mass * np.outer(n, n) + inertia * np.outer(dn, dn)
        self.K[at, at] += stiffness * np.outer(n, n) + rotational_stiffness * np.outer(dn, dn)
        self.C[at, at] += damping * np.outer(n, n) + rotational_damping * np.outer(dn, dn)
        if mass:
            if position == 1.0:
                self.tip_mass += mass
            else:
                self.point_masses.append((position, mass))

    def tension(self, omega, hub_radius=0.0):
        """Centrifugal axial force at each element midpoint (N)."""
        x = 0.5 * (self.nodes[:-1] + self.nodes[1:]) * self.length
        force = self.m * self.h * (hub_radius + x)
        outboard = np.concatenate([np.cumsum(force[::-1])[::-1][1:], [0.0]]) + 0.5 * force
        outboard += self.tip_mass * (hub_radius + self.length)
        for position, mass in self.point_masses:
            outboard += np.where(x < position * self.length, mass * (hub_radius + position * self.length), 0.0)
        return omega**2 * outboard

    def geometric_stiffness(self, tension):
        h = self.h
        g = np.array([[36, 3 * h, -36, 3 * h], [3 * h, 4 * h**2, -3 * h, -h**2],
                      [-36, -3 * h, 36, -3 * h], [3 * h, -h**2, -3 * h, 4 * h**2]]) / (30.0 * h)
        out = np.zeros_like(self.K)
        for e in range(self.elements):
            at = slice(2 * e, 2 * e + 4)
            out[at, at] += tension[e] * g
        return out


# ------------------------------------------------------------------ eigen solution

def _solve(K, M, C, modes, damping_ratio):
    free = slice(2, K.shape[0])
    K, M, C = K[free, free], M[free, free], C[free, free]
    count = min(modes, K.shape[0])
    values, vectors = eigh(K, M)
    if values[0] <= 0:
        raise ModalError('The structure is unstable at this rotor speed (negative stiffness)')
    omega = np.sqrt(values)
    if not np.any(C):
        omega, vectors = omega[:count], vectors[:, :count]
        ratio = np.full(count, damping_ratio)
        return omega, ratio, omega * np.sqrt(np.maximum(1 - ratio**2, 0.0)) / (2 * np.pi), vectors
    # modal structural damping over every mode, plus the discrete dampers, solved in state space
    modal = M @ vectors @ np.diag(2 * damping_ratio * omega) @ vectors.T @ M
    size = K.shape[0]
    Minv = np.linalg.inv(M)
    A = np.block([[np.zeros((size, size)), np.eye(size)], [-Minv @ K, -Minv @ (C + modal)]])
    lam, vec = eig(A)
    keep = lam.imag > 1e-9
    lam, vec = lam[keep], vec[:size, keep]
    order = np.argsort(np.abs(lam))[:count]
    lam, vec = lam[order], vec[:, order]
    natural = np.abs(lam)
    ratio = -lam.real / natural
    shapes = np.empty((size, len(order)))
    for k in range(len(order)):
        v = vec[:, k]
        v = v / v[np.argmax(np.abs(v))]
        shapes[:, k] = v.real
    return natural, ratio, lam.imag / (2 * np.pi), shapes


def _shapes(vectors):
    """Deflection (translation dofs) with the clamped node prepended, unit maximum, positive at the tip."""
    out = []
    for k in range(vectors.shape[1]):
        w = np.concatenate([[0.0], vectors[0::2, k]])
        peak = w[np.argmax(np.abs(w))]
        w = w / peak if abs(peak) > 1e-15 else w
        if w[-1] < 0:
            w = -w
        out.append(w)
    return out


def _zero_crossings(w):
    signs = np.sign(w[1:][np.abs(w[1:]) > 1e-3])
    return int(np.sum(signs[1:] != signs[:-1]))


def mac(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return float(np.dot(a, b) ** 2 / (np.dot(a, a) * np.dot(b, b)))


def modes(beam, *, modes=3, omega=0.0, hub_radius=0.0, direction='flap', damping_ratio=0.0, label='Mode'):
    """Modes of a (possibly rotating) clamped beam: list of dicts with frequency, damping and unit shape."""
    if not 1 <= modes <= MAX_MODES:
        raise ModalError(f'Between 1 and {MAX_MODES} modes can be computed')
    if direction not in ('flap', 'edge', 'none'):
        raise ModalError('direction must be flap, edge or none')
    K = beam.K.copy()
    if omega:
        K += beam.geometric_stiffness(beam.tension(omega, hub_radius))
        if direction == 'edge':
            K -= omega**2 * beam.M
    natural, ratio, damped, vectors = _solve(K, beam.M, beam.C, modes, damping_ratio)
    out = []
    for k, w in enumerate(_shapes(vectors)):
        out.append({'label': f'{label} {k + 1}', 'natural_hz': float(natural[k] / (2 * np.pi)),
                    'frequency_hz': float(damped[k]), 'damping_ratio': float(ratio[k]),
                    'nodes': _zero_crossings(w), 'shape': w})
    return out


def sample(beam, shape, points=SHAPE_POINTS):
    x = np.linspace(0.0, 1.0, points)
    return [round(float(v), 6) for v in np.interp(x, beam.nodes, shape)]


def track(previous, current):
    """Reorder `current` modes so each follows the most similar `previous` mode (MAC assignment)."""
    cost = np.array([[1.0 - mac(p['shape'], c['shape']) for c in current] for p in previous])
    rows, cols = linear_sum_assignment(cost)
    order = [cols[i] for i in np.argsort(rows)]
    rest = [i for i in range(len(current)) if i not in order]
    return [current[i] for i in order + rest], [float(1.0 - cost[r, c]) for r, c in zip(rows, cols)]


# ------------------------------------------------------------------ components

def blade_beam(blade, length_m, direction, attachments=()):
    fraction, mass, flap, edge = (np.array(c) for c in zip(*blade['stations']))
    beam = Beam(fraction, mass, flap if direction == 'flap' else edge, length_m)
    if blade.get('tip_mass_kg'):
        beam.add_point(1.0, mass=blade['tip_mass_kg'])
    _attach(beam, attachments, 'blade', direction)
    return beam


def tower_beam(tower, direction, top_mass_kg=0.0, top_inertia_kg_m2=0.0, attachments=()):
    x, mass, fa, ss = (np.array(c) for c in zip(*tower['stations']))
    beam = Beam(x, mass, fa if direction == 'fore_aft' else ss, tower['height_m'])
    if top_mass_kg or top_inertia_kg_m2:
        beam.add_point(1.0, mass=top_mass_kg, inertia=top_inertia_kg_m2)
    _attach(beam, attachments, 'tower', direction)
    return beam


def _attach(beam, attachments, target, direction):
    for a in attachments or ():
        if a['target'] != target or a.get('direction', 'both') not in ('both', direction):
            continue
        beam.add_point(a['position'], mass=a.get('mass_kg', 0.0), inertia=a.get('inertia_kg_m2', 0.0),
                       stiffness=a.get('stiffness_n_m', 0.0), damping=a.get('damping_ns_m', 0.0),
                       rotational_stiffness=a.get('rotational_stiffness_nm_rad', 0.0),
                       rotational_damping=a.get('rotational_damping_nms_rad', 0.0))


def blade_mass_kg(blade, length_m, attachments=()):
    return blade_beam(blade, length_m, 'flap', attachments).mass_kg


def campbell(blade, blade_length_m, hub_radius_m, blades, rpm, *, tower=None, top_mass_kg=0.0, top_inertia_kg_m2=0.0,
             flap_modes=2, edge_modes=1, tower_modes=2, harmonics=None, attachments=()):
    """Campbell diagram over `rpm` (rotating-frame blade modes, fixed tower modes, nP excitation lines)."""
    rpm = np.asarray(rpm, dtype=float)
    if rpm.ndim != 1 or len(rpm) < 2 or np.any(rpm < 0) or np.any(np.diff(rpm) <= 0):
        raise ModalError('Rotor speeds must be at least two increasing, non-negative values')
    harmonics = sorted(set(harmonics or [1, blades, 2 * blades]))
    curves = []
    for direction, count, ratio in (('flap', flap_modes, blade.get('flap_damping_pct', 0.0) / 100),
                                    ('edge', edge_modes, blade.get('edge_damping_pct', 0.0) / 100)):
        if not count:
            continue
        beam = blade_beam(blade, blade_length_m, direction, attachments)
        family = [[] for _ in range(count)]
        mac_min = [1.0] * count
        previous = None
        for speed in rpm:
            found = modes(beam, modes=count, omega=speed * np.pi / 30, hub_radius=hub_radius_m, direction=direction,
                          damping_ratio=ratio, label=f'Blade {direction}')
            if previous is not None:
                found, similarity = track(previous, found)
                mac_min = [min(a, b) for a, b in zip(mac_min, similarity)]
            previous = found
            for k in range(count):
                family[k].append(found[k])
        for k in range(count):
            curves.append({'id': f'blade_{direction}{k + 1}', 'label': f'Blade {direction} {k + 1}', 'component': 'blade',
                           'direction': direction, 'frame': 'rotating',
                           'frequency_hz': [m['frequency_hz'] for m in family[k]],
                           'damping_ratio': [m['damping_ratio'] for m in family[k]],
                           'shapes': [sample(beam, m['shape']) for m in family[k]], 'tracking_mac_min': mac_min[k]})
    if tower is not None and tower_modes:
        for direction, short in (('fore_aft', 'fa'), ('side_side', 'ss')):
            beam = tower_beam(tower, direction, top_mass_kg, top_inertia_kg_m2, attachments)
            found = modes(beam, modes=tower_modes, direction='none', damping_ratio=tower.get('damping_pct', 0.0) / 100,
                          label=f'Tower {direction}')
            for k, m in enumerate(found):
                curves.append({'id': f'tower_{short}{k + 1}', 'label': f'Tower {direction.replace("_", "-")} {k + 1}',
                               'component': 'tower', 'direction': direction, 'frame': 'fixed',
                               'frequency_hz': [m['frequency_hz']] * len(rpm), 'damping_ratio': [m['damping_ratio']] * len(rpm),
                               'shapes': [sample(beam, m['shape'])], 'tracking_mac_min': 1.0})
    excitation = {f'{h}P': (h * rpm / 60.0).tolist() for h in harmonics}
    crossings = []
    for curve in curves:
        f = np.asarray(curve['frequency_hz'])
        for h in harmonics:
            gap = f - h * rpm / 60.0
            for i in np.nonzero(np.sign(gap[:-1]) * np.sign(gap[1:]) < 0)[0]:
                t = gap[i] / (gap[i] - gap[i + 1])
                at = float(rpm[i] + t * (rpm[i + 1] - rpm[i]))
                crossings.append({'mode': curve['id'], 'harmonic': f'{h}P', 'rpm': at,
                                  'frequency_hz': float(f[i] + t * (f[i + 1] - f[i]))})
    return {'rpm': rpm.tolist(), 'curves': curves, 'excitation': excitation, 'harmonics': harmonics,
            'crossings': sorted(crossings, key=lambda c: c['rpm'])}


def whirl(curve, rpm):
    """Approximate fixed-frame frequencies of an isotropic rotor's asymmetric blade modes: f ± Ω/2π."""
    f, p = np.asarray(curve['frequency_hz']), np.asarray(rpm) / 60.0
    return {'backward': np.abs(f - p).tolist(), 'forward': (f + p).tolist()}


def margins(result, operating_rpm):
    """Smallest relative distance (%) of every mode from every excitation harmonic at the operating speed."""
    rpm = np.asarray(result['rpm'])
    worst, at = np.inf, None
    values = {}
    for curve in result['curves']:
        f = float(np.interp(operating_rpm, rpm, curve['frequency_hz']))
        values[curve['id']] = f
        for h in result['harmonics']:
            excitation = h * operating_rpm / 60.0
            if excitation <= 0:
                continue
            margin = abs(f - excitation) / excitation * 100.0
            if margin < worst:
                worst, at = margin, f'{curve["id"]} vs {h}P'
    return values, (float(worst) if np.isfinite(worst) else None), at
