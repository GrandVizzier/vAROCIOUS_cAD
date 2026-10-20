import { useState } from "react";
import { SimResults } from "./api";
import { REPORTS, Report } from "./ProjectTree";
import { PMarker, PSeries, Plot, TRACE_COLORS, fmtNum, useSize, yAt } from "./Plot";

type Mark = { id: string; series: string; x: number };

function seriesFor(res: SimResults, report: Report): PSeries[] {
  const f = res.freqs.map((x) => x / 1e9);
  const S = Object.entries(res.S).map(([k, [re, im]]) => ({ k, re, im, i: k.split(",") }));
  const refl = S.filter((s) => s.i[0] === s.i[1]);
  const raw: Omit<PSeries, "color" | "id">[] =
    report === "smith" ? refl.map((s) => ({ label: `S(${s.k})`, x: s.re, y: s.im, f }))
    : report === "sdb" ? S.map((s) => ({ label: `dB(S(${s.k}))`, x: f, y: s.re.map((r, i) => 20 * Math.log10(Math.hypot(r, s.im[i]))) }))
    : report === "sphase" ? S.map((s) => ({ label: `ang_deg(S(${s.k}))`, x: f, y: s.re.map((r, i) => (Math.atan2(s.im[i], r) * 180) / Math.PI) }))
    : report === "vswr" ? refl.map((s) => ({ label: `VSWR(${s.i[0]})`, x: f, y: s.re.map((r, i) => { const m = Math.hypot(r, s.im[i]); return Math.min((1 + m) / (1 - m), 50); }) }))
    : Object.entries(res.Z).flatMap(([k, [re, im]]) => [{ label: `re(Z(${k}))`, x: f, y: re }, { label: `im(Z(${k}))`, x: f, y: im }]);
  return raw.map((s, i) => ({ ...s, id: s.label, color: TRACE_COLORS[i % TRACE_COLORS.length] }));
}

const Y_LABEL: Record<Report, string> = { sdb: "dB", sphase: "Phase (deg)", vswr: "VSWR", z: "Impedance (Ω)", smith: "" };

function exportCsv(name: string, series: PSeries[]) {
  const xs = series[0].f ?? series[0].x;
  const cols = series[0].f ? series.flatMap((s) => [`"re ${s.label}"`, `"im ${s.label}"`]) : series.map((s) => `"${s.label}"`);
  const rows = xs.map((x, i) => [x, ...series.flatMap((s) => (s.f ? [s.x[i], s.y[i]] : [s.y[i]]))].map((v) => +v.toPrecision(8)).join(","));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([[["freq_GHz", ...cols].join(","), ...rows].join("\n")], { type: "text/csv" }));
  a.download = `${name}.csv`;
  a.click();
}

function AxesRow({ x, y, onApply }: { x?: [number, number]; y?: [number, number]; onApply: (x?: [number, number], y?: [number, number]) => void }) {
  const [v, setV] = useState({ x0: x?.[0] ?? "", x1: x?.[1] ?? "", y0: y?.[0] ?? "", y1: y?.[1] ?? "" });
  const range = (a: string | number, b: string | number): [number, number] | undefined =>
    a !== "" && b !== "" && Number.isFinite(+a) && Number.isFinite(+b) && +b > +a ? [+a, +b] : undefined;
  const apply = () => onApply(range(v.x0, v.x1), range(v.y0, v.y1));
  const f = (k: keyof typeof v) => <input value={v[k]} placeholder="auto" onChange={(e) => setV({ ...v, [k]: e.target.value })} onKeyDown={(e) => e.key === "Enter" && apply()} />;
  return (
    <div className="rp-axes">
      <span>X</span>{f("x0")}<span>to</span>{f("x1")}<span>Y</span>{f("y0")}<span>to</span>{f("y1")}
      <button onClick={apply}>Apply</button>
      <button onClick={() => { setV({ x0: "", x1: "", y0: "", y1: "" }); onApply(); }}>Auto</button>
    </div>
  );
}

