"""Wind-farm wake model (native NOJ / Jensen) and wind-climate binning.

N.O. Jensen's top-hat wake (Jensen 1983, Katic et al. 1986) as in PyWake's ``NOJ`` defaults: the deficit
behind turbine i at downstream distance x is U∞ (1 − √(1 − C_T,i)) (R / (R + k x))², C_T,i taken at the
upstream turbine's effective speed; the deficit seen by a rotor is weighted by the fraction of its disc
inside the wake circle (area overlap) and deficits from several wakes are combined as a root sum of
squares. Flat terrain, uniform inflow (no shear), one turbine type, no turbulence model.
Wind direction is meteorological: the direction the wind comes from, degrees clockwise from north;
x points east and y north.
"""
import math

import numpy as np


class FarmError(ValueError):
    pass


def overlap_fraction(wake_radius, rotor_radius, distance):
    """Fraction of a rotor disc (radius r) inside a wake circle (radius R) whose centres are `distance` apart."""
    R, r, d = wake_radius, rotor_radius, abs(distance)
    if d >= R + r:
        return 0.0
    if d <= R - r:
        return 1.0
    if d <= r - R:
        return (R / r) ** 2
    a = r * r * math.acos(max(-1.0, min(1.0, (d * d + r * r - R * R) / (2 * d * r))))
    b = R * R * math.acos(max(-1.0, min(1.0, (d * d + R * R - r * r) / (2 * d * R))))
    c = 0.5 * math.sqrt(max(0.0, (-d + r + R) * (d + r - R) * (d - r + R) * (d + r + R)))
    return (a + b - c) / (math.pi * r * r)


def effective_speeds(x, y, *, direction_deg, speed, diameter, ct_curve, k=0.1):
    """Effective wind speed at every turbine for one free-stream condition."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    theta = math.radians(direction_deg)
    downwind = np.array([-math.sin(theta), -math.cos(theta)])
    along = x * downwind[0] + y * downwind[1]
    across = -x * downwind[1] + y * downwind[0]
    order = np.argsort(along)
    radius = diameter / 2
    effective = np.full(len(x), float(speed))
    deficits = np.zeros(len(x))
    for position, i in enumerate(order):
        effective[i] = speed - math.sqrt(deficits[i])
        ct = min(float(ct_curve(effective[i])), 0.9999)
        strength = speed * (1 - math.sqrt(1 - ct))
        for j in order[position + 1:]:
            dx = along[j] - along[i]
            if dx <= 1e-9:
                continue
            wake = radius + k * dx
            fraction = overlap_fraction(wake, radius, across[j] - across[i])
            if fraction:
                deficits[j] += (strength * (radius / wake) ** 2 * fraction) ** 2
    return effective


def farm_aep(layout, turbine, climate, *, k=0.1):
    """Gross and waked AEP (GWh) per turbine for a joint direction × speed probability table."""
    ws, power, ct = (np.asarray(turbine[key], float) for key in ('wind_speed_m_s', 'power_w', 'ct'))

    def curve(values):
        return lambda v: float(np.interp(v, ws, values, left=0.0, right=0.0))
    ct_curve, power_curve = curve(ct), curve(power)
    n = len(layout['x_m'])
    waked = np.zeros(n)
    gross = np.zeros(n)
    for d, direction in enumerate(climate['directions_deg']):
        for s, speed in enumerate(climate['speeds_m_s']):
            p = climate['probabilities'][d][s]
            if p <= 0:
                continue
            effective = effective_speeds(layout['x_m'], layout['y_m'], direction_deg=direction, speed=speed,
                                         diameter=turbine['diameter_m'], ct_curve=ct_curve, k=k)
            waked += p * np.array([power_curve(v) for v in effective])
            gross += p * power_curve(speed)
    hours = 8760 * (1 - climate.get('excluded_probability', 0.0))
    return waked * hours / 1e9, gross * hours / 1e9


def weibull_climate(*, sectors=12, frequencies=None, mean_wind_m_s=8.0, shape=2.0, scale=None, speeds=None):
    """Joint direction × speed probabilities from a Weibull distribution per sector (bins centred on `speeds`).

    The probability outside the speed bins (calms and storms) is reported as `excluded_probability`; the table is
    renormalised to sum to one and energy estimates multiply by (1 − excluded)."""
    if not 1 <= sectors <= 72:
        raise FarmError('sectors must be in 1–72')
    directions = [i * 360.0 / sectors for i in range(sectors)]
    frequencies = np.full(sectors, 1.0 / sectors) if frequencies is None else np.asarray(frequencies, float)
    if len(frequencies) != sectors or np.any(frequencies < 0) or not math.isclose(frequencies.sum(), 1.0, abs_tol=1e-6):
        raise FarmError('Sector frequencies must be non-negative, one per sector, and sum to one')
    speeds = np.asarray(speeds if speeds is not None else np.arange(3.0, 25.01, 1.0), float)
    if len(speeds) < 2 or np.any(np.diff(speeds) <= 0):
        raise FarmError('Speed bins must increase')
    shapes = np.broadcast_to(np.asarray(shape, float), (sectors,))
    if scale is None:
        scales = np.broadcast_to(np.asarray(mean_wind_m_s, float), (sectors,)) / np.array([math.gamma(1 + 1 / s) for s in shapes])
    else:
        scales = np.broadcast_to(np.asarray(scale, float), (sectors,))
    edges = np.concatenate([[speeds[0] - (speeds[1] - speeds[0]) / 2], (speeds[1:] + speeds[:-1]) / 2,
                            [speeds[-1] + (speeds[-1] - speeds[-2]) / 2]])
    edges[0] = max(edges[0], 0.0)
    table = np.zeros((sectors, len(speeds)))
    for i in range(sectors):
        cdf = 1 - np.exp(-(edges / scales[i]) ** shapes[i])
        table[i] = frequencies[i] * np.diff(cdf)
    inside = table.sum()
    if inside <= 0:
        raise FarmError('No probability inside the speed bins')
    return {'directions_deg': directions, 'speeds_m_s': speeds.tolist(), 'probabilities': (table / inside).tolist(),
            'excluded_probability': float(1 - inside), 'weibull_scale_m_s': scales.tolist(), 'weibull_k': shapes.tolist()}
