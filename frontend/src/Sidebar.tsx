import { Obj, ProjectInfo, materialColor } from "./api";

export default function Sidebar({ projects, current, onPick, objects, hidden, onToggle, selected, onSelect }: {
  projects: ProjectInfo[]; current: string | null; onPick: (id: string) => void;
  objects: Obj[]; hidden: Set<string>; onToggle: (n: string) => void;
  selected: string | null; onSelect: (n: string) => void;
}) {
  return (
    <aside className="panel left">
      <h3>Projects</h3>
      <ul className="list">
        {projects.map((p) => (
          <li key={p.id} className={p.id === current ? "active" : ""} onClick={() => onPick(p.id)}>
            <span className={`dot ${p.status}`} />
            <span className="grow">{p.id}</span>
            <span className="muted small">{new Date(p.mtime * 1000).toLocaleTimeString()}</span>
          </li>
        ))}
        {!projects.length && <li className="muted">No projects in projects/</li>}
      </ul>

      <h3>Objects</h3>
      <ul className="list">
        {objects.map((o) => (
          <li key={o.name} className={o.name === selected ? "active" : ""} onClick={() => onSelect(o.name)}>
            <input type="checkbox" checked={!hidden.has(o.name)} title="Visible"
                   onClick={(e) => e.stopPropagation()} onChange={() => onToggle(o.name)} />
            <span className="swatch" style={{ background: materialColor(o.material) }} />
            <span className="grow">{o.name}</span>
            <span className="muted small">{o.op} · {o.material}</span>
          </li>
        ))}
      </ul>
    </aside>
  );
}
