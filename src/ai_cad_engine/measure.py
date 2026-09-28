"""Measurements on built solids, used by tests and the verification report.

Helpers here are generic (Z-axis-aligned features). Part families combine them
to measure their critical dimensions by role.
"""

from dataclasses import dataclass
from math import atan2, degrees, hypot

from build123d import GeomType, Shape

_TOL = 1e-6


@dataclass(frozen=True)
class CylHole:
    """Cylindrical face with axis parallel to Z."""

    dia: float
    x: float
    y: float
    z_min: float = 0.0
    z_max: float = 0.0

    @property
    def radial_pos(self) -> float:
        return hypot(self.x, self.y)

    @property
    def angle_deg(self) -> float:
        return degrees(atan2(self.y, self.x)) % 360


@dataclass(frozen=True)
class ZPlane:
    """Planar face normal to Z."""

    z: float
    outer_dia: float


@dataclass(frozen=True)
class ZCone:
    """Conical face on the Z axis: (z, dia) at each end."""

    ends: tuple[tuple[float, float], tuple[float, float]]


def z_axis_cylinders(shape: Shape, tol: float = 1e-6) -> list[CylHole]:
    """All cylindrical faces whose axis is parallel to Z, deduplicated by axis position + dia."""
    found: list[CylHole] = []
    for face in shape.faces().filter_by(GeomType.CYLINDER):
        axis = face.axis_of_rotation
        if abs(abs(axis.direction.Z) - 1) > tol:
            continue
        bb = face.bounding_box()
        c = CylHole(
            dia=2 * face.radius,
            x=axis.position.X,
            y=axis.position.Y,
            z_min=bb.min.Z,
            z_max=bb.max.Z,
        )
        if not any(
            abs(c.dia - h.dia) < 1e-4 and hypot(c.x - h.x, c.y - h.y) < 1e-4 for h in found
        ):
            found.append(c)
    return found


def z_planes(shape: Shape) -> list[ZPlane]:
    out = []
    for face in shape.faces().filter_by(GeomType.PLANE):
        bb = face.bounding_box()
        if bb.size.Z < _TOL:
            out.append(ZPlane(z=bb.min.Z, outer_dia=max(bb.size.X, bb.size.Y)))
    return out


def z_cones(shape: Shape) -> list[ZCone]:
    out = []
    for face in shape.faces().filter_by(GeomType.CONE):
        circles = [e for e in face.edges() if e.geom_type == GeomType.CIRCLE]
        if len(circles) != 2:
            continue
        a, b = sorted(((e.center().Z, 2 * e.radius) for e in circles))
        out.append(ZCone(ends=(a, b)))
    return out
