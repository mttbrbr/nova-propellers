import { createContext, useContext } from 'react';
import { createPortal } from 'react-dom';

// Inside the Design workspace every stage is mounted at once and its three bands
// are routed into the design sheet: inputs into the stage's section (when that
// section is open), content and side into the centre and right columns (when the
// stage is the active view). Elsewhere a stage renders its own three-band grid.
export const SheetContext = createContext(null);

export function SheetStage({ stage, targets, active, children }) {
  return <SheetContext.Provider value={{ stage, targets, active }}>{children}</SheetContext.Provider>;
}

// Inputs on the left, data in the flexible centre, square render with linked data
// on the right. Below 1280 px the render moves under the content; below 768 px
// everything stacks. See docs/UI_NAVIGATION.md for the breakpoint rules.
export default function StageLayout({ inputsLabel, inputs, contentLabel, content, sideLabel, side, flush = false }) {
  const sheet = useContext(SheetContext);
  if (sheet) {
    const { targets, active } = sheet;
    return <>
      {targets.inputs && createPortal(<div aria-label={inputsLabel} role="group" className="flex flex-col gap-5">{inputs}</div>, targets.inputs)}
      {active && targets.content && createPortal(<div aria-label={contentLabel} role="region" className={`flex min-w-0 flex-1 flex-col ${flush ? '' : 'gap-9 px-6 py-6 lg:px-10'}`}>{content}</div>, targets.content)}
      {active && side && targets.side && createPortal(<div aria-label={sideLabel} role="region" className="flex flex-col gap-7">{side}</div>, targets.side)}
    </>;
  }
  const columns = side
    ? 'md:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_500px] wide:grid-cols-[340px_minmax(0,1fr)_660px]'
    : 'md:grid-cols-[300px_minmax(0,1fr)] wide:grid-cols-[340px_minmax(0,1fr)]';
  return <div className={`grid min-h-0 flex-1 grid-cols-1 xl:overflow-hidden ${columns}`}>
    <aside aria-label={inputsLabel} className={`flex min-w-0 flex-col gap-7 border-b border-nv-line px-6 py-6 md:border-b-0 md:border-r xl:h-full xl:overflow-y-auto ${side ? 'md:row-span-2 xl:row-span-1' : ''}`}>
      {inputs}
    </aside>
    <main aria-label={contentLabel} className={`flex min-w-0 flex-col xl:h-full xl:overflow-y-auto ${flush ? '' : 'gap-9 px-6 py-6 lg:px-10'}`}>
      {content}
    </main>
    {side && <section aria-label={sideLabel} className="flex min-w-0 flex-col gap-7 px-6 pb-6 md:col-start-2 md:max-w-[560px] xl:col-start-auto xl:h-full xl:max-w-none xl:overflow-y-auto xl:py-6 xl:pl-0">
      {side}
    </section>}
  </div>;
}

// In the design sheet the section header already names the stage, so only the
// one-line description is kept.
export function StageTitle({ title, detail }) {
  const sheet = useContext(SheetContext);
  if (sheet) return detail ? <p className="m-0 text-[12.5px] leading-relaxed text-nv-muted">{detail}</p> : null;
  return <div>
    <h1 className="m-0 text-lg font-semibold">{title}</h1>
    {detail && <p className="m-0 mt-1.5 text-[13px] text-nv-muted">{detail}</p>}
  </div>;
}
