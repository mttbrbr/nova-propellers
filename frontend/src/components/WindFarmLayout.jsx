import { useId } from 'react';

const finite = (value) => value != null && String(value).trim() !== '' && Number.isFinite(Number(value));
const number = (value) => Number(value).toLocaleString(undefined, { maximumSignificantDigits: 6 });

export default function WindFarmLayout({ layout = [] }) {
  const id = useId();
  if (!layout.length || layout.some((row) => !finite(row.x) || !finite(row.y))) {
    return <div aria-label="Wind farm layout preview" className="rounded border border-dashed border-zinc-700 bg-zinc-950/50 p-4"><p role="status" className="text-xs text-zinc-400">Enter finite x and y coordinates for every turbine to preview the layout. Empty coordinates are not interpreted as zero.</p></div>;
  }
  const points = layout.map((row, index) => ({ x: Number(row.x), y: Number(row.y), index }));
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  for (const point of points) { xmin = Math.min(xmin, point.x); xmax = Math.max(xmax, point.x); ymin = Math.min(ymin, point.y); ymax = Math.max(ymax, point.y); }
  const dx = xmax - xmin, dy = ymax - ymin;
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) return <p role="status" className="text-xs text-zinc-400">Coordinate ranges are too large to display. Check the layout units and values.</p>;
  const width = 520, height = 270, left = 64, right = 24, top = 30, bottom = 52;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  // One pixel-per-metre scale applies to both axes, including singleton and collinear layouts.
  const scale = .8 * Math.min(plotWidth / Math.max(dx, 1), plotHeight / Math.max(dy, 1));
  const cx = xmin + dx / 2, cy = ymin + dy / 2;
  const px = (x) => left + plotWidth / 2 + (x - cx) * scale;
  const py = (y) => top + plotHeight / 2 - (y - cy) * scale;
  const xlow = cx - plotWidth / (2 * scale), xhigh = cx + plotWidth / (2 * scale);
  const ylow = cy - plotHeight / (2 * scale), yhigh = cy + plotHeight / (2 * scale);
  return <figure className="rounded-xl border border-zinc-800 bg-zinc-950/50 p-3">
    <svg role="img" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} viewBox={`0 0 ${width} ${height}`} className="max-h-72 w-full">
      <title id={`${id}-title`}>Wind farm layout preview</title><desc id={`${id}-description`}>{points.length} turbines in Cartesian coordinates. East is positive x and North is positive y, measured in metres. Both axes use the same distance scale; turbine markers do not represent rotor diameter.</desc>
      <rect x={left} y={top} width={plotWidth} height={plotHeight} fill="#09090b" stroke="#3f3f46" />
      {[.25, .5, .75].map((fraction) => <g key={fraction} stroke="#27272a"><line x1={left + fraction * plotWidth} x2={left + fraction * plotWidth} y1={top} y2={height - bottom} /><line x1={left} x2={width - right} y1={top + fraction * plotHeight} y2={top + fraction * plotHeight} /></g>)}
      {xlow <= 0 && xhigh >= 0 && <line x1={px(0)} x2={px(0)} y1={top} y2={height - bottom} stroke="#52525b" strokeDasharray="3 4" />}
      {ylow <= 0 && yhigh >= 0 && <line x1={left} x2={width - right} y1={py(0)} y2={py(0)} stroke="#52525b" strokeDasharray="3 4" />}
      {points.map((point) => <g key={point.index} tabIndex={0} role="img" aria-label={`Turbine ${point.index + 1}: East ${number(point.x)} m, North ${number(point.y)} m`}>
        <title>Turbine {point.index + 1}: East {number(point.x)} m, North {number(point.y)} m</title><circle cx={px(point.x)} cy={py(point.y)} r="6" fill="#a5b4fc" stroke="#18181b" strokeWidth="2" /><text x={px(point.x) + 10} y={py(point.y) - 9} fill="#e4e4e7" fontSize="11">T{point.index + 1}</text>
      </g>)}
      <g fill="#a1a1aa" fontSize="10"><text x={left} y={height - bottom + 16}>{number(xlow)}</text><text x={width - right} y={height - bottom + 16} textAnchor="end">{number(xhigh)}</text><text x={left - 7} y={height - bottom} textAnchor="end">{number(ylow)}</text><text x={left - 7} y={top + 4} textAnchor="end">{number(yhigh)}</text><text x={left + plotWidth / 2} y={height - 9} textAnchor="middle">East / x [m] →</text><text transform={`translate(15 ${top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">North / y [m] →</text></g>
    </svg>
    <figcaption className="text-[10px] text-zinc-500">Cartesian layout · equal distance scale on both axes. Turbine markers are schematic; hover or focus them for coordinates.</figcaption>
  </figure>;
}
