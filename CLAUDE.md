# EM Geometry Studio

Geometry front end for a separate FEM electromagnetic solver. Project JSON → Gmsh OCC →
conformal, labeled `.msh` + `.step`, plus a live 3D viewer.

## Stack
- Backend: Python 3.13 (`.venv`), FastAPI, `gmsh` (OCC kernel only, never `gmsh.model.geo`),
  pydantic v2, watchfiles, WebSockets. Solver: openEMS 0.37 (`tools/openEMS`, `backend/openems_sim.py`).
- Frontend: Vite + React + TypeScript, `@react-three/fiber` + `@react-three/drei` (`frontend/`).

## Commands (from repo root)
Use the venv's Python: `.venv\Scripts\python` on Windows, `.venv/bin/python` on macOS/Linux
(written `PY` below). If `.venv` doesn't exist yet, set it up first, following README §2.
- Run app: `PY scripts/dev.py` → http://localhost:5173 (API on :8000)
- Build one project: `PY scripts/build.py projects/<name>.json --render`
- Simulate one project: `PY scripts/simulate.py projects/<name>.json` (needs openEMS:
  `PY scripts/install_openems.py` on Windows)
- Tests: `PY -m pytest`
- Frontend type-check: `cd frontend && npx tsc --noEmit`
- Reading a paper (PDF): `PY -m pip install pymupdf`, then extract the text and render the figure
  pages to PNGs under `out/` and look at them. Dimensions are usually in the figure captions.

## Layout
- `backend/schema.py`: Project JSON schema (pydantic). **Read this first** for op fields.
- `backend/expr.py`: safe AST expression evaluator, variable resolution, and cycle detection.
- `backend/engine.py`: replay, fragment, physical groups, mesh, export, tessellation. All gmsh code lives here.
- `backend/render.py`: matplotlib PNG views. `backend/server.py`: watcher, REST, `/ws`.
- `scripts/build.py`: CLI (also what the server runs, in a subprocess). `scripts/dev.py`: starts both servers.
- `projects/examples/`: reference projects and test fixtures. `out/`: build artifacts (gitignored).

## Architecture rules (do not deviate)
1. The Project JSON history is the single source of truth. The UI only shows triangles and edits `variables`.
2. Track objects by NAME (`names: name -> [(dim, tag)]`), never by gmsh tag.
3. After the history, ONE `occ.fragment` over everything → conformal shared faces. A fragment piece
   claimed by several objects goes to the object with the **smallest original volume/area**
   (a substrate inside an air box owns its region; the air box keeps the rest).
4. Physical groups, assigned after fragment: volumes `mat:<material>`; metal sheets (PEC/copper)
   `bc:PEC`; `boundaries` → `bc:radiation` / `bc:PEC`; `ports[i]` → `port:<i+1>` (1-based).
5. Internal units SI (m, Hz). `units` in the JSON scales lengths only; frequencies stay in Hz.
   UI displays mm / GHz.
6. Every gmsh build runs in its own process with a timeout (gmsh is not thread-safe).

## Project JSON conventions
- Every numeric field is an expression string over `variables` (`+ - * / ** ( )`, `sqrt sin cos tan
  asin acos atan exp log abs min max`, constants `pi`, `c0`). Variables can reference each other.
- `units: "mm"` (default) → lengths in mm. `f0` and other frequencies in Hz (`"2.4e9"`).
- Ops: `box{origin,size}`, `cylinder{origin(base centre),axis(vector incl. length),radius}`,
  `sphere{center,radius}`, `rectangle{origin,size[2],plane}`, `disk{center,radius,plane}`,
  `translate{target,vector}`, `rotate{target,origin,axis,angle(deg)}`,
  `unite|subtract|intersect{object,tools[],name?}` (consumes the tools; the result keeps `object`'s
  name and material unless `name` is given).
- Sheet planes: `XY` size = (dx,dy); `XZ` = (dx,dz); `YZ` = (dy,dz).
- Radiation boundary: `{"type":"radiation","target":"<air volume>","faces":"outer"}`.
- Boundary types: `radiation`, `PEC`, `floquet`, `master1/slave1/master2/slave2` → group `bc:<type>`.
  `faces`: `outer` | `all` | `+x -x +y -y +z -z` (outer faces of the target on that side of the model
  bbox). `target: "*"` = all volumes (use it for periodic walls, which cut every layer).
  Unit-cell template: `projects/me_dipole_dp_cell.json`.
