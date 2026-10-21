# EM Geometry Studio

Geometry front end for a separate FEM electromagnetic solver. Project JSON → Gmsh OCC →
conformal, labeled `.msh` + `.step`, plus a live 3D viewer.

## Stack
- Backend: Python 3.13 (`.venv`), FastAPI, `gmsh` (OCC kernel only, never `gmsh.model.geo`),
  pydantic v2, watchfiles, WebSockets. Solvers (`simulation.solver`, dispatched by `backend/solvers.py`):
  openEMS 0.37 FDTD (`tools/openEMS`, `backend/openems_sim.py`) and Palace 0.18 FEM (`tools/palace`,
  `backend/palace_sim.py`, Linux/macOS).
- Frontend: Vite + React + TypeScript, `@react-three/fiber` + `@react-three/drei` (`frontend/`).

## Commands (from repo root)
Use the venv's Python: `.venv\Scripts\python` on Windows, `.venv/bin/python` on macOS/Linux
(written `PY` below). If `.venv` doesn't exist yet, set it up first, following README §2.
- Run app: `PY scripts/dev.py` → http://localhost:5173 (API on :8000)
- Build one project: `PY scripts/build.py projects/<name>.json --render`
- Simulate one project: `PY scripts/simulate.py projects/<name>.json` (uses `simulation.solver`;
  openEMS: `PY scripts/install_openems.py` on Windows; Palace: README "Simulating with Palace")
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

