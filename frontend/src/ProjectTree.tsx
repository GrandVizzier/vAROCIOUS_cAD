import { ProjectInfo, Result, SimStatus, ghz, materialColor } from "./api";

export type Tab = "modeler" | "analysis" | "results";
export type Report = "sdb" | "sphase" | "smith" | "z" | "vswr";
export const REPORTS: Record<Report, string> = {
  sdb: "S Parameter Plot (dB)",
  sphase: "S Parameter Phase",
  smith: "Smith Chart",
  z: "Input Impedance",
  vswr: "VSWR",
};

/** HFSS-style Project Manager: project picker + design tree (Model, Boundaries, Excitations,
 *  Analysis, Results, Field Overlays). Native <details> gives the collapsible tree. */
export default function ProjectTree({ projects, current, onPick, r, sim, hidden, onToggle, selected,
  onSelect, onOpen, overlay, onOverlay }: {
  projects: ProjectInfo[]; current: string | null; onPick: (id: string) => void;
  r: Result | null | undefined; sim: SimStatus | null; hidden: Set<string>; onToggle: (n: string) => void;
  selected: string | null; onSelect: (n: string) => void;
  onOpen: (tab: Tab, report?: Report) => void; overlay: boolean; onOverlay: () => void;
}) {
  const solids = r?.objects.filter((o) => o.dim === 3) ?? [];
  const sheets = r?.objects.filter((o) => o.dim === 2) ?? [];
  const bcs = r?.groups.filter((g) => g.name.startsWith("bc:")) ?? [];
  const objRow = (o: Result["objects"][number]) => (
    <li key={o.name} className={o.name === selected ? "sel" : ""} onClick={() => { onSelect(o.name); onOpen("modeler"); }}>
      <input type="checkbox" checked={!hidden.has(o.name)} title="Visible"
             onClick={(e) => e.stopPropagation()} onChange={() => onToggle(o.name)} />
      <span className="swatch" style={{ background: materialColor(o.material) }} />
      <span className="grow">{o.name}</span>
      <span className="dim">{o.material}</span>
    </li>
  );
  return (
    <aside className="pane tree">
      <div className="pane-title">Project Manager</div>
      <select className="picker" value={current ?? ""} onChange={(e) => onPick(e.target.value)}>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>{p.id}{p.status === "error" ? "  (error)" : ""}</option>
        ))}
      </select>
      {r && (
        <div className="treebody">
          <details open>
            <summary>Model</summary>
            <details open><summary>Solids ({solids.length})</summary><ul>{solids.map(objRow)}</ul></details>
            <details open><summary>Sheets ({sheets.length})</summary><ul>{sheets.map(objRow)}</ul></details>
          </details>
          <details open>
            <summary>Boundaries ({bcs.length})</summary>
            <ul>{bcs.map((g) => (
              <li key={g.name}><span className="ico">▭</span><span className="grow">{g.name.slice(3)}</span>
                <span className="dim">{g.count} face{g.count === 1 ? "" : "s"}</span></li>
            ))}</ul>
          </details>
          <details open>
            <summary>Excitations ({r.ports.length})</summary>
            <ul>{r.ports.map((p) => (
              <li key={p.index} title={p.ok ? "Port is valid" : p.problems.join("\n")} onClick={() => onSelect(p.target)}>
                <span className={p.ok ? "ok" : "bad"}>{p.ok ? "✓" : "⚠"}</span>
                <span className="grow">{p.index}: {p.target}</span>
                <span className="dim">{p.type} {p.impedance ?? "?"} Ω {p.direction}</span>
              </li>
            ))}
            {!r.ports.length && <li className="dim">No ports defined</li>}</ul>
          </details>
          <details open>
            <summary>Analysis</summary>
            <ul>
              <li onClick={() => onOpen("analysis")}>
                <span className="ico">⚙</span>
                <span className="grow">Setup1 {r.simulation ? "(openEMS)" : "(not defined)"}</span>
              </li>
              {r.simulation && (
                <li className="indent" onClick={() => onOpen("analysis")}>
                  <span className="ico">↝</span>
                  <span className="grow">Sweep {ghz(r.simulation.sweep.start)} – {ghz(r.simulation.sweep.stop)}</span>
                </li>
              )}
            </ul>
          </details>
          <details open>
            <summary>Results{sim?.stale ? " (outdated)" : ""}</summary>
            <ul>
              {sim?.results ? (Object.keys(REPORTS) as Report[]).map((k) => (
                <li key={k} onClick={() => onOpen("results", k)}>
                  <span className="ico">📈</span><span className="grow">{REPORTS[k]}</span>
                </li>
              )) : <li className="dim">Run the analysis to create reports</li>}
            </ul>
          </details>
          <details open>
            <summary>Field Overlays</summary>
            <ul>
              {sim?.results?.fields_at.length ? (
                <li className={overlay ? "sel" : ""} onClick={onOverlay}>
                  <span className="ico">➶</span><span className="grow">E Field (Mag_E + Vector_E)</span>
                </li>
              ) : <li className="dim">No field data (set "Save fields at")</li>}
            </ul>
          </details>
        </div>
      )}
    </aside>
  );
}
