"""Measurements on built solids, used by tests and (later) the verification loop."""

from dataclasses import dataclass
from math import hypot

from build123d import GeomType, Shape


@dataclass(frozen=True)
class CylHole:
    dia: float
    x: float
    y: float

    @property
    def radial_pos(self) -> float:
        return hypot(self.x, self.y)


def z_axis_cylinders(shape: Shape, tol: float = 1e-6) -> list[CylHole]:
    """All cylindrical faces whose axis is parallel to Z, deduplicated by axis position + dia."""
    found: list[CylHole] = []
    for face in shape.faces().filter_by(GeomType.CYLINDER):
        axis = face.axis_of_rotation
        if abs(abs(axis.direction.Z) - 1) > tol:
            continue
        c = CylHole(dia=2 * face.radius, x=axis.position.X, y=axis.position.Y)
        if not any(
            abs(c.dia - h.dia) < 1e-4 and hypot(c.x - h.x, c.y - h.y) < 1e-4
            for h in found
        ):
            found.append(c)
    return found
