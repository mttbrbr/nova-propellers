import { Save, Upload } from 'lucide-react';
import { useState } from 'react';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import { Button, Field, Metric, Notice, Section, Segmented, StatusDot, buttonClass } from '../ui/controls.jsx';
import SectionView from '../ui/SectionView.jsx';
import { formatValue } from '../lib/blade.js';
import { PolarCharts } from './AnalysisStage.jsx';
import { ReportBody } from './ResultsStage.jsx';

function AirfoilDetail({ detail }) {
  if (!detail) return <p className="m-0 text-[13px] text-nv-muted">Select an airfoil from the list.</p>;
  const rows = detail.polars || [], quality = detail.polar_quality;
  return <>
    <div><p className="m-0 text-xs uppercase tracking-[0.08em] text-nv-muted">Airfoil</p><h2 className="m-0 mt-1.5 text-[22px] font-semibold">{detail.name}</h2>
      <p className="m-0 mt-1.5 text-[13px] text-nv-muted">{detail.family} · {detail.source}</p></div>
    <dl className="m-0 grid grid-cols-2 gap-6 border-y border-nv-line py-5 sm:grid-cols-4">
      <Metric label="Camber" value={detail.camber} /><Metric label="Thickness" value={detail.thickness} />
      <Metric label="Polar sets" value={detail.polar_sets?.length || 0} /><Metric label="Points" value={rows.length} />
    </dl>
    <Notice tone={quality?.status === 'ok' ? 'ok' : 'warn'}>Polar quality: {quality?.status || 'missing'}{quality?.warnings?.length ? ` · ${quality.warnings.join(' · ')}` : ''}</Notice>
    <PolarCharts title="Polar curves" points={rows} />
    {detail.coordinates?.length ? <SectionView caption="Normalized coordinates" outline={detail.coordinates.map(([x, y]) => [Number(x), Number(y)])} chordMm={null} twistDeg={0} />
      : <p className="m-0 text-[13px] text-nv-muted">No DAT coordinates imported for this airfoil.</p>}
    {(detail.polar_sets || []).length > 0 && <section className="grid gap-3 md:grid-cols-2">{detail.polar_sets.map((set) =>
      <div key={set.id} className="rounded-lg border border-nv-line p-3.5 text-[13px]">
        <div className="flex justify-between"><span>{set.label}</span><span className="font-mono text-nv-muted">#{set.id}</span></div>
        <p className="m-0 mt-1.5 text-nv-muted">{set.method} · Re {set.min_reynolds}–{set.max_reynolds} · {set.points} points</p>
      </div>)}</section>}
    {rows.length > 0 && <div className="max-h-[420px] overflow-auto">
      <table aria-label="Polar points" className="w-full min-w-[760px] border-collapse font-mono text-[12.5px] tabular">
        <thead className="sticky top-0 bg-nv-canvas"><tr>{['Set', 'Re', 'Mach', 'Alpha', 'Cl', 'Cd', 'Cm', 'Source'].map((x) => <th key={x} scope="col" className="px-2.5 pb-2.5 text-right font-sans text-xs font-medium text-nv-muted first:pl-0 first:text-left">{x}</th>)}</tr></thead>
        <tbody>{rows.map((row, i) => <tr key={i} className="border-t border-nv-line text-right">
          {[row.polar_set_id, formatValue(row.reynolds, 6), row.mach, formatValue(row.alpha_deg, 4), formatValue(row.cl, 4), formatValue(row.cd, 4), formatValue(row.cm, 4), row.source].map((x, j) => <td key={j} className="px-2.5 py-1.5 first:pl-0 first:text-left">{x}</td>)}
        </tr>)}</tbody>
      </table>
    </div>}
  </>;
}

