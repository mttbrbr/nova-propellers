import { Button, Metric, StatusDot } from '../ui/controls.jsx';

// Always-visible summary of the latest run of the open simulation, so results are
// never a page you have to navigate to.
export default function RunCard({ title = 'Latest run', when, metrics, stale, staleDetail, onOpen, onRun, runDisabled, empty }) {
  return <section aria-label="Latest run" className="flex flex-col gap-3 rounded-[10px] border border-nv-line bg-nv-chrome p-4">
    <div className="flex items-baseline justify-between gap-3">
      <h2 className="m-0 flex items-center gap-2 text-[13.5px] font-semibold"><StatusDot tone={!metrics ? 'muted' : stale ? 'warn' : 'ok'} />{title}</h2>
      {when && <span className="font-mono text-xs text-nv-muted">{when}</span>}
    </div>
    {metrics ? <>
      <dl className={`m-0 grid grid-cols-3 gap-x-5 gap-y-3 ${stale ? 'opacity-60' : ''}`}>
        {metrics.map(([label, value, unit]) => <Metric key={label} size="md" label={label} value={value} unit={unit} />)}
      </dl>
      {stale && <p className="m-0 text-xs leading-relaxed text-nv-warn-ink">Out of date{staleDetail ? `: ${staleDetail}` : ' — inputs changed since this run'}.</p>}
      <div className="flex gap-2">
        {onOpen && <Button className="!h-8" onClick={onOpen}>Open results</Button>}
        {stale && onRun && <Button className="!h-8" disabled={runDisabled} onClick={onRun}>Run again…</Button>}
      </div>
    </> : <p className="m-0 text-[13px] text-nv-muted">{empty || 'Not run yet.'}</p>}
  </section>;
}
