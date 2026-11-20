"""Structural modal analysis without aerodynamics: 3-D coupled beam for blades and towers, Campbell diagram.

Beam model
----------
Geometrically linear 3-D Timoshenko beam in the sense of BeamDyn: six degrees of freedom per node
(axial u1, in-plane u2, out-of-plane u3, torsion θ1 and the two section rotations θ2, θ3), generalised
strains [u1', u2' − θ3, u3' + θ2, θ1', θ2', θ3'] and 6×6 sectional stiffness and mass matrices. Axial,
shear, bending and torsion are therefore coupled through the structural twist (principal axes rotate
along the span) and through the offset of the centre of mass from the reference axis.

Frame of a blade: x along the span, y in the rotor plane (edgewise), z along the rotor axis (flapwise).
Frame of a tower: x up, y side-to-side, z fore-aft (downwind).

Discretisation: spectral (high-order Lagrange) elements on Gauss–Lobatto–Legendre nodes; stiffness is
integrated with reduced Gauss quadrature (no shear locking), mass and rotation terms with full
quadrature. Section properties are interpolated linearly between the user's stations at every
quadrature point.

Rotation (blade, about z at Ω, hub radius r_h): the centrifugal tension T(x) gives the geometric
stiffness; the rotating frame adds Coriolis (gyroscopic) coupling and centrifugal softening of the
in-plane motions, the gyroscopic and "propeller moment" terms of the section rotary inertia, and the
centrifugal moment of an offset centre of mass. Precone, prebend and sweep are not modelled.

Missing data: properties that the user does not give are not invented. Missing axial, shear or
torsional stiffness makes that deformation rigid (a large penalty stiffness, about 10⁶ times the
bending scale); missing rotary inertia leaves those rotations without mass, and they are condensed
statically (Guyan, exact for massless degrees of freedom). With bending stiffness and mass only the
model reduces to Euler–Bernoulli.

Solution: dense symmetric eigensolution of the condensed undamped problem, then — when there are
gyroscopic or damping terms — the state-space problem in the basis of the lowest undamped modes.
"""
import numpy as np
from scipy.linalg import eig, eigh
from scipy.optimize import linear_sum_assignment

ELEMENTS = 8        # minimum number of elements
MAX_ELEMENTS = 40   # beyond this many stations the elements are evenly spaced
ORDER = 6           # highest polynomial order
MAX_NODES = 120     # order is lowered so that elements × order stays within this
MAX_MODES = 8
BASIS = 40
SHAPE_POINTS = 41
PENALTY = 1e6
FAMILIES = {'blade': ('axial', 'edge', 'flap', 'torsion'), 'tower': ('axial', 'ss', 'fa', 'torsion')}
# degree of freedom of each node → family index (axial, in-plane, out-of-plane, torsion)
DOF_FAMILY = (0, 1, 2, 3, 2, 1)
FIELDS = ('mass', 'ei_out', 'ei_in', 'ea', 'gj', 'ga_in', 'ga_out', 'i_torsion', 'i_out', 'i_in', 'cm_in', 'twist_deg')


class ModalError(ValueError):
    pass


def _skew(v):
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def _rot_x(deg):
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _gll(order):
    interior = np.polynomial.legendre.Legendre.basis(order).deriv().roots()
    return np.concatenate([[-1.0], np.sort(interior.real), [1.0]])


def _lagrange(nodes, xi):
    """Values and derivatives (d/dξ) of the Lagrange polynomials on `nodes` at the points `xi` (barycentric form)."""
    nodes = np.asarray(nodes, dtype=float)
    xi = np.atleast_1d(np.asarray(xi, dtype=float))
    gap = nodes[:, None] - nodes[None, :]
    np.fill_diagonal(gap, 1.0)
    weights = 1.0 / np.prod(gap, axis=1)
    D = (weights[None, :] / weights[:, None]) / gap
    np.fill_diagonal(D, 0.0)
    np.fill_diagonal(D, -D.sum(axis=1))  # D[i, j] = dN_j/dξ at node i
    distance = xi[:, None] - nodes[None, :]
    exact = np.abs(distance) < 1e-14
    distance[exact] = 1.0
    terms = weights[None, :] / distance
    values = terms / terms.sum(axis=1, keepdims=True)
    hit = exact.any(axis=1)
    values[hit] = exact[hit].astype(float)
    return values, values @ D


