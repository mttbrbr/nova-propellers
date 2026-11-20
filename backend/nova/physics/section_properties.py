"""Thin-walled cross-section properties of a blade (2-D, isotropic layers smeared through the thickness).

A section is the airfoil outline (NACA four-digit shape, or a circle at the root, blended in between) scaled
by the chord, with a shell of uniform thickness, spar caps on the upper and lower surface and vertical shear
webs. Each wall segment carries its own E, G, density and thickness. The properties follow classical
thin-wall theory:

* axial stiffness EA = Σ E t ds and the modulus-weighted centroid (the elastic axis reference);
* bending stiffnesses about the centroid and their principal axes (angle measured from the chord line);
* torsional stiffness of the closed multi-cell section (cells separated by the webs), Bredt–Batho with
  compatible twist of every cell: Σ_j δ_kj q_j = 2 A_k θ′, GJ = Σ 2 A_k q_k;
* shear stiffness Σ G t ds cos²(wall angle) along each axis (no shear-correction factor);
* mass per length, centre of mass and mass moments of inertia per length about the centre of mass.

Coordinates: y chordwise from the leading edge towards the trailing edge, z normal to the chord (suction
side positive). Wall bending about its own mid-surface, warping and laminate coupling terms are neglected.
"""
import math

import numpy as np


class SectionError(ValueError):
    pass


def naca_outline(code, points=80):
    """Upper and lower surfaces (chord-normalised) of a NACA four-digit airfoil, from the leading edge to the trailing edge."""
    code = str(code)
    if len(code) != 4 or not code.isdigit():
        raise SectionError('Airfoil must be a NACA four-digit code such as 4418')
    m, p, t = int(code[0]) / 100, int(code[1]) / 10, int(code[2:]) / 100
    if t <= 0:
        raise SectionError('Airfoil thickness must be positive')
    beta = np.linspace(0, math.pi, points)
    x = (1 - np.cos(beta)) / 2
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1036 * x**4)  # open TE
    if m and p:
        yc = np.where(x < p, m / p**2 * (2 * p * x - x**2), m / (1 - p) ** 2 * (1 - 2 * p + 2 * p * x - x**2))
        slope = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p) ** 2 * (p - x))
    else:
        yc, slope = np.zeros_like(x), np.zeros_like(x)
    theta = np.arctan(slope)
    upper = np.column_stack([x - yt * np.sin(theta), yc + yt * np.cos(theta)])
    lower = np.column_stack([x + yt * np.sin(theta), yc - yt * np.cos(theta)])
    return upper, lower


def circle_outline(points=80, centre=0.5):
    """Circle of unit diameter whose leftmost point is at y = 0 (upper and lower halves)."""
    beta = np.linspace(0, math.pi, points)
    y = centre - 0.5 * np.cos(beta)
    return np.column_stack([y, 0.5 * np.sin(beta)]), np.column_stack([y, -0.5 * np.sin(beta)])


def outline(code, blend=1.0, points=80):
    """Airfoil (blend = 1) or circle (blend = 0) or a linear blend of the two."""
    if blend >= 1:
        return naca_outline(code, points)
    au, al = naca_outline(code, points) if blend > 0 else (None, None)
    cu, cl = circle_outline(points)
    if au is None:
        return cu, cl
    return blend * au + (1 - blend) * cu, blend * al + (1 - blend) * cl


def _segments(curve, chord, region, materials):
    """Wall segments along a surface curve: midpoints, lengths, angle and the material of the region they lie in."""
    pts = curve * chord
    mid = (pts[1:] + pts[:-1]) / 2
    d = np.diff(pts, axis=0)
    length = np.hypot(d[:, 0], d[:, 1])
    angle = np.arctan2(d[:, 1], d[:, 0])
    props = [region(m[0] / chord, materials) for m in mid]
    return mid, length, angle, props


