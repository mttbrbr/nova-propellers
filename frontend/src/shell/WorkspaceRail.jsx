import { Database, FlaskConical, GitBranch, GitCompareArrows, Layers3, Plug } from 'lucide-react';
import { IconButton } from '../ui/controls.jsx';

export const workspaces = [
  { id: 'design', label: 'Design', icon: Layers3, detail: 'Sizing, geometry, analysis and results' },
  { id: 'comparisons', label: 'Comparisons', icon: GitCompareArrows, detail: 'Compare runs across projects' },
  { id: 'studies', label: 'Studies', icon: FlaskConical, detail: 'Sweeps and solver comparisons' },
  { id: 'workflow', label: 'Workflow', icon: GitBranch, detail: 'Project graph and constraint-driven block workflows' },
  { id: 'library', label: 'Library', icon: Database, detail: 'Airfoils, polars, models and archives' },
  { id: 'integrations', label: 'Integrations', icon: Plug, detail: 'External software and imported results' },
];

export default function WorkspaceRail({ workspace, onSelect }) {
  return <nav aria-label="Workspaces" className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-nv-line px-3 py-1.5 md:w-14 md:flex-col md:overflow-visible md:border-b-0 md:border-r md:px-0 md:py-3">
    {workspaces.map((item) => <IconButton key={item.id} label={item.label} icon={item.icon} tooltipSide="right"
      active={workspace === item.id} aria-current={workspace === item.id ? 'page' : undefined} onClick={() => onSelect(item.id)}
      className={workspace === item.id ? '!text-nv-accent' : ''} />)}
  </nav>;
}
