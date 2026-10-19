"""Build + simulate a project with openEMS: python scripts/simulate.py projects/<name>.json

Writes out/sims/<name>/results.json (+ fields.npz). Exit 1 on build/setup errors, 2 on solver errors.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine import BuildError, build  # noqa: E402
from backend.openems_sim import SimError, preflight, run  # noqa: E402


def summary(res, values):
    f = np.array(res["freqs"])
    lines = [f"\nSimulated in {res['seconds']} s, {res['cells']:,} cells"]
    for key, (re, im) in res["S"].items():
        s = np.array(re) + 1j * np.array(im)
        db = 20 * np.log10(np.abs(s))
        i, j = key.split(",")
        line = f"  S{i}{j}: min {db.min():.2f} dB at {f[db.argmin()] / 1e9:.4g} GHz"
        if i == j:
            band = f[db < -10]
            line += (f", -10 dB band {band.min() / 1e9:.4g}-{band.max() / 1e9:.4g} GHz"
                     if band.size else ", never below -10 dB")
        lines.append(line)
    f0 = values.get("f0")
    for k, (re, im) in res["Z"].items():
        z = np.array(re) + 1j * np.array(im)
        at = f0 if f0 and f[0] <= f0 <= f[-1] else f[len(f) // 2]
        zi = np.interp(at, f, z.real) + 1j * np.interp(at, f, z.imag)
        lines.append(f"  Z{k} at {at / 1e9:.4g} GHz: {zi.real:.1f} {'+' if zi.imag >= 0 else '-'} j{abs(zi.imag):.1f} ohm")
    lines += ["Warnings:" if res["warnings"] else "Warnings: none"] + [f"  ! {w}" for w in res["warnings"]]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    try:
        r = build(args.project, args.out)
    except BuildError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    Path(args.out, f"{r['name']}.result.json").write_text(json.dumps(r), encoding="utf-8")
    problems = preflight(r)
    if problems:
        print("ERROR: cannot simulate: " + "; ".join(problems), file=sys.stderr)
        return 1
    try:
        res = run(r, Path(args.out) / "sims" / r["name"], log=lambda m: print(m, flush=True))
    except SimError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(summary(res, r["values"]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
