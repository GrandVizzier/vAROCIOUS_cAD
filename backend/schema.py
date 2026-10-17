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
    type: Literal["radiation", "PEC"]
    target: str
    faces: Literal["outer", "all"] = "outer"


class Port(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str             # name of a sheet object


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    units: Literal["m", "cm", "mm", "um"] = "mm"
    description: str = ""
    variables: dict[str, Expr] = {}
    history: Annotated[list[Step], Field(min_length=1)]
    boundaries: list[Boundary] = []
    ports: list[Port] = []

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
