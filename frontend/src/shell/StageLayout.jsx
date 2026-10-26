// Inputs on the left, data in the flexible centre, square render with linked data
// on the right. Below 1280 px the render moves under the content; below 768 px
// everything stacks. See docs/UI_NAVIGATION.md for the breakpoint rules.
export default function StageLayout({ inputsLabel, inputs, contentLabel, content, sideLabel, side, flush = false }) {
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

export function StageTitle({ title, detail }) {
  return <div>
    <h1 className="m-0 text-lg font-semibold">{title}</h1>
    {detail && <p className="m-0 mt-1.5 text-[13px] text-nv-muted">{detail}</p>}
  </div>;
}