function ReportView({ res, report, name }: { res: SimResults; report: Report; name: string }) {
  const all = seriesFor(res, report);
  const [hidden, setHidden] = useState<string[]>([]);
  const [marks, setMarks] = useState<Mark[]>([]);
  const [axes, setAxes] = useState(false);
  const [range, setRange] = useState<{ x?: [number, number]; y?: [number, number] }>({});
  const [box, size] = useSize<HTMLDivElement>();
  const series = all.filter((s) => !hidden.includes(s.id));
  const smith = report === "smith";
  const z0 = res.ports[0]?.impedance ?? 50;

  const add = (x: number, sid = series[0]?.id) => {
    if (!sid) return;
    const n = marks.length ? Math.max(...marks.map((m) => +m.id.slice(1))) + 1 : 1;
    setMarks([...marks, { id: `m${n}`, series: sid, x }]);
  };
  // smith: extremes of |Γ| over frequency; rect: extremes of y
  const extreme = (max: boolean) => {
    const s = series[0];
    if (!s) return;
    const v = smith ? s.x.map((r, i) => Math.hypot(r, s.y[i])) : s.y;
    const i = v.reduce((b, y, k) => ((max ? y > v[b] : y < v[b]) ? k : b), 0);
    add(smith ? s.f![i] : s.x[i], s.id);
  };
  const markers: PMarker[] = marks.flatMap((m) => {
    const s = series.find((q) => q.id === m.series);
    return s ? [{ ...m, y: smith ? 0 : yAt(s, m.x), color: s.color }] : [];
  });
  const smithAt = (s: PSeries, f: number) => {
    const i = s.f!.reduce((b, v, k) => (Math.abs(v - f) < Math.abs(s.f![b] - f) ? k : b), 0);
    const g = { r: s.x[i], i: s.y[i] }, d = (1 - g.r) ** 2 + g.i ** 2;
    return `${((z0 * (1 - g.r ** 2 - g.i ** 2)) / d).toFixed(1)} ${g.i < 0 ? "−" : "+"} j${Math.abs((z0 * 2 * g.i) / d).toFixed(1)} Ω`;
  };

  return (
    <div className="rp">
      <div className="rp-bar">
        <button onClick={() => extreme(true)} disabled={!series.length}>Marker: max</button>
        <button onClick={() => extreme(false)} disabled={!series.length}>min</button>
        <button onClick={() => setMarks([])} disabled={!marks.length}>Clear</button>
        <span className="rp-sep" />
        {!smith && <button className={axes ? "on" : ""} onClick={() => setAxes(!axes)}>Axes…</button>}
        <button onClick={() => exportCsv(`${name}_${report}`, series)} disabled={!series.length}>Export CSV</button>
        <span className="rp-info">openEMS · FDTD · {res.cells.toLocaleString()} cells · {res.seconds}s · click the plot to place a marker</span>
      </div>
      {axes && !smith && <AxesRow x={range.x} y={range.y} onApply={(x, y) => setRange({ x, y })} />}
      <div className="rp-plot" ref={box}>
        <Plot kind={smith ? "smith" : "rect"} series={series} xLabel={smith ? "" : "Freq (GHz)"} yLabel={Y_LABEL[report]}
              xRange={smith ? undefined : range.x} yRange={smith ? undefined : range.y} markers={markers} z0={z0}
              height={Math.max(200, Math.floor(size.h) - (series.length > 1 ? 34 : 12))}
              onPick={(x, sid) => add(+x.toFixed(4), sid)} />
      </div>
      <div className="rp-tables">
        <table className="grid">
          <thead><tr><th /><th>Trace</th><th /></tr></thead>
          <tbody>{all.map((s) => {
            const off = hidden.includes(s.id);
            return (
              <tr key={s.id} className={off ? "off" : ""}>
                <td><svg width="20" height="8"><line x1="0" x2="20" y1="4" y2="4" stroke={s.color} strokeWidth="2" /></svg></td>
                <td className="mono">{s.label}</td>
                <td className="act"><button title={off ? "Show" : "Hide"} onClick={() => setHidden(off ? hidden.filter((h) => h !== s.id) : [...hidden, s.id])}>{off ? "○" : "◉"}</button></td>
              </tr>
            );
          })}</tbody>
        </table>
        {markers.length > 0 && (
          <table className="grid">
            <thead><tr><th>Marker</th><th>Freq (GHz)</th><th>Trace</th><th>{smith ? "Z" : "Value"}</th><th /></tr></thead>
            <tbody>{markers.map((m) => {
              const s = series.find((q) => q.id === m.series)!;
              return (
                <tr key={m.id}>
                  <td className="mono">{m.id}</td><td className="mono">{fmtNum(m.x, 0.0001)}</td><td className="mono">{s.label}</td>
                  <td className="mono">{smith ? smithAt(s, m.x) : fmtNum(m.y, 0.01)}</td>
                  <td className="act"><button onClick={() => setMarks(marks.filter((q) => q.id !== m.id))}>×</button></td>
                </tr>
              );
            })}</tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default function ResultsTab({ res, report, onReport, name }: {
  res: SimResults; report: Report; onReport: (r: Report) => void; name: string;
}) {
  return (
    <div className="results">
      <div className="report-tabs">
        {(Object.keys(REPORTS) as Report[]).map((k) => (
          <button key={k} className={k === report ? "on" : ""} onClick={() => onReport(k)}>{REPORTS[k]}</button>
        ))}
      </div>
      {/* keyed: markers, hidden traces and axis ranges belong to one report */}
      <ReportView key={report} res={res} report={report} name={name} />
    </div>
  );
}
