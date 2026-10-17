"""Replay a Project in Gmsh OCC, fragment, tag physical groups, mesh, export.

Objects are tracked by NAME: `names[name] -> [(dim, tag), ...]`. Gmsh tags are
never stored in the project and change on every rebuild.
"""
import contextlib
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import gmsh
from pydantic import ValidationError

from .expr import C0, ExprError, evaluate, resolve_variables
from .schema import (Boolean, Box, Cylinder, Disk, Project, Rectangle, Rotate, Sphere,
                     Translate, UNIT_SCALE, format_validation_error)

occ = gmsh.model.occ
METALS = {"PEC", "copper", "Cu"}


class BuildError(Exception):
    pass


def load_project(path) -> Project:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise BuildError(f"file not found: {path}") from None
    except json.JSONDecodeError as e:
        raise BuildError(f"invalid JSON in {path.name}: line {e.lineno} col {e.colno}: {e.msg}") from None
    try:
        return Project.model_validate(data)
    except ValidationError as e:
        raise BuildError(format_validation_error(e)) from None


@contextlib.contextmanager
def _quiet_stdout():
    sys.stdout.flush()
    saved = os.dup(1)
    with open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 1)
        try:
            yield
        finally:
            os.dup2(saved, 1)
            os.close(saved)


def _place_sheet(dt, plane, x, y, z):
    """Sheet was created in XY at the origin; orient it to `plane` and move it."""
    if plane in ("XZ", "YZ"):
        occ.rotate(dt, 0, 0, 0, 1, 0, 0, math.pi / 2)      # (u,v,0) -> (u,0,v)
    if plane == "YZ":
        occ.rotate(dt, 0, 0, 0, 0, 0, 1, math.pi / 2)      # (u,0,v) -> (0,u,v)
    occ.translate(dt, x, y, z)


def _replay(project, values, scale, warnings):
    """Run the history. Returns (names, meta)."""
    num = lambda e: evaluate(e, values)
    length = lambda e: num(e) * scale
    vec = lambda v: [length(e) for e in v]
    names, meta = {}, {}

    def lookup(name):
        if name not in names:
            raise BuildError(f"unknown object '{name}'")
        return names[name]

    for i, s in enumerate(project.history):
        label = getattr(s, "name", None) or getattr(s, "target", None) or getattr(s, "object", "")
        try:
            if isinstance(s, Box):
                tag = occ.addBox(*vec(s.origin), *vec(s.size))
                names[s.name] = [(3, tag)]
            elif isinstance(s, Cylinder):
                tag = occ.addCylinder(*vec(s.origin), *vec(s.axis), length(s.radius))
                names[s.name] = [(3, tag)]
            elif isinstance(s, Sphere):
                tag = occ.addSphere(*vec(s.center), length(s.radius))
                names[s.name] = [(3, tag)]
            elif isinstance(s, Rectangle):
                dt = [(2, occ.addRectangle(0, 0, 0, *vec(s.size)))]
                _place_sheet(dt, s.plane, *vec(s.origin))
                names[s.name] = dt
            elif isinstance(s, Disk):
                r = length(s.radius)
                dt = [(2, occ.addDisk(0, 0, 0, r, r))]
                _place_sheet(dt, s.plane, *vec(s.center))
                names[s.name] = dt
            elif isinstance(s, Translate):
                occ.translate(lookup(s.target), *vec(s.vector))
            elif isinstance(s, Rotate):
                occ.rotate(lookup(s.target), *vec(s.origin), *[num(a) for a in s.axis],
                           math.radians(num(s.angle)))
            elif isinstance(s, Boolean):
                obj = lookup(s.object)
                tools = [dt for t in s.tools for dt in lookup(t)]
                fn = {"unite": occ.fuse, "subtract": occ.cut, "intersect": occ.intersect}[s.op]
                out, _ = fn(obj, tools)                        # consumes object and tools
                result = s.name or s.object
                obj_meta = meta[s.object]
                for t in [s.object, *s.tools]:
                    names.pop(t, None)
                    meta.pop(t, None)
                if out:
                    names[result] = out
                    meta[result] = {**obj_meta, "op": s.op}
                else:
                    warnings.append(f"'{result}' fully consumed by {s.op} (history[{i}])")
                continue
            if s.op in ("box", "cylinder", "sphere", "rectangle", "disk"):
                meta[s.name] = {"op": s.op, "material": s.material,
                                "dim": names[s.name][0][0]}
        except ExprError as e:
            raise BuildError(f"history[{i}] {s.op} '{label}': {e}") from None
        except BuildError as e:
            raise BuildError(f"history[{i}] {s.op} '{label}': {e}") from None
        except Exception as e:  # gmsh raises plain Exception
            raise BuildError(f"history[{i}] {s.op} '{label}': gmsh: {e}") from None
    return names, meta


