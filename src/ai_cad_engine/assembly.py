"""Assemblies built by connecting component ports.

A Port is a connection frame on a component, in the component's local
coordinates: origin at the center of the connecting face, `direction` pointing
OUT of the part, and `x_dir` a reference direction in the face (for flanges: a
centerline the bolt holes straddle). Connecting port B to port A places B so
the two frames coincide face to face (B's direction opposite A's), with an
optional clocking rotation about the shared axis.

Butt-weld connections carry a root gap: the mating faces are separated by
`gap` along the shared axis (the weld fills it). Face-to-face lengths therefore
include the gaps, and pipe cut lengths must subtract them.

Ports are declarations by the component builder, so `validate_ports` checks
each one against the geometry: the origin must be the center of a planar face
whose outward normal is `direction`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from itertools import combinations
from math import cos, radians, sin
from pathlib import Path

from OCP.gp import gp_Dir, gp_Pnt
from build123d import Compound, GeomType, Location, Plane, Solid, Unit, Vector, export_step

POS_TOL = 1e-4  # mm
ANG_TOL = 1e-6  # |1 - cos| for direction checks


@dataclass(frozen=True)
class Port:
    origin: tuple[float, float, float]
    direction: tuple[float, float, float]
    x_dir: tuple[float, float, float] = (1, 0, 0)
    end: str = ""  # connection type, e.g. "BW" (butt weld), "RF" (raised-face flange)
    attrs: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def plane(self) -> Plane:
        return Plane(origin=self.origin, x_dir=self.x_dir, z_dir=self.direction)

    def moved(self, loc: Location) -> Port:
        t = loc.wrapped.Transformation()
        o = gp_Pnt(*self.origin).Transformed(t)
        d = gp_Dir(*self.direction).Transformed(t)
        x = gp_Dir(*self.x_dir).Transformed(t)
        return Port(
            (o.X(), o.Y(), o.Z()), (d.X(), d.Y(), d.Z()), (x.X(), x.Y(), x.Z()), self.end, self.attrs
        )


@dataclass
class Component:
    tag: str  # instance tag on the drawing / BOM, e.g. "F1"
    part_no: str
    description: str
    solid: Solid  # in component-local coordinates
    ports: dict[str, Port]
    meta: dict = field(default_factory=dict)


@dataclass
class Placed:
    comp: Component
    loc: Location

    @property
    def solid(self) -> Solid:
        s = self.loc * self.comp.solid
        s.label = self.comp.tag
        return s

    def port(self, name: str) -> Port:
        return self.comp.ports[name].moved(self.loc)


def validate_ports(comp: Component) -> list[str]:
    """Each port origin must be the center of a planar face with outward normal = direction."""
    problems = []
    for name, p in comp.ports.items():
        o, d = Vector(p.origin), Vector(p.direction).normalized()
        ok = False
        for f in comp.solid.faces().filter_by(GeomType.PLANE):
            n = f.normal_at()
            if n.dot(d) < 1 - ANG_TOL or abs((o - f.center()).dot(n)) > POS_TOL:
                continue
            # origin in the face plane; require it at the face's (annulus/disc) center
            if (Vector(f.center()) - o).length < POS_TOL or _center_of_circles(f, o):
                ok = True
                break
        if not ok:
            problems.append(f"{comp.tag}.{name}: no planar face centered at port with matching normal")
    return problems


def _center_of_circles(face, o: Vector) -> bool:
    circles = [e for e in face.edges() if e.geom_type == GeomType.CIRCLE]
    return bool(circles) and all((Vector(e.arc_center) - o).length < POS_TOL for e in circles)


@dataclass(frozen=True)
class Connection:
    a: str  # "TAG.port"
    b: str
    gap: float = 0.0  # mm between the mating faces (butt-weld root gap)


class Assembly:
    def __init__(self, name: str):
        self.name = name
        self.placed: dict[str, Placed] = {}
        self.connections: list[Connection] = []

    def add_root(self, comp: Component, port: str, at: Plane) -> Placed:
        """Place `comp` so its `port` frame lands on plane `at` (origin, x_dir, z_dir=out)."""
        return self._put(comp, at.location * comp.ports[port].plane.location.inverse())

    def connect(
        self,
        comp: Component,
        port: str,
        to: str,
        clock_deg: float = 0.0,
        gap: float = 0.0,
        align_x: tuple[float, float, float] | None = None,
    ) -> Placed:
        """Place `comp` so its `port` mates face-to-face with placed port `to` ("TAG.port"),
        `gap` mm apart along the shared axis (butt-weld root gap; must be 0 for other ends).

        Orientation about the axis: the new port's x_dir follows the target's x_dir rotated by
        `clock_deg`, or, if `align_x` is given, points along that world direction (projected into
        the face plane) — e.g. an eccentric reducer's flat side straight down."""
        tag, pname = to.split(".")
        target = self.placed[tag].port(pname)
        if gap and (target.end != "BW" or comp.ports[port].end != "BW"):
            raise ValueError(f"root gap only applies to butt-weld ends ({to} / {comp.tag}.{port})")
        if gap < 0:
            raise ValueError("negative gap")
        z = Vector(target.direction) * -1
        x = Vector(target.x_dir)
        if align_x is not None:
            a = Vector(align_x)
            zn = z.normalized()
            x = a - zn * a.dot(zn)
            if x.length < 1e-9:
                raise ValueError("align_x is parallel to the connection axis")
            x = x.normalized()
        if clock_deg:  # rotate x_dir about the shared axis (Rodrigues; x is perpendicular to z)
            a = radians(clock_deg)
            x = x * cos(a) + z.normalized().cross(x) * sin(a)
        origin = Vector(target.origin) + Vector(target.direction).normalized() * gap
        mate = Plane(origin=origin, x_dir=x, z_dir=z)
        placed = self._put(comp, mate.location * comp.ports[port].plane.location.inverse())
        self.connections.append(Connection(to, f"{comp.tag}.{port}", gap))
        return placed

    def _put(self, comp: Component, loc: Location) -> Placed:
        if comp.tag in self.placed:
            raise ValueError(f"duplicate tag {comp.tag}")
        self.placed[comp.tag] = Placed(comp, loc)
        return self.placed[comp.tag]

    def port(self, ref: str) -> Port:
        tag, pname = ref.split(".")
        return self.placed[tag].port(pname)

    # ---- checks ----

    def connection_errors(self) -> list[str]:
        """Mated ports are coaxial, face each other, sit exactly `gap` apart, and have
        compatible ends."""
        errs = []
        for c in self.connections:
            pa, pb = self.port(c.a), self.port(c.b)
            expected = Vector(pa.origin) + Vector(pa.direction).normalized() * c.gap
            off = (Vector(pb.origin) - expected).length
            if off > POS_TOL:
                errs.append(f"{c.a} / {c.b}: faces not {c.gap:.4f} mm apart on axis (off by {off:.4f} mm)")
            if Vector(pa.direction).dot(Vector(pb.direction)) > -1 + ANG_TOL:
                errs.append(f"{c.a} / {c.b}: not face to face")
            if pa.end != pb.end:
                errs.append(f"{c.a} / {c.b}: end types {pa.end} vs {pb.end}")
            for k in ("od", "id"):  # butt-weld ends must match OD and ID (no step at the weld)
                if pa.end == "BW" and abs(pa.attrs.get(k, 0) - pb.attrs.get(k, 0)) > POS_TOL:
                    errs.append(
                        f"{c.a} / {c.b}: weld-end {k.upper()} mismatch "
                        f"{pa.attrs.get(k):.3f} vs {pb.attrs.get(k):.3f} mm"
                    )
        return errs

    def interferences(self, tol_mm3: float = 1e-3) -> list[str]:
        out = []
        for (ta, a), (tb, b) in combinations(self.placed.items(), 2):
            common = a.solid.intersect(b.solid)
            if common is None:
                vol = 0.0
            elif hasattr(common, "volume"):
                vol = common.volume
            else:  # ShapeList of pieces
                vol = sum(s.volume for s in common)
            if vol > tol_mm3:
                out.append(f"{ta} / {tb}: {vol:.3f} mm^3")
        return out

    # ---- outputs ----

    def compound(self) -> Compound:
        return Compound(children=[p.solid for p in self.placed.values()], label=self.name)

    def export_step(self, path: Path) -> None:
        export_step(self.compound(), path, unit=Unit.MM)

    def unverified(self) -> list[str]:
        """Tags of components built from table rows not verified against the standard."""
        return [t for t, p in self.placed.items() if not p.comp.meta.get("verified", True)]

    def bom(self) -> list[dict]:
        rows: dict[str, dict] = {}
        for p in self.placed.values():
            c = p.comp
            r = rows.setdefault(c.part_no, {"part_no": c.part_no, "description": c.description, "qty": 0, "tags": []})
            r["qty"] += 1
            r["tags"].append(c.tag)
        return [dict(r, item=i, tags=" ".join(r["tags"])) for i, r in enumerate(rows.values(), 1)]

    def gaps(self) -> list[tuple[str, str, float]]:
        """Measured distance between mated butt-weld faces, from the placed ports."""
        out = []
        for c in self.connections:
            pa, pb = self.port(c.a), self.port(c.b)
            if pa.end == "BW":
                out.append((c.a, c.b, (Vector(pb.origin) - Vector(pa.origin)).dot(Vector(pa.direction).normalized())))
        return out

    def write_bom_csv(self, path: Path) -> None:
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["item", "qty", "part_no", "description", "tags"])
            w.writeheader()
            for r in self.bom():
                w.writerow({k: r[k] for k in w.fieldnames})


def bolt_hole_angles(placed: Placed, axis_port: str, ref_dir: Vector) -> list[float]:
    """Angles (deg, 0..360) of bolt holes of a placed flange about its axis, measured from
    ref_dir projected into the flange face plane. Measured on geometry, not from the table."""
    from math import atan2, degrees

    p = placed.port(axis_port)
    z = Vector(p.direction).normalized()
    x = (ref_dir - z * ref_dir.dot(z)).normalized()
    y = z.cross(x)
    o = Vector(p.origin)
    angles = []
    for f in placed.solid.faces().filter_by(GeomType.CYLINDER):
        ax = f.axis_of_rotation
        if abs(abs(ax.direction.dot(z)) - 1) > 1e-6:
            continue
        v = ax.position - o
        v = v - z * v.dot(z)
        if v.length < 1e-3:
            continue  # on the flange axis (bore / OD / RF)
        angles.append(degrees(atan2(v.dot(y), v.dot(x))) % 360)
    return sorted({round(a, 6) for a in angles})
