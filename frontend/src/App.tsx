import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Build, FieldPlane, ProjectInfo, SimStatus, WsMsg, cancelSim, getBuild, getField, getSim, ghz, importProject,
  listProjects, recomputeFields,
} from "./api";

type Theme = "light" | "dark";
function initialTheme(): Theme {
  const q = new URLSearchParams(location.search).get("theme");
  if (q === "dark" || q === "light") return q;
  try { return localStorage.getItem("theme") === "dark" ? "dark" : "light"; } catch { return "light"; }
}
import AnalysisTab from "./AnalysisTab";
import FieldOverlay, { FieldScale, magnitudes, rainbow } from "./FieldOverlay";
import ProjectTree, { REPORTS, Report, Tab } from "./ProjectTree";
import ResultsTab from "./Reports";
import VariablesPanel from "./VariablesPanel";
import Viewport from "./Viewport";

type Overlay = { on: boolean; f: number; plane: "x" | "y" | "z"; pos: number; phase: number;
  animate: boolean; scale: FieldScale; vectors: boolean };

export default function App() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [build, setBuild] = useState<Build | null>(null);
  const [sim, setSim] = useState<SimStatus | null>(null);
  // deep links: #analysis, #results/smith
  const [[hashTab, hashReport]] = useState(() => location.hash.slice(1).split("/")); // initial hash only
  const [tab, setTab] = useState<Tab>((["modeler", "analysis", "results"].includes(hashTab) ? hashTab : "modeler") as Tab);
  const [report, setReport] = useState<Report>((hashReport in REPORTS ? hashReport : "sdb") as Report);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [wireframe, setWireframe] = useState(false);
  const [grid, setGrid] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ov, setOv] = useState<Overlay>({ on: false, f: 0, plane: "z", pos: 0, phase: 0, animate: false, scale: "log", vectors: true });
  const [fp, setFp] = useState<FieldPlane | null>(null);
  useEffect(() => {
    history.replaceState(null, "", `#${tab}${tab === "results" ? "/" + report : tab === "modeler" && ov.on ? "/field" : ""}`);
  }, [tab, report, ov.on]);
  const currentRef = useRef(current);
  currentRef.current = current;
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* private mode etc. */ }
  }, [theme]);
  const [menu, setMenu] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refreshProjects = useCallback(async () => {
    try {
      const list = await listProjects();
      setProjects(list);
      const wanted = new URLSearchParams(location.search).get("project"); // deep link ?project=<id>
      setCurrent((c) => c ?? (list.some((p) => p.id === wanted) ? wanted : list[0]?.id ?? null));
      setError(null);
    } catch (e) {
      setError(`backend unreachable: ${e}`);
    }
  }, []);
  const refreshBuild = useCallback(async (id: string) => {
    try {
      const b = await getBuild(id);
      if (id === currentRef.current) setBuild(b);
    } catch (e) { setError(String(e)); }
  }, []);
  const refreshSim = useCallback(async (id: string) => {
    try {
      const s = await getSim(id);
      if (id === currentRef.current) setSim(s);
    } catch (e) { setError(String(e)); }
  }, []);

  useEffect(() => { refreshProjects(); }, [refreshProjects]);
  useEffect(() => {
    if (!current) return;
    setBuild(null); setSim(null); setFp(null);
    setHidden(new Set()); setSelected(null); setOv((o) => ({ ...o, on: false }));
    refreshBuild(current); refreshSim(current);
  }, [current, refreshBuild, refreshSim]);

  // live updates: builds and simulation progress
  useEffect(() => {
    let ws: WebSocket;
    let retry: number;
    const connect = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onmessage = (ev) => {
        const msg: WsMsg = JSON.parse(ev.data);
        const mine = msg.id === currentRef.current;
        if (msg.type === "sim") {
          if (!mine) return;
          if (msg.status === "running")
            setSim((s) => s && { ...s, status: "running", progress: msg.progress ?? s.progress, stage: msg.stage ?? s.stage });
          else refreshSim(msg.id);
          return;
        }
        refreshProjects();
        if (msg.type === "build" && msg.new && msg.status === "building") setCurrent(msg.id);
        else if (mine && msg.status !== "building") { refreshBuild(msg.id); refreshSim(msg.id); }
        else if (mine) setBuild((b) => (b ? { ...b, status: "building" } : b));
        if (msg.type === "deleted" && mine) setCurrent(null);
      };
      ws.onclose = () => { retry = window.setTimeout(connect, 1500); };
    };
    connect();
    return () => { clearTimeout(retry); ws.onclose = null; ws.close(); };
  }, [refreshProjects, refreshBuild, refreshSim]);

  const r = build?.result;
  const res = sim?.results;
  const readonly = !!projects.find((p) => p.id === current)?.readonly;
  const sourceVars = useMemo(() => {
    try { return JSON.parse(build?.source ?? "").variables as Record<string, string>; } catch { return undefined; }
  }, [build?.source]);

  // ---- field overlay ----
  const enableOverlay = () => {
    if (!r || !res?.fields_at.length) return;
    // default cut: normal to the model's thinnest (non-air) extent, through its middle
    const pts = r.objects.filter((o) => o.material !== "air").flatMap((o) => o.positions);
    const lo = [0, 1, 2].map((k) => Math.min(...pts.filter((_, i) => i % 3 === k)));
    const hi = [0, 1, 2].map((k) => Math.max(...pts.filter((_, i) => i % 3 === k)));
    const k = [0, 1, 2].reduce((a, b) => (hi[b] - lo[b] < hi[a] - lo[a] ? b : a), 0);
    setOv((o) => ({ ...o, on: true, f: res.fields_at[0], plane: "xyz"[k] as Overlay["plane"], pos: (lo[k] + hi[k]) / 2 }));
    setTab("modeler");
  };
  useEffect(() => {
    if (!ov.on || !current) return;
    const t = setTimeout(() => getField(current, ov.f, ov.plane, ov.pos).then(setFp).catch((e) => setError(String(e))), 120);
    return () => clearTimeout(t);
  }, [ov.on, ov.f, ov.plane, ov.pos, current, res?.fields_updated_at]);
  useEffect(() => {
    if (!ov.animate) return;
    let raf = 0, t0 = performance.now();
    const step = (t: number) => { setOv((o) => ({ ...o, phase: (o.phase + ((t - t0) / 2000) * 2 * Math.PI) % (2 * Math.PI) })); t0 = t; raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [ov.animate]);
  const fieldMax = useMemo(() => (fp ? magnitudes(fp).max : 1), [fp]);
  // Palace: probe grid density for the field plot; Recompute re-probes without a new sweep
  const [fieldPts, setFieldPts] = useState(40);
  useEffect(() => { setFieldPts(res?.field_points ?? 40); }, [res?.field_points]);
  const recompute = () => current && recomputeFields(current, fieldPts).catch((e) => setError(String(e)));
  // deep link #modeler/field opens the E-field overlay once results are loaded
  useEffect(() => { if (hashReport === "field" && res?.fields_at.length && !ov.on) enableOverlay(); }, [res]); // eslint-disable-line

  // ---- File menu ----
  const openFile = async (file: File) => {
    const text = await file.text();
    try {
      const { id } = await importProject(text);
      setCurrent(id);
    } catch (e) {
      const msg = String(e);
      if (msg.includes("409") && confirm(`${msg.replace(/^Error: 409 /, "")}\n\nOverwrite it?`)) {
        importProject(text, true).then(({ id }) => setCurrent(id)).catch((e2) => setError(String(e2)));
      } else if (!msg.includes("409")) setError(`Open project failed: ${msg}`);
    }
  };
  const exportProject = () => {
    if (!build) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([build.source], { type: "application/json" }));
    a.download = `${current?.split("/").pop() ?? "project"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const toggle = (n: string) => setHidden((h) => { const s = new Set(h); s.has(n) ? s.delete(n) : s.add(n); return s; });
  const open = (t: Tab, rep?: Report) => { setTab(t); if (rep) setReport(rep); };

  const messages = [
    ...(build?.status === "error" ? [{ kind: "error", text: build.error ?? "" }] : []),
    ...(r?.warnings ?? []).map((w) => ({ kind: "warn", text: w })),
    ...(sim?.results?.warnings ?? []).map((w) => ({ kind: "warn", text: `[sim] ${w}` })),
    // solver log: only meaningful lines (the full log stays on the server)
    ...(sim?.log ?? []).filter((l) => /^\[sim\]|warning|error|Traceback|end-criteria|Simulated in|^\s+(S\d\d|Z\d)/i.test(l) && !/Warnings: none/.test(l))
      .slice(-40).map((l) => ({ kind: /error|Traceback/i.test(l) ? "error" : /warning/i.test(l) ? "warn" : "info", text: l.trim() })),
  ];

  return (
    <div className={`app ${tab === "modeler" ? "" : "wide"}`}>
      <header className="titlebar">
        <span className="brand">EM Geometry Studio</span>
        <div className="menu" onMouseLeave={() => setMenu(false)}>
          <button className={menu ? "open" : ""} onClick={() => setMenu(!menu)}>File</button>
          {menu && (
            <div className="menu-drop" onClick={() => setMenu(false)}>
              <button onClick={() => fileInput.current?.click()}>Open Project…</button>
              <button disabled={!build} onClick={exportProject}>Export Project (.json)…</button>
              <hr />
              <a className={r?.files.msh ? "" : "disabled"} href={`/download/${current}.msh`}>Export Mesh (.msh)</a>
              <a className={r?.files.step ? "" : "disabled"} href={`/download/${current}.step`}>Export CAD (.step)</a>
            </div>
          )}
          <input ref={fileInput} type="file" accept=".json,application/json" hidden
                 onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) openFile(f); }} />
        </div>
        <span className="dim">{r?.name ?? current ?? ""}</span>
        <button className="theme-toggle" title="Toggle dark theme"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? "☀ Light" : "☾ Dark"}
        </button>
        <nav className="tabs">
          {([["modeler", "3D Modeler"], ["analysis", "Analysis"], ["results", "Results"]] as [Tab, string][]).map(([k, label]) => (
            <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
      </header>

      <ProjectTree projects={projects} current={current} onPick={setCurrent} r={r} sim={sim}
                   hidden={hidden} onToggle={toggle} selected={selected} onSelect={setSelected}
                   onOpen={open} overlay={ov.on} onOverlay={enableOverlay} />

      <main className="center">
        {(build?.status === "error" || error) && <div className="banner">{error ?? build?.error}</div>}

        {tab === "modeler" && (
          <>
            <div className="toolbar">
              <span className="dim">{r?.description}</span>
              <span className="push">
                <label><input type="checkbox" checked={grid} onChange={(e) => setGrid(e.target.checked)} />grid</label>
                <label><input type="checkbox" checked={wireframe} onChange={(e) => setWireframe(e.target.checked)} />mesh</label>
                {res?.fields_at.length ? (
                  <label><input type="checkbox" checked={ov.on} onChange={(e) => (e.target.checked ? enableOverlay() : setOv({ ...ov, on: false }))} />E field</label>
                ) : null}
              </span>
            </div>
            <div className="viewport">
              {r ? (
                <Viewport fitKey={current ?? ""} objects={r.objects} hidden={hidden} selected={selected}
                          wireframe={wireframe} grid={grid} onSelect={setSelected} dark={theme === "dark"}>
                  {ov.on && fp && <FieldOverlay fp={fp} phase={ov.phase} scale={ov.scale} vectors={ov.vectors} />}
                </Viewport>
              ) : <div className="empty">{build?.status === "error" ? "No successful build yet" : "Building…"}</div>}
              {ov.on && fp && (
                <>
                  <div className="field-panel">
                    <div className="pane-title">E Field — {ghz(fp.freq)}</div>
                    <label>Freq <select value={ov.f} onChange={(e) => setOv({ ...ov, f: +e.target.value })}>
                      {res!.fields_at.map((f) => <option key={f} value={f}>{ghz(f)}</option>)}</select></label>
                    <label>Plane <select value={ov.plane} onChange={(e) => {
                      const p = e.target.value as Overlay["plane"]; const [a, b] = fp.range[p];
                      setOv({ ...ov, plane: p, pos: (a + b) / 2 });
                    }}>{(["x", "y", "z"] as const).map((p) => <option key={p} value={p}>{p.toUpperCase()} = const</option>)}</select></label>
                    <label>{ov.plane} = {(fp.pos * 1e3).toFixed(3)} mm
                      <input type="range" min={fp.range[ov.plane][0]} max={fp.range[ov.plane][1]}
                             step={(fp.range[ov.plane][1] - fp.range[ov.plane][0]) / 400} value={ov.pos}
                             onChange={(e) => setOv({ ...ov, pos: +e.target.value })} /></label>
                    <label>Phase {Math.round((ov.phase * 180) / Math.PI)}°
                      <input type="range" min={0} max={2 * Math.PI} step={0.01} value={ov.phase}
                             onChange={(e) => setOv({ ...ov, phase: +e.target.value, animate: false })} /></label>
                    <label><input type="checkbox" checked={ov.animate} onChange={(e) => setOv({ ...ov, animate: e.target.checked })} />Animate phase</label>
                    <label><input type="checkbox" checked={ov.vectors} onChange={(e) => setOv({ ...ov, vectors: e.target.checked })} />Vector_E arrows</label>
                    <label>Scale <select value={ov.scale} onChange={(e) => setOv({ ...ov, scale: e.target.value as FieldScale })}>
                      <option value="log">log (40 dB)</option><option value="lin">linear</option></select></label>
                    {res?.solver === "palace" && (
                      <div className="field-grid">
                        <label>Grid density (points, longest side)
                          <input type="number" min={8} max={100} value={fieldPts}
                                 onChange={(e) => setFieldPts(Math.max(8, Math.min(100, +e.target.value || 8)))} /></label>
                        <div className="dim">{res.field_grid ? `now ${res.field_grid.join(" × ")} probes` : ""}</div>
                        {sim?.status === "running"
                          ? <div className="dim">Recomputing… {Math.round(sim.progress)}%</div>
                          : <button disabled={fieldPts === res.field_points} onClick={recompute}>Recompute field</button>}
                      </div>
                    )}
                  </div>
                  <div className="colorbar">
                    <div className="dim">Mag_E [V/m], 1 W in</div>
                    {Array.from({ length: 11 }, (_, i) => 10 - i).map((i) => {
                      const t = i / 10;
                      const v = ov.scale === "log" ? fieldMax * 10 ** (((t - 1) * 40) / 20) : fieldMax * t;
                      return <div key={i} className="cb-row"><span className="cb-sw" style={{ background: `#${rainbow(t).getHexString()}` }} />{v.toExponential(2)}</div>;
                    })}
                  </div>
                </>
              )}
            </div>
          </>
        )}

        {tab === "analysis" && r && current && build && (
          <AnalysisTab id={current} r={r} source={build.source} readonly={readonly} sim={sim} onError={setError}
                       onPlotField={enableOverlay} />
        )}

        {tab === "results" && (res
          ? <ResultsTab res={res} report={report} onReport={setReport} />
          : <div className="empty">No results yet — set up and run the analysis ({REPORTS[report]})</div>)}
      </main>

      {tab === "modeler" && (
        <aside className="pane props">
          <div className="pane-title">Properties</div>
          {r && current && (
            <VariablesPanel id={current} variables={sourceVars ?? r.variables} values={r.values} readonly={readonly} />
          )}
          <details>
            <summary>Project JSON</summary>
            <pre className="json">{build?.source}</pre>
          </details>
        </aside>
      )}

      <section className="pane messages">
        <div className="pane-title">Message Manager</div>
        <div className="msglist">
          {messages.length ? messages.map((m, i) => <div key={i} className={`msg ${m.kind}`}>{m.text}</div>)
            : <div className="msg info">No messages</div>}
        </div>
      </section>

      <section className="pane progress">
        <div className="pane-title">Progress</div>
        {sim?.status === "running" ? (
          <>
            <div className="dim">{current} — Setup1: {sim.stage}</div>
            <div className="bar"><div style={{ width: `${sim.progress}%` }} /></div>
            <button className="danger" onClick={() => current && cancelSim(current).catch((e) => setError(String(e)))}>Abort</button>
          </>
        ) : <div className="dim">{sim?.status && sim.status !== "idle" ? `Last analysis: ${sim.status}` : "Idle"}</div>}
        {r && (
          <div className="status dim">
            {r.stats.volumes} volumes · {r.stats.nodes?.toLocaleString() ?? "–"} nodes · {r.stats.tetrahedra?.toLocaleString() ?? "–"} tets
          </div>
        )}
      </section>
    </div>
  );
}