def properties(chord, code='4418', *, shell, spar_cap=None, webs=(), blend=1.0, points=120):
    """Section properties per unit length. `shell`, `spar_cap` and every web are dicts with E_pa, G_pa, density_kg_m3,
    thickness_m (spar cap also centre and width as chord fractions; web also position as chord fraction)."""
    if chord <= 0:
        raise SectionError('Chord must be positive')
    for name, m in (('shell', shell), *((f'web {i + 1}', w) for i, w in enumerate(webs)), *((('spar cap', spar_cap),) if spar_cap else ())):
        for key in ('E_pa', 'G_pa', 'density_kg_m3', 'thickness_m'):
            if not isinstance(m.get(key), (int, float)) or m[key] < 0:
                raise SectionError(f'{name}: {key} must be a non-negative number')
    upper, lower = outline(code, blend, points)

    def region(y, _):
        if spar_cap and abs(y - spar_cap['centre']) <= spar_cap['width'] / 2:
            t = shell['thickness_m'] + spar_cap['thickness_m']
            return {'t': t, 'E': (shell['E_pa'] * shell['thickness_m'] + spar_cap['E_pa'] * spar_cap['thickness_m']) / t,
                    'G': (shell['G_pa'] * shell['thickness_m'] + spar_cap['G_pa'] * spar_cap['thickness_m']) / t,
                    'rho': (shell['density_kg_m3'] * shell['thickness_m'] + spar_cap['density_kg_m3'] * spar_cap['thickness_m']) / t}
        return {'t': shell['thickness_m'], 'E': shell['E_pa'], 'G': shell['G_pa'], 'rho': shell['density_kg_m3']}

    walls = []  # (midpoint, length, angle, props, tag)
    for curve, tag in ((upper, 'upper'), (lower, 'lower')):
        mid, length, angle, props = _segments(curve, chord, region, None)
        walls += [(m, ln, a, p, tag) for m, ln, a, p in zip(mid, length, angle, props)]
    # trailing-edge closure (open NACA trailing edge) and webs
    te = [upper[-1] * chord, lower[-1] * chord]
    if np.hypot(*(te[0] - te[1])) > 1e-9:
        walls.append(((te[0] + te[1]) / 2, float(np.hypot(*(te[0] - te[1]))), math.pi / 2, region(1.0, None), 'te'))
    web_lines = []
    for w in sorted(webs, key=lambda w: w['position']):
        y = w['position']
        if not 0 < y < 1:
            raise SectionError('Web positions must be inside the chord (0–1)')
        zu, zl = np.interp(y, upper[:, 0], upper[:, 1]), np.interp(y, lower[:, 0], lower[:, 1])
        top, bottom = np.array([y, zu]) * chord, np.array([y, zl]) * chord
        n = 8
        for k in range(n):
            a, b = bottom + (top - bottom) * k / n, bottom + (top - bottom) * (k + 1) / n
            walls.append(((a + b) / 2, float(np.hypot(*(b - a))), math.pi / 2,
                          {'t': w['thickness_m'], 'E': w['E_pa'], 'G': w['G_pa'], 'rho': w['density_kg_m3']}, f'web{len(web_lines)}'))
        web_lines.append((y * chord, top, bottom, w))
    mid = np.array([w[0] for w in walls])
    ds = np.array([w[1] for w in walls])
    ang = np.array([w[2] for w in walls])
    t = np.array([w[3]['t'] for w in walls])
    E = np.array([w[3]['E'] for w in walls])
    G = np.array([w[3]['G'] for w in walls])
    rho = np.array([w[3]['rho'] for w in walls])
    EA = float(np.sum(E * t * ds))
    if EA <= 0:
        raise SectionError('The section has no axial stiffness')
    yc, zc = (np.sum((E * t * ds)[:, None] * mid, axis=0) / EA)
    y, z = mid[:, 0] - yc, mid[:, 1] - zc
    # wall own inertia along its length (a thin plate of length ds at angle a)
    own_yy = E * t * ds**3 / 12 * np.cos(ang) ** 2
    own_zz = E * t * ds**3 / 12 * np.sin(ang) ** 2
    own_yz = E * t * ds**3 / 12 * np.sin(ang) * np.cos(ang)
    EIzz = float(np.sum(E * t * ds * z**2 + own_zz))   # bending with displacement normal to the chord (flapwise)
    EIyy = float(np.sum(E * t * ds * y**2 + own_yy))   # bending with displacement along the chord (edgewise)
    EIyz = float(np.sum(E * t * ds * y * z + own_yz))
    principal = 0.5 * math.atan2(-2 * EIyz, EIyy - EIzz)
    mean, half = (EIyy + EIzz) / 2, math.hypot((EIyy - EIzz) / 2, EIyz)
    EI_flap, EI_edge = mean - half, mean + half
    mass = float(np.sum(rho * t * ds))
    ym, zm = np.sum((rho * t * ds)[:, None] * mid, axis=0) / mass
    i_flap = float(np.sum(rho * t * ds * (mid[:, 1] - zm) ** 2))
    i_edge = float(np.sum(rho * t * ds * (mid[:, 0] - ym) ** 2))
    GJ, cells = _torsion(upper * chord, lower * chord, web_lines, walls)
    return {'mass_kg_m': mass, 'EA_n': EA, 'EI_flap_nm2': EI_flap, 'EI_edge_nm2': EI_edge, 'principal_angle_deg': math.degrees(principal),
            'EI_chord_normal_nm2': EIzz, 'EI_chordwise_nm2': EIyy, 'GJ_nm2': GJ, 'cells': cells,
            'GA_edge_n': float(np.sum(G * t * ds * np.cos(ang) ** 2)), 'GA_flap_n': float(np.sum(G * t * ds * np.sin(ang) ** 2)),
            'elastic_centre_m': (float(yc), float(zc)), 'mass_centre_m': (float(ym), float(zm)),
            'torsional_inertia_kg_m': i_flap + i_edge, 'flap_inertia_kg_m': i_flap, 'edge_inertia_kg_m': i_edge,
            'cm_offset_m': float(ym - yc), 'area_enclosed_m2': sum(c['area_m2'] for c in cells)}


