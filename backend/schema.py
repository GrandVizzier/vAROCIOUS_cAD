"""Project JSON schema. Numeric fields are expression strings (see expr.py)."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Expr = Union[str, float]
Vec3 = Annotated[list[Expr], Field(min_length=3, max_length=3)]
Vec2 = Annotated[list[Expr], Field(min_length=2, max_length=2)]
Plane = Literal["XY", "YZ", "XZ"]


class Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Box(Op):
    op: Literal["box"]
    name: str
    origin: Vec3
    size: Vec3
    material: str = "air"


class Cylinder(Op):
    op: Literal["cylinder"]
    name: str
    origin: Vec3            # base center
    axis: Vec3              # direction and length
    radius: Expr
    material: str = "air"


class Sphere(Op):
    op: Literal["sphere"]
    name: str
    center: Vec3
    radius: Expr
    material: str = "air"


class Rectangle(Op):
    op: Literal["rectangle"]
    name: str
    origin: Vec3
    size: Vec2              # XY: (dx, dy)  XZ: (dx, dz)  YZ: (dy, dz)
    plane: Plane = "XY"
    material: str = "PEC"


class Disk(Op):
    op: Literal["disk"]
    name: str
    center: Vec3
    radius: Expr
    plane: Plane = "XY"
    material: str = "PEC"


class Translate(Op):
    op: Literal["translate"]
    target: str
    vector: Vec3


class Rotate(Op):
    op: Literal["rotate"]
    target: str
    origin: Vec3 = ["0", "0", "0"]
    axis: Vec3
    angle: Expr             # degrees


class Boolean(Op):
    op: Literal["unite", "subtract", "intersect"]
    object: str
    tools: Annotated[list[str], Field(min_length=1)]
    name: str | None = None  # result name; defaults to `object`


Step = Annotated[Union[Box, Cylinder, Sphere, Rectangle, Disk, Translate, Rotate, Boolean],
                 Field(discriminator="op")]
PRIMITIVES = (Box, Cylinder, Sphere, Rectangle, Disk)


class Boundary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["radiation", "PEC", "floquet", "master1", "slave1", "master2", "slave2"]
    target: str             # object name, or "*" for all volumes
    # outer: target faces on the model's outer boundary; all: whole target boundary;
    # +x/-x/...: outer target faces lying on that side of the model's bounding box
    faces: Literal["outer", "all", "+x", "-x", "+y", "-y", "+z", "-z"] = "outer"


class Port(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str             # name of a flat, axis-aligned sheet bridging two conductors
    type: Literal["lumped"] = "lumped"
    impedance: Expr = "50"  # ohm
    direction: Literal["+x", "-x", "+y", "-y", "+z", "-z"] = "+z"  # in the sheet, metal to metal
    excite: bool = True


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid")
    epsr: Expr = "1"
    tand: Expr = "0"


class Sweep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: Expr             # Hz
    stop: Expr              # Hz
    points: Annotated[int, Field(ge=2, le=10001)] = 401


class MeshSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cells_per_wavelength: Annotated[int, Field(ge=6, le=100)] = 20
    ratio: Annotated[float, Field(ge=1.05, le=2.0)] = 1.4


class Simulation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solver: Literal["openems"] = "openems"
    sweep: Sweep
    fields_at: list[Expr] = []          # Hz; frequencies for E/H field snapshots
    mesh: MeshSettings = MeshSettings()
    absorber: Literal["PML_8", "MUR"] = "PML_8"
    end_criteria_db: Annotated[float, Field(le=-10, ge=-80)] = -40
    max_timesteps: Annotated[int, Field(ge=1000)] = 300000


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    units: Literal["m", "cm", "mm", "um"] = "mm"
    description: str = ""
    variables: dict[str, Expr] = {}
    history: Annotated[list[Step], Field(min_length=1)]
    boundaries: list[Boundary] = []
    ports: list[Port] = []
    materials: dict[str, Material] = {}  # overrides/additions to the built-in library
    simulation: Simulation | None = None

    @model_validator(mode="after")
    def unique_names(self):
        seen = set()
        for i, s in enumerate(self.history):
            name = getattr(s, "name", None)
            if isinstance(s, PRIMITIVES) and name in seen:
                raise ValueError(f"history[{i}]: duplicate object name '{name}'")
            if name:
                seen.add(name)
        return self


UNIT_SCALE = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6}


def format_validation_error(e: ValidationError) -> str:
    lines = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return "invalid project: " + "; ".join(lines)
