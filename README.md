# EM Geometry Studio

Local web app that builds 3D geometry for an EM FEM solver from JSON project files and shows it
live. Geometry is built with Gmsh's OpenCascade kernel, fragmented so all regions share conformal
faces, and labeled with physical groups (`mat:*`, `bc:*`, `port:*`). It exports `.msh` and `.step`.

## Setup (Windows)
Requirements: Python 3.11+ and Node.js 18+.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # `gmsh` wheel bundles OpenCascade
cd frontend; npm install; cd ..
```

## Run
```powershell
.venv\Scripts\python scripts\dev.py
```
Open http://localhost:5173. The backend (:8000) watches `projects/`. Any new or changed `.json` is
rebuilt and pushed to the viewer. Edits in the Variables panel are written back to the JSON file.
Example projects under `projects/examples/` are read-only in the UI.

Build one project from the command line (summary, warnings, exports, PNG views):
```powershell
.venv\Scripts\python scripts\build.py projects\examples\patch_on_fr4.json --render
```
Tests: `.venv\Scripts\python -m pytest`

## Workflow: asking Claude Code for models
Run `claude` in this folder and describe a model, e.g. *"2.4 GHz inset-fed patch on 1.6 mm FR4 with
a radiation air box"*. Following `CLAUDE.md`, Claude writes `projects/<name>.json` with the
physics-derived dimensions stored as variables. It then builds the project with `--render`, checks
the summary and images, fixes any problems, and reports the key dimensions. The app shows the new
project automatically. You can then tweak variables in the UI.

The schema lives in `backend/schema.py`, and `projects/examples/` holds templates.

## License
GPL-3.0 (see `LICENSE`). Gmsh is GPL-licensed and this tool links to it via the `gmsh` Python package.
