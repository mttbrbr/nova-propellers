import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Button, Notice } from '../ui/controls.jsx';

// Every run asks which models to execute; the last choice is preselected.
// Air propeller: several models — the first selected is the main run, the others
// run on the same frozen inputs as a comparison. VAWT: one streamtube model.
// HAWT and marine: BEMT, the only model available today.
export default function RunChooser({ family, title, methods, vawtMethods, initial, polarsMissing, onCancel, onConfirm }) {
  const [selected, setSelected] = useState(initial);
  const dialog = useRef(null);
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  useEffect(() => {
    dialog.current?.querySelector('input:not([disabled]), button')?.focus();
    const onKey = (event) => { if (event.key === 'Escape') { event.preventDefault(); cancel.current(); } };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  let options, multiple = false;
  if (family === 'propeller') {
    multiple = true;
    options = methods.map((m) => ({ id: m.id, label: m.id.toUpperCase(), detail: m.name !== m.id.toUpperCase() ? m.name : '', note: m.fidelity }));
  } else if (family === 'vawt') {
    options = vawtMethods.map((m) => ({ id: m.id, label: m.label.split(' (')[0], detail: m.label.includes('(') ? m.label.slice(m.label.indexOf('(') + 1, -1) : '', note: 'streamtube' }));
  } else {
    options = [{ id: 'bemt', label: 'BEMT', detail: 'Blade-element momentum with the selected corrections', note: 'preliminary' }];
  }
  const toggle = (id) => setSelected((list) => multiple
    ? (list.includes(id) ? list.filter((item) => item !== id) : [...list, id])
    : [id]);
  const ordered = multiple ? [selected[0], ...options.map((o) => o.id).filter((id) => id !== selected[0] && selected.includes(id))].filter(Boolean) : selected;
  const main = ordered[0];
  const confirm = () => { if (main) onConfirm(ordered); };

  return createPortal(<div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
    <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="run-chooser-title" className="flex w-[560px] max-w-full flex-col gap-4 rounded-xl border border-nv-edge bg-nv-panel p-6 shadow-2xl shadow-black/50"
      onKeyDown={(event) => { if (event.key === 'Enter' && event.target.tagName !== 'BUTTON') { event.preventDefault(); confirm(); } }}>
      <div>
        <h2 id="run-chooser-title" className="m-0 text-[17px] font-semibold">Run {title}</h2>
        <p className="m-0 mt-1.5 text-[13px] text-nv-muted">{multiple ? 'Choose the models for this run. The first one is the main run; the others are computed on the same frozen inputs and overlaid in Results.' : 'Choose the model for this run.'}</p>
      </div>
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-2 text-[12.5px] text-nv-muted">Models available for this rotor</legend>
        {options.map((option) => {
          const checked = selected.includes(option.id);
          const isMain = option.id === main;
          return <label key={option.id} className={`grid cursor-pointer grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border px-3 py-2.5 text-[13.5px] ${checked ? 'border-nv-accent/70 bg-nv-raised' : 'border-nv-edge hover:bg-nv-hover'}`}>
            <input type={multiple ? 'checkbox' : 'radio'} name="run-model" className="h-4 w-4 accent-nv-accent" checked={checked}
              disabled={options.length === 1} onChange={() => toggle(option.id)} aria-label={`${option.label}${option.detail ? ` — ${option.detail}` : ''}`} />
            <span className="min-w-0"><span className="font-medium">{option.label}</span>{option.detail && <span className="text-nv-muted"> · {option.detail}</span>}</span>
            <span className="text-xs text-nv-muted">{multiple && isMain && ordered.length > 1 ? 'main run' : option.note}</span>
          </label>;
        })}
      </fieldset>
      {multiple && ordered.length > 1 && <div className="flex items-center gap-2 text-[13px] text-nv-muted">
        Main run
        <select aria-label="Main run" className="h-8 rounded-md border border-nv-edge bg-nv-chrome px-2 text-[13px] text-nv-ink" value={main}
          onChange={(event) => setSelected((list) => [event.target.value, ...list.filter((id) => id !== event.target.value)])}>
          {ordered.map((id) => <option key={id} value={id} className="bg-nv-panel">{id.toUpperCase()}</option>)}
        </select>
      </div>}
      {family !== 'propeller' && <p className="m-0 text-xs leading-relaxed text-nv-muted">Higher-fidelity models (free-vortex wake) are planned.{family === 'hawt' ? ' Aeroelastic OpenFAST cases run from Integrations.' : ''}</p>}
      {polarsMissing && selected.includes('bemt') && <Notice tone="warn">BEMT needs section polars: select imported or demonstration polars in Analysis first.</Notice>}
      <div className="flex items-center justify-between border-t border-nv-line pt-4">
        <span className="text-xs text-nv-muted">Saves the simulation, then runs {ordered.map((id) => id.toUpperCase()).join(' + ') || 'nothing'}.</span>
        <span className="flex gap-2">
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="primary" disabled={!main} onClick={confirm}>Start run</Button>
        </span>
      </div>
    </div>
  </div>, document.body);
}
