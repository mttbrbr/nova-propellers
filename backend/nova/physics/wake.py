"""Velocity deficit that an upstream rotor or body leaves on the disk of this rotor.

Level-1 model: the deficit is averaged over the disk (area-weighted) and applied
as one reduced inflow velocity, so the solver stays axisymmetric. A deficit that
covers only part of the disk (lateral offset) lowers the mean accordingly but
cannot make the blade load vary around the azimuth; that needs the azimuthal
BEMT.

  * jensen   : top-hat wake that grows linearly with k (Jensen 1983; Katic 1986)
  * gaussian : Gaussian profile (Bastankhah & Porté-Agel 2014)

An upstream *rotor* is described by its thrust coefficient and diameter; an
upstream *body* (fuselage, nacelle, tower) by its drag coefficient on frontal
area π d²/4 and diameter d. Both reduce to the same actuator-equivalent source.
"""
import math

import numpy as np

KINDS = ('none', 'rotor', 'body')
MODELS = ('jensen', 'gaussian')
LIMITS = {'diameter_m': (1e-3, 1e4), 'coefficient': (0.0, 1.5), 'distance_m': (1e-3, 1e5),
          'offset_m': (-1e5, 1e5), 'decay': (0.0, 0.5)}
DEFAULT_DECAY = {'rotor': 0.04, 'body': 0.06}
GAUSSIAN_EPSILON = 0.2


def _number(config, key, default=None):
    value = config.get(key, default)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'Upstream wake needs a numeric {key.replace("_", " ")}')
    low, high = LIMITS[key]
    if not low <= value <= high:
        raise ValueError(f'Upstream wake {key.replace("_", " ")} must be between {low:g} and {high:g}')
    return float(value)


def validate(config):
    """Normalise an upstream-wake description; None means no wake."""
    if not config or config.get('kind', 'none') == 'none':
        return None
    unknown = set(config) - {'kind', 'model', 'diameter_m', 'coefficient', 'distance_m', 'offset_m', 'decay'}
    if unknown:
        raise ValueError(f'Unsupported upstream wake fields: {", ".join(sorted(unknown))}')
    kind, model = config['kind'], config.get('model', 'gaussian')
    if kind not in KINDS or model not in MODELS:
        raise ValueError(f'Upstream wake kind must be one of {", ".join(KINDS)} and model one of {", ".join(MODELS)}')
    return {'kind': kind, 'model': model, 'diameter_m': _number(config, 'diameter_m'),
            'coefficient': _number(config, 'coefficient'), 'distance_m': _number(config, 'distance_m'),
            'offset_m': _number(config, 'offset_m', 0.0), 'decay': _number(config, 'decay', DEFAULT_DECAY[kind])}


def local_deficit(wake, lateral_m):
    """Fractional velocity deficit at a lateral distance from the wake axis."""
    D0, ct, x, k = wake['diameter_m'], min(wake['coefficient'], 0.99), wake['distance_m'], wake['decay']
    if wake['model'] == 'jensen':
        radius = D0 / 2 + k * x
        return np.where(lateral_m <= radius, (1 - math.sqrt(1 - ct)) * (D0 / (2 * radius)) ** 2, 0.0)
    sigma = k * x + GAUSSIAN_EPSILON * D0
    centre = 1 - math.sqrt(max(1 - ct * D0**2 / (8 * sigma**2), 0.0))
    return centre * np.exp(-lateral_m**2 / (2 * sigma**2))


def mean_deficit(config, rotor_diameter_m, radial=24, azimuthal=48):
    """Area-weighted mean deficit over this rotor's disk; also the covered fraction."""
    wake = validate(config)
    if wake is None:
        return {'kind': 'none', 'mean_deficit': 0.0, 'covered_fraction': 0.0}
    r = (np.arange(radial) + 0.5) / radial * rotor_diameter_m / 2
    theta = (np.arange(azimuthal) + 0.5) / azimuthal * 2 * math.pi
    rr, tt = np.meshgrid(r, theta, indexing='ij')
    lateral = np.hypot(wake['offset_m'] + rr * np.cos(tt), rr * np.sin(tt))
    deficit = local_deficit(wake, lateral)
    weight = np.broadcast_to(rr, rr.shape)
    mean = float(np.sum(deficit * weight) / np.sum(weight))
    return {**wake, 'mean_deficit': mean, 'peak_deficit': float(deficit.max()),
            'covered_fraction': float(np.sum((deficit > 1e-3) * weight) / np.sum(weight))}
