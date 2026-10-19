import { useMemo, useState } from "react";
import type { MouseEvent } from "react";
import { SimResults } from "./api";
import { REPORTS, Report } from "./ProjectTree";

// HFSS default trace colours
const COLORS = ["#ff0000", "#0000ff", "#008000", "#c000c0", "#008b8b", "#b8860b", "#000000"];
type Trace = { name: string; x: number[]; y: number[] };

function ticks(lo: number, hi: number, n = 6) {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw)!;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}

const fmt = (v: number) => (Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(2) : +v.toPrecision(5) + "");

function XYPlot({ title, xLabel, yLabel, traces, markMin }: {
  title: string; xLabel: string; yLabel: string; traces: Trace[]; markMin?: boolean;
}) {
  const W = 900, H = 500, L = 80, R = 230, T = 40, B = 60;
  const xs = traces[0].x;
  const ys = traces.flatMap((t) => t.y).filter(Number.isFinite);
  let ylo = Math.min(...ys), yhi = Math.max(...ys);
  if (ylo === yhi) { ylo -= 1; yhi += 1; }
  // snap the y range outward to whole tick steps (so e.g. 0 dB gets a gridline)
  const ystep = ticks(ylo, yhi)[1] - ticks(ylo, yhi)[0] || 1;
  ylo = Math.floor(ylo / ystep) * ystep; yhi = Math.ceil(yhi / ystep) * ystep;
  const yt = ticks(ylo, yhi), xt = ticks(xs[0], xs[xs.length - 1], 8);
  const px = (x: number) => L + ((x - xs[0]) / (xs[xs.length - 1] - xs[0])) * (W - L - R);
  const py = (y: number) => T + ((yhi - y) / (yhi - ylo)) * (H - T - B);
  const [hover, setHover] = useState<number | null>(null);
  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * W;
    if (x < L || x > W - R) return setHover(null);
    const f = xs[0] + ((x - L) / (W - L - R)) * (xs[xs.length - 1] - xs[0]);
    let i = 0;
    for (let k = 1; k < xs.length; k++) if (Math.abs(xs[k] - f) < Math.abs(xs[i] - f)) i = k;
    setHover(i);
  };
  const m1 = markMin ? traces[0].y.indexOf(Math.min(...traces[0].y)) : -1;
  return (
    <svg className="plot" viewBox={`0 0 ${W} ${H}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <rect x={0} y={0} width={W} height={H} fill="#fff" />
      <text x={L} y={24} className="ptitle">{title}</text>
      <text x={W - 12} y={24} className="pbrand" textAnchor="end">openEMS · FDTD</text>
      {yt.map((v) => <g key={"y" + v}>
        <line x1={L} x2={W - R} y1={py(v)} y2={py(v)} className="grid" />
        <text x={L - 8} y={py(v) + 4} textAnchor="end" className="tick">{fmt(v)}</text>
      </g>)}
      {xt.map((v) => <g key={"x" + v}>
        <line x1={px(v)} x2={px(v)} y1={T} y2={H - B} className="grid" />
        <text x={px(v)} y={H - B + 18} textAnchor="middle" className="tick">{fmt(v)}</text>
      </g>)}
      <rect x={L} y={T} width={W - L - R} height={H - T - B} className="frame" />
      <text x={(L + W - R) / 2} y={H - 14} textAnchor="middle" className="alabel">{xLabel}</text>
      <text transform={`translate(18 ${(T + H - B) / 2}) rotate(-90)`} textAnchor="middle" className="alabel">{yLabel}</text>
      <clipPath id="pc"><rect x={L} y={T} width={W - L - R} height={H - T - B} /></clipPath>
      <g clipPath="url(#pc)">
        {traces.map((t, k) => (
          <polyline key={t.name} fill="none" stroke={COLORS[k % COLORS.length]} strokeWidth={1.6}
                    points={t.x.map((x, i) => `${px(x)},${py(t.y[i])}`).join(" ")} />
        ))}
      </g>
      {m1 >= 0 && <g>
        <polygon points={`${px(xs[m1])},${py(traces[0].y[m1]) - 2} ${px(xs[m1]) - 6},${py(traces[0].y[m1]) - 12} ${px(xs[m1]) + 6},${py(traces[0].y[m1]) - 12}`} fill="#000" />
        <text x={px(xs[m1]) + 8} y={py(traces[0].y[m1]) - 12} className="mk">m1</text>
      </g>}
      {/* legend ("Curve Info") */}
      <g transform={`translate(${W - R + 14} ${T})`}>
        <rect width={R - 24} height={24 + traces.length * 20} className="legend" />
        <text x={8} y={16} className="lhead">Curve Info</text>
        {traces.map((t, k) => <g key={t.name} transform={`translate(8 ${34 + k * 20})`}>
          <line x1={0} x2={22} y1={-4} y2={-4} stroke={COLORS[k % COLORS.length]} strokeWidth={2} />
          <text x={28} y={0} className="ltext">{t.name}</text>
        </g>)}
      </g>
      {m1 >= 0 && <g transform={`translate(${W - R + 14} ${T + 40 + traces.length * 20})`}>
        <rect width={R - 24} height={44} className="legend" />
        <text x={8} y={16} className="lhead">Name   X        Y</text>
        <text x={8} y={34} className="ltext">m1  {fmt(xs[m1])}  {fmt(traces[0].y[m1])}</text>
      </g>}
      {hover !== null && <g>
        <line x1={px(xs[hover])} x2={px(xs[hover])} y1={T} y2={H - B} className="cursor" />
        {traces.map((t, k) => <circle key={k} cx={px(xs[hover])} cy={py(t.y[hover])} r={3.5} fill={COLORS[k % COLORS.length]} />)}
        <g transform={`translate(${Math.min(px(xs[hover]) + 10, W - R - 190)} ${T + 10})`}>
          <rect width={180} height={20 + traces.length * 16} className="readout" />
          <text x={6} y={14} className="ltext">{xLabel.split(" ")[0]} = {fmt(xs[hover])}</text>
          {traces.map((t, k) => <text key={k} x={6} y={30 + k * 16} className="ltext" fill={COLORS[k % COLORS.length]}>
            {t.name}: {fmt(t.y[hover])}</text>)}
        </g>
      </g>}
    </svg>
  );
}

function SmithChart({ f, gammas, z0 }: { f: number[]; gammas: { name: string; re: number[]; im: number[] }[]; z0: number }) {
  const S = 520, C = S / 2, Rr = S / 2 - 40;
  const X = (gr: number) => C + gr * Rr, Y = (gi: number) => C - gi * Rr;
  const rs = [0.2, 0.5, 1, 2, 5], xsv = [0.2, 0.5, 1, 2, 5];
  const [hover, setHover] = useState<number | null>(null);
  const g0 = gammas[0];
  const m1 = useMemo(() => {
    let i = 0;
    for (let k = 1; k < f.length; k++) if (Math.hypot(g0.re[k], g0.im[k]) < Math.hypot(g0.re[i], g0.im[i])) i = k;
    return i;
  }, [f, g0]);
  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    const gx = (((e.clientX - b.left) / b.width) * (S + 260) - C) / Rr, gy = (C - ((e.clientY - b.top) / b.height) * S) / Rr;
    let i = 0, best = Infinity;
    g0.re.forEach((r, k) => { const d = Math.hypot(r - gx, g0.im[k] - gy); if (d < best) { best = d; i = k; } });
    setHover(best < 0.15 ? i : null);
  };
  const readout = (i: number) => {
    const gr = g0.re[i], gi = g0.im[i], den = (1 - gr) ** 2 + gi ** 2;
    const zr = (z0 * (1 - gr * gr - gi * gi)) / den, zi = (z0 * 2 * gi) / den;
    return { f: f[i], db: 20 * Math.log10(Math.hypot(gr, gi)), zr, zi };
  };
  const info = (i: number, label: string, y: number) => {
    const o = readout(i);
    return <g transform={`translate(${S + 10} ${y})`}>
      <rect width={240} height={72} className="legend" />
      <text x={8} y={18} className="lhead">{label}</text>
      <text x={8} y={36} className="ltext">Freq  {fmt(o.f / 1e9)} GHz</text>
      <text x={8} y={52} className="ltext">|Γ|   {fmt(o.db)} dB</text>
      <text x={8} y={68} className="ltext">Z     {fmt(o.zr)} {o.zi >= 0 ? "+" : "−"} j{fmt(Math.abs(o.zi))} Ω</text>
    </g>;
  };
  return (
    <svg className="plot" viewBox={`0 0 ${S + 260} ${S}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <rect width={S + 260} height={S} fill="#fff" />
      <defs><clipPath id="uc"><circle cx={C} cy={C} r={Rr} /></clipPath></defs>
      <g clipPath="url(#uc)">
        {rs.map((r) => <circle key={"r" + r} cx={X(r / (1 + r))} cy={C} r={Rr / (1 + r)} className="sgrid" />)}
        {xsv.flatMap((x) => [x, -x]).map((x) => <circle key={"x" + x} cx={X(1)} cy={Y(1 / x)} r={Rr / Math.abs(x)} className="sgrid" />)}
      </g>
      <circle cx={C} cy={C} r={Rr} className="frame" />
      <line x1={X(-1)} x2={X(1)} y1={C} y2={C} className="sgrid" />
      {rs.map((r) => <text key={"rl" + r} x={X((r - 1) / (r + 1)) + 3} y={C - 4} className="tick">{r}</text>)}
      {xsv.map((x) => {
        const d = 1 + x * x, gr = (x * x - 1) / d, gi = (2 * x) / d;
        return <g key={"xl" + x}>
          <text x={X(gr) + (gr > 0 ? 6 : -4)} y={Y(gi) - 4} className="tick" textAnchor={gr > 0 ? "start" : "end"}>{x}</text>
          <text x={X(gr) + (gr > 0 ? 6 : -4)} y={Y(-gi) + 12} className="tick" textAnchor={gr > 0 ? "start" : "end"}>-{x}</text>
        </g>;
      })}
      {gammas.map((g, k) => <polyline key={g.name} fill="none" stroke={COLORS[k]} strokeWidth={1.6}
        points={g.re.map((r, i) => `${X(r)},${Y(g.im[i])}`).join(" ")} />)}
      <circle cx={X(g0.re[m1])} cy={Y(g0.im[m1])} r={4} fill="#000" />
      <text x={X(g0.re[m1]) + 6} y={Y(g0.im[m1]) - 6} className="mk">m1</text>
      {hover !== null && <circle cx={X(g0.re[hover])} cy={Y(g0.im[hover])} r={5} fill="none" stroke="#000" />}
      <text x={S + 10} y={24} className="ptitle">Smith Chart — {gammas.map((g) => g.name).join(", ")}</text>
      {info(m1, "m1 (min |Γ|)", 40)}
      {hover !== null && info(hover, "cursor", 124)}
      <text x={S + 10} y={S - 14} className="dim">Normalized to Z0 = {z0} Ω</text>
    </svg>
  );
}

