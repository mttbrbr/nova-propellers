"""Full-range (±180°) section polars for rotor analysis.

Wind and water turbines, and especially vertical-axis rotors, operate far
beyond the attached-flow range of measured polars. Each Reynolds table is
extended with the Viterna–Corrigan post-stall model and a flat-plate mirror
for reversed flow (the AirfoilPrep convention). Synthetic sections are clearly
labelled demonstration data: they reproduce plausible trends, not a specific
measured airfoil.
"""
import math
from dataclasses import dataclass, field

import numpy as np

GRID_DEG = np.arange(-180.0, 180.0001, 0.5)

# cl0, lift slope [1/deg], clmax, cd0 at re_ref, thickness ratio, re_ref
SYNTHETIC_SECTIONS = {
    'NACA 0012': dict(cl0=0.00, slope=0.105, clmax=1.10, cd0=0.0090, thickness=0.12, re_ref=1e6),
    'NACA 0015': dict(cl0=0.00, slope=0.104, clmax=1.15, cd0=0.0095, thickness=0.15, re_ref=1e6),
    'NACA 0018': dict(cl0=0.00, slope=0.103, clmax=1.20, cd0=0.0105, thickness=0.18, re_ref=1e6),
    'NACA 0021': dict(cl0=0.00, slope=0.100, clmax=1.20, cd0=0.0115, thickness=0.21, re_ref=1e6),
    'NACA 2412': dict(cl0=0.22, slope=0.098, clmax=1.18, cd0=0.0150, thickness=0.12, re_ref=2e5),
    'NACA 4412': dict(cl0=0.42, slope=0.103, clmax=1.28, cd0=0.0160, thickness=0.12, re_ref=2e5),
    'NACA 6409': dict(cl0=0.55, slope=0.096, clmax=1.22, cd0=0.0130, thickness=0.09, re_ref=2e5),
    'Wind turbine 21% (synthetic)': dict(cl0=0.35, slope=0.110, clmax=1.45, cd0=0.0090, thickness=0.21, re_ref=3e6),
    'Marine a=0.8 10% (synthetic)': dict(cl0=0.25, slope=0.105, clmax=0.95, cd0=0.0065, thickness=0.10, re_ref=1e7),
}
SYNTHETIC_REYNOLDS = (3e4, 1e5, 3e5, 1e6, 3e6, 1e7, 3e7)


def viterna(alpha_deg, alpha_stall_deg, cl_stall, cd_stall, cd_max):
    """Viterna–Corrigan post-stall coefficients for 0 < alpha_stall < alpha <= 90°."""
    a = np.radians(np.asarray(alpha_deg, dtype=float))
    s = math.radians(alpha_stall_deg)
    b1, a1 = cd_max, cd_max / 2.0
    b2 = (cd_stall - cd_max * math.sin(s) ** 2) / math.cos(s)
    a2 = (cl_stall - cd_max * math.sin(s) * math.cos(s)) * math.sin(s) / math.cos(s) ** 2
    sin_a = np.maximum(np.sin(a), 1e-9)
    return a1 * np.sin(2 * a) + a2 * np.cos(a) ** 2 / sin_a, b1 * np.sin(a) ** 2 + b2 * np.cos(a)


def extend_table(alpha_deg, cl, cd, aspect_ratio=10.0):
    """Extend an attached-flow table to the full ±180° grid."""
    order = np.argsort(alpha_deg)
    alpha, cl, cd = (np.asarray(v, dtype=float)[order] for v in (alpha_deg, cl, cd))
    if alpha[0] > 0 or alpha[-1] < 0:
        raise ValueError('A polar table must bracket zero incidence to be extrapolated')
    cd_max = 1.11 + 0.018 * min(max(aspect_ratio, 1.0), 50.0)
    lo, hi = max(alpha[0], -89.0), min(alpha[-1], 89.0)

    def base(angle):
        angle = np.asarray(angle, dtype=float)
        out_cl, out_cd = np.interp(angle, alpha, cl), np.interp(angle, alpha, cd)
        upper, lower = angle > hi, angle < lo
        if upper.any():
            out_cl[upper], out_cd[upper] = viterna(angle[upper], hi, np.interp(hi, alpha, cl), np.interp(hi, alpha, cd), cd_max)
        if lower.any():
            vc, vd = viterna(-angle[lower], -lo, -np.interp(lo, alpha, cl), np.interp(lo, alpha, cd), cd_max)
            out_cl[lower], out_cd[lower] = -vc, vd
        return out_cl, out_cd

    grid = GRID_DEG
    out_cl, out_cd = np.empty_like(grid), np.empty_like(grid)
    middle = np.abs(grid) <= 90
    out_cl[middle], out_cd[middle] = base(grid[middle])
    for mask, mirror in ((grid > 90, 180.0 - grid), (grid < -90, -180.0 - grid)):
        bc, bd = base(mirror[mask])
        out_cl[mask], out_cd[mask] = -0.7 * bc, bd
    return out_cl, np.maximum(out_cd, 1e-4)


def synthetic_attached(cl0, slope, clmax, cd0):
    clmin = -clmax + 1.2 * cl0
    alpha_zero = -cl0 / slope
    stall_pos, stall_neg = (clmax - cl0) / slope, (clmin - cl0) / slope
    alpha = np.arange(math.floor(stall_neg) - 3.0, math.ceil(stall_pos) + 3.0001, 0.5)
    cl = cl0 + slope * alpha
    # Rounded stall: soft saturation followed by a mild post-stall drop.
    cl = np.where(alpha > stall_pos, clmax - 0.04 * (alpha - stall_pos), cl)
    cl = np.where(alpha < stall_neg, clmin - 0.04 * (alpha - stall_neg), cl)
    span = max(stall_pos - alpha_zero, 1.0)
    cd = cd0 * (1.0 + 4.0 * ((alpha - alpha_zero) / span) ** 2)
    return alpha, cl, cd


