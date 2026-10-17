import { useCallback, useEffect, useRef, useState } from "react";
import { Build, ProjectInfo, WsMsg, getBuild, listProjects } from "./api";
import Sidebar from "./Sidebar";
import Viewport from "./Viewport";

export default function App() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [build, setBuild] = useState<Build | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [wireframe, setWireframe] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const currentRef = useRef(current);
  currentRef.current = current;

  const refreshProjects = useCallback(async () => {
    try {
      const list = await listProjects();
      setProjects(list);
      setCurrent((c) => c ?? list[0]?.id ?? null);
      setFetchError(null);
    } catch (e) {
      setFetchError(`backend unreachable: ${e}`);
    }
  }, []);

  const refreshBuild = useCallback(async (id: string) => {
    try {
      const b = await getBuild(id);
      if (id === currentRef.current) setBuild(b);
    } catch (e) {
      setFetchError(String(e));
    }
  }, []);

  useEffect(() => { refreshProjects(); }, [refreshProjects]);

  useEffect(() => {
    if (!current) return;
    setBuild(null);
    setHidden(new Set());
    setSelected(null);
    refreshBuild(current);
  }, [current, refreshBuild]);

  // live updates
  useEffect(() => {
    let ws: WebSocket;
    let retry: number;
    const connect = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onmessage = (ev) => {
        const msg: WsMsg = JSON.parse(ev.data);
        refreshProjects();
        if (msg.type === "build" && msg.new && msg.status === "building") setCurrent(msg.id);
        else if (msg.id === currentRef.current && msg.status !== "building") refreshBuild(msg.id);
        else if (msg.id === currentRef.current && msg.status === "building")
          setBuild((b) => (b ? { ...b, status: "building" } : b));
        if (msg.type === "deleted" && msg.id === currentRef.current) setCurrent(null);
      };
      ws.onclose = () => { retry = window.setTimeout(connect, 1500); };
    };
    connect();
    return () => { clearTimeout(retry); ws.onclose = null; ws.close(); };
  }, [refreshProjects, refreshBuild]);

  const r = build?.result;
  const toggle = (n: string) =>
    setHidden((h) => { const s = new Set(h); s.has(n) ? s.delete(n) : s.add(n); return s; });

  return (
    <div className="app">
      <Sidebar projects={projects} current={current} onPick={setCurrent}
               objects={r?.objects ?? []} hidden={hidden} onToggle={toggle}
               selected={selected} onSelect={setSelected} />

      <main className="center">
        {(build?.status === "error" || fetchError) && (
          <div className="banner">{fetchError ?? build?.error}</div>
        )}
        <div className="toolbar">
          <span className="title">{r?.name ?? current ?? "—"}</span>
          <span className="muted">{r?.description}</span>
          <label className="push">
            <input type="checkbox" checked={wireframe} onChange={(e) => setWireframe(e.target.checked)} />
            mesh wireframe
          </label>
        </div>
        <div className="viewport">
          {r ? (
            <Viewport fitKey={current ?? ""} objects={r.objects} hidden={hidden}
                      selected={selected} wireframe={wireframe} onSelect={setSelected} />
          ) : (
            <div className="empty muted">{build?.status === "error" ? "No successful build yet" : "Building…"}</div>
          )}
        </div>
      </main>

      <aside className="panel right">
        <details>
          <summary>Project JSON</summary>
          <pre className="json">{build?.source}</pre>
        </details>
      </aside>

      <footer className="bottom">
        <span className={`dot ${build?.status ?? ""}`} />
        <span>{build?.status ?? "idle"}{r ? ` · ${r.build_seconds}s` : ""}</span>
        {r && (
          <>
            <span>{r.stats.volumes} volumes · {r.stats.surfaces} surfaces</span>
            {r.stats.nodes !== undefined && <span>{r.stats.nodes.toLocaleString()} nodes · {r.stats.tetrahedra!.toLocaleString()} tets</span>}
            <span className="muted" title={r.groups.map((g) => `${g.name} (dim ${g.dim}): ${g.count}`).join("\n")}>
              {r.groups.map((g) => g.name).join("  ")}
            </span>
            <span className={r.warnings.length ? "warn" : "muted"} title={r.warnings.join("\n")}>
              {r.warnings.length ? `⚠ ${r.warnings.length} warning(s): ${r.warnings[0]}` : "no warnings"}
            </span>
            <span className="push">
              <a className="btn" href={`/download/${current}.msh`}>.msh</a>
              <a className="btn" href={`/download/${current}.step`}>.step</a>
            </span>
          </>
        )}
      </footer>
    </div>
  );
}
