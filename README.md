# EM Geometry Studio

A local web app that turns JSON project files into exact, conformal 3D geometry for
electromagnetic FEM solvers, and shows it live in the browser.

- Geometry is built with **Gmsh's OpenCascade kernel**, then **fragmented** so every region shares
  conformal faces.
- Regions and faces are labeled with **physical groups**: `mat:<material>`,
  `bc:radiation`, `bc:PEC`, `bc:floquet`, `bc:master1`/`bc:slave1`/…, and `port:<n>`.
- It exports a volume mesh (`.msh`) and CAD (`.step`).
- The viewer  updates live whenever a project file changes.
- **Simulate it** with the open-source FDTD solver [openEMS](https://openems.de): set up a frequency
  sweep in the Analysis tab, then view S-parameters, a Smith chart, impedance, VSWR and E-field
  overlays. The UI is laid out like HFSS.
- **[Claude Code](https://claude.com/claude-code) writes the geometry for you.** Describe an antenna
  in plain English, or point it at a paper. It writes the project JSON, builds it, checks the
  result, and fixes any problems.

---

## 1. Prerequisites

| Tool | Version | Check | Install |
|---|---|---|---|
| Python | **3.13** (3.11+ without simulation) | `python --version` | https://www.python.org/downloads/ (Windows: `winget install Python.Python.3.13`) |
| Node.js | 18+ | `node --version` | https://nodejs.org (Windows: `winget install OpenJS.NodeJS.LTS`) |
| Git | any | `git --version` | https://git-scm.com |
| Claude Code | latest | `claude --version` | https://docs.claude.com/en/docs/claude-code (optional, but it's the point) |

You don't need a separate Gmsh or OpenCascade install. The `gmsh` pip wheel bundles both.
On Windows, openEMS is installed by a script (step 2); its packages are built for Python 3.13 and
3.14 only, which is why 3.13 is required.

## 2. Setup

```bash
git clone https://github.com/GrandVizzier/vAROCIOUS_cAD.git
cd vAROCIOUS_cAD
```

**Windows (PowerShell)**
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\install_openems.py   # downloads openEMS 0.37 into tools\openEMS
cd frontend; npm install; cd ..
```

**macOS / Linux**
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
(cd frontend && npm install)
```

Check that it works by running the test suite. It builds all the example geometries:
```bash
.venv/bin/python -m pytest          # Windows: .venv\Scripts\python -m pytest
```

> Linux note: Gmsh may need a few system libraries (`libglu1-mesa`, `libxft2`, `libxinerama1`).
> If `import gmsh` fails, install them with your package manager.
>
> macOS / Linux simulation: build openEMS with its Python extensions (see the
> [openEMS install docs](https://docs.openems.de/install/index.html)), install them into `.venv`, and
> set `CSXCAD_INSTALL_PATH` to the openEMS install folder. Everything except simulation works
> without it.

## 3. Run the app

```bash
.venv/bin/python scripts/dev.py     # Windows: .venv\Scripts\python scripts\dev.py
```

This starts the backend (FastAPI on :8000) and the frontend (Vite on :5173). Open
**http://localhost:5173** and press Ctrl+C to stop both.

| Where | What |
|---|---|
| Tabs (top right) | **3D Modeler**, **Analysis**, **Results** |
| Project Manager (left) | Project picker, then the design tree: Model (solids, sheets; visibility toggles), Boundaries, Excitations (✓ valid / ⚠ problem), Analysis (setup and sweep), Results (reports), Field Overlays |
| 3D Modeler | Left-drag to orbit, right-drag to pan, scroll to zoom, click an object to select it. Toggles for grid, mesh wireframe and E field |
| Properties (right) | **Variables:** edit a value and press Enter. It's saved to the JSON file and the model rebuilds. Below that, the read-only project JSON |
| Analysis | Driven solution setup (sweep, field frequencies, mesh density, absorber, convergence), Validation Check, and **Analyze** / Abort |
| Results | dB(S), S phase, Smith chart, input impedance and VSWR, with markers and a hover readout |
| Message Manager / Progress (bottom) | Warnings, errors and solver messages; the analysis progress bar; `.msh` / `.step` downloads |

If a build fails, the last good geometry stays on screen and the error appears in a red banner.

### Simulating (openEMS)

1. The project needs a **port** and a **simulation** block. Claude adds both when you ask for an
   antenna "ready to simulate". `projects/patch_inset_2p4ghz.json` is a full example.
2. Open **Analysis**, check the sweep, then press **Analyze**. One broadband FDTD run per excited
   port typically takes 1–5 minutes; progress shows in the bottom right.
3. Open **Results** for the reports, or tick **E field** in the 3D Modeler. The field plot is
   |E| (V/m, for 1 W incident) on a cut plane, plus arrows. You can move the plane, pick the
   frequency and animate the phase.

From the command line: `.venv\Scripts\python scripts\simulate.py projects\<name>.json`.
openEMS can't do periodic or Floquet boundaries, so the reflectarray unit cell can only be built,
not simulated.

## 4. Generate geometry with Claude Code

Open a terminal **in the repo root** and run:

```bash
claude
```

Claude Code reads [`CLAUDE.md`](CLAUDE.md) automatically. That file gives it all the context it
needs: the architecture rules, the JSON schema, units, physics formulas for sizing antennas, and
the build-and-check loop. You don't need to explain any of this yourself. Keep the app running in
another terminal and ask for a model:

- *"2.4 GHz inset-fed patch on 1.6 mm FR4 with a radiation air box"*
- *"Half-wave dipole at 915 MHz in a spherical air region"*
- *"Build the unit cell from the paper `my_paper.pdf` in this folder"*

Claude will then:
1. write `projects/<name>.json`, storing the inputs (`f0`, `er`, `h`, …) and the derived dimensions
   as variables so you can tweak them;
2. run `scripts/build.py projects/<name>.json --render`, read the summary, look at the rendered
   top/front/iso PNGs, and fix any errors or mismatches;
3. report the key dimensions and anything it assumed.

The running app picks up the new file and displays it immediately.

## 5. Build from the command line

```bash
.venv/bin/python scripts/build.py projects/examples/patch_on_fr4.json --render
```

This prints the objects, volumes per material, physical groups, mesh statistics and warnings, and
writes `out/<name>.msh`, `out/<name>.step` and `out/<name>_{top,front,iso}.png`. It exits non-zero
with a precise error message if anything fails.

The warnings it checks for:
- an object fully consumed by a boolean;
- an object sticking out of the air box;
- a radiation boundary closer than λ/4 to any metal at `f0`.

## 6. Project files

Project files are JSON in `projects/`. The schema is defined in
[`backend/schema.py`](backend/schema.py), and [`projects/examples/`](projects/examples) has
templates (box in air, patch on FR4, coax section, half-wave dipole).
[`projects/me_dipole_dp_cell.json`](projects/me_dipole_dp_cell.json) is a full periodic unit-cell
example with master/slave walls and a Floquet port.

```json
{
  "name": "patch_on_fr4",
  "units": "mm",
  "variables": { "f0": "2.4e9", "h": "1.6", "W": "38" },
  "history": [
    { "op": "box", "name": "substrate", "origin": ["-30","-30","0"], "size": ["60","60","h"], "material": "FR4" },
    { "op": "rectangle", "name": "patch", "origin": ["-W/2","-14.7","h"], "size": ["W","29.4"], "material": "PEC" },
    { "op": "box", "name": "airbox", "origin": ["-60","-60","-40"], "size": ["120","120","80"], "material": "air" }
  ],
  "boundaries": [ { "type": "radiation", "target": "airbox", "faces": "outer" } ],
  "ports": []
}
```

- **Ops:** `box`, `cylinder`, `sphere`, `rectangle`, `disk`, `translate`, `rotate`, `unite`,
  `subtract`, `intersect`.
- **Numbers are expressions.** Every number is a string expression over `variables`, using
  `+ - * / **`, `sqrt`, `sin`/`cos`/`tan`, `pi` and `c0`. It goes through a safe evaluator (no
  `eval`), and circular references between variables are detected and reported.
- **Units:** lengths are in `units`, frequencies in Hz. Internally everything is SI.

## 7. Repository layout

```
backend/    schema.py, expr.py (safe evaluator), engine.py (all Gmsh code), openems_sim.py (solver),
            render.py, server.py, tests/
scripts/    build.py / simulate.py (CLIs, also used by the server), dev.py (starts both servers),
            install_openems.py
frontend/   Vite + React + TypeScript + react-three-fiber viewer
projects/   your project JSON files; examples/ are reference fixtures (read-only in the UI)
out/        build outputs and out/sims/<name>/ simulation results (gitignored)
tools/      openEMS install (gitignored)
CLAUDE.md   context and instructions for Claude Code
```

## 8. Troubleshooting

- **The viewer says "backend unreachable".** The backend didn't start. Check the `dev.py` terminal
  output and make sure port 8000 is free.
- **`npm` is not found on Windows right after installing Node.** Open a new terminal so the
  updated PATH is loaded.
- **Builds are slow or time out (120 s).** Add or raise the `mesh_size` variable, which sets the
  max element size in project units.

## License

GPL-3.0 (see `LICENSE`). Gmsh is GPL-licensed, and this tool links to it through the `gmsh`
Python package.