- Optional `mesh_size` variable sets the max element size (project units).
- Sheets default to PEC; volumes default to air.

## Ports & simulation (openEMS, FDTD)
- A project is simulated when it has `ports` and a `simulation` block (template:
  `projects/patch_inset_2p4ghz.json`; dipole gap port: `projects/examples/dipole_halfwave.json`).
- **Lumped port** = a flat, axis-aligned sheet (`material: "port"`) that bridges two conductors, plus
  `{"target": "<sheet>", "type": "lumped", "impedance": "50", "direction": "+z"}`.
  `direction` lies IN the sheet and points from one conductor to the other. Width ≈ trace/arm width.
  - Microstrip edge feed: XZ (or YZ) sheet at the trace end, from ground (z=0) to the trace (z=h), `+z`.
  - Dipole / gap feed: sheet spanning the gap between the two arms, direction along the dipole axis.
  - The build checks both ends of the port touch metal and that the direction lies in the sheet; any
    `PROBLEM` in the build summary's **Ports** section must be fixed before simulating.
- `simulation`: `sweep` start/stop are Hz expressions (`"0.8*f0"`), `points`, `fields_at` (Hz list),
  `mesh.cells_per_wavelength` (20 default; 15 for quick checks), `absorber` `PML_8`|`MUR`,
  `end_criteria_db` (-40). Keep ≥ λ/4 air (λ at the lowest frequency) between metal and the air box.
- Materials: built-in `air FR4 RO4003C RO4350B RO5880 RO4450F TLY5 PTFE` (`backend/engine.py`
  `MATERIAL_LIBRARY`); anything else goes in project `"materials": {"Name": {"epsr": "..", "tand": ".."}}`
  (take values from the paper/datasheet). Metals (`PEC`, `copper`) are perfect conductors.
- openEMS limits: no periodic/master-slave/Floquet (the build is fine, `simulate.py` refuses), sheets
  must be axis-aligned; curved parts are staircased on the grid.
- Run `PY scripts/simulate.py projects/<name>.json` (minutes; prints cells, runtime, S11 minimum and
  −10 dB band, Z at f0). Check the resonance against the target and |S11| < −10 dB; if the
  resonance is off, rescale the resonant dimension (≈ 1/f) in `variables` and re-run. Report the
  numbers you got, not the design targets. Results land in `out/sims/<name>/`; the app's Results
  tab and E-field overlay pick them up.

## Generating geometry
When the user describes a model:
1. Write a valid Project JSON to `projects/<name>.json` (snake_case name; the `name` field equals the
   file stem). Use `projects/examples/*.json` as format templates. **Never edit files in
   `projects/examples/` unless asked.**
2. Compute dimensions from physics where relevant, and store both the inputs and the derived values as
   `variables` (expressions, so the user can tweak `f0`/`er`/`h` and everything follows):
   - Patch (transmission-line model), with λ0 = c0/f0:
     `W = c0/(2*f0)*sqrt(2/(er+1))`,
     `eeff = (er+1)/2 + (er-1)/2*(1+12*h/W)**-0.5`,
     `dL = 0.412*h*(eeff+0.3)*(W/h+0.264)/((eeff-0.258)*(W/h+0.8))`,
     `L = c0/(2*f0*sqrt(eeff)) - 2*dL`. Keep SI ↔ mm consistent (e.g. `c0/f0*1000` for λ in mm).
   - Inset feed: `y0 = L/pi*acos(sqrt(Z0/Rin_edge))`, where the edge resistance is estimated from
     `G1 = W/(120*lambda0)` (for W < λ0): `Rin_edge ≈ 1/(2*G1)`.
   - 50 Ω microstrip width: Hammerstad/Wheeler synthesis (`A`/`B` formulas).
   - Dipole: total length ≈ 0.48 λ, with a small feed gap.
   - Air box padding ≥ λ/4 at the lowest frequency from any metal.
3. Run `PY scripts/build.py projects/<name>.json --render`, read the summary
   (objects, groups, warnings), and look at `out/<name>_top.png`, `_front.png` and `_iso.png`. Fix errors,
   warnings and mismatches until it builds cleanly and matches the request.
4. Tell the user the key dimensions (mm) and every assumption. The running app picks the file up
   automatically.