def _fragment(names):
    """One fragment over everything. Pieces claimed by several objects go to the
    object with the smallest original measure (nested object wins over its container)."""
    order = [(n, dt) for n, dts in names.items() for dt in dts]
    if len(order) < 2:
        occ.synchronize()
        return names
    measure = defaultdict(float)
    for n, (d, t) in order:
        measure[n] += occ.getMass(d, t)
    dts = [dt for _, dt in order]
    _, out_map = occ.fragment(dts[:1], dts[1:])
    claims = defaultdict(list)
    for (n, _), pieces in zip(order, out_map):
        for p in pieces:
            claims[p].append(n)
    new = {n: [] for n in names}
    for piece, owners in claims.items():
        owner = min(owners, key=lambda n: measure[n])
        if piece not in new[owner]:
            new[owner].append(piece)
    occ.synchronize()
    return new


def _faces_of(dts):
    faces = []
    for d, t in dts:
        if d == 2:
            faces.append(t)
        elif d == 3:
            faces += [abs(f) for _, f in gmsh.model.getBoundary([(3, t)], combined=False, oriented=False)]
    return list(dict.fromkeys(faces))


def _bbox(dts):
    boxes = [occ.getBoundingBox(d, t) for d, t in dts]
    return ([min(b[i] for b in boxes) for i in range(3)],
            [max(b[i + 3] for b in boxes) for i in range(3)])


def _groups(project, names, meta, warnings):
    """Physical groups after fragment. Returns {(dim, name): [tags]}."""
    groups = defaultdict(list)
    for n, dts in names.items():
        mat = meta[n]["material"]
        for d, t in dts:
            if d == 3:
                groups[(3, f"mat:{mat}")].append(t)
            elif d == 2 and mat in METALS:
                groups[(2, "bc:PEC")].append(t)
        if dts and dts[0][0] == 2 and mat not in METALS:
            warnings.append(f"sheet '{n}' has non-metal material '{mat}'; no physical group assigned")

    all_vols = gmsh.model.getEntities(3)
    outer = {abs(t) for _, t in gmsh.model.getBoundary(all_vols, combined=True, oriented=False)}
    for b in project.boundaries:
        if b.target not in names:
            raise BuildError(f"boundary {b.type}: unknown object '{b.target}'")
        vols = [dt for dt in names[b.target] if dt[0] == 3]
        if not vols:
            raise BuildError(f"boundary {b.type}: '{b.target}' is not a volume")
        if b.faces == "outer":
            faces = [f for f in _faces_of(vols) if f in outer]
        else:
            faces = [abs(t) for _, t in gmsh.model.getBoundary(vols, combined=True, oriented=False)]
        if not faces:
            warnings.append(f"boundary {b.type} on '{b.target}' selected no faces")
        groups[(2, f"bc:{b.type}")] += faces

    for i, p in enumerate(project.ports, 1):
        if p.target not in names:
            raise BuildError(f"port {i}: unknown object '{p.target}'")
        faces = [t for d, t in names[p.target] if d == 2]
        if not faces:
            raise BuildError(f"port {i}: '{p.target}' is not a sheet")
        groups[(2, f"port:{i}")] += faces

    for (d, name), tags in groups.items():
        tags[:] = list(dict.fromkeys(tags))
        if tags:
            gmsh.model.addPhysicalGroup(d, tags, name=name)
    return groups


