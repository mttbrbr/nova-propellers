import { useLayoutEffect, useRef, useState } from 'react';
import { formatValue, interpolate, niceTicks } from '../lib/blade.js';

export function useElementWidth(fallback = 480) {
  const ref = useRef(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(160, Math.round(entry.contentRect.width))));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

const baseMargin = { right: 14, top: 12, bottom: 26 };

// One chart for every curve in Nova: title with unit, two or three ticks, a shared
// station selection, hover readout, dashed reference series and optional
// vertically draggable control points.
export default function LineChart({ title, unit, series, height = 220, xDomain = [0, 1], yDomain, xTicks = [0, 0.25, 0.5, 0.75, 1],
  xLabel = 'span', selection, onSelect, controlPoints, onMovePoint, selectedPoint, onSelectPoint, ariaLabel, digits = 3, legend, empty = 'No data available', formatTick = (value) => formatValue(value, 3), formatReadout = (value) => formatValue(value, digits) }) {
  const [box, width] = useElementWidth();
  const [hover, setHover] = useState(null);
  const svg = useRef(null);
  const drag = useRef(null);
  const visible = series.filter((item) => item.points?.length);
  const values = visible.flatMap((item) => item.points.map((point) => point.y)).concat((controlPoints || []).map((point) => point.y));
  const ticks = yDomain ? niceTicks(yDomain[0], yDomain[1], 3).filter((tick) => tick >= yDomain[0] - 1e-9 && tick <= yDomain[1] + 1e-9) : niceTicks(Math.min(...values), Math.max(...values), 3);
  const yMin = yDomain ? yDomain[0] : ticks[0];
  const yMax = yDomain ? yDomain[1] : ticks[ticks.length - 1];
  // Left margin follows the longest tick label so values like "50 000" are never clipped.
  const margin = { ...baseMargin, left: Math.max(36, 14 + Math.max(...ticks.map((tick) => String(formatTick(tick)).length)) * 6.8) };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const shownXTicks = plotW < 320 && xTicks.length > 3 ? [xTicks[0], xTicks[Math.floor(xTicks.length / 2)], xTicks[xTicks.length - 1]] : xTicks;
  const sx = (x) => margin.left + (x - xDomain[0]) / (xDomain[1] - xDomain[0]) * plotW;
  const sy = (y) => margin.top + (1 - (y - yMin) / Math.max(yMax - yMin, 1e-12)) * plotH;
  const invertX = (px) => Math.min(xDomain[1], Math.max(xDomain[0], xDomain[0] + (px - margin.left) / plotW * (xDomain[1] - xDomain[0])));
  const invertY = (py) => yMin + (1 - (py - margin.top) / plotH) * (yMax - yMin);
  const local = (event) => {
    const rect = svg.current.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const primary = visible[0];
  const readout = (x) => primary ? interpolate(primary.points, x) : null;
  const marker = (x, emphasis) => {
    const value = readout(x);
    if (value == null) return null;
    const label = `${formatReadout(value)}${unit ? ` ${unit}` : ''}`;
    const labelWidth = label.length * 7 + 14;
    const px = sx(x), py = sy(value);
    const flip = px + 12 + labelWidth > width - margin.right;
    return <g pointerEvents="none">
      <circle cx={px} cy={py} r={4.5} fill={primary.color} stroke="#0B0D10" strokeWidth="2" />
      <rect x={flip ? px - 12 - labelWidth : px + 10} y={Math.max(margin.top, py - 30)} width={labelWidth} height={22} rx={4} fill="#1A1E25" stroke={emphasis ? '#3A424E' : '#2A303A'} />
      <text x={(flip ? px - 12 - labelWidth : px + 10) + labelWidth / 2} y={Math.max(margin.top, py - 30) + 15} textAnchor="middle" className="fill-nv-ink-strong font-mono text-[11.5px]">{label}</text>
    </g>;
  };
  const description = ariaLabel || `${title}${unit ? ` in ${unit}` : ''} along the blade${selection != null && readout(selection) != null ? `; ${formatReadout(readout(selection))} at ${xLabel} ${selection.toFixed(2)}` : ''}`;
  return <figure className="m-0 min-w-0">
    <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <span className="text-[13px] text-nv-ink">{title}{unit && <span className="ml-1.5 text-nv-muted">{unit}</span>}</span>
      {legend && <span className="flex gap-4 text-xs text-nv-muted">{visible.filter((item) => item.label).map((item) =>
        <span key={item.id} className="inline-flex items-center gap-1.5"><svg width="16" height="4" aria-hidden="true"><line x1="0" x2="16" y1="2" y2="2" stroke={item.color} strokeWidth="2" strokeDasharray={item.dashed ? '4 3' : undefined} /></svg>{item.label}</span>)}</span>}
    </figcaption>
    <div ref={box} className="w-full">
      {!visible.length && !controlPoints?.length ? <div className="grid place-items-center rounded-md border border-dashed border-nv-edge text-xs text-nv-muted" style={{ height }}>{empty}</div> :
      <svg ref={svg} width={width} height={height} role={onMovePoint ? 'group' : 'img'} aria-label={description} className="block touch-none select-none"
        onPointerMove={(event) => {
          const point = local(event);
          if (drag.current != null && onMovePoint) {
            const value = Math.min(yMax, Math.max(yMin, invertY(point.y)));
            onMovePoint(drag.current, value);
            return;
          }
          setHover(point.x >= margin.left && point.x <= width - margin.right ? invertX(point.x) : null);
        }}
        onPointerLeave={() => setHover(null)}
        onPointerUp={() => { drag.current = null; }}
        onClick={(event) => { if (onSelect && drag.current == null) onSelect(Number(invertX(local(event).x).toFixed(3))); }}>
        {ticks.map((tick) => <g key={tick}>
          <line x1={margin.left} x2={width - margin.right} y1={sy(tick)} y2={sy(tick)} stroke={tick === yMin ? '#2A303A' : '#171B21'} />
          <text x={margin.left - 8} y={sy(tick) + 4} textAnchor="end" className="fill-nv-muted font-mono text-[11px]">{formatTick(tick)}</text>
        </g>)}
        {shownXTicks.map((tick, index) => <text key={tick} x={sx(tick)} y={height - 6} textAnchor={index === 0 ? 'start' : index === shownXTicks.length - 1 ? 'end' : 'middle'} className="fill-nv-muted font-mono text-[11px]">
          {index === shownXTicks.length - 1 ? `${tick} ${xLabel}` : tick}</text>)}
        {selection != null && <line x1={sx(selection)} x2={sx(selection)} y1={margin.top} y2={margin.top + plotH} stroke="#FF8533" strokeDasharray="2 4" opacity=".6" />}
        {controlPoints && <polyline points={controlPoints.map((point) => `${sx(point.x)},${sy(point.y)}`).join(' ')} fill="none" stroke="#2A303A" strokeDasharray="3 4" />}
        {[...visible].reverse().map((item) => <polyline key={item.id} points={item.points.map((point) => `${sx(point.x)},${sy(point.y)}`).join(' ')}
          fill="none" stroke={item.color} strokeWidth={item.width || (item.dashed ? 1.6 : 2.25)} strokeDasharray={item.dashed ? '6 5' : undefined} strokeLinejoin="round" />)}
        {controlPoints?.map((point, index) => {
          const active = index === selectedPoint;
          return <g key={index}>
            {active && <circle cx={sx(point.x)} cy={sy(point.y)} r={11} fill={primary?.color || '#FF8533'} opacity=".2" />}
            <circle cx={sx(point.x)} cy={sy(point.y)} r={active ? 6 : 5.5} fill={active ? primary?.color || '#FF8533' : '#0B0D10'} stroke={primary?.color || '#FF8533'} strokeWidth="2"
              className={onMovePoint ? 'cursor-ns-resize' : ''} tabIndex={onMovePoint ? 0 : undefined} role={onMovePoint ? 'slider' : undefined}
              aria-label={onMovePoint ? `${title} point P${index + 1}` : undefined} aria-valuenow={onMovePoint ? Number(point.y.toFixed(4)) : undefined}
              aria-valuemin={onMovePoint ? yMin : undefined} aria-valuemax={onMovePoint ? yMax : undefined}
              onPointerDown={(event) => { if (!onMovePoint) return; event.stopPropagation(); event.currentTarget.ownerSVGElement.setPointerCapture(event.pointerId); drag.current = index; onSelectPoint?.(index); }}
              onClick={(event) => { event.stopPropagation(); onSelectPoint?.(index); }}
              onKeyDown={(event) => {
                if (!onMovePoint || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
                event.preventDefault();
                const delta = (yMax - yMin) / 100 * (event.key === 'ArrowUp' ? 1 : -1) * (event.shiftKey ? 10 : 1);
                onMovePoint(index, Math.min(yMax, Math.max(yMin, point.y + delta)));
              }} />
          </g>;
        })}
        {hover != null && hover !== selection && <line x1={sx(hover)} x2={sx(hover)} y1={margin.top} y2={margin.top + plotH} stroke="#3A424E" pointerEvents="none" />}
        {selection != null && marker(selection, true)}
        {hover != null && Math.abs(hover - (selection ?? -1)) > 0.02 && marker(hover, false)}
      </svg>}
    </div>
  </figure>;
}
