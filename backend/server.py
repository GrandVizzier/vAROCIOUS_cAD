"""FastAPI app: watches projects/, rebuilds in a subprocess, pushes updates over /ws.

Project id = path under projects/ without .json, e.g. "examples/patch_on_fr4".
"""
import asyncio
import json
import re
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import ValidationError
from watchfiles import Change, awatch

from .openems_sim import preflight
from .schema import Simulation, format_validation_error

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
OUT = ROOT / "out"
BUILD_TIMEOUT = 120  # seconds

state = {}      # id -> {"status": "building"|"ok"|"error", "error": str|None, "result": last good}
locks = {}      # id -> asyncio.Lock (one build per project at a time)
clients = set()


def project_path(pid):
    p = (PROJECTS / f"{pid}.json").resolve()
    if PROJECTS.resolve() not in p.parents:
        raise HTTPException(400, "invalid project id")
    if not p.exists():
        raise HTTPException(404, f"no project '{pid}'")
    return p


def pid_of(path):
    return Path(path).resolve().relative_to(PROJECTS.resolve()).with_suffix("").as_posix()


async def broadcast(msg):
    for ws in list(clients):
        try:
            await ws.send_json(msg)
        except Exception:
            clients.discard(ws)


def _run_build(path):
    """Gmsh is not thread-safe: every build runs in its own process with a timeout."""
    cmd = [sys.executable, str(ROOT / "scripts" / "build.py"), str(path), "--json", "--out", str(OUT)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return None, f"build timed out after {BUILD_TIMEOUT} s"
    if r.returncode != 0:
        msg = r.stderr.strip().splitlines()
        return None, (msg[-1].removeprefix("ERROR: ") if msg else f"build exited with {r.returncode}")
    return json.loads(r.stdout.strip().splitlines()[-1]), None


async def rebuild(pid):
    new = pid not in state
    entry = state.setdefault(pid, {"status": "building", "error": None, "result": None})
    async with locks.setdefault(pid, asyncio.Lock()):
        entry["status"] = "building"
        await broadcast({"type": "build", "id": pid, "status": "building", "new": new})
        result, error = await asyncio.to_thread(_run_build, PROJECTS / f"{pid}.json")
        if result:
            entry.update(status="ok", error=None, result=result)
        else:
            entry.update(status="error", error=error)  # keep last good result
        await broadcast({"type": "build", "id": pid, "status": entry["status"], "new": new})


async def watch():
    async for changes in awatch(PROJECTS, debounce=300, step=50,
                                watch_filter=lambda _, p: p.endswith(".json")):
        for change, path in changes:
            pid = pid_of(path)
            if change == Change.deleted:
                state.pop(pid, None)
                await broadcast({"type": "deleted", "id": pid})
            else:
                asyncio.create_task(rebuild(pid))


@asynccontextmanager
async def lifespan(_):
    global LOOP
    LOOP = asyncio.get_running_loop()  # for the simulation reader thread
    PROJECTS.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    for p in PROJECTS.rglob("*.json"):
        state[pid_of(p)] = {"status": "building", "error": None, "result": None}
        asyncio.create_task(rebuild(pid_of(p)))
    task = asyncio.create_task(watch())
    yield
    task.cancel()


app = FastAPI(title="EM Geometry Studio", lifespan=lifespan)


@app.get("/projects")
def list_projects():
    files = sorted(PROJECTS.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"id": pid_of(p), "mtime": p.stat().st_mtime,
             "status": state.get(pid_of(p), {}).get("status", "pending"),
             "readonly": pid_of(p).startswith("examples/")} for p in files]


@app.get("/build/{pid:path}")
async def get_build(pid: str):
    path = project_path(pid)
    if pid not in state:
        await rebuild(pid)
    elif state[pid]["result"] is None and state[pid]["status"] == "building":
        async with locks.setdefault(pid, asyncio.Lock()):
            pass  # wait for the in-flight build
    return {**state[pid], "id": pid, "source": path.read_text(encoding="utf-8-sig")}


@app.put("/projects/{pid:path}/variables")
def set_variables(pid: str, variables: dict[str, str] = Body(...)):
    """Write variable values back to the JSON file; the watcher triggers the rebuild."""
    if pid.startswith("examples/"):
        raise HTTPException(403, "example projects are read-only")
    path = project_path(pid)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data.setdefault("variables", {}).update({k: str(v) for k, v in variables.items()})
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"ok": True}


@app.get("/download/{file:path}")
def download(file: str):
    pid, _, ext = file.rpartition(".")
    result = state.get(pid, {}).get("result")
    if ext not in ("msh", "step") or not result or ext not in result["files"]:
        raise HTTPException(404, f"no {ext} file for '{pid}'")
    path = Path(result["files"][ext])
    if not path.is_absolute():
        path = ROOT / path
    return FileResponse(path, filename=path.name)


@app.put("/projects/{pid:path}/simulation")
def set_simulation(pid: str, simulation: dict = Body(...)):
    """Write the analysis setup back to the JSON file (validated); the watcher rebuilds."""
    if pid.startswith("examples/"):
        raise HTTPException(403, "example projects are read-only")
    try:
        Simulation.model_validate(simulation)
    except ValidationError as e:
        raise HTTPException(422, format_validation_error(e)) from None
    path = project_path(pid)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data["simulation"] = simulation
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"ok": True}