def _checks(project, values, names, meta, groups, warnings):
    rad_targets = [b.target for b in project.boundaries if b.type == "radiation"]
    for target in rad_targets:
        lo, hi = _bbox(names[target])
        tol = 1e-9 + 1e-6 * max(h - l for l, h in zip(lo, hi))
        for n, dts in names.items():
            if n == target or not dts:
                continue
            blo, bhi = _bbox(dts)
            if any(blo[i] < lo[i] - tol or bhi[i] > hi[i] + tol for i in range(3)):
                warnings.append(f"'{n}' extends outside radiation box '{target}'")

    f0 = values.get("f0")
    rad_faces = groups.get((2, "bc:radiation"), [])
    metal = [dt for n, dts in names.items() if meta[n]["material"] in METALS for dt in dts]
    if f0 and rad_faces and metal:
        quarter = C0 / f0 / 4
        dmin = min(occ.getDistance(2, f, d, t)[0] for f in rad_faces for d, t in metal)
        if dmin < quarter:
            warnings.append(f"radiation boundary is {dmin * 1e3:.2f} mm from metal; "
                            f"< λ/4 = {quarter * 1e3:.2f} mm at f0 = {f0 / 1e9:g} GHz")


def _tessellate(names, meta):
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    index = {int(t): i for i, t in enumerate(node_tags)}
    objects = []
    for n, dts in names.items():
        faces = _faces_of(dts)
        local, positions, indices = {}, [], []
        for f in faces:
            _, tri_nodes = gmsh.model.mesh.getElementsByType(2, f)
            for nt in tri_nodes:
                nt = int(nt)
                if nt not in local:
                    local[nt] = len(local)
                    j = index[nt] * 3
                    positions += [round(float(c), 9) for c in coords[j:j + 3]]
                indices.append(local[nt])
        objects.append({"name": n, **meta[n], "entities": len(dts),
                        "faces": faces, "positions": positions, "indices": indices})
    return objects


def build(path, out_dir="out", mesh=True):
    """Build a project file. Returns a JSON-serialisable result dict; raises BuildError."""
    t0 = time.time()
    project = load_project(path)
    try:
        values = resolve_variables(project.variables)
    except ExprError as e:
        raise BuildError(str(e)) from None
    scale = UNIT_SCALE[project.units]
    warnings = []

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(project.name)
        names, meta = _replay(project, values, scale, warnings)
        try:
            names = _fragment(names)
        except Exception as e:
            raise BuildError(f"fragment failed: {e}") from None
        for n in [n for n, d in names.items() if not d]:
            warnings.append(f"'{n}' was fully overlapped by smaller objects and has no region left")
            del names[n]
        groups = _groups(project, names, meta, warnings)
        _checks(project, values, names, meta, groups, warnings)

        stats = {"volumes": len(gmsh.model.getEntities(3)), "surfaces": len(gmsh.model.getEntities(2))}
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        files = {}
        if mesh:
            if "mesh_size" in values:
                gmsh.option.setNumber("Mesh.MeshSizeMax", values["mesh_size"] * scale)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
            try:
                gmsh.model.mesh.generate(3)
            except Exception as e:
                raise BuildError(f"meshing failed: {e}") from None
            stats["nodes"] = len(gmsh.model.mesh.getNodes()[0])
            stats["tetrahedra"] = len(gmsh.model.mesh.getElementsByType(4)[0])
            files["msh"] = str(out / f"{project.name}.msh")
            gmsh.write(files["msh"])
        else:
            gmsh.model.mesh.generate(2)
        files["step"] = str(out / f"{project.name}.step")
        with _quiet_stdout():  # OCC's STEP writer prints straight to fd 1
            gmsh.write(files["step"])
        objects = _tessellate(names, meta)
    finally:
        gmsh.finalize()

    return {
        "name": project.name,
        "description": project.description,
        "units": project.units,
        "variables": {k: str(v) for k, v in project.variables.items()},
        "values": values,
        "objects": objects,
        "groups": [{"name": n, "dim": d, "count": len(t), "tags": t} for (d, n), t in groups.items() if t],
        "stats": stats,
        "warnings": warnings,
        "files": files,
        "built_at": time.time(),
        "build_seconds": round(time.time() - t0, 2),
    }
