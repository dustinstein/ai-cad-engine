"""Orthographic projected views with hidden-line removal.

Each view's 2D coordinates are the model coordinates projected onto the view
plane (the camera looks at the model origin), so view -> model is a pure
axis mapping with no offset or scale. Layout offsets are applied later.

HLR output is normalised into simple primitives (Line/Circle/Arc, Polyline as
a last resort) so downstream DXF writing and dimensioning never see OCP types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, degrees, hypot

from build123d import Edge, GeomType, Shape, Vector

TOL = 1e-4  # geometric classification / dedupe tolerance, in the view's units
_SAMPLES = 9


@dataclass(frozen=True)
class Line:
    p1: tuple[float, float]
    p2: tuple[float, float]


@dataclass(frozen=True)
class Circle:
    center: tuple[float, float]
    radius: float


@dataclass(frozen=True)
class Arc:
    """CCW from start_angle to end_angle, degrees (DXF convention)."""

    center: tuple[float, float]
    radius: float
    start_angle: float
    end_angle: float


@dataclass(frozen=True)
class Polyline:
    points: tuple[tuple[float, float], ...]


Prim = Line | Circle | Arc | Polyline


@dataclass(frozen=True)
class ViewSpec:
    name: str
    toward_viewer: tuple[float, float, float]  # unit vector from model to eye
    up: tuple[float, float, float]


# Z-up model, third-angle projection (ASME Y14.3).
FRONT = ViewSpec("FRONT", (0, -1, 0), (0, 0, 1))
TOP = ViewSpec("TOP", (0, 0, 1), (0, 1, 0))
RIGHT = ViewSpec("RIGHT", (1, 0, 0), (0, 0, 1))


@dataclass
class View:
    spec: ViewSpec
    visible: list[Prim] = field(default_factory=list)
    hidden: list[Prim] = field(default_factory=list)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for p in self.visible + self.hidden:
            for x, y in _extent_points(p):
                xs.append(x)
                ys.append(y)
        return min(xs), min(ys), max(xs), max(ys)


def project(shape: Shape, spec: ViewSpec) -> View:
    eye = Vector(spec.toward_viewer) * 10_000
    vis, hid = shape.project_to_viewport(eye, spec.up, look_at=(0, 0, 0))
    visible = _clean([_to_prim(e) for e in vis if e.length >= TOL])
    hidden = _clean([_to_prim(e) for e in hid if e.length >= TOL])
    # HLR can emit a hidden edge exactly under a visible one; drop those.
    hidden = [p for p in hidden if not any(_covers(v, p) for v in visible)]
    return View(spec, visible, hidden)


def _clean(prims: list[Prim]) -> list[Prim]:
    """Merge collinear touching/overlapping lines (HLR splits at seams) and drop duplicates."""
    lines = [p for p in prims if isinstance(p, Line)]
    out: list[Prim] = []
    for p in prims:
        if not isinstance(p, Line) and not any(_covers(q, p) for q in out):
            out.append(p)
    return _merge_lines(lines) + out


def _merge_lines(lines: list[Line]) -> list[Line]:
    groups: list[tuple[Line, list[tuple[float, float]]]] = []  # (reference, intervals)
    for ln in lines:
        for ref, ivs in groups:
            if _collinear_lines(ref, ln):
                ivs.append(_interval(ref, ln))
                break
        else:
            groups.append((ln, [_interval(ln, ln)]))
    merged: list[Line] = []
    for ref, ivs in groups:
        ivs.sort()
        cur = list(ivs[0])
        spans = []
        for a, b in ivs[1:]:
            if a <= cur[1] + TOL:
                cur[1] = max(cur[1], b)
            else:
                spans.append(cur)
                cur = [a, b]
        spans.append(cur)
        merged += [Line(_at(ref, a), _at(ref, b)) for a, b in spans]
    return merged


def _unit(ln: Line) -> tuple[float, float, float]:
    dx, dy = ln.p2[0] - ln.p1[0], ln.p2[1] - ln.p1[1]
    n = hypot(dx, dy)
    return dx / n, dy / n, n


def _dist_to_inf_line(ref: Line, pt: tuple[float, float]) -> float:
    ux, uy, _ = _unit(ref)
    return abs((pt[0] - ref.p1[0]) * uy - (pt[1] - ref.p1[1]) * ux)


def _collinear_lines(ref: Line, ln: Line) -> bool:
    return _dist_to_inf_line(ref, ln.p1) < TOL and _dist_to_inf_line(ref, ln.p2) < TOL


def _param(ref: Line, pt: tuple[float, float]) -> float:
    ux, uy, _ = _unit(ref)
    return (pt[0] - ref.p1[0]) * ux + (pt[1] - ref.p1[1]) * uy


def _interval(ref: Line, ln: Line) -> tuple[float, float]:
    a, b = _param(ref, ln.p1), _param(ref, ln.p2)
    return (min(a, b), max(a, b))


def _at(ref: Line, t: float) -> tuple[float, float]:
    ux, uy, _ = _unit(ref)
    return (ref.p1[0] + t * ux, ref.p1[1] + t * uy)


def _same_pt(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return hypot(a[0] - b[0], a[1] - b[1]) < TOL


def _covers(big: Prim, small: Prim) -> bool:
    """True if `small` lies entirely on `big`."""
    if isinstance(big, Line) and isinstance(small, Line):
        if not _collinear_lines(big, small):
            return False
        a, b = _interval(big, small)
        return a > -TOL and b < _unit(big)[2] + TOL
    if isinstance(big, (Circle, Arc)) and isinstance(small, (Circle, Arc)):
        if not (_same_pt(big.center, small.center) and abs(big.radius - small.radius) < TOL):
            return False
        if isinstance(big, Circle):
            return True
        if isinstance(small, Circle):
            return False
        sweep = (big.end_angle - big.start_angle) % 360
        return (
            (small.start_angle - big.start_angle) % 360 <= sweep + 1e-6
            and (small.end_angle - big.start_angle) % 360 <= sweep + 1e-6
        )
    if isinstance(big, Polyline) and isinstance(small, Polyline):
        return len(big.points) == len(small.points) and all(
            _same_pt(a, b) for a, b in zip(big.points, small.points)
        )
    return False


def _xy(v: Vector) -> tuple[float, float]:
    return (v.X, v.Y)


def _samples(e: Edge) -> list[Vector]:
    return [e.position_at(i / (_SAMPLES - 1)) for i in range(_SAMPLES)]


def _to_prim(e: Edge) -> Prim:
    if e.geom_type == GeomType.LINE:
        return Line(_xy(e.start_point()), _xy(e.end_point()))
    if e.geom_type == GeomType.CIRCLE:
        return _arc_or_circle(_xy(e.arc_center), e.radius, e)
    pts = _samples(e)
    if _collinear(pts):
        return Line(_xy(pts[0]), _xy(pts[-1]))
    fit = _circle_fit(pts)
    if fit is not None:
        return _arc_or_circle(fit[0], fit[1], e)
    n = max(16, int(e.length / 0.5))  # ~0.5 mm segments; exact types preferred above
    return Polyline(tuple(_xy(e.position_at(i / n)) for i in range(n + 1)))


def _arc_or_circle(c: tuple[float, float], r: float, e: Edge) -> Circle | Arc:
    if e.is_closed:
        return Circle(c, r)
    a0, am, a1 = (
        degrees(atan2(p.Y - c[1], p.X - c[0])) % 360
        for p in (e.position_at(0), e.position_at(0.5), e.position_at(1))
    )
    # Pick the CCW direction that passes through the midpoint.
    if (am - a0) % 360 < (a1 - a0) % 360:
        return Arc(c, r, a0, a1)
    return Arc(c, r, a1, a0)


def _collinear(pts: list[Vector]) -> bool:
    a, b = pts[0], pts[-1]
    d = b - a
    ln = d.length
    if ln < TOL:
        return False
    return all(abs(d.cross(p - a).Z) / ln < TOL for p in pts)


def _circle_fit(pts: list[Vector]) -> tuple[tuple[float, float], float] | None:
    (x1, y1), (x2, y2), (x3, y3) = (_xy(pts[0]), _xy(pts[len(pts) // 2]), _xy(pts[-1]))
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return None
    s1, s2, s3 = x1**2 + y1**2, x2**2 + y2**2, x3**2 + y3**2
    cx = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    cy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    r = hypot(x1 - cx, y1 - cy)
    if all(abs(hypot(p.X - cx, p.Y - cy) - r) < TOL for p in pts):
        return (cx, cy), r
    return None


def _extent_points(p: Prim) -> list[tuple[float, float]]:
    if isinstance(p, Line):
        return [p.p1, p.p2]
    if isinstance(p, Polyline):
        return list(p.points)
    (cx, cy), r = p.center, p.radius
    if isinstance(p, Circle):
        return [(cx - r, cy - r), (cx + r, cy + r)]
    # Arc: endpoints plus any quadrant points it sweeps through.
    from math import cos, radians, sin

    angs = [p.start_angle, p.end_angle]
    sweep = (p.end_angle - p.start_angle) % 360
    angs += [q for q in (0, 90, 180, 270) if (q - p.start_angle) % 360 <= sweep]
    return [(cx + r * cos(radians(a)), cy + r * sin(radians(a))) for a in angs]


def scale_view(view: View, k: float) -> View:
    """Uniformly scale a view's 2D geometry (e.g. k = 1/25.4 for mm -> inch)."""

    def pt(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0] * k, p[1] * k)

    def sc(p: Prim) -> Prim:
        if isinstance(p, Line):
            return Line(pt(p.p1), pt(p.p2))
        if isinstance(p, Circle):
            return Circle(pt(p.center), p.radius * k)
        if isinstance(p, Arc):
            return Arc(pt(p.center), p.radius * k, p.start_angle, p.end_angle)
        return Polyline(tuple(pt(q) for q in p.points))

    return View(view.spec, [sc(p) for p in view.visible], [sc(p) for p in view.hidden])
