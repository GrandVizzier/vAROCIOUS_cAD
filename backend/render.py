"""Top / front / iso PNG views of a build result (matplotlib on the tessellation)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

COLORS = {"PEC": "#d4a017", "copper": "#c87533", "FR4": "#3a8f4a", "PTFE": "#e8e8e8",
          "air": "#6fa8dc"}
VIEWS = {"top": (90, -90), "front": (0, -90), "iso": (28, -55)}


def color(material):
    return COLORS.get(material, f"C{sum(map(ord, material)) % 10}")


def render(result, out_dir="out"):
    paths = []
    objs = [o for o in result["objects"] if o["indices"]]
    allpts = np.concatenate([np.reshape(o["positions"], (-1, 3)) for o in objs]) * 1e3
    lo, hi = allpts.min(0), allpts.max(0)
    for view, (elev, azim) in VIEWS.items():
        fig = plt.figure(figsize=(7, 6), dpi=110)
        ax = fig.add_subplot(projection="3d", computed_zorder=False)
        # ponytail: fixed draw order (air, volumes, sheets) instead of depth sorting, so sheets
        # lying on a face stay visible; good enough for sanity-check renders.
        for z, o in enumerate(sorted(objs, key=lambda o: (o["material"] != "air", o["dim"] == 2))):
            pts = np.reshape(o["positions"], (-1, 3)) * 1e3
            tris = pts[np.reshape(o["indices"], (-1, 3))]
            air = o["material"] == "air"
            ax.add_collection3d(Poly3DCollection(
                tris, facecolor=color(o["material"]), alpha=0.08 if air else 0.9,
                edgecolor=(0, 0, 0, 0.05 if air else 0.25), linewidth=0.2,
                label=f"{o['name']} ({o['material']})", zorder=z))
        ax.set(xlim=(lo[0], hi[0]), ylim=(lo[1], hi[1]), zlim=(lo[2], hi[2]),
               xlabel="x [mm]", ylabel="y [mm]", zlabel="z [mm]")
        ax.set_box_aspect(np.maximum(hi - lo, 1e-3 * (hi - lo).max()))
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(f"{result['name']} — {view}")
        ax.legend(loc="upper left", fontsize=7)
        p = Path(out_dir) / f"{result['name']}_{view}.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close(fig)
        paths.append(str(p))
    return paths
