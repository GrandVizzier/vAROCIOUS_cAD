import json
import shutil
import time

from fastapi.testclient import TestClient

from backend import server


def test_import_project(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(server, "PROJECTS", projects)
    monkeypatch.setattr(server, "OUT", tmp_path / "out")
    server.state.clear()
    server.locks.clear()
    src = (server.ROOT / "projects/examples/box_in_air.json").read_text()
    with TestClient(server.app) as c:
        assert c.post("/projects/import", json={"content": src}).json() == {"id": "box_in_air"}
        assert (projects / "box_in_air.json").exists()
        assert c.post("/projects/import", json={"content": src}).status_code == 409
        assert c.post("/projects/import", json={"content": src, "overwrite": True}).status_code == 200
        bad = c.post("/projects/import", json={"content": "{nope"})
        assert bad.status_code == 422 and "not valid JSON" in bad.json()["detail"]
        assert c.post("/projects/import", json={"content": '{"name": "x"}'}).status_code == 422
        weird = json.loads(src) | {"name": "../evil name"}
        assert c.post("/projects/import", json={"content": json.dumps(weird)}).json() == {"id": "___evil_name"}


def test_server_build_writeback_download(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    shutil.copy(server.ROOT / "projects/examples/box_in_air.json", projects / "box.json")
    monkeypatch.setattr(server, "PROJECTS", projects)
    monkeypatch.setattr(server, "OUT", tmp_path / "out")
    server.state.clear()
    server.locks.clear()

    with TestClient(server.app) as c:
        assert [p["id"] for p in c.get("/projects").json()] == ["box"]
        b = c.get("/build/box").json()
        assert b["status"] == "ok" and b["result"]["stats"]["volumes"] == 2
        assert c.get("/download/box.msh").status_code == 200
        assert c.get("/download/box.exe").status_code == 404
        assert c.get("/build/..%2F..%2Fpyproject").status_code in (400, 404)
        assert c.put("/projects/examples/box_in_air/variables", json={"a": "5"}).status_code in (403, 404)

        with c.websocket_connect("/ws") as ws:
            assert c.put("/projects/box/variables", json={"a": "12"}).status_code == 200
            assert json.loads((projects / "box.json").read_text())["variables"]["a"] == "12"
            deadline = time.time() + 30
            while time.time() < deadline:   # watcher -> rebuild -> push
                msg = ws.receive_json()
                if msg["status"] == "ok":
                    break
        assert c.get("/build/box").json()["result"]["values"]["a"] == 12

        (projects / "box.json").write_text("{broken")
        time.sleep(2)
        b = c.get("/build/box").json()
        assert b["status"] == "error" and "invalid JSON" in b["error"]
        assert b["result"]["values"]["a"] == 12     # last good geometry kept
