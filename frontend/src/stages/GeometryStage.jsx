import { Activity, Download, Loader2, Plus, X } from 'lucide-react';
import PropellerViewport from '../components/PropellerViewport.jsx';
import { formatValue, interpolate, nacaFromName, nacaOutline, sampleBezier, stationAt, stationSeries } from '../lib/blade.js';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import { Button, Disclosure, Field, LabeledSegmented, Metric, Notice, Section, SelectField, buttonClass } from '../ui/controls.jsx';
import LineChart from '../ui/LineChart.jsx';
import SectionView from '../ui/SectionView.jsx';

const toMm = (points) => points.map((point) => ({ x: point.x, y: point.y * 1000 }));

function PointTable({ title, unit, points, scale = 1, onChange, highlight }) {
  return <table className="w-full min-w-[220px] border-collapse font-mono text-[13px] tabular">
    <caption className="pb-3 text-left font-sans text-[13px] font-semibold">{title}</caption>
    <thead><tr className="font-sans text-xs text-nv-muted">
      <th scope="col" className="pb-2.5 text-left font-medium">Point</th><th scope="col" className="pb-2.5 text-right font-medium">Span</th><th scope="col" className="pb-2.5 text-right font-medium">{unit}</th>
    </tr></thead>
    <tbody>{points.map((point, index) => <tr key={index} className={`border-t border-nv-line ${highlight === index ? 'bg-nv-accent/[.07]' : ''}`}>
      <td className={`py-1.5 ${highlight === index ? 'text-nv-accent' : 'text-nv-muted'}`}>P{index + 1}{index === 0 ? ' · root' : index === points.length - 1 ? ' · tip' : ''}</td>
      <td className="py-1.5 text-right">{point.x.toFixed(2)}</td>
      <td className="py-1 pl-3 text-right"><input type="number" step="any" aria-label={`${title} P${index + 1} ${unit}`} value={Number((point.y * scale).toFixed(3))}
        onChange={(event) => onChange(index, Number(event.target.value) / scale)}
        className="h-7 w-20 rounded border border-transparent bg-transparent px-1.5 text-right hover:border-nv-edge focus:border-nv-accent focus:outline-none" /></td>
    </tr>)}</tbody>
  </table>;
}

