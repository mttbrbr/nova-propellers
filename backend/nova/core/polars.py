"""Source-preserving polar parsing and explicit condition interpolation."""
import csv
import io
import re

import numpy as np

FIELDS = ('reynolds', 'mach', 'ncrit', 'alpha_deg', 'cl', 'cd', 'cm')


def parse_polar(content, format='csv', *, reynolds=None, mach=.03, ncrit=9., mapping=None):
    points = []
    defaults = {'reynolds': reynolds, 'mach': mach, 'ncrit': ncrit, 'cm': 0.}
    if format == 'csv':
        reader = csv.DictReader(io.StringIO(content))
        mapping = mapping or {field: field for field in FIELDS}
        for line, row in enumerate(reader, 2):
            try:
                item = {field: float(row[mapping[field]]) if mapping.get(field) and row.get(mapping[field], '').strip()
                        else defaults.get(field) for field in FIELDS}
            except (ValueError, TypeError) as exc:
                raise ValueError(f'CSV line {line}: invalid numeric value') from exc
            points.append(item)
    elif format == 'xfoil':
        match = re.search(r'Re\s*=\s*([\d.]+)\s*[eE]\s*([+-]?\d+)', content)
        if match:
            defaults['reynolds'] = float(match[1]) * 10 ** int(match[2])
        for label, pattern in [('mach', r'Mach\s*=\s*([\d.]+)'), ('ncrit', r'Ncrit\s*=\s*([\d.]+)')]:
            match = re.search(pattern, content, re.I)
            if match:
                defaults[label] = float(match[1])
        started = False
        for line, text in enumerate(content.splitlines(), 1):
            if 'alpha' in text.lower() and 'cl' in text.lower() and 'cd' in text.lower():
                started = True
                continue
            if not started or not text.strip() or set(text.strip()) <= {'-', ' '}:
                continue
            try:
                values = [float(value.replace('D', 'E')) for value in text.split()]
                if len(values) < 5:
                    raise ValueError('expected alpha CL CD CDp CM')
            except ValueError as exc:
                raise ValueError(f'XFOIL line {line}: malformed polar sample') from exc
            points.append({**defaults, 'alpha_deg': values[0], 'cl': values[1], 'cd': values[2], 'cm': values[4]})
    else:
        raise ValueError('Supported polar formats are csv and xfoil')
    validate_points(points)
    return points


def validate_points(points):
    if len(points) < 2:
        raise ValueError('At least two polar samples are required')
    seen = set()
    for index, point in enumerate(points, 1):
        try:
            values = [float(point[field]) for field in FIELDS]
        except (TypeError, KeyError, ValueError) as exc:
            raise ValueError(f'Polar sample {index}: missing or invalid quantity') from exc
        if not np.all(np.isfinite(values)) or values[0] <= 0 or values[1] < 0 or values[2] <= 0 or values[5] < 0:
            raise ValueError(f'Polar sample {index}: nonphysical or nonfinite value')
        key = tuple(values[:4])
        if key in seen:
            raise ValueError(f'Polar sample {index}: duplicate condition/alpha')
        seen.add(key)


class PolarProvider:
    """Interpolate actual samples at one explicitly selected Mach/Ncrit.

    Endpoint clipping is deliberate and recorded; no synthetic substitution.
    """
    def __init__(self, points, mach, ncrit):
        validate_points(points)
        selected = [p for p in points if abs(p['mach'] - mach) < 1e-8 and abs(p['ncrit'] - ncrit) < 1e-8]
        if not selected:
            raise ValueError('No polar data for the selected Mach/Ncrit')
        self.reynolds = sorted({p['reynolds'] for p in selected})
        self.slices = [sorted([p for p in selected if p['reynolds'] == re], key=lambda p: p['alpha_deg'])
                       for re in self.reynolds]
        if any(len(part) < 2 for part in self.slices):
            raise ValueError('Each selected Reynolds slice requires at least two alpha samples')
        self.clipped = False

    def __call__(self, alpha, reynolds, strategy='clip'):
        if strategy != 'clip':
            raise ValueError('Imported polar families currently support explicit endpoint clipping only')
        for a, re_value in zip(alpha, reynolds):
            context = self.context(float(a), float(re_value))
            self.clipped |= context['alpha_clipped'] or context['reynolds_clipped']
        outputs = []
        for field in ('cl', 'cd'):
            slices = np.array([np.interp(alpha, [p['alpha_deg'] for p in part], [p[field] for p in part])
                               for part in self.slices])
            outputs.append(np.array([np.interp(reynolds[i], self.reynolds, slices[:, i]) for i in range(len(alpha))]))
        return outputs[0], outputs[1]

    def context(self, alpha, reynolds):
        exact = next((i for i, value in enumerate(self.reynolds) if value == reynolds), None)
        right = int(np.searchsorted(self.reynolds, reynolds))
        indices = [exact] if exact is not None else sorted({max(0, right - 1), min(right, len(self.reynolds) - 1)})
        segments = []
        clipped = False
        for index in indices:
            grid = [p['alpha_deg'] for p in self.slices[index]]
            clipped |= not grid[0] <= alpha <= grid[-1]
            upper = min(max(int(np.searchsorted(grid, alpha, side='right')), 1), len(grid) - 1)
            segments.append([grid[upper - 1], grid[upper]])
        return {'alpha_clipped': bool(clipped),
                'reynolds_clipped': not self.reynolds[0] <= reynolds <= self.reynolds[-1],
                'alpha_segment_deg': [min(s[0] for s in segments), max(s[1] for s in segments)],
                'alpha_segments_by_re': segments,
                'reynolds_segment': [self.reynolds[indices[0]], self.reynolds[indices[-1]]],
                'low_re_strategy': 'clip', 'source': 'selected_polar_asset'}