class Sections:
    """Section properties over the normalised length, linear between stations.

    `mass` (kg/m), `ei_out` (bending that moves the beam out of plane: blade flap / tower fore-aft, N·m²),
    `ei_in` (blade edge / tower side-side), optional `ea` (N), `gj` (N·m²), `ga_in`, `ga_out` (N, shear),
    `i_torsion`, `i_out`, `i_in` (rotary inertia per length about the section centre of mass, kg·m), `cm_in` (centre-of-mass offset in the
    in-plane direction, m) and `twist_deg` (orientation of the principal axes). Absent stiffness is
    rigid, absent inertia is zero.
    """

    def __init__(self, fraction, **fields):
        self.fraction = np.asarray(fraction, dtype=float)
        if self.fraction.ndim != 1 or len(self.fraction) < 2 or np.any(np.diff(self.fraction) <= 0):
            raise ModalError('Stations must be at least two increasing positions')
        unknown = set(fields) - set(FIELDS)
        if unknown:
            raise ModalError(f'Unknown section fields: {", ".join(sorted(unknown))}')
        self.values = {}
        for key, value in fields.items():
            if value is None:
                continue
            if callable(value):
                self.values[key] = value
                continue
            array = np.asarray(value, dtype=float)
            if array.shape != self.fraction.shape or not np.all(np.isfinite(array)):
                raise ModalError(f'{key} needs one finite value per station')
            self.values[key] = array
        for key in ('mass', 'ei_out', 'ei_in'):
            if key not in self.values or np.any(self.values[key] <= 0):
                raise ModalError('Mass per length and both bending stiffnesses are required and must be positive')
        for key in ('ea', 'gj', 'ga_in', 'ga_out'):
            if key in self.values and np.any(self.values[key] <= 0):
                raise ModalError(f'{key} must be positive')
        for key in ('i_torsion', 'i_out', 'i_in'):
            if key in self.values and np.any(self.values[key] < 0):
                raise ModalError(f'{key} cannot be negative')
        if 'gj' in self.values and 'i_torsion' not in self.values:
            raise ModalError('Torsional stiffness needs the torsional inertia per length as well')

    def has(self, key):
        return key in self.values

    def at(self, key, x, default=0.0):
        value = self.values.get(key)
        if value is None:
            return np.full_like(np.asarray(x, dtype=float), default)
        if callable(value):
            return np.asarray(value(x), dtype=float)
        return np.interp(x, self.fraction, value)