# ---- simulation runs -------------------------------------------------------------------------
# ponytail: one global run at a time; a queue if several users ever share this server
sim = {"pid": None, "proc": None, "status": "idle", "progress": 0.0, "stage": "", "log": deque(maxlen=300)}
ENERGY = re.compile(r"Energy: ~\S+ \(\s*(-?)\s*([\d.]+)dB\)")  # also "(- 0.00dB)"
LOOP = None


def sim_command(path):
    return [sys.executable, "-u", str(ROOT / "scripts" / "simulate.py"), str(path), "--out", str(OUT)]


def sims_dir(pid):
    result = state.get(pid, {}).get("result")
    return OUT / "sims" / result["name"] if result else None


def _push(msg):
    if LOOP:
        asyncio.run_coroutine_threadsafe(broadcast(msg), LOOP)


def _watch_sim(pid, proc, end_db):
    """Reader thread: parse openEMS progress lines, keep a log tail, push updates."""
    last = 0.0
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        m = ENERGY.search(line)
        if m:  # energy falls from 0 dB to the end criterion
            db = -float(m.group(2)) if m.group(1) else float(m.group(2))
            sim["progress"] = max(sim["progress"], min(99.0, 100 * db / end_db))
        else:
            sim["log"].append(line)
            if line.startswith("[sim]"):
                sim["stage"] = line[6:]
        if time.time() - last > 0.5 or not m:
            last = time.time()
            _push({"type": "sim", "id": pid, "status": "running", "progress": sim["progress"],
                   "stage": sim["stage"]})
    code = proc.wait()
    if sim["status"] != "cancelled":
        sim["status"] = "done" if code == 0 else "error"
    if code != 0 and sim["status"] == "error":
        sim["log"].append(f"simulation exited with code {code}")
    sim["progress"] = 100.0 if code == 0 else sim["progress"]
    _push({"type": "sim", "id": pid, "status": sim["status"], "progress": sim["progress"]})


@app.post("/simulate/{pid:path}/cancel")
def cancel_simulation(pid: str):
    if sim["pid"] != pid or sim["status"] != "running":
        raise HTTPException(409, "no running simulation for this project")
    sim["status"] = "cancelled"
    sim["proc"].terminate()
    return {"ok": True}


@app.post("/simulate/{pid:path}")
def start_simulation(pid: str):
    path = project_path(pid)
    if sim["status"] == "running":
        raise HTTPException(409, f"a simulation is already running ({sim['pid']})")
    entry = state.get(pid)
    if not entry or entry["status"] != "ok":
        raise HTTPException(400, "the project must build successfully before simulating")
    problems = preflight(entry["result"])
    if problems:
        raise HTTPException(400, "; ".join(problems))
    proc = subprocess.Popen(sim_command(path), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    sim.update(pid=pid, proc=proc, status="running", progress=0.0, stage="starting", log=deque(maxlen=300))
    threading.Thread(target=_watch_sim, daemon=True,
                     args=(pid, proc, entry["result"]["simulation"]["end_criteria_db"])).start()
    return {"ok": True}


@app.get("/sim/{pid:path}/field")
def field_plane(pid: str, f: float, plane: str = "z", pos: float = 0.0, max_n: int = 120):
    """Complex E on an axis-aligned plane of the last run (subsampled to <= max_n per axis)."""
    d = sims_dir(pid)
    if d is None or not (d / "fields.npz").exists() or plane not in ("x", "y", "z"):
        raise HTTPException(404, "no field data; set fields_at and run the simulation")
    with np.load(d / "fields.npz") as z:
        fi = int(np.argmin(np.abs(z["freqs"] - f)))
        freq = float(z["freqs"][fi])
        axes = {a: z[a] for a in "xyz"}
        k = "xyz".index(plane)
        i = int(np.argmin(np.abs(axes[plane] - pos)))
        sl = [fi, slice(None)] + [slice(None)] * 3
        sl[2 + k] = i
        re, im = z["re"][tuple(sl)], z["im"][tuple(sl)]  # (3, nu, nv)
    u, v = [a for a in "xyz" if a != plane]
    su = max(1, -(-len(axes[u]) // max_n))
    sv = max(1, -(-len(axes[v]) // max_n))
    return {"freq": freq, "plane": plane, "pos": float(axes[plane][i]), "u_axis": u, "v_axis": v,
            "u": axes[u][::su].tolist(), "v": axes[v][::sv].tolist(),
            "re": re[:, ::su, ::sv].tolist(), "im": im[:, ::su, ::sv].tolist(),
            "range": {a: [float(axes[a][0]), float(axes[a][-1])] for a in "xyz"}}


@app.get("/sim/{pid:path}")
def get_sim(pid: str):
    d = sims_dir(pid)
    results = None
    if d and (d / "results.json").exists():
        results = json.loads((d / "results.json").read_text(encoding="utf-8"))
    built = state.get(pid, {}).get("result")
    mine = sim["pid"] == pid
    return {
        "status": sim["status"] if mine else ("done" if results else "idle"),
        "progress": sim["progress"] if mine else (100.0 if results else 0.0),
        "stage": sim["stage"] if mine else "",
        "log": list(sim["log"]) if mine else [],
        "problems": preflight(built) if built else ["project has not built yet"],
        "results": results,
        "stale": bool(results and built and results.get("source_hash") != built.get("source_hash")),
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)
