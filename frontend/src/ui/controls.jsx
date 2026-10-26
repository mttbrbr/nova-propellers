import { ChevronDown, ChevronRight } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';

const variants = {
  primary: 'bg-nv-accent text-nv-accent-ink font-semibold hover:bg-nv-accent-soft',
  secondary: 'border border-nv-edge text-nv-ink hover:bg-nv-hover',
  ghost: 'text-nv-ink hover:bg-nv-hover',
  danger: 'border border-nv-err/40 text-nv-err-ink hover:bg-nv-err/10',
};

export function buttonClass(variant = 'secondary', extra = '') {
  return `inline-flex h-[34px] items-center justify-center gap-2 rounded-[7px] px-3.5 text-[13px] transition disabled:cursor-not-allowed disabled:opacity-40 ${variants[variant]} ${extra}`;
}

export function Button({ variant = 'secondary', className = '', ...props }) {
  return <button type="button" className={buttonClass(variant, className)} {...props} />;
}

// Icon-only control: the visually hidden label is the accessible name and the
// tooltip repeats it with the keyboard shortcut, so nothing relies on hover alone.
export function IconButton({ label, shortcut, icon: Icon, active = false, tooltipSide = 'bottom', className = '', badge = false, children, ...props }) {
  const tooltip = useId();
  const side = tooltipSide === 'right' ? 'left-full top-1/2 ml-2 -translate-y-1/2' : tooltipSide === 'left' ? 'right-full top-1/2 mr-2 -translate-y-1/2' : 'left-1/2 top-full mt-2 -translate-x-1/2';
  return <span className="group relative inline-flex">
    <button type="button" aria-describedby={tooltip} className={`relative grid h-9 w-9 place-items-center rounded-lg transition disabled:opacity-40 ${active ? 'bg-nv-active text-nv-ink-strong' : 'text-nv-muted hover:bg-nv-hover hover:text-nv-ink'} ${className}`} {...props}>
      {Icon && <Icon size={18} strokeWidth={1.6} aria-hidden="true" />}{children}
      <span className="sr-only">{label}</span>
      {badge && <span aria-hidden="true" className="absolute right-[7px] top-[7px] h-1.5 w-1.5 rounded-full bg-nv-warn" />}
    </button>
    <span id={tooltip} role="tooltip" className={`pointer-events-none absolute z-50 whitespace-nowrap rounded-md bg-nv-active px-2.5 py-1.5 text-xs text-nv-ink shadow-lg shadow-black/40 hidden group-hover:block group-has-[:focus-visible]:block ${side}`}>
      {label}{shortcut && <span className="ml-2 font-mono text-nv-muted">{shortcut}</span>}
    </span>
  </span>;
}

function FieldFrame({ children, invalid }) {
  return <span className={`flex h-[34px] min-w-0 items-center gap-1.5 rounded-md border bg-nv-chrome px-2.5 focus-within:border-nv-accent ${invalid ? 'border-nv-err' : 'border-nv-edge hover:border-nv-edge-strong'}`}>{children}</span>;
}

export function Field({ label, ariaLabel, unit, value, onChange, text = false, disabled = false, step = 'any', inline = false, ...props }) {
  const input = <FieldFrame>
    <input aria-label={ariaLabel || label} type={text ? 'text' : 'number'} step={step} value={value} disabled={disabled}
      className={`h-8 min-w-0 flex-1 bg-transparent text-[13px] outline-none disabled:opacity-50 ${text ? '' : 'font-mono tabular'}`}
      onChange={(event) => onChange(text ? event.target.value : Number(event.target.value))} {...props} />
    {unit && <span className="shrink-0 text-xs text-nv-muted">{unit}</span>}
  </FieldFrame>;
  if (inline) return input;
  return <label className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-3">
    <span className="text-[13px] text-nv-muted">{label}</span>{input}
  </label>;
}

export function SelectField({ label, ariaLabel, value, onChange, options, disabled = false, inline = false, className = '' }) {
  const select = <FieldFrame>
    <select aria-label={ariaLabel || label} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}
      className={`h-8 min-w-0 flex-1 appearance-none bg-transparent text-[13px] outline-none disabled:opacity-50 ${className}`}>
      {options.map(([id, name, optionDisabled]) => <option key={id} value={id} disabled={optionDisabled} className="bg-nv-panel">{name}</option>)}
    </select>
    <ChevronDown size={14} className="shrink-0 text-nv-muted" aria-hidden="true" />
  </FieldFrame>;
  if (inline) return select;
  return <label className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-3">
    <span className="text-[13px] text-nv-muted">{label}</span>{select}
  </label>;
}

export function Segmented({ label, value, options, onChange, disabled = false, size = 'md' }) {
  return <div role="group" aria-label={label} className="grid auto-cols-fr grid-flow-col rounded-[7px] border border-nv-edge bg-nv-chrome p-[3px]">
    {options.map(([id, name, optionDisabled, title]) => <button key={id} type="button" aria-pressed={value === id} title={title}
      disabled={disabled || optionDisabled} onClick={() => onChange(id)}
      className={`${size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-7 px-3 text-[13px]'} whitespace-nowrap rounded-[5px] transition disabled:cursor-not-allowed disabled:opacity-40 ${value === id ? 'bg-nv-active text-nv-ink-strong' : 'text-nv-muted hover:text-nv-ink'}`}>{name}</button>)}
  </div>;
}

export function LabeledSegmented({ label, ...props }) {
  return <div className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-3">
    <span className="text-[13px] text-nv-muted">{label}</span><Segmented label={label} {...props} />
  </div>;
}