export default function LibraryWorkspace({ l }) {
  const [station, setStation] = useState(0.7);
  const [showAll, setShowAll] = useState(false);
  const [reportModel, setReportModel] = useState('');
  const tabs = <Segmented label="Library section" value={l.tab} onChange={l.setTab} size="sm" options={[['airfoils', 'Airfoils'], ['models', 'Models'], ['archives', 'Archives']]} />;
  if (l.tab === 'models') return <StageLayout inputsLabel="Library navigation" contentLabel="Physical models"
    inputs={<><StageTitle title="Library" detail="Airfoils, polars, models and archived projects." />{tabs}
      <p className="m-0 text-[13px] leading-relaxed text-nv-muted">Each solver states its role, maturity and the geometry it supports. Only methods that match the implemented geometry and analysis paths are exposed.</p></>}
    content={<>
      <h2 className="m-0 text-[22px] font-semibold">Physical models and solver capabilities</h2>
      {l.methods.map((method) => <section key={method.id} aria-labelledby={`model-${method.id}`} className="flex flex-col gap-2.5 border-t border-nv-line pt-6">
        <div className="flex flex-wrap items-baseline justify-between gap-3"><h3 id={`model-${method.id}`} className="m-0 text-[15px] font-semibold">{method.name}</h3>
          <span className={`text-xs capitalize ${method.fidelity === 'experimental' ? 'text-nv-warn-ink' : 'text-nv-accent-soft'}`}>{method.fidelity}</span></div>
        <p className="m-0 max-w-3xl text-[13px] leading-relaxed text-nv-reference">{method.description}</p>
        {method.warnings.map((warning) => <p key={warning} className="m-0 flex items-center gap-2 text-[13px] text-nv-warn-ink"><StatusDot tone="warn" />{warning}</p>)}
        <p className="m-0 text-[13px] text-nv-muted">Supported geometry: {method.suitable_for.join(', ')}</p>
        {method.role === 'analysis' && <Button className="self-start" onClick={() => l.configure(method.id)}>Configure analysis</Button>}
      </section>)}
    </>} />;
  if (l.tab === 'archives') {
    const project = l.selectedProject;
    const analyses = project?.analyses || [];
    const analysis = analyses.find((item) => (item.node_id || item.model) === reportModel) || analyses[0];
    return <StageLayout inputsLabel="Library navigation" contentLabel="Archived project report"
      inputs={<><StageTitle title="Library" detail="Airfoils, polars, models and archived projects." />{tabs}
        <Section title="Legacy snapshot archive">
          <p className="m-0 text-[13px] leading-relaxed text-nv-muted">Compatibility library from Nova Propellers. Projects and named simulations use the global Save action.</p>
          <Button disabled={!l.geometryCurrent || l.busy} onClick={l.save}><Save size={15} aria-hidden="true" />{l.savedId ? `Saved #${l.savedId}` : 'Archive legacy snapshot'}</Button>
        </Section>
        <Section title="Legacy saved projects">
          {!l.projects.length && <p className="m-0 text-[13px] text-nv-muted">No legacy projects.</p>}
          <div className="-mx-2.5 flex flex-col gap-0.5">{l.projects.map((item) => <div key={item.id} className={`rounded-lg p-2.5 ${project?.id === item.id ? 'bg-nv-hover' : 'hover:bg-nv-raised'}`}>
            <button type="button" className="w-full text-left" onClick={() => l.open(item.id)}>
              <span className="flex justify-between text-[13px]"><span>{item.project_name}</span><span className="font-mono text-nv-muted">#{item.id}</span></span>
              <span className="mt-1 block text-xs text-nv-muted">{item.geometry_method} · {(item.models || []).join(', ')} · {item.created_at}</span>
            </button>
            <div className="mt-2 flex gap-4 text-xs"><button type="button" className="text-nv-accent" onClick={() => l.downloadStl(item)}>STL</button>
              <button type="button" className="text-nv-err-ink" onClick={() => l.remove(item.id)}>Delete</button></div>
          </div>)}</div>
        </Section>
      </>}
      content={project ? <ReportBody title={project.project_name} analyses={analyses} analysis={analysis} onSelectAnalysis={setReportModel} geometry={project.geometry}
        station={station} setStation={setStation} showAllStations={showAll} setShowAllStations={setShowAll} />
        : <p className="m-0 text-[13px] text-nv-muted">Select an archived project.</p>} />;
  }
  return <StageLayout inputsLabel="Library navigation" contentLabel="Airfoil detail"
    inputs={<><StageTitle title="Library" detail="Airfoils, polars, models and archived projects." />{tabs}
      <Section title="Import XFOIL/UIUC coordinates">
        <p className="m-0 text-[13px] leading-relaxed text-nv-muted">The .dat file is cleaned and normalized to 100 points.</p>
        <label className={`${buttonClass('secondary')} cursor-pointer`}><Upload size={15} aria-hidden="true" />Select .dat file
          <input type="file" accept=".dat,text/plain" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) l.importDat(file); event.target.value = ''; }} /></label>
      </Section>
      <Section title={`Airfoils · ${l.airfoils.length}`}>
        <div className="-mx-2.5 flex max-h-64 flex-col gap-0.5 overflow-auto">{l.airfoils.map((name) => <button key={name} type="button" aria-current={l.selectedAirfoil === name ? 'true' : undefined}
          onClick={() => l.setSelectedAirfoil(name)} className={`rounded-lg px-2.5 py-2 text-left text-[13px] ${l.selectedAirfoil === name ? 'bg-nv-hover text-nv-ink-strong' : 'text-nv-reference hover:bg-nv-raised'}`}>{name}</button>)}</div>
      </Section>
      <Section title="New airfoil">
        <Field label="Name" text value={l.airfoilForm.name} onChange={(value) => l.setAirfoilForm({ ...l.airfoilForm, name: value })} />
        <Field label="Family" text value={l.airfoilForm.family} onChange={(value) => l.setAirfoilForm({ ...l.airfoilForm, family: value })} />
        <Field label="Source" text value={l.airfoilForm.source} onChange={(value) => l.setAirfoilForm({ ...l.airfoilForm, source: value })} />
        <Button disabled={!l.airfoilForm.name || l.busy} onClick={l.createAirfoil}>Create airfoil</Button>
      </Section>
      {l.airfoilDetail && <Section title="Edit selected">
        <Field label="Family" ariaLabel="Edit family" text value={l.airfoilEdit.family} onChange={(value) => l.setAirfoilEdit({ ...l.airfoilEdit, family: value })} />
        <Field label="Source" ariaLabel="Edit source" text value={l.airfoilEdit.source} onChange={(value) => l.setAirfoilEdit({ ...l.airfoilEdit, source: value })} />
        <Field label="Notes" text value={l.airfoilEdit.notes} onChange={(value) => l.setAirfoilEdit({ ...l.airfoilEdit, notes: value })} />
        <div className="grid grid-cols-2 gap-2"><Button onClick={l.updateAirfoil}>Update</Button><Button variant="danger" onClick={l.deleteAirfoil}>Delete airfoil</Button></div>
      </Section>}
    </>}
    content={<AirfoilDetail detail={l.airfoilDetail} />} />;
}