export default function ResultsTab({ res, report, onReport }: {
  res: SimResults; report: Report; onReport: (r: Report) => void;
}) {
  const f = res.freqs.map((x) => x / 1e9);
  const S = Object.entries(res.S).map(([k, [re, im]]) => ({ k, re, im, i: k.split(",") }));
  const z0 = res.ports[0]?.impedance ?? 50;
  const refl = S.filter((s) => s.i[0] === s.i[1]);
  let body;
  if (report === "smith") {
    body = <SmithChart f={res.freqs} gammas={refl.map((s) => ({ name: `S(${s.k})`, re: s.re, im: s.im }))} z0={z0} />;
  } else {
    const tr: Trace[] =
      report === "sdb" ? S.map((s) => ({ name: `dB(S(${s.k}))`, x: f, y: s.re.map((r, i) => 20 * Math.log10(Math.hypot(r, s.im[i]))) }))
      : report === "sphase" ? S.map((s) => ({ name: `ang_deg(S(${s.k}))`, x: f, y: s.re.map((r, i) => (Math.atan2(s.im[i], r) * 180) / Math.PI) }))
      : report === "vswr" ? refl.map((s) => ({ name: `VSWR(${s.i[0]})`, x: f, y: s.re.map((r, i) => { const m = Math.hypot(r, s.im[i]); return Math.min((1 + m) / (1 - m), 50); }) }))
      : Object.entries(res.Z).flatMap(([k, [re, im]]) => [
          { name: `re(Z(${k}))`, x: f, y: re }, { name: `im(Z(${k}))`, x: f, y: im }]);
    const yl = { sdb: "dB", sphase: "Phase (deg)", vswr: "VSWR", z: "Impedance (Ω)" }[report];
    body = <XYPlot title={REPORTS[report]} xLabel="Freq (GHz)" yLabel={yl} traces={tr} markMin={report === "sdb" || report === "vswr"} />;
  }
  return (
    <div className="results">
      <div className="report-tabs">
        {(Object.keys(REPORTS) as Report[]).map((k) => (
          <button key={k} className={k === report ? "on" : ""} onClick={() => onReport(k)}>{REPORTS[k]}</button>
        ))}
      </div>
      <div className="report">{body}</div>
    </div>
  );
}
