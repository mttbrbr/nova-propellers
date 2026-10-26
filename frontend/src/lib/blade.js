// Small numerical helpers shared by charts, the viewport and the stage panels.

const binomial = (n, k) => {
  let result = 1;
  for (let i = 1; i <= k; i += 1) result = result * (n - k + i) / i;
  return result;
};

// Same Bernstein evaluation as backend/geometry_engine.py::_bezier_values.
export function bezierValue(points, s) {
  const ordered = [...points].sort((a, b) => a.x - b.x);
  const degree = ordered.length - 1;
  return ordered.reduce((sum, point, index) =>
    sum + binomial(degree, index) * (1 - s) ** (degree - index) * s ** index * point.y, 0);
}

export function sampleBezier(points, count = 64) {
  return Array.from({ length: count }, (_, index) => {
    const x = index / (count - 1);
    return { x, y: bezierValue(points, x) };
  });
}

export function interpolate(points, x) {
  if (!points.length) return null;
  const sorted = points[0].x <= points[points.length - 1].x ? points : [...points].reverse();
  if (x <= sorted[0].x) return sorted[0].y;
  for (let index = 1; index < sorted.length; index += 1) {
    if (x <= sorted[index].x) {
      const left = sorted[index - 1], right = sorted[index];
      const weight = (x - left.x) / Math.max(right.x - left.x, 1e-12);
      return left.y + (right.y - left.y) * weight;
    }
  }
  return sorted[sorted.length - 1].y;
}

export function niceTicks(min, max, count = 3) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) { const pad = Math.abs(min) * 0.1 || 1; min -= pad; max += pad; }
  const raw = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((value) => value >= raw) || 10 * magnitude;
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks = [];
  for (let value = start; value <= end + step / 2; value += step) ticks.push(Number(value.toPrecision(12)));
  return ticks;
}

export function formatValue(value, digits = 3) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const number = Number(value);
  const magnitude = Math.abs(number);
  if (magnitude !== 0 && (magnitude >= 1e7 || magnitude < 1e-3)) return number.toExponential(2);
  if (magnitude >= 1000) return Math.round(number).toLocaleString('en-US').replaceAll(',', ' ');
  return Number(number.toPrecision(digits)).toString();
}

// Station series along the span fraction (0 at the root section, 1 at the tip).
export function stationSeries(stations, field, scale = 1) {
  return (stations || [])
    .map((station) => ({ x: Number(station.r_over_R), y: Number(station[field]) * scale }))
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
    .sort((a, b) => a.x - b.x);
}

// NACA four-digit section outline for the section preview, closed from the trailing edge.
export function nacaOutline(m, p, t, count = 40) {
  const upper = [], lower = [];
  for (let index = 0; index <= count; index += 1) {
    const beta = Math.PI * index / count;
    const x = (1 - Math.cos(beta)) / 2;
    const yt = 5 * t * (0.2969 * Math.sqrt(x) - 0.126 * x - 0.3516 * x ** 2 + 0.2843 * x ** 3 - 0.1015 * x ** 4);
    let yc = 0, slope = 0;
    if (m > 0 && p > 0) {
      if (x < p) { yc = m / p ** 2 * (2 * p * x - x ** 2); slope = 2 * m / p ** 2 * (p - x); }
      else { yc = m / (1 - p) ** 2 * (1 - 2 * p + 2 * p * x - x ** 2); slope = 2 * m / (1 - p) ** 2 * (p - x); }
    }
    const theta = Math.atan(slope);
    upper.push([x - yt * Math.sin(theta), yc + yt * Math.cos(theta)]);
    lower.push([x + yt * Math.sin(theta), yc - yt * Math.cos(theta)]);
  }
  return [...upper.reverse(), ...lower.slice(1)];
}

export function nacaFromName(name) {
  const digits = /NACA\s*(\d)(\d)(\d\d)$/i.exec(name || '');
  return digits ? { m: Number(digits[1]) / 100, p: Number(digits[2]) / 10, t: Number(digits[3]) / 100 } : null;
}

// Values of a canonical geometry at one span fraction, used by the section and readouts.
export function stationAt(stations, s) {
  if (!stations?.length) return null;
  const pick = (field) => interpolate(stationSeries(stations, field), s);
  return {
    s,
    radius_m: pick('radius_m'), chord_m: pick('chord_m'), twist_deg: pick('twist_deg'),
    m: pick('airfoil_m'), p: pick('airfoil_p'), t: pick('airfoil_t'),
  };
}