## Ports & simulation (openEMS FDTD / Palace FEM)
Two solvers read the same project: openEMS (FDTD on a rectilinear grid built from the CAD features)
and Palace (FEM on the build's tetra mesh). **Build every simulatable project so both can run it
unchanged**; switching solver is then a one-word edit of `simulation.solver` (or the Analysis tab's
Solver dropdown). Templates: `projects/patch_inset_2p4ghz.json` (microstrip inset feed),
`projects/examples/dipole_halfwave.json` (gap port).

### Model rules that keep a project valid for both solvers
1. **Air box**: one axis-aligned `box` (name it `airbox`, material `air`) enclosing every other object,
   ≥ λ/4 (λ at the lowest sweep frequency) from any metal or port on every side.
   - Always add `{"type": "radiation", "target": "airbox", "faces": "outer"}`. Palace requires it
     (it becomes the absorbing boundary). openEMS ignores the group and puts its absorber (`PML_8` /
     `MUR`) on the domain bounding box, which is this box. A box, not a sphere: openEMS's domain is
     the bounding box.
2. **Metal**: `PEC` / `copper` sheets (`rectangle`, `disk`, booleans of them) or volumes. Use zero-
   thickness sheets for thin traces, patches and ground planes (cheaper for both). Keep sheets in
   XY / YZ / XZ planes: openEMS cannot place tilted sheets (Palace can, so a tilted sheet makes the
   project Palace-only; say so). Curved volumes are fine for both (openEMS staircases them), except:
   - **Probes, vias and posts: use a square `box` of equal cross-section (side `sqrt(pi)*r`), not a
     thin `cylinder`.** In thin layers the tetra mesher can put a zero-volume element on a cylinder's
     seam line, and Palace aborts on it (non-positive Jacobi diagonal); openEMS staircases the
     cylinder to the same box anyway.
3. **Dielectrics**: volumes whose material is built-in or listed in `"materials"`. An unknown material
   blocks both solvers.
4. **Ports**: lumped ports only, built as below. Waveguide ports and Floquet ports are supported by
   neither: say so and propose a lumped-fed alternative.
5. **Mesh size**: leave out the `mesh_size` variable for simulated projects. Without it the build sizes
   Palace's tetra mesh from `palace.elements_per_wavelength`; with it, `mesh_size` wins, and a coarse
   value (the patch template's `lam0/10` gives ~4,900 tetrahedra) costs Palace accuracy. openEMS ignores
   the tetra mesh. Only set `mesh_size` if the build is too slow, and then keep it ≤ λ/6 at the stop
   frequency in the densest dielectric (`c0/f_stop/sqrt(er_max)/6`, in project units).
6. **Periodic cells** (`master/slave`, `floquet` boundaries) build fine but neither solver runs them.

### Lumped ports
- **Lumped port** = a flat, axis-aligned sheet (`material: "port"`) that bridges two conductors, plus
  `{"target": "<sheet>", "type": "lumped", "impedance": "50", "direction": "+z"}`.
  `direction` lies IN the sheet and points from one conductor to the other. Width ≈ trace/arm width.
  - The build checks both ends of the port touch metal and that the direction lies in the sheet; any
    `PROBLEM` in the build summary's **Ports** section must be fixed before simulating.
- **Pick the port from the design's actual feed** (never leave a radiator/circuit without a port
  unless the user asked for geometry only). Model the feed the paper/user describes, then place:

  | Feed | Port sheet (material `"port"`) | `direction` |
  |---|---|---|
  | Microstrip line (edge / inset / line-fed patch, filters) | at the open end of the 50 Ω line on the substrate edge: XZ/YZ sheet, width = line width `wf`, from ground (z=0) to the trace (z=h) | `+z` |
  | Coax / probe feed (patch, ME-dipole, PIFA) | replace the probe by the port: sheet in the probe's position from ground to the patch/feed strip, width = probe diameter | `+z` (ground → probe top) |
  | Dipole, loop, bow-tie, spiral (balanced, gap fed) | the sheet filling the feed gap between the two arms, width = arm width | along the gap, arm → arm |
  | Monopole over ground | sheet from the ground plane up to the monopole base (leave a small gap below the wire) | away from ground |
  | CPW / slot / Vivaldi (coplanar) | sheet in the metal plane across the slot at the feed point, from signal to ground | across the slot |
  | Two-port devices (filters, couplers, lines) | one port per terminal, `index` order = port number; same rules per end | ground → signal |

  - Impedance: the system reference (50 Ω unless the paper states otherwise). Make sure the feed line
    is actually designed for it (e.g. Hammerstad `wf` for 50 Ω).
  - Keep every port ≥ λ/4 from the air-box faces (openEMS's PML eats the outer 8 cells; Palace's
    absorbing boundary is only accurate away from sources).

### The `simulation` block (one block serves both solvers)
Write the full block, with the settings for both solvers, so switching never needs other edits:
```json
"simulation": {
  "solver": "openems",
  "sweep": {"start": "0.8*f0", "stop": "1.2*f0", "points": 401},
  "fields_at": ["f0"],
  "mesh": {"cells_per_wavelength": 20, "ratio": 1.4},
  "absorber": "PML_8",
  "end_criteria_db": -40,
  "palace": {"order": 2, "elements_per_wavelength": 6, "adaptive_tol": 1e-3, "absorbing_order": 1, "processes": 4}
}
```
| Setting | Used by | Meaning |
|---|---|---|
| `solver` | both | `"openems"` or `"palace"` |
| `sweep` | both | start/stop as Hz expressions, `points` |
| `fields_at` | both | E-field plot frequencies (Hz); `[]` = no field plot (Analysis tab: "Plot E-field") |
| `mesh.cells_per_wavelength`, `mesh.ratio` | openEMS | grid density (20; 15 for quick checks) and grading |
| `absorber`, `end_criteria_db`, `max_timesteps` | openEMS | `PML_8` / `MUR`; energy decay to stop at (−40 dB) |
| `palace.elements_per_wavelength` | Palace (via the build) | max tetra size λ/N at the stop frequency in the densest dielectric |
| `palace.order` | Palace | finite element order (2) |
| `palace.adaptive_tol` | Palace | adaptive fast sweep tolerance (1e-3); 0 solves every point |
| `palace.absorbing_order` | Palace | 1st/2nd order absorbing boundary on `bc:radiation` |
| `palace.processes` | Palace | MPI ranks (≤ CPU cores) |
| `palace.field_points` | Palace | E-field probe grid, points along the model's longest side (40) |

Materials: built-in `air FR4 RO4003C RO4350B RO5880 RO4450F TLY5 PTFE` (`backend/engine.py`
`MATERIAL_LIBRARY`); anything else goes in project `"materials": {"Name": {"epsr": "..", "tand": ".."}}`
(take values from the paper/datasheet). Metals (`PEC`, `copper`) are perfect conductors in both.

### Choosing and running a solver
- Use the solver the user asks for. Otherwise default to openEMS: on `patch_inset_2p4ghz` it ran in
  75 s vs Palace's 196 s. Suggest Palace for curved or tilted geometry (exact on the tetra mesh, no
  staircasing) and narrowband / high-Q structures. Both give the E-field plot.
