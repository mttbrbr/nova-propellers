import { Plus, X } from 'lucide-react';
import { StatusDot } from '../ui/controls.jsx';

const familyShort = { propeller: 'propeller', marine: 'marine', hawt: 'HAWT', vawt: 'VAWT' };

// Projects open side by side. The active tab is the project in the workspace;
// selecting another tab opens it (unsaved changes are protected by the usual
// save/discard prompt). An unsaved draft shows as its own tab.
export default function ProjectTabs({ tabs, activeId, draftLabel, dirty, disabled, onSelect, onClose, onNew }) {
  return <div role="tablist" aria-label="Open projects" className="flex min-w-0 items-stretch gap-0.5 overflow-x-auto">
    {!activeId && <span role="tab" aria-selected="true" className="flex h-9 shrink-0 items-center gap-2 rounded-t-md border-b-2 border-nv-accent bg-nv-panel px-3 text-[13px] text-nv-ink-strong">
      <StatusDot tone="warn" />{draftLabel || 'Unsaved draft'}
    </span>}
    {tabs.map((tab) => {
      const active = tab.id === activeId;
      return <span key={tab.id} className={`group flex h-9 shrink-0 items-center rounded-t-md border-b-2 ${active ? 'border-nv-accent bg-nv-panel' : 'border-transparent hover:bg-nv-hover'}`}>
        <button type="button" role="tab" aria-selected={active} disabled={disabled && !active} title={`${tab.name}${tab.simulationName ? ` · ${tab.simulationName}` : ''}`}
          onClick={() => { if (!active) onSelect(tab); }}
          className={`flex h-full max-w-[240px] items-center gap-2 pl-3 pr-1.5 text-[13px] disabled:opacity-50 ${active ? 'text-nv-ink-strong' : 'text-nv-muted hover:text-nv-ink'}`}>
          <StatusDot tone={active && dirty ? 'warn' : 'ok'} />
          <span className="truncate">{tab.name}</span>
          <span className="shrink-0 text-xs text-nv-muted">· {familyShort[tab.family] || tab.family}</span>
        </button>
        <button type="button" aria-label={`Close ${tab.name}`} disabled={disabled} onClick={() => onClose(tab)}
          className="mr-1 grid h-6 w-6 place-items-center rounded text-nv-muted opacity-60 hover:bg-nv-active hover:text-nv-ink hover:opacity-100 disabled:opacity-30"><X size={13} aria-hidden="true" /></button>
      </span>;
    })}
    <button type="button" aria-label="Create a new project" title="New project" disabled={disabled} onClick={onNew}
      className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-nv-muted hover:bg-nv-hover hover:text-nv-ink disabled:opacity-40"><Plus size={16} aria-hidden="true" /></button>
  </div>;
}