export default function GeometryStage({ g }) {
  const { inputs, set, bezier, preview, station, setStation, published } = g;
  const bezierMode = g.designMode === 'inverse' || inputs.geometry_method === 'bezier';
  const stations = preview.canonical?.stations || [];
  const selected = stationAt(stations, station);
  const radius = (Number(inputs.diameter) || 0) / 2;
  const rootFraction = stations.length ? stations[0].radius_m / Math.max(preview.canonical.diameter_m / 2, 1e-9) : 0.14;
  const publishedParams = published?.definition?.geometry_method === 'bezier' ? published.definition.geometry_parameters : null;
  const moveChord = (index, mm) => { g.setBezier({ ...bezier, chord_points: bezier.chord_points.map((p, i) => i === index ? { ...p, y: mm / 1000 } : p) }); g.clearInverse(); g.setSelectedPoint({ curve: 'chord', index }); };
  const moveTwist = (index, deg) => { g.setBezier({ ...bezier, twist_points: bezier.twist_points.map((p, i) => i === index ? { ...p, y: deg } : p) }); g.clearInverse(); g.setSelectedPoint({ curve: 'twist', index }); };
  const chordSeries = bezierMode ? toMm(sampleBezier(bezier.chord_points)) : stationSeries(stations, 'chord_m', 1000);
  const twistSeries = bezierMode ? sampleBezier(bezier.twist_points) : stationSeries(stations, 'twist_deg');
  const publishedChanged = (key) => publishedParams && JSON.stringify(publishedParams[key]) !== JSON.stringify(bezier[key]);
  const chordAt = selected ? selected.chord_m * 1000 : interpolate(chordSeries, station);
  const twistAt = selected ? selected.twist_deg : interpolate(twistSeries, station);
  const naca = selected?.t ? { m: selected.m, p: selected.p, t: selected.t } : nacaFromName(inputs.airfoil);
  const methods = (g.methods.length ? g.methods : [{ id: 'bemt', name: 'BEMT', fidelity: 'preliminary' }, { id: 'llt', name: 'LLT', fidelity: 'preliminary' }])
    .filter((method) => method.role !== 'sizing_reference' && method.id !== 'actuator_disk');
  const tooManyPoints = bezier.chord_points.length > 4 || bezier.twist_points.length > 4;
  const sigma = stations.length ? (inputs.blades * interpolate(stationSeries(stations, 'chord_m'), 0.75)) / (Math.PI * radius) : null;

  return <StageLayout inputsLabel="Stage inputs" contentLabel="Blade distributions" sideLabel="Preview and section"
    inputs={<>
      <StageTitle title="Geometry" detail="The preview updates as you edit." />
      <Section title="Blade">
        <Field label="Diameter" unit="m" value={inputs.diameter} onChange={(v) => set('diameter', v)} />
        <Field label="Blades" ariaLabel="Blade count" value={inputs.blades} step={1} onChange={(v) => set('blades', v)} />
        <Field label="Design speed" ariaLabel="Design RPM" unit="rpm" value={inputs.rpm} onChange={(v) => set('rpm', v)} />
        <SelectField label="Base airfoil" ariaLabel="Airfoil" value={inputs.airfoil} onChange={(v) => set('airfoil', v)} options={g.airfoils.map((name) => [name, name])} />
      </Section>
      <Section title="Shape">
        <LabeledSegmented label="Approach" value={g.designMode} onChange={(value) => { g.setDesignMode(value); if (value === 'inverse') set('geometry_method', 'bezier'); g.clearInverse(); }}
          options={[['direct', 'Direct'], ['inverse', 'Inverse']]} />
        <LabeledSegmented label="Method" value={bezierMode ? 'bezier' : 'laguerre'} onChange={(v) => set('geometry_method', v)}
          options={[['bezier', 'Bézier'], ['laguerre', 'Laguerre', g.designMode === 'inverse']]} />
        {bezierMode ? <div className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-3">
          <span className="text-[13px] text-nv-muted">Control points</span>
          <div className="grid grid-cols-2 gap-2">
            <Field inline ariaLabel="Chord control points" unit="chord" step={1} min={2} max={10} value={bezier.chord_points.length} onChange={(v) => g.setBezierPointCount('chord', v)} />
            <Field inline ariaLabel="Twist control points" unit="twist" step={1} min={2} max={10} value={bezier.twist_points.length} onChange={(v) => g.setBezierPointCount('twist', v)} />
          </div>
        </div> : Object.keys(g.laguerre).map((key) => <div key={key} className="flex flex-col gap-2">
          <span className="text-[13px] text-nv-muted">{key === 'chord_coefficients' ? 'Chord coefficients' : 'Twist coefficients'}</span>
          <div className="grid grid-cols-4 gap-1.5">{g.laguerre[key].map((value, i) => <input key={i} aria-label={`${key.replace('_coefficients', '')} coefficient ${i + 1}`} type="number" step="any" value={value}
            className="h-[34px] min-w-0 rounded-md border border-nv-edge bg-nv-chrome px-2 font-mono text-xs focus:border-nv-accent focus:outline-none"
            onChange={(e) => g.setLaguerre({ ...g.laguerre, [key]: g.laguerre[key].map((x, j) => j === i ? Number(e.target.value) : x) })} />)}</div>
        </div>)}
        {tooManyPoints && bezierMode && <p className="m-0 text-xs leading-relaxed text-nv-warn-ink">More than 4 points: direct geometry works, inverse design is blocked by the safety guard.</p>}
      </Section>
      {g.designMode === 'inverse' && <Section title="Inverse design">
        <Field label="Target thrust" unit="N" value={inputs.thrust_target} onChange={(v) => { set('thrust_target', v); g.clearInverse(); }} />
        <SelectField label="Loss solver" ariaLabel="Solver used in the loss function" value={g.inverseSolver} onChange={(v) => { g.setInverseSolver(v); g.clearInverse(); }}
          options={methods.map((m) => [m.id, `${m.name} — ${m.fidelity}`])} />
        <p className="m-0 text-xs leading-relaxed text-nv-muted">The optimizer adjusts Bézier chord and twist to reach the target thrust within the mesh limits.</p>
        <Button disabled={g.busy || tooManyPoints} onClick={g.optimize}>{g.busy ? <><Loader2 size={15} className="animate-spin" aria-hidden="true" />Optimizing…</> : <><Activity size={15} aria-hidden="true" />Find candidate geometry</>}</Button>
        {g.inverseResult && <div className="flex flex-col gap-3 rounded-lg border border-nv-edge p-3.5">
          <dl className="m-0 grid grid-cols-2 gap-3">
            <Metric size="md" label="Initial thrust" value={g.inverseResult.initial_performance ? formatValue(g.inverseResult.initial_performance.thrust) : '—'} unit="N" />
            <Metric size="md" label="Candidate" value={formatValue(g.inverseResult.performance.thrust)} unit="N" />
            <Metric size="md" label="Target error" value={(100 * Math.abs(g.inverseResult.performance.thrust - inputs.thrust_target) / inputs.thrust_target).toFixed(2)} unit="%" />
            <Metric size="md" label="Iterations" value={g.inverseResult.iterations} />
          </dl>
          <Notice tone={g.inverseResult.success ? 'ok' : 'warn'}>{g.inverseResult.success ? 'Optimizer converged.' : `Stopped before tolerance: ${g.inverseResult.message}. Review before applying.`}</Notice>
          <div className="grid grid-cols-2 gap-2"><Button variant="secondary" disabled={g.busy} onClick={g.applyInverse}>Apply candidate</Button><Button variant="ghost" onClick={g.clearInverse}>Discard</Button></div>
        </div>}
      </Section>}
      <Disclosure title="Airfoil loft" summary={g.useAirfoilLoft ? 'On' : 'Off'}>
        <label className="flex items-center justify-between gap-3 text-[13px]">Use distributed DAT airfoils
          <input type="checkbox" className="h-4 w-4 accent-nv-accent" checked={g.useAirfoilLoft} disabled={g.coordinateAirfoils.length < 1}
            onChange={(event) => { g.setUseAirfoilLoft(event.target.checked); g.setLoftPreview(null); }} /></label>
        {g.coordinateAirfoils.length < 1 && <p className="m-0 text-xs text-nv-muted">Import at least one .dat airfoil in Library.</p>}
        {g.useAirfoilLoft && (inputs.geometry_method === 'bezier'
          ? <>{bezier.chord_points.map((point, index) => <SelectField key={`${point.x}-${index}`} label={`Span ${point.x.toFixed(2)}`} ariaLabel={`Airfoil P${index + 1}`}
            value={g.bezierProfileAssignments[index] || g.coordinateAirfoils[0] || ''} options={g.coordinateAirfoils.map((name) => [name, name])}
            onChange={(value) => g.setBezierProfileAssignments((current) => current.map((item, itemIndex) => itemIndex === index ? value : item))} />)}</>
          : <>{g.laguerreProfileAssignments.map((assignment, index) => <div key={index} className="grid grid-cols-[86px_minmax(0,1fr)_34px] items-center gap-2">
            <Field inline ariaLabel="Span fraction" value={assignment.radial_fraction} onChange={(value) => g.updateLaguerreProfileStation(index, { radial_fraction: Math.max(0, Math.min(1, value)) })} />
            <SelectField inline ariaLabel="Airfoil" value={assignment.airfoil} options={g.coordinateAirfoils.map((name) => [name, name])} onChange={(value) => g.updateLaguerreProfileStation(index, { airfoil: value })} />
            <button type="button" aria-label={`Remove station ${index + 1}`} className={buttonClass('danger', '!px-0')} disabled={g.laguerreProfileAssignments.length <= 2 || index === 0 || index === g.laguerreProfileAssignments.length - 1}
              onClick={() => g.removeLaguerreStation(index)}><X size={14} aria-hidden="true" /></button>
          </div>)}
          <Button disabled={g.laguerreProfileAssignments.length >= 10} onClick={g.addLaguerreProfileStation}><Plus size={15} aria-hidden="true" />Add airfoil station</Button></>)}
        {g.useAirfoilLoft && <Button onClick={g.previewLoft}>Preview section at span 0.5</Button>}
      </Disclosure>
      <Section title="Revision"><div ref={g.slotRef('revision')} className="flex flex-col gap-2.5" /></Section>
      {preview.stlUrl && <a className={buttonClass('secondary')} href={preview.stlUrl} download={`nova_${inputs.geometry_method}.stl`}><Download size={15} aria-hidden="true" />Export STL</a>}
    </>}
    content={<>
      {preview.error && <Notice tone="err" role="alert">Preview not updated: {preview.error}</Notice>}
      <LineChart title="Chord" unit="mm" height={250} legend selection={station} onSelect={setStation} digits={3}
        yDomain={bezierMode ? [0, Number(inputs.diameter) * 0.16 * 1000] : undefined}
        series={[{ id: 'draft', label: published ? 'Draft' : undefined, color: '#4CC9F0', points: chordSeries },
          ...(bezierMode && publishedChanged('chord_points') ? [{ id: 'published', label: `Published r${published.geometry_revision}`, color: '#6B7480', dashed: true, points: toMm(sampleBezier(publishedParams.chord_points)) }] : [])]}
        controlPoints={bezierMode ? toMm(bezier.chord_points) : undefined} onMovePoint={bezierMode ? moveChord : undefined}
        selectedPoint={g.selectedPoint.curve === 'chord' ? g.selectedPoint.index : undefined} onSelectPoint={(index) => g.setSelectedPoint({ curve: 'chord', index })} />
      <LineChart title="Twist" unit="°" height={250} legend selection={station} onSelect={setStation}
        yDomain={bezierMode ? [0, 45] : undefined}
        series={[{ id: 'draft', label: published ? 'Draft' : undefined, color: '#B49CFB', points: twistSeries },
          ...(bezierMode && publishedChanged('twist_points') ? [{ id: 'published', label: `Published r${published.geometry_revision}`, color: '#6B7480', dashed: true, points: sampleBezier(publishedParams.twist_points) }] : [])]}
        controlPoints={bezierMode ? bezier.twist_points : undefined} onMovePoint={bezierMode ? moveTwist : undefined}
        selectedPoint={g.selectedPoint.curve === 'twist' ? g.selectedPoint.index : undefined} onSelectPoint={(index) => g.setSelectedPoint({ curve: 'twist', index })} />
      {bezierMode && <section aria-label="Control points" className="grid gap-x-14 gap-y-6 lg:grid-cols-2">
        <PointTable title="Chord points" unit="mm" scale={1000} points={bezier.chord_points} onChange={(index, value) => moveChord(index, value * 1000)}
          highlight={g.selectedPoint.curve === 'chord' ? g.selectedPoint.index : undefined} />
        <PointTable title="Twist points" unit="°" points={bezier.twist_points} onChange={moveTwist}
          highlight={g.selectedPoint.curve === 'twist' ? g.selectedPoint.index : undefined} />
        <p className="m-0 text-xs text-nv-muted lg:col-span-2">Drag a point, use ↑/↓ on a focused point, or type the value. Span 0 is the root section, 1 the tip. Chord is limited to {formatValue(Number(inputs.diameter) * 160)} mm (0.16 D).</p>
      </section>}
      {g.loftPreview && <SectionView caption="Interpolated loft at span 0.5" outline={g.loftPreview} chordMm={null} twistDeg={0} />}
    </>}
    side={<>
      <PropellerViewport geometry={preview.mesh} busy={preview.busy} station={station} rootFraction={rootFraction}
        stationLabel={selected ? `span ${station.toFixed(2)} · r ${formatValue(selected.radius_m * 1000)} mm` : null} label="3D preview of the propeller; the ring marks the selected station" />
      <div className="grid gap-8 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <dl className="m-0 grid grid-cols-2 content-start gap-x-5 gap-y-[18px]">
          <Metric size="md" label="Diameter" value={formatValue(Number(inputs.diameter) * 1000, 4)} unit="mm" />
          <Metric size="md" label="Stations" value={stations.length || '—'} />
          <Metric size="md" label="Root chord" value={stations.length ? formatValue(stations[0].chord_m * 1000) : '—'} unit="mm" />
          <Metric size="md" label="Tip chord" value={stations.length ? formatValue(stations.at(-1).chord_m * 1000) : '—'} unit="mm" />
          <Metric size="md" label="Solidity σ₀.₇₅" value={sigma ? formatValue(sigma) : '—'} />
          <Metric size="md" label="Blades" value={inputs.blades} />
        </dl>
        <SectionView caption={`Section at span ${station.toFixed(2)}`} outline={naca ? nacaOutline(naca.m, naca.p, naca.t) : null} chordMm={chordAt} twistDeg={twistAt} />
      </div>
    </>} />;
}
