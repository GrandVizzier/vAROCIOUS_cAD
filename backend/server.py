"""FastAPI app: watches projects/, rebuilds in a subprocess, pushes updates over /ws.

Project id = path under projects/ without .json, e.g. "examples/patch_on_fr4".
"""
import asyncio
import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from watchfiles import Change, awatch

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


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)