@dataclass
class SectionPolar:
    """Reynolds-indexed full-range polar with log-Reynolds interpolation."""
    name: str
    reynolds: np.ndarray
    cl_tables: np.ndarray
    cd_tables: np.ndarray
    thickness: float = 0.12
    synthetic: bool = True
    clipped: int = field(default=0)

    @classmethod
    def synthetic_section(cls, name, aspect_ratio=10.0):
        if name not in SYNTHETIC_SECTIONS:
            raise ValueError(f'Unknown section {name!r}; import a polar or choose {", ".join(SYNTHETIC_SECTIONS)}')
        p = SYNTHETIC_SECTIONS[name]
        cls_, cds_ = [], []
        for re in SYNTHETIC_REYNOLDS:
            scale = float(np.clip((re / p['re_ref']) ** -0.2, 0.5, 3.0))
            clmax = p['clmax'] * float(np.clip((re / p['re_ref']) ** 0.05, 0.75, 1.15))
            a, cl, cd = synthetic_attached(p['cl0'], p['slope'], clmax, p['cd0'] * scale)
            full_cl, full_cd = extend_table(a, cl, cd, aspect_ratio)
            cls_.append(full_cl)
            cds_.append(full_cd)
        return cls(name, np.asarray(SYNTHETIC_REYNOLDS), np.asarray(cls_), np.asarray(cds_), p['thickness'], True)

    @classmethod
    def from_points(cls, name, points, thickness=0.12, aspect_ratio=10.0):
        groups = {}
        for point in points:
            groups.setdefault(float(point['reynolds']), []).append(point)
        reynolds, cls_, cds_ = [], [], []
        for re in sorted(groups):
            rows = sorted(groups[re], key=lambda p: p['alpha_deg'])
            if len(rows) < 3:
                continue
            full_cl, full_cd = extend_table([r['alpha_deg'] for r in rows], [r['cl'] for r in rows],
                                            [r['cd'] for r in rows], aspect_ratio)
            reynolds.append(re)
            cls_.append(full_cl)
            cds_.append(full_cd)
        if not reynolds:
            raise ValueError('Imported polar needs at least three samples per Reynolds number')
        return cls(name, np.asarray(reynolds), np.asarray(cls_), np.asarray(cds_), float(thickness), False)

    def __call__(self, alpha_deg, reynolds):
        alpha = (np.asarray(alpha_deg, dtype=float) + 180.0) % 360.0 - 180.0
        re = np.broadcast_to(np.asarray(reynolds, dtype=float), alpha.shape)
        if len(self.reynolds) == 1:
            return (np.interp(alpha, GRID_DEG, self.cl_tables[0]), np.interp(alpha, GRID_DEG, self.cd_tables[0]))
        log_re = np.log(np.clip(re, 1.0, None))
        grid = np.log(self.reynolds)
        self.clipped += int(np.count_nonzero((log_re < grid[0]) | (log_re > grid[-1])))
        position = np.clip(np.interp(log_re, grid, np.arange(len(grid))), 0, len(grid) - 1)
        low = np.floor(position).astype(int)
        high = np.minimum(low + 1, len(grid) - 1)
        weight = position - low
        all_cl = np.stack([np.interp(alpha, GRID_DEG, table) for table in self.cl_tables])
        all_cd = np.stack([np.interp(alpha, GRID_DEG, table) for table in self.cd_tables])
        pick = lambda tables, index: np.take_along_axis(tables, index[None, ...], axis=0)[0]  # noqa: E731
        cl = pick(all_cl, low) * (1 - weight) + pick(all_cl, high) * weight
        cd = pick(all_cd, low) * (1 - weight) + pick(all_cd, high) * weight
        return cl, cd

    def zero_lift_angle_deg(self, reynolds=1e6):
        alpha = np.linspace(-15, 15, 301)
        cl, _ = self(alpha, np.full_like(alpha, reynolds))
        return float(np.interp(0.0, cl[(alpha > -10) & (alpha < 8)], alpha[(alpha > -10) & (alpha < 8)]))

    def lift_slope_per_rad(self, reynolds=1e6):
        alpha0 = self.zero_lift_angle_deg(reynolds)
        cl, _ = self(np.array([alpha0 - 2.0, alpha0 + 2.0]), np.full(2, reynolds))
        return float((cl[1] - cl[0]) / math.radians(4.0))

    def static_stall_angle_deg(self, reynolds=1e6):
        alpha = np.linspace(0, 40, 401)
        cl, _ = self(alpha, np.full_like(alpha, reynolds))
        return float(alpha[int(np.argmax(cl))])


def section_from(config, aspect_ratio=10.0):
    """Build a section polar from {'name': ...} or {'points': [...], 'thickness': ...}."""
    if isinstance(config, SectionPolar):
        return config
    if isinstance(config, str):
        return SectionPolar.synthetic_section(config, aspect_ratio)
    config = config or {}
    if config.get('points'):
        return SectionPolar.from_points(config.get('name', 'Imported polar'), config['points'],
                                        config.get('thickness', 0.12), aspect_ratio)
    return SectionPolar.synthetic_section(config.get('name', 'NACA 0018'), aspect_ratio)
