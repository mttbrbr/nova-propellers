import { formatValue } from '../lib/blade.js';
import { useElementWidth } from './LineChart.jsx';

// Airfoil section drawn at its pitch angle against the rotation plane.
export default function SectionView({ outline, chordMm, twistDeg, caption, height = 170 }) {
  const [box, width] = useElementWidth(340);
  if (!outline?.length) return <div className="grid place-items-center rounded-md border border-dashed border-nv-edge text-xs text-nv-muted" style={{ height }}>No section available</div>;
  const originX = 26, originY = height * 0.66;
  const angle = -(Number(twistDeg) || 0);
  // Shrink the chord when a steep pitch would push the trailing edge out of the frame.
  const scale = Math.min((width - 60) * 0.82, (originY - 16) / Math.max(Math.sin(Math.abs(angle) * Math.PI / 180), 0.2));
  const points = outline.map(([x, y]) => `${(x - 0.0) * scale},${-y * scale}`).join(' ');
  const arcRadius = Math.min(110, scale * 0.42);
  const arcAngle = (Number(twistDeg) || 0) * Math.PI / 180;
  return <figure className="m-0 min-w-0">
    {caption && <figcaption className="mb-2 text-[13px] font-semibold">{caption}</figcaption>}
    <div ref={box}>
      <svg width={width} height={height} role="img" aria-label={`Airfoil section, chord ${formatValue(chordMm)} millimetres, pitched ${formatValue(twistDeg)} degrees to the rotation plane`}>
        <line x1={8} x2={width - 8} y1={originY} y2={originY} stroke="#2A303A" />
        <g transform={`translate(${originX} ${originY}) rotate(${angle})`}>
          <line x1={-6} x2={scale + 6} y1={0} y2={0} stroke="#4A5260" strokeDasharray="3 4" />
          <polygon points={points} fill="rgba(255, 133, 51,.14)" stroke="#FF8533" strokeWidth="1.8" strokeLinejoin="round" />
        </g>
        <path d={`M ${originX + arcRadius} ${originY} A ${arcRadius} ${arcRadius} 0 0 0 ${originX + arcRadius * Math.cos(arcAngle)} ${originY - arcRadius * Math.sin(arcAngle)}`} fill="none" stroke="#9AA3AE" strokeWidth="1.2" />
        <text x={originX + arcRadius + 10} y={originY - 10} className="fill-nv-muted font-mono text-[11.5px]">θ {formatValue(twistDeg)}°</text>
        <text x={8} y={height - 6} className="fill-nv-muted font-mono text-[11.5px]">c {formatValue(chordMm)} mm</text>
        <text x={width - 8} y={height - 6} textAnchor="end" className="fill-nv-muted font-mono text-[11.5px]">rotation plane</text>
      </svg>
    </div>
  </figure>;
}