def _area(polygon):
    x, y = polygon[:, 0], polygon[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _between(curve, a, b):
    """Points of a surface curve (increasing chordwise coordinate) between a and b, with the end points interpolated."""
    a, b = max(a, curve[0, 0]), min(b, curve[-1, 0])
    inside = curve[(curve[:, 0] > a) & (curve[:, 0] < b)]
    ends = [np.array([[x, np.interp(x, curve[:, 0], curve[:, 1])]]) for x in (a, b)]
    return np.vstack([ends[0], inside, ends[1]])


def _torsion(upper, lower, webs, walls):
    """Multi-cell Bredt–Batho torsional stiffness. Cells are bounded by the webs (chordwise positions)."""
    cuts = [0.0] + [w[0] for w in webs] + [max(upper[-1, 0], lower[-1, 0]) + 1e-9]
    flex = {}

    def integral(selector):
        return float(sum(w[1] / (w[3]['G'] * w[3]['t']) for w in walls if selector(w)))
    n = len(cuts) - 1
    areas, delta = np.zeros(n), np.zeros((n, n))
    for k in range(n):
        a, b = cuts[k], cuts[k + 1]
        up, lo = _between(upper, a, b), _between(lower, a, b)
        if len(up) < 2 or len(lo) < 2:
            raise SectionError('Webs are too close together for the outline resolution')
        areas[k] = _area(np.vstack([up, lo[::-1]]))
        delta[k, k] = integral(lambda w: w[4] in ('upper', 'lower', 'te') and a <= w[0][0] < b)
        for j, web in enumerate(webs):
            if abs(web[0] - a) < 1e-12 or abs(web[0] - b) < 1e-12:
                flex[j] = integral(lambda w, j=j: w[4] == f'web{j}')
                delta[k, k] += flex[j]
        if k > 0:
            delta[k, k - 1] = delta[k - 1, k] = -flex[k - 1]
    q = np.linalg.solve(delta, 2 * areas)
    GJ = float(np.sum(2 * areas * q))
    return GJ, [{'area_m2': float(a), 'shear_flow_per_twist': float(v)} for a, v in zip(areas, q)]


def solid_properties(chord, code='4412', *, material, blend=1.0, points=120):
    """Properties of a solid (moulded or machined) homogeneous section filling the outline.

    Area, centroid and second moments from the polygon (Green's theorem); torsion constant from Saint-Venant's
    approximation J ≈ A⁴ / (4π² I_p), exact for an ellipse; shear stiffness κ G A with κ = 5/6."""
    if chord <= 0:
        raise SectionError('Chord must be positive')
    for key in ('E_pa', 'G_pa', 'density_kg_m3'):
        if not isinstance(material.get(key), (int, float)) or material[key] <= 0:
            raise SectionError(f'solid material: {key} must be positive')
    upper, lower = outline(code, blend, points)
    polygon = np.vstack([upper, lower[::-1][1:-1]]) * chord
    x, y = polygon[:, 0], polygon[:, 1]
    if (x * np.roll(y, -1) - np.roll(x, -1) * y).sum() < 0:  # make the outline counter-clockwise
        x, y = x[::-1].copy(), y[::-1].copy()
    xn, yn = np.roll(x, -1), np.roll(y, -1)
    cross = x * yn - xn * y
    A = cross.sum() / 2
    cy = ((x + xn) * cross).sum() / (6 * A)
    cz = ((y + yn) * cross).sum() / (6 * A)
    Izz = ((y * y + y * yn + yn * yn) * cross).sum() / 12 - A * cz * cz   # about the chord-parallel centroidal axis
    Iyy = ((x * x + x * xn + xn * xn) * cross).sum() / 12 - A * cy * cy
    Iyz = ((x * yn + 2 * x * y + 2 * xn * yn + xn * y) * cross).sum() / 24 - A * cy * cz
    E, G, rho = material['E_pa'], material['G_pa'], material['density_kg_m3']
    principal = 0.5 * math.atan2(-2 * Iyz, Iyy - Izz)
    mean, half = (Iyy + Izz) / 2, math.hypot((Iyy - Izz) / 2, Iyz)
    Ip = Iyy + Izz
    J = A**4 / (4 * math.pi**2 * Ip)
    return {'mass_kg_m': rho * A, 'EA_n': E * A, 'EI_flap_nm2': E * (mean - half), 'EI_edge_nm2': E * (mean + half),
            'principal_angle_deg': math.degrees(principal), 'EI_chord_normal_nm2': E * Izz, 'EI_chordwise_nm2': E * Iyy,
            'GJ_nm2': G * J, 'cells': [], 'GA_edge_n': 5 / 6 * G * A, 'GA_flap_n': 5 / 6 * G * A,
            'elastic_centre_m': (float(cy), float(cz)), 'mass_centre_m': (float(cy), float(cz)),
            'torsional_inertia_kg_m': rho * Ip, 'flap_inertia_kg_m': rho * Izz, 'edge_inertia_kg_m': rho * Iyy,
            'cm_offset_m': 0.0, 'area_enclosed_m2': float(A)}