- Run `PY scripts/simulate.py projects/<name>.json` (uses `simulation.solver`; minutes; prints the solver,
  mesh size, runtime, S11 minimum and −10 dB band, Z at f0). If it prints `cannot simulate:`, fix each
  listed problem (the same list appears in the app's Validation Check).
- Check the resonance against the target and |S11| < −10 dB; if the resonance is off, rescale the
  resonant dimension (≈ 1/f) in `variables` and re-run. Report the numbers you got, not the design
  targets. Results land in `out/sims/<name>/`; the app's Results tab picks them up.
- Cross-check when the user wants confidence: run both solvers on the same file and compare. Expect
  resonances within a few percent (patch template: openEMS 2.308 GHz, Palace 2.276 GHz). Deep S11
  nulls differ much more (−35 vs −16 dB there), so compare frequencies and bands, not null depths.

### Solver specifics (reference)
- openEMS (`backend/openems_sim.py`, `tools/openEMS`): rectilinear grid from CAD feature lines,
  smoothed to `cells_per_wavelength`; ≥ 3 cells across every feature gap; one run per excited port.
- Palace (`backend/palace_sim.py`, `tools/palace`, Linux/macOS only): reads `out/<name>.palace.msh`
  (Gmsh 2.2, written by the build only when `solver` is `palace`; MFEM rejects the 4.1 `.msh`).
  Metal volumes are left out of that mesh (holes whose skin is `bc:PEC`); meshed PEC interiors make
  Palace abort with "Required mesh-end tag not found".
  Physical groups map to attributes: `mat:*` → domains, `bc:PEC` → PEC, `bc:radiation` → absorbing,
  `port:N` → lumped port N. One run excites every port in turn. With `fields_at`, a second short run
  solves only those frequencies (first excited port) and probes E on a uniform grid of
  `palace.field_points` along the longest side; fields are rescaled to the overlay's convention
  (peak, 1 W incident: Palace's own excitation is V_inc = √(R·1 W), read from `port-V.csv`). The grid
  is uniform, so features thinner than its spacing (substrates, gaps) are not resolved in the plot;
  raise `field_points` for those. To change only the plot density after a run (no new sweep, project
  file untouched): the overlay's "Grid density" + "Recompute field", or
  `PY scripts/simulate.py projects/<name>.json --fields-only --field-points N`.

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
     Both solvers put this model's resonance ~4 % low on FR4; expect to retune `L`.
   - Inset feed: `y0 = L/pi*acos(sqrt(Z0/Rin_edge))`, where the edge resistance is estimated from
     `G1 = W/(120*lambda0)` (for W < λ0): `Rin_edge ≈ 1/(2*G1)`.
   - 50 Ω microstrip width: Hammerstad/Wheeler synthesis (`A`/`B` formulas).
   - Dipole: total length ≈ 0.48 λ, with a small feed gap.
   - Air box padding ≥ λ/4 at the lowest frequency from any metal (`pad` variable).
3. Follow "Model rules that keep a project valid for both solvers": axis-aligned `airbox` with the
   `radiation` boundary, axis-aligned sheets, known materials, no `mesh_size`.
4. **Assign the correct port(s) for this design's feed** (table in "Lumped ports") and add the full
   `simulation` block above (sweep around the target band, `fields_at` the centre frequency).
5. Run `PY scripts/build.py projects/<name>.json --render`, read the summary
   (objects, groups, **Ports: every port must be OK**, warnings), and look at `out/<name>_top.png`,
   `_front.png` and `_iso.png`. The groups must include `bc:radiation`, every `port:<n>`, and a `mat:`
   group per material. Fix errors, warnings and mismatches until it builds cleanly and matches the
   request.
6. Simulate with the chosen solver (`PY scripts/simulate.py projects/<name>.json`) and check the
   resonance/match (see "Choosing and running a solver"); retune if needed.
7. Tell the user the key dimensions (mm), the port you chose and why, the solver and the simulated
   numbers, anything that limits the model to one solver, and every assumption. The running app picks
   the file up automatically.
