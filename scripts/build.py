"""Build a project: python scripts/build.py projects/<name>.json [--render] [--out out]

Exit 0 on success (writes <out>/<name>.msh, .step, .result.json), 1 on a build error.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine import BuildError, build  # noqa: E402


def summary(r):
    lines = [f"{r['name']}  {r['description']}".rstrip(), "", f"Objects ({len(r['objects'])}):"]
    for o in r["objects"]:
        kind = "volume" if o["dim"] == 3 else "sheet"
        lines.append(f"  {o['name']:<16} {o['op']:<10} {o['material']:<8} {o['entities']} {kind}(s)")
    lines += ["", "Physical groups:"]
    for g in r["groups"]:
        lines.append(f"  {g['name']:<16} dim {g['dim']}  {g['count']} entit{'y' if g['count'] == 1 else 'ies'}")
    if r["ports"]:
        lines += ["", "Ports:"]
        for p in r["ports"]:
            status = "OK" if p["ok"] else "PROBLEM: " + "; ".join(p["problems"])
            lines.append(f"  port {p['index']}  {p['target']:<12} {p['type']} {p['impedance']:g} ohm "
                         f"{p['direction']}  {status}")
    if r["simulation"]:
        sw = r["simulation"]["sweep"]
        lines.append(f"Simulation: {r['simulation']['solver']}, sweep {sw['start'] / 1e9:g}-"
                     f"{sw['stop'] / 1e9:g} GHz ({sw['points']} pts)")
    s = r["stats"]
    lines += ["", f"Geometry: {s['volumes']} volumes, {s['surfaces']} surfaces"]
    if "nodes" in s:
        lines.append(f"Mesh: {s['nodes']} nodes, {s['tetrahedra']} tetrahedra")
    lines += ["", "Warnings:" if r["warnings"] else "Warnings: none"]
    lines += [f"  ! {w}" for w in r["warnings"]]
    lines += ["", "Files: " + ", ".join(r["files"].values()), f"Built in {r['build_seconds']} s"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project")
    ap.add_argument("--render", action="store_true", help="save top/front/iso PNGs")
    ap.add_argument("--out", default="out")
    ap.add_argument("--json", action="store_true", help="print the result JSON instead of the summary")
    args = ap.parse_args()
    try:
        r = build(args.project, args.out)
    except BuildError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    text = json.dumps(r)
    Path(args.out, f"{r['name']}.result.json").write_text(text, encoding="utf-8")
    print(text if args.json else summary(r))
    if args.render:
        from backend.render import render
        print("Rendered: " + ", ".join(render(r, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