class Beam:
    """Clamped-free 3-D beam over the normalised length 0–1 (clamped at 0)."""

    def __init__(self, sections, length_m, elements=None, order=None):
        if not np.isfinite(length_m) or length_m <= 0:
            raise ModalError('Length must be positive')
        self.sections, self.length = sections, float(length_m)
        edges = _edges(sections.fraction) if elements is None else np.linspace(0.0, 1.0, int(elements) + 1)
        self.elements = len(edges) - 1
        self.order = int(order) if order is not None else max(2, min(ORDER, MAX_NODES // self.elements))
        self.ref = _gll(self.order)
        count = self.elements * self.order + 1
        self.size = 6 * count
        self.edges = edges
        self.nodes = np.concatenate([edges[e] + (self.ref[:-1] + 1) / 2 * (edges[e + 1] - edges[e]) for e in range(self.elements)] + [[1.0]])
        bending = max(np.max(sections.at('ei_out', sections.fraction)), np.max(sections.at('ei_in', sections.fraction)))
        self.penalty = PENALTY * bending / self.length**2
        self.K = np.zeros((self.size, self.size))
        self.M = np.zeros((self.size, self.size))
        self.C = np.zeros((self.size, self.size))
        self.bodies = []  # (position, mass, offset[3], inertia 3×3 about the body centre of mass)
        self._rotating = {}
        self._mass_split = None
        reduced, full = np.polynomial.legendre.leggauss(self.order), np.polynomial.legendre.leggauss(self.order + 2)
        self._full = full
        for e in range(self.elements):
            a, b = edges[e], edges[e + 1]
            jac = (b - a) * self.length / 2
            dofs = self._element_dofs(e)
            xi, w = reduced
            n, dn = _lagrange(self.ref, xi)
            for g in range(len(xi)):
                x = a + (xi[g] + 1) / 2 * (b - a)
                B = self._strain(n[g], dn[g] / jac)
                self.K[np.ix_(dofs, dofs)] += B.T @ self._stiffness(x) @ B * w[g] * jac
            xi, w = full
            n, _ = _lagrange(self.ref, xi)
            for g in range(len(xi)):
                x = a + (xi[g] + 1) / 2 * (b - a)
                N = np.kron(n[g], np.eye(6))
                mass6, *_ = self._mass(x)
                self.M[np.ix_(dofs, dofs)] += N.T @ mass6 @ N * w[g] * jac

    # -------------------------------------------------------------- sections
    def _element_dofs(self, e):
        first = e * self.order
        return np.arange(6 * first, 6 * (first + self.order + 1))

    def _frame(self, x):
        q = _rot_x(float(self.sections.at('twist_deg', x)))
        return np.block([[q, np.zeros((3, 3))], [np.zeros((3, 3)), q]]), q

    def _stiffness(self, x):
        s = self.sections
        p = self.penalty
        local = np.diag([s.at('ea', x, p) if s.has('ea') else p,
                         s.at('ga_in', x) if s.has('ga_in') else p,
                         s.at('ga_out', x) if s.has('ga_out') else p,
                         s.at('gj', x) if s.has('gj') else p * self.length**2,
                         s.at('ei_out', x), s.at('ei_in', x)])
        t, _ = self._frame(x)
        return t @ local @ t.T

    def _mass(self, x):
        """Sectional 6×6 mass matrix about the reference axis, plus mass, centre-of-mass offset and inertia about it."""
        s = self.sections
        m = float(s.at('mass', x))
        _, q = self._frame(x)
        offset = q @ np.array([0.0, float(s.at('cm_in', x)), 0.0])
        about_cm = q @ np.diag([float(s.at('i_torsion', x)), float(s.at('i_out', x)), float(s.at('i_in', x))]) @ q.T
        return _body(m, offset, about_cm), m, offset, about_cm

    @staticmethod
    def _strain(n, dn):
        B = np.zeros((6, 6 * len(n)))
        for i in range(len(n)):
            c = 6 * i
            B[0, c] = dn[i]
            B[1, c + 1], B[1, c + 5] = dn[i], -n[i]
            B[2, c + 2], B[2, c + 4] = dn[i], n[i]
            B[3, c + 3] = dn[i]
            B[4, c + 4] = dn[i]
            B[5, c + 5] = dn[i]
        return B

    def _locate(self, position):
        if not 0.0 <= position <= 1.0:
            raise ModalError('Attachment position must be between 0 and 1')
        e = min(int(np.searchsorted(self.edges, position, side='right')) - 1, self.elements - 1)
        a, b = self.edges[e], self.edges[e + 1]
        n, _ = _lagrange(self.ref, 2 * (position - a) / (b - a) - 1)
        return self._element_dofs(e), np.kron(n[0], np.eye(6))

    # -------------------------------------------------------------- attachments
    def add_body(self, position, mass=0.0, offset=(0.0, 0.0, 0.0), inertia=None):
        """Rigid body at a position: mass with centre-of-mass offset and 3×3 inertia about its centre of mass."""
        offset = np.asarray(offset, dtype=float)
        inertia = np.zeros((3, 3)) if inertia is None else np.asarray(inertia, dtype=float)
        dofs, N = self._locate(position)
        self.M[np.ix_(dofs, dofs)] += N.T @ _body(mass, offset, inertia) @ N
        self.bodies.append((float(position), float(mass), offset, inertia))
        self._rotating.clear()
        self._mass_split = None

    def add_spring(self, position, stiffness=(0.0,) * 6, damping=(0.0,) * 6):
        """Grounded springs and dampers on the six degrees of freedom at a position."""
        dofs, N = self._locate(position)
        self.K[np.ix_(dofs, dofs)] += N.T @ np.diag(stiffness) @ N
        self.C[np.ix_(dofs, dofs)] += N.T @ np.diag(damping) @ N

    @property
    def mass_kg(self):
        x = np.linspace(0, 1, 2001)
        return float(np.trapezoid(self.sections.at('mass', x), x) * self.length + sum(b[1] for b in self.bodies))

    # -------------------------------------------------------------- rotation
    def tension(self, x, hub_radius=0.0):
        """Centrifugal axial force per Ω² (N·s²) at positions x."""
        grid = np.linspace(0.0, 1.0, 4001)
        density = self.sections.at('mass', grid) * (hub_radius + grid * self.length) * self.length
        outboard = np.concatenate([[0.0], np.cumsum((density[1:] + density[:-1]) / 2 * np.diff(grid))])
        outboard = outboard[-1] - outboard
        force = np.interp(x, grid, outboard)
        for position, mass, offset, _ in self.bodies:
            force = force + np.where(np.asarray(x) < position, mass * (hub_radius + position * self.length + offset[0]), 0.0)
        return force

    def rotating(self, hub_radius=0.0):
        """Per-Ω² geometric minus softening stiffness and per-Ω gyroscopic matrix (rotation about z)."""
        key = round(float(hub_radius), 12)
        if key in self._rotating:
            return self._rotating[key]
        axis = np.array([0.0, 0.0, 1.0])
        W = _skew(axis)
        geometric = np.zeros((self.size, self.size))
        soft = np.zeros((self.size, self.size))
        gyro = np.zeros((self.size, self.size))
        xi, w = self._full
        n, dn = _lagrange(self.ref, xi)
        for e in range(self.elements):
            a, b = self.edges[e], self.edges[e + 1]
            jac = (b - a) * self.length / 2
            dofs = self._element_dofs(e)
            x = a + (xi + 1) / 2 * (b - a)
            tension = self.tension(x, hub_radius)
            for g in range(len(xi)):
                D = np.zeros((2, 6 * (self.order + 1)))
                D[0, 1::6] = dn[g] / jac
                D[1, 2::6] = dn[g] / jac
                geometric[np.ix_(dofs, dofs)] += tension[g] * D.T @ D * w[g] * jac
                _, m, offset, inertia = self._mass(x[g])
                N = np.kron(n[g], np.eye(6))
                position = np.array([hub_radius + x[g] * self.length, 0.0, 0.0])
                s6, g6 = _rotation_terms(m, offset, inertia, position, axis, W)
                soft[np.ix_(dofs, dofs)] += N.T @ s6 @ N * w[g] * jac
                gyro[np.ix_(dofs, dofs)] += N.T @ g6 @ N * w[g] * jac
        for position, mass, offset, inertia in self.bodies:
            dofs, N = self._locate(position)
            s6, g6 = _rotation_terms(mass, offset, inertia, np.array([hub_radius + position * self.length, 0.0, 0.0]), axis, W)
            soft[np.ix_(dofs, dofs)] += N.T @ s6 @ N
            gyro[np.ix_(dofs, dofs)] += N.T @ g6 @ N
        self._rotating[key] = (geometric - soft, gyro)
        return self._rotating[key]

    # -------------------------------------------------------------- sampling
    def interpolation(self, points=SHAPE_POINTS):
        cache = self.__dict__.setdefault('_interpolation', {})
        if points not in cache:
            cache[points] = self._interpolation_matrix(points)
        return cache[points]

    def _interpolation_matrix(self, points):
        x = np.linspace(0.0, 1.0, points)
        P = np.zeros((points, len(self.nodes)))
        for k, position in enumerate(x):
            e = min(int(np.searchsorted(self.edges, position, side='right')) - 1, self.elements - 1)
            a, b = self.edges[e], self.edges[e + 1]
            n, _ = _lagrange(self.ref, 2 * (position - a) / (b - a) - 1)
            P[k, e * self.order:e * self.order + self.order + 1] = n[0]
        return P


def _edges(stations):
    """Element boundaries on the stations (properties are linear inside every element), refined to at least
    ELEMENTS elements; evenly spaced when there are too many stations."""
    if len(stations) - 1 > MAX_ELEMENTS:
        return np.linspace(0.0, 1.0, MAX_ELEMENTS + 1)
    edges = np.asarray(stations, dtype=float)
    while len(edges) - 1 < ELEMENTS:
        longest = int(np.argmax(np.diff(edges)))
        edges = np.insert(edges, longest + 1, 0.5 * (edges[longest] + edges[longest + 1]))
    return edges


def _body(mass, offset, inertia):
    """6×6 mass matrix of a rigid body about the reference point (inertia given about its centre of mass)."""
    S = _skew(offset)
    return np.block([[mass * np.eye(3), -mass * S], [mass * S, inertia + mass * S.T @ S]])


def _rotation_terms(mass, offset, inertia, position, axis, W):
    """Per-Ω² softening (to subtract from K) and per-Ω gyroscopic 6×6 matrices of a body in the rotating frame."""
    T = np.hstack([np.eye(3), -_skew(offset)])
    soft = T.T @ (mass * W.T @ W) @ T
    momentum = inertia @ axis
    rot = W.T @ inertia @ W + 0.5 * (np.outer(momentum, axis) + np.outer(axis, momentum)) - (momentum @ axis) * np.eye(3)
    force = mass * (W.T @ W) @ (position + offset)
    rot += 0.5 * (np.outer(force, offset) + np.outer(offset, force)) - (force @ offset) * np.eye(3)
    soft[3:, 3:] += rot
    gyro = T.T @ (2 * mass * W) @ T
    gyro[3:, 3:] += inertia @ W + W @ inertia - _skew(momentum)  # Euler: (J1 + J2 − J3)Ω coupling
    return soft, gyro


# ------------------------------------------------------------------ eigen solution

def mac(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return float(np.abs(np.vdot(a, b)) ** 2 / (np.real(np.vdot(a, a)) * np.real(np.vdot(b, b))))


def basis(beam, *, omega=0.0, hub_radius=0.0, count=BASIS):
    """Lowest undamped real modes of the clamped beam (gyroscopic terms left out): natural angular frequencies,
    mass-normalised shapes on the free degrees of freedom and the free-dof K, M, C, G matrices."""
    K, M, C = beam.K.copy(), beam.M, beam.C
    G = np.zeros_like(K)
    if omega:
        stiffening, gyro = beam.rotating(hub_radius)
        K += omega**2 * stiffening
        G = omega * gyro
    free = np.arange(6, beam.size)
    K, M, C, G = (A[np.ix_(free, free)] for A in (K, M, C, G))
    # Static condensation of the motions without inertia (null space of M): exact for them, and it keeps the
    # undamped problem positive definite when rotary inertias or mass offsets are absent.
    if getattr(beam, '_mass_split', None) is None:
        beam._mass_split = eigh((M + M.T) / 2)
    mass_values, mass_vectors = beam._mass_split
    inertial = mass_values > 1e-10 * mass_values[-1]
    R, Z = mass_vectors[:, inertial], mass_vectors[:, ~inertial]
    T = R
    if Z.shape[1]:
        KZ = K @ Z
        T = R - Z @ np.linalg.solve(Z.T @ KZ, KZ.T @ R)
    Kc = T.T @ K @ T
    Mc = np.diag(mass_values[inertial])
    Kc = (Kc + Kc.T) / 2
    count = min(count, R.shape[1])
    values, vectors = eigh(Kc, Mc, subset_by_index=[0, count - 1])
    if values[0] <= 0:
        raise ModalError('The structure is unstable at this rotor speed (negative stiffness)')
    return np.sqrt(values), T @ vectors, (K, M, C, G)


def solve(beam, *, omega=0.0, hub_radius=0.0, damping=None, component='blade', basis_size=BASIS):
    """All modes of the beam within the reduced basis, lowest first.

    `damping` maps a family name to a modal damping ratio. Returns a list of dicts: family, frequency_hz
    (damped), natural_hz, damping_ratio, participation per family and the full complex vector `q`.
    """
    natural, phi, (K, M, C, G) = basis(beam, omega=omega, hub_radius=hub_radius, count=basis_size)
    count = len(natural)
    names = FAMILIES[component]
    damping = damping or {}
    weights = np.diag(M)

    def family_of(q):
        energy = np.zeros(4)
        for dof in range(6):
            energy[DOF_FAMILY[dof]] += np.sum(np.abs(q[dof::6]) ** 2 * weights[dof::6])
        energy = energy / max(energy.sum(), 1e-300)
        return names[int(np.argmax(energy))], {names[i]: float(energy[i]) for i in range(4)}

    undamped = [family_of(phi[:, k]) for k in range(count)]
    ratio = np.array([damping.get(f, 0.0) for f, _ in undamped])
    if not np.any(G) and not np.any(C):
        out = []
        for k in range(count):
            family, share = undamped[k]
            out.append({'family': family, 'participation': share, 'natural_hz': float(natural[k] / (2 * np.pi)),
                        'frequency_hz': float(natural[k] * np.sqrt(max(1 - ratio[k] ** 2, 0.0)) / (2 * np.pi)),
                        'damping_ratio': float(ratio[k]), 'q': phi[:, k].astype(complex)})
        return out
    reduced_g = phi.T @ G @ phi
    reduced_c = phi.T @ C @ phi + np.diag(2 * ratio * natural)
    A = np.block([[np.zeros((count, count)), np.eye(count)], [-np.diag(natural**2), -(reduced_g + reduced_c)]])
    lam, vec = eig(A)
    upper = lam.imag > 1e-9 * natural[0]
    lam, vec = lam[upper], vec[:count, upper]
    order = np.argsort(np.abs(lam))
    out = []
    for k in order:
        q = phi @ vec[:, k]
        family, share = family_of(q)
        out.append({'family': family, 'participation': share, 'natural_hz': float(np.abs(lam[k]) / (2 * np.pi)),
                    'frequency_hz': float(lam[k].imag / (2 * np.pi)), 'damping_ratio': float(-lam[k].real / np.abs(lam[k])), 'q': q})
    return out


def describe(beam, mode, component='blade', points=SHAPE_POINTS):
    """Mode shape sampled along the length: every component, scaled so the dominant one peaks at +1."""
    names = FAMILIES[component]
    q = np.concatenate([np.zeros(6, dtype=complex), mode['q']]).reshape(-1, 6)
    P = beam.interpolation(points)
    fields = {names[0]: P @ q[:, 0], names[1]: P @ q[:, 1], names[2]: P @ q[:, 2], names[3]: P @ q[:, 3]}
    dominant = fields[mode['family']]
    peak = dominant[np.argmax(np.abs(dominant))]
    if abs(peak) < 1e-300:
        peak = 1.0
    components = {k: (v / peak).real for k, v in fields.items()}
    if components[mode['family']][-1] < 0:
        components = {k: -v for k, v in components.items()}
    shape = components[mode['family']]
    signs = np.sign(shape[1:][np.abs(shape[1:]) > 1e-3])
    return {'shape': [round(float(v), 6) for v in shape],
            'components': {k: [round(float(v), 6) for v in c] for k, c in components.items()},
            'nodes': int(np.sum(signs[1:] != signs[:-1]))}


def pick(found, counts):
    """First `counts[family]` modes of each family, in frequency order."""
    out = {family: [] for family in counts}
    for mode in found:
        family = mode['family']
        if family in out and len(out[family]) < counts[family]:
            out[family].append(mode)
    return out


def track(previous, current):
    """Reorder `current` modes so each follows the most similar `previous` mode (MAC assignment)."""
    cost = np.array([[1.0 - mac(p['q'], c['q']) for c in current] for p in previous])
    rows, cols = linear_sum_assignment(cost)
    order = [cols[i] for i in np.argsort(rows)]
    rest = [i for i in range(len(current)) if i not in order]
    return [current[i] for i in order + rest], [float(1.0 - cost[r, c]) for r, c in zip(rows, cols)]


# ------------------------------------------------------------------ components

def _optional(extended, name):
    return None if not extended or name not in extended else extended[name]


def blade_sections(blade, twist=None):
    """Sections of a blade record; `twist` (fraction → degrees) is used when the record has no structural twist."""
    fraction, mass, flap, edge = (np.array(c) for c in zip(*blade['stations']))
    extended = blade.get('extended') or {}
    structural = _optional(extended, 'structural_twist_deg')
    return Sections(fraction, mass=mass, ei_out=flap, ei_in=edge, ea=_optional(extended, 'axial_stiffness_n'),
                    gj=_optional(extended, 'torsional_stiffness_nm2'), ga_in=_optional(extended, 'edge_shear_stiffness_n'),
                    ga_out=_optional(extended, 'flap_shear_stiffness_n'), i_torsion=_optional(extended, 'torsional_inertia_kg_m'),
                    i_out=_optional(extended, 'flap_inertia_kg_m'), i_in=_optional(extended, 'edge_inertia_kg_m'),
                    cm_in=_optional(extended, 'cm_offset_m'), twist_deg=structural if structural is not None else twist)


def tower_sections(tower):
    x, mass, fa, ss = (np.array(c) for c in zip(*tower['stations']))
    extended = tower.get('extended') or {}
    return Sections(x, mass=mass, ei_out=fa, ei_in=ss, ea=_optional(extended, 'axial_stiffness_n'),
                    gj=_optional(extended, 'torsional_stiffness_nm2'), ga_in=_optional(extended, 'side_side_shear_stiffness_n'),
                    ga_out=_optional(extended, 'fore_aft_shear_stiffness_n'), i_torsion=_optional(extended, 'torsional_inertia_kg_m'),
                    i_out=_optional(extended, 'fore_aft_inertia_kg_m'), i_in=_optional(extended, 'side_side_inertia_kg_m'))


DIRECTION_DOFS = {'both': (1, 2), 'flap': (2,), 'edge': (1,), 'fore_aft': (2,), 'side_side': (1,), 'torsion': (), 'axial': (0,)}
ROTATION_DOFS = {'both': (4, 5), 'flap': (4,), 'edge': (5,), 'fore_aft': (4,), 'side_side': (5,), 'torsion': (3,), 'axial': ()}


def attach(beam, attachments, target):
    for a in attachments or ():
        if a['target'] != target:
            continue
        direction = a.get('direction', 'both')
        if a['kind'] == 'point_mass':
            inertia = np.zeros((3, 3))
            for dof in ROTATION_DOFS[direction]:
                inertia[dof - 3, dof - 3] = a.get('inertia_kg_m2', 0.0)
            beam.add_body(a['position'], mass=a.get('mass_kg', 0.0), inertia=inertia)
        else:
            k, c = np.zeros(6), np.zeros(6)
            for dof in DIRECTION_DOFS[direction]:
                k[dof], c[dof] = a.get('stiffness_n_m', 0.0), a.get('damping_ns_m', 0.0)
            for dof in ROTATION_DOFS[direction]:
                k[dof], c[dof] = a.get('rotational_stiffness_nm_rad', 0.0), a.get('rotational_damping_nms_rad', 0.0)
            beam.add_spring(a['position'], k, c)


def blade_beam(blade, length_m, twist=None, attachments=()):
    beam = Beam(blade_sections(blade, twist), length_m)
    if blade.get('tip_mass_kg'):
        beam.add_body(1.0, mass=blade['tip_mass_kg'])
    attach(beam, attachments, 'blade')
    return beam


def tower_beam(tower, top_bodies=(), attachments=()):
    """`top_bodies`: (mass, offset[3] in the tower frame, 3×3 inertia about its own centre of mass)."""
    beam = Beam(tower_sections(tower), tower['height_m'])
    for mass, offset, inertia in top_bodies:
        beam.add_body(1.0, mass=mass, offset=offset, inertia=inertia)
    attach(beam, attachments, 'tower')
    return beam


def blade_damping(blade):
    flap, edge = blade.get('flap_damping_pct', 0.0) / 100, blade.get('edge_damping_pct', 0.0) / 100
    return {'flap': flap, 'edge': edge, 'torsion': min(flap, edge), 'axial': min(flap, edge)}


def available(beam, component):
    """Families that the data can describe: torsion needs GJ, axial needs EA."""
    names = FAMILIES[component]
    out = [names[1], names[2]]
    if beam.sections.has('gj'):
        out.append(names[3])
    if beam.sections.has('ea'):
        out.append(names[0])
    return out


def campbell(blade, blade_length_m, hub_radius_m, blades, rpm, *, twist=None, tower=None, top_bodies=(), counts=None,
             tower_counts=None, harmonics=None, attachments=()):
    """Campbell diagram over `rpm`: rotating-frame blade modes, fixed tower modes, nP excitation lines."""
    rpm = np.asarray(rpm, dtype=float)
    if rpm.ndim != 1 or len(rpm) < 2 or np.any(rpm < 0) or np.any(np.diff(rpm) <= 0):
        raise ModalError('Rotor speeds must be at least two increasing, non-negative values')
    harmonics = sorted(set(harmonics or [1, blades, 2 * blades]))
    counts = {k: v for k, v in (counts or {'flap': 2, 'edge': 1}).items() if v}
    beam = blade_beam(blade, blade_length_m, twist, attachments)
    counts = {k: v for k, v in counts.items() if k in available(beam, 'blade')}
    ratios = blade_damping(blade)
    families = {f: [[] for _ in range(n)] for f, n in counts.items()}
    mac_min = {f: [1.0] * n for f, n in counts.items()}
    previous = None
    for speed in rpm:
        found = pick(solve(beam, omega=speed * np.pi / 30, hub_radius=hub_radius_m, damping=ratios), counts)
        for family, n in counts.items():
            if len(found[family]) < n:
                raise ModalError(f'Only {len(found[family])} blade {family} modes found within the first {BASIS} modes')
            if previous is not None:
                found[family], similarity = track(previous[family], found[family])
                mac_min[family] = [min(a, b) for a, b in zip(mac_min[family], similarity)]
            for k in range(n):
                families[family][k].append(found[family][k])
        previous = found
    curves = []
    for family, n in counts.items():
        for k in range(n):
            modes = families[family][k]
            curves.append({'id': f'blade_{family}{k + 1}', 'label': f'Blade {family} {k + 1}', 'component': 'blade',
                           'direction': family, 'frame': 'rotating',
                           'frequency_hz': [m['frequency_hz'] for m in modes], 'damping_ratio': [m['damping_ratio'] for m in modes],
                           'shapes': [describe(beam, m) for m in modes], 'tracking_mac_min': mac_min[family][k]})
    if tower is not None and tower_counts:
        tower_model = tower_beam(tower, top_bodies, attachments)
        tower_counts = {k: v for k, v in tower_counts.items() if v and k in available(tower_model, 'tower')}
        ratio = tower.get('damping_pct', 0.0) / 100
        found = pick(solve(tower_model, damping={f: ratio for f in FAMILIES['tower']}, component='tower'), tower_counts)
        for family, modes in found.items():
            for k, m in enumerate(modes):
                curves.append({'id': f'tower_{family}{k + 1}', 'label': f'Tower {family} {k + 1}', 'component': 'tower',
                               'direction': family, 'frame': 'fixed', 'frequency_hz': [m['frequency_hz']] * len(rpm),
                               'damping_ratio': [m['damping_ratio']] * len(rpm),
                               'shapes': [describe(tower_model, m, 'tower')], 'tracking_mac_min': 1.0})
    excitation = {f'{h}P': (h * rpm / 60.0).tolist() for h in harmonics}
    return {'rpm': rpm.tolist(), 'curves': curves, 'excitation': excitation, 'harmonics': harmonics,
            'crossings': crossings(curves, rpm, harmonics)}


def crossings(curves, rpm, harmonics):
    """Speeds where a mode frequency meets an excitation harmonic h·Ω/2π (linear interpolation)."""
    rpm = np.asarray(rpm, dtype=float)
    out = []
    for curve in curves:
        f = np.asarray(curve['frequency_hz'])
        for h in harmonics:
            gap = f - h * rpm / 60.0
            for i in np.nonzero(np.sign(gap[:-1]) * np.sign(gap[1:]) < 0)[0]:
                t = gap[i] / (gap[i] - gap[i + 1])
                out.append({'mode': curve['id'], 'harmonic': f'{h}P', 'rpm': float(rpm[i] + t * (rpm[i + 1] - rpm[i])),
                            'frequency_hz': float(f[i] + t * (f[i + 1] - f[i]))})
    return sorted(out, key=lambda c: c['rpm'])


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
