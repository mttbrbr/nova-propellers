import { ChevronDown, ChevronRight } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { StatusDot } from '../ui/controls.jsx';

// Element registry for portal targets: stable callback refs that store each
// mounted element in state so stages can render into it.
export function useTargets() {
  const [targets, setTargets] = useState({});
  const callbacks = useRef({});
  const ref = useCallback((name) => {
    if (!callbacks.current[name]) {
      callbacks.current[name] = (element) => setTargets((current) => current[name] === element ? current : { ...current, [name]: element });
    }
    return callbacks.current[name];
  }, []);
  return [targets, ref];
}

// The design sheet: the process reads top to bottom as stacked sections. Several
// can be open; closed ones keep a one-line summary and a status dot. Clicking a
// section title makes it the active view (centre and right columns); clicking the
// active one folds it.
export default function DesignSheet({ sections, open, active, onSection, onExpandAll, onFoldAll, views, view, onView, targetRef, runCard }) {
  return <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[340px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)_540px] xl:overflow-hidden wide:grid-cols-[360px_minmax(0,1fr)_640px]">
    <aside aria-label="Design sheet" className="flex min-w-0 flex-col gap-2 border-b border-nv-line px-4 py-5 md:row-span-2 md:border-b-0 md:border-r xl:row-span-1 xl:h-full xl:overflow-y-auto">
      <div className="flex items-baseline justify-between px-2 pb-2">
        <span className="text-[15px] font-semibold">Design</span>
        <span className="flex gap-3 text-xs">
          <button type="button" className="text-nv-muted hover:text-nv-ink" onClick={onExpandAll}>Expand all</button>
          <button type="button" className="text-nv-muted hover:text-nv-ink" onClick={onFoldAll}>Fold all</button>
        </span>
      </div>
      <nav aria-label="Design stages" className="flex flex-col gap-2">
        {sections.map((section) => {
          const isOpen = open.includes(section.id);
          const isActive = active === section.id;
          return <section key={section.id} aria-labelledby={`sheet-${section.id}`}
            className={`rounded-[10px] border ${isActive ? 'border-nv-accent/70 bg-nv-panel' : 'border-nv-line bg-nv-chrome'}`}>
            <div className="flex cursor-pointer items-start gap-3 px-3.5 py-3" onClick={() => onSection(section.id)}>
              <StatusDot tone={section.tone} className="mt-[7px]" />
              <div className="min-w-0 flex-1">
                <h2 className="m-0 text-[13.5px] font-semibold leading-snug">
                  <button type="button" id={`sheet-${section.id}`} aria-expanded={isOpen} aria-current={isActive ? 'step' : undefined}
                    aria-describedby={`sheet-${section.id}-summary`} title={`${section.label} · Alt+${section.key}`}
                    onClick={(event) => { event.stopPropagation(); onSection(section.id); }}
                    className="text-left hover:text-nv-ink-strong focus-visible:outline-none focus-visible:underline">{section.label}</button>
                </h2>
                <p id={`sheet-${section.id}-summary`} className={`m-0 mt-0.5 truncate text-xs ${isOpen ? 'text-nv-muted' : 'text-nv-reference'}`}>{section.summary}</p>
              </div>
              {isOpen ? <ChevronDown size={15} className="mt-1 text-nv-muted" aria-hidden="true" /> : <ChevronRight size={15} className="mt-1 text-nv-muted" aria-hidden="true" />}
            </div>
            {isOpen && <div ref={targetRef(`inputs:${section.id}`)} className="border-t border-nv-line px-3.5 pb-4 pt-3.5" />}
          </section>;
        })}
      </nav>
    </aside>
    <main aria-label="Design view" className="flex min-w-0 flex-col xl:h-full xl:overflow-y-auto">
      <div role="tablist" aria-label="Views" className="sticky top-0 z-10 flex shrink-0 flex-wrap gap-0.5 border-b border-nv-line bg-nv-canvas px-6">
        {views.map((item) => <button key={item.id} type="button" role="tab" aria-selected={view === item.id} onClick={() => onView(item.id)}
          className={`h-10 border-b-2 px-3.5 text-[13px] transition ${view === item.id ? 'border-nv-accent font-medium text-nv-ink-strong' : 'border-transparent text-nv-muted hover:text-nv-ink'}`}>{item.label}</button>)}
      </div>
      <div ref={targetRef('content')} className="flex min-w-0 flex-1 flex-col" />
    </main>
    <section aria-label="Results and preview" className="flex min-w-0 flex-col gap-6 px-6 pb-6 md:col-start-2 xl:col-start-auto xl:h-full xl:overflow-y-auto xl:border-l xl:border-nv-line xl:py-6">
      {runCard}
      <div ref={targetRef('side')} className="flex flex-col gap-7" />
    </section>
  </div>;
}