export function Section({ title, aside, children, className = '', titleId }) {
  const generated = useId();
  const id = titleId || generated;
  return <section aria-labelledby={id} className={`flex flex-col gap-2.5 ${className}`}>
    <div className="mb-1 flex items-baseline justify-between gap-3">
      <h2 id={id} className="text-[13px] font-semibold text-nv-ink">{title}</h2>{aside}
    </div>
    {children}
  </section>;
}

// A row that expands in place; used for optional groups so the default view stays short.
export function Disclosure({ title, summary, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  const panel = useId();
  return <div className="border-y border-nv-line">
    <button type="button" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)}
      className="flex h-10 w-full items-center justify-between gap-3 text-left text-[13px] text-nv-reference hover:text-nv-ink-strong">
      <span className="font-medium">{title}</span>
      <span className="flex min-w-0 items-center gap-2 text-nv-muted"><span className="truncate">{summary}</span>
        {open ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}</span>
    </button>
    {open && <div id={panel} className="flex flex-col gap-2.5 pb-4">{children}</div>}
  </div>;
}

// Click-to-open popover. Escape and outside clicks close it and return focus.
export function Popover({ label, trigger, children, align = 'left', width = 'w-72', panelLabel, open: controlledOpen, onOpenChange }) {
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const setOpen = (value) => { setLocalOpen(value); onOpenChange?.(value); };
  const root = useRef(null);
  const button = useRef(null);
  const panel = useRef(null);
  const [shift, setShift] = useState(0);
  const shiftRef = useRef(0);
  // Keep the panel inside the window when the trigger sits near an edge, also after resizes.
  useLayoutEffect(() => {
    if (!open) { shiftRef.current = 0; setShift(0); return undefined; }
    const place = () => {
      if (!panel.current) return;
      const rect = panel.current.getBoundingClientRect();
      const left = rect.left - shiftRef.current, right = rect.right - shiftRef.current;
      const next = right > window.innerWidth - 12 ? window.innerWidth - 12 - right : left < 12 ? 12 - left : 0;
      shiftRef.current = next; setShift(next);
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const outside = (event) => {
      if (root.current?.contains(event.target)) return;
      // Dialogs rendered elsewhere (unsaved-changes guard) must not close the popover underneath.
      if (event.target.closest?.('[role="dialog"][aria-modal="true"]')) return;
      setOpen(false);
    };
    const escape = (event) => { if (event.key === 'Escape') { setOpen(false); button.current?.focus(); } };
    document.addEventListener('mousedown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape); };
    // setOpen is recreated each render; the listeners only depend on open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  return <div ref={root} className="relative">
    {trigger({ ref: button, open, toggle: () => setOpen(!open), label })}
    {open && <div ref={panel} role="dialog" aria-label={panelLabel || label} style={shift ? { transform: `translateX(${shift}px)` } : undefined}
      className={`absolute top-full z-40 mt-2 max-h-[calc(100vh-80px)] overflow-y-auto rounded-xl border border-nv-edge bg-nv-hover shadow-2xl shadow-black/60 ${align === 'right' ? 'right-0' : 'left-0'} ${width} max-w-[calc(100vw-24px)]`}>
      {typeof children === 'function' ? children(() => setOpen(false)) : children}
    </div>}
  </div>;
}

export function MenuItem({ children, hint, className = '', ...props }) {
  return <button type="button" className={`flex h-[34px] w-full items-center justify-between gap-3 rounded-md px-2.5 text-left text-[13px] text-nv-ink hover:bg-nv-active disabled:cursor-not-allowed disabled:opacity-40 ${className}`} {...props}>
    <span className="flex items-center gap-2">{children}</span>{hint && <span className="font-mono text-xs text-nv-muted">{hint}</span>}
  </button>;
}

export function StatusDot({ tone = 'muted', className = '' }) {
  const color = { ok: 'bg-nv-ok', warn: 'bg-nv-warn', err: 'bg-nv-err', accent: 'bg-nv-accent', muted: 'bg-nv-muted' }[tone];
  return <span aria-hidden="true" className={`inline-block h-[7px] w-[7px] shrink-0 rounded-full ${color} ${className}`} />;
}

export function Notice({ tone = 'warn', children, action, role }) {
  const style = { warn: 'border-nv-warn/30 bg-nv-warn/10 text-[#F2D9A6]', err: 'border-nv-err/40 bg-nv-err/10 text-nv-err-ink', ok: 'border-nv-ok/30 bg-nv-ok/10 text-nv-ok-ink', info: 'border-nv-edge bg-nv-raised text-nv-reference' }[tone];
  return <div role={role} className={`flex items-center gap-3 rounded-lg border px-3.5 py-2.5 text-[13px] leading-snug ${style}`}>
    <StatusDot tone={tone === 'info' ? 'accent' : tone} /><span className="min-w-0 flex-1">{children}</span>{action}
  </div>;
}

export function Metric({ label, value, unit, sub, size = 'lg' }) {
  return <div className="min-w-0">
    <dt className="text-[12.5px] text-nv-muted">{label}</dt>
    <dd className={`m-0 mt-1 truncate font-mono tabular text-nv-ink-strong ${size === 'lg' ? 'text-[22px]' : 'text-lg'}`}>{value}{unit && <span className="ml-1 text-xs text-nv-muted">{unit}</span>}</dd>
    {sub && <p className={`m-0 mt-1 font-mono text-xs text-nv-muted ${String(sub).includes('\n') ? 'whitespace-pre-line' : 'truncate'}`}>{sub}</p>}
  </div>;
}

export function KeyValue({ label, children }) {
  return <div className="flex justify-between gap-3 text-[13px]"><span className="text-nv-muted">{label}</span><span className="min-w-0 truncate text-right">{children}</span></div>;
}
