"""Generic annotation helpers: dimstyle, centerlines, tagged DIMENSION entities,
and role-based feature finders shared by part families.

Dimension defpoints are snapped to features found in the projected geometry
by *role* (largest circle, off-axis circles, view extents, faces), never to
table values. The DXF DIMENSION therefore reports what was actually drawn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, hypot, radians, sin

import ezdxf.document

from ai_cad_engine.drawing.views import TOL, Circle, View
from ai_cad_engine.verify import tag_dimension

DIMSTYLE = "ENGINE_IN"
CL_OVERSHOOT = 0.125  # paper inches: centerline extension past the feature
TEXT_H = 0.125  # paper inches (dimtxt)
CHAR_W_EST = 1.05  # conservative glyph advance / text height (rendered fonts run ~1.0)
TEXT_CLEAR = 0.1  # paper inches between text and extension line when text goes outside
HALF_DIM = {"dimsd2": 1, "dimse2": 1, "dimsah": 1, "dimblk1": "", "dimblk2": "NONE"}


def setup(doc: ezdxf.document.Drawing, scale: float) -> None:
    doc.layers.add("CENTER", color=1, linetype="CENTER", lineweight=25)
    doc.layers.add("DIM", color=3, lineweight=25)
    # Own style: ezdxf's EZ_* styles are scaled for other units (e.g. EZ_RADIUS shows 20 mm as 2000).
    # ASME Y14.5 inch conventions: 3 decimals, no leading zero (.750), horizontal text.
    style = doc.dimstyles.new(DIMSTYLE)
    style.dxf.dimtxt = 0.125  # paper text height
    style.dxf.dimasz = 0.125
    style.dxf.dimexo = 0.0625
    style.dxf.dimexe = 0.125
    style.dxf.dimgap = 0.0625
    style.dxf.dimscale = scale  # all of the above are paper sizes
    style.dxf.dimlunit = 2  # decimal
    style.dxf.dimdec = 3
    style.dxf.dimzin = 4  # suppress leading zero
    style.dxf.dimlfac = 1.0
    style.dxf.dimtad = 0  # text centered in the (broken) dimension line
    style.dxf.dimtih = 1
    style.dxf.dimtoh = 1
    style.dxf.dimtofl = 0  # diameter dims with text outside: leader only, no line through center
    style.dxf.dimdsep = ord(".")
    style.dxf.dimblk = ""  # closed filled arrows


Pt = tuple[float, float]


@dataclass
class Annotator:
    """Adds centerlines and tagged dimensions in model space; lengths given in paper inches
    are multiplied by the scale S. Collects entities per view for DXF groups."""

    doc: ezdxf.document.Drawing
    S: float
    groups: dict[str, list] = field(default_factory=dict)

    def __post_init__(self):
        setup(self.doc, self.S)
        self.msp = self.doc.modelspace()

    def _keep(self, view: str, e):
        self.groups.setdefault(view, []).append(e)
        return e

    def centerline(self, view: str, p1: Pt, p2: Pt):
        return self._keep(view, self.msp.add_line(p1, p2, dxfattribs={"layer": "CENTER"}))

    def circle_centerline(self, view: str, c: Pt, r: float):
        return self._keep(view, self.msp.add_circle(c, r, dxfattribs={"layer": "CENTER"}))

    def linear(
        self,
        view: str,
        key: str,
        p1: Pt,
        p2: Pt,
        base: Pt,
        angle: float,
        text: str = "<>",
        location: Pt | None = None,
        override: dict | None = None,
    ):
        if location is None:
            location = self._outside_text_location(p1, p2, base, angle, text, override)
        d = self.msp.add_linear_dim(
            base=base,
            p1=p1,
            p2=p2,
            angle=angle,
            text=text,
            location=location,
            dimstyle=DIMSTYLE,
            override=override,
            dxfattribs={"layer": "DIM"},
        )
        d.render()
        tag_dimension(d.dimension, key)
        return self._keep(view, d.dimension)

    def _outside_text_location(self, p1: Pt, p2: Pt, base: Pt, angle: float, text: str, override) -> Pt | None:
        """Explicit text position (ezdxf's own placement shifts some vertical-dim texts off
        the dimension line): centered on the dimension line when it fits between the
        extension lines, otherwise outside, before p1 (the lower/left one)."""
        if override:  # half dims etc. place their own text
            return None
        horizontal = abs(angle) < 1e-9
        i = 0 if horizontal else 1
        span = abs(p2[i] - p1[i])
        shown = text.replace("<>", fmt_inch(span)).replace("%%c", "X")
        w = len(shown) * TEXT_H * CHAR_W_EST * self.S
        extent = w if horizontal else TEXT_H * self.S  # along the dimension line
        lo = min(p1[i], p2[i])
        if extent + 2 * TEXT_CLEAR * self.S <= span:
            c = lo + span / 2
        else:
            c = lo - TEXT_CLEAR * self.S - extent / 2
        return (c, base[1]) if horizontal else (base[0], c)

    def diameter(
        self,
        view: str,
        key: str,
        c: Pt,
        r: float,
        angle_deg: float,
        out_paper: float,
        text: str = "<>",
        count_key: str | None = None,
    ):
        """Leader-style diameter dimension; text outside the circle along angle_deg."""
        a = radians(angle_deg)
        dist = r + out_paper * self.S
        loc = (c[0] + dist * cos(a), c[1] + dist * sin(a))
        d = self.msp.add_diameter_dim(
            center=c, radius=r, location=loc, text=text, dimstyle=DIMSTYLE, dxfattribs={"layer": "DIM"}
        )
        d.render()
        tag_dimension(d.dimension, key, count_key)
        return self._keep(view, d.dimension)

    def finish(self) -> None:
        for view, ents in self.groups.items():
            self.doc.groups.new(f"ANNOT_{view}").set_data(ents)


# ---- feature finding (by role) -------------------------------------------------


@dataclass(frozen=True)
class BoltPattern:
    center: Pt
    od_radius: float
    hole_radius: float
    hole_centers: list[Pt]
    bc_radius: float


def find_bolt_pattern(view: View) -> BoltPattern:
    """Largest visible circle = OD; off-center circles of one size on one circle = bolt holes."""
    circles = [p for p in view.visible if isinstance(p, Circle)]
    od = max(circles, key=lambda c: c.radius)
    cx, cy = od.center
    holes = [c for c in circles if hypot(c.center[0] - cx, c.center[1] - cy) > TOL]
    radii = {round(c.radius, 4) for c in holes}
    if len(radii) != 1:
        raise ValueError(f"expected one off-axis hole size, found radii {sorted(radii)}")
    dists = [hypot(c.center[0] - cx, c.center[1] - cy) for c in holes]
    if max(dists) - min(dists) > TOL:
        raise ValueError(f"hole centers not on one circle: {min(dists)}..{max(dists)}")
    return BoltPattern(
        center=od.center,
        od_radius=od.radius,
        hole_radius=holes[0].radius,
        hole_centers=[c.center for c in holes],
        bc_radius=sum(dists) / len(dists),
    )


def fmt_inch(v: float, dec: int = 3) -> str:
    """ASME inch format as the dimstyle renders it: fixed decimals, no leading zero."""
    t = f"{v:.{dec}f}"
    return t[1:] if t.startswith("0.") else t
