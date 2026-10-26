import { Activity, Boxes, Database, FileText, FlaskConical, Gauge, GitBranch, Layers3, Plug } from 'lucide-react';

const groups = [
  { title: 'Propeller workflow', items: [
    { id: 'sizing', label: 'Initial sizing', icon: Gauge, detail: 'Project targets and initial dimensions', guided: true },
    { id: 'geometry', label: 'Geometry', icon: Layers3, detail: 'Blade shape and geometry preview', guided: true },
    { id: 'forces', label: 'Force analysis', icon: Activity, detail: 'Operating conditions and aerodynamic analysis', guided: true },
    { id: 'report', label: 'Results', icon: FileText, detail: 'Performance, diagnostics and report' },
  ] },
  { title: 'Analysis tools', items: [
    { id: 'models', label: 'Models', icon: Boxes, detail: 'Physical models, capabilities and assumptions' },
    { id: 'workflow', label: 'Workflow', icon: GitBranch, detail: 'Inspect, customize and execute the project graph' },
    { id: 'studies', label: 'Studies', icon: FlaskConical, detail: 'Parameter sweeps and result comparisons' },
  ] },
  { title: 'Library & software', items: [
    { id: 'database', label: 'Database', icon: Database, detail: 'Archived projects, airfoils and polar data' },
    { id: 'integrations', label: 'Integrations', icon: Plug, detail: 'External software, cases and imported results' },
  ] },
];

export function workspaceInfo(phase) {
  return groups.flatMap((group) => group.items).find((item) => item.id === phase) || groups[0].items[0];
}

export default function WorkspaceNavigation({ phase, onNavigate, guidedCompatible }) {
  return <>
    <div className="border-b border-white/[0.07] bg-zinc-950 px-4 py-3 lg:hidden">
      <label className="flex items-center gap-3 text-xs text-zinc-400">Workspace
        <select aria-label="Workspace" className="min-w-0 flex-1 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100"
          value={phase} onChange={(event) => onNavigate(event.target.value)}>
          {groups.map((group) => <optgroup key={group.title} label={group.title}>{group.items.map((item) =>
            <option key={item.id} value={item.id} disabled={item.guided && !guidedCompatible}>{item.label}</option>)}</optgroup>)}
        </select>
      </label>
    </div>
    <nav aria-label="Workspace navigation" className="hidden min-h-0 flex-col gap-7 overflow-y-auto border-r border-white/[0.07] bg-zinc-950/70 px-3 py-6 lg:flex">
      {groups.map((group) => <div key={group.title}>
        <h2 className="mb-2 px-3 text-[10px] font-medium uppercase tracking-[0.12em] text-zinc-500">{group.title}</h2>
        <div className="space-y-1">{group.items.map(({ id, label, icon: Icon, detail, guided }) => {
          const unavailable = guided && !guidedCompatible;
          return <button key={id} type="button" aria-current={phase === id ? 'page' : undefined} disabled={unavailable}
            title={unavailable ? 'This customized project uses the Workflow workspace' : detail} onClick={() => onNavigate(id)}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-xs transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-400 disabled:cursor-not-allowed disabled:opacity-35 ${phase === id ? 'bg-zinc-100 font-medium text-zinc-950' : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100'}`}>
            <Icon size={16} aria-hidden="true" className="shrink-0" /><span>{label}</span>
          </button>;
        })}</div>
        {group === groups[0] && !guidedCompatible && <p className="mt-3 px-3 text-[10px] leading-relaxed text-zinc-500">Customized graph. Continue in Workflow.</p>}
      </div>)}
    </nav>
  </>;
}
