"""Core diff engine: compares the modelspace entities of two DXF documents.

Matching happens in passes, from strictest to loosest:

1. ``unchanged``  - identical geometry *and* properties.
2. ``modified``   - same handle in both files, or same geometry with
                    different properties (layer, color, linetype, ...).
3. ``moved``      - same shape (translation-invariant signature) at a
                    different position.
4. ``modified``   - (fuzzy) same type and layer with overlapping bounding
                    boxes, e.g. a wall that was shortened.
5. ``added`` / ``removed`` - everything left over.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import ezdxf
from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic

PROPS = ("layer", "color", "linetype", "lineweight", "true_color")
CHANGE_KINDS = ("added", "removed", "modified", "moved")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load(path: str | Path) -> Drawing:
    """Load a DXF file, or a DWG file when ODA File Converter is installed."""
    path = Path(path)
    if path.suffix.lower() == ".dwg":
        from ezdxf.addons import odafc

        if not odafc.is_installed():
            raise RuntimeError(
                "Reading DWG needs the free ODA File Converter "
                "(https://www.opendesign.com/guestfiles/oda_file_converter). "
                "Install it, or convert the file to DXF first."
            )
        return odafc.readfile(str(path))
    return ezdxf.readfile(str(path))


# --------------------------------------------------------------------------- #
# Signatures
# --------------------------------------------------------------------------- #
def _r(value: float, ndigits: int) -> float:
    v = round(float(value), ndigits)
    return 0.0 if v == 0 else v  # normalise -0.0


def _pt(p: Iterable[float], nd: int) -> tuple[float, ...]:
    return tuple(_r(c, nd) for c in tuple(p)[:3])


def _anchor(e: DXFGraphic) -> tuple[float, float, float] | None:
    """Reference point used to make a signature translation-invariant."""
    t = e.dxftype()
    d = e.dxf
    if t == "LINE":
        a, b = sorted([tuple(d.start), tuple(d.end)])
        return a
    if t in ("CIRCLE", "ARC", "ELLIPSE"):
        return tuple(d.center)
    if t in ("TEXT", "MTEXT", "INSERT", "ATTRIB"):
        return tuple(d.insert)
    if t == "POINT":
        return tuple(d.location)
    if t == "LWPOLYLINE":
        pts = list(e.get_points("xy"))
        return (pts[0][0], pts[0][1], 0.0) if pts else None
    return None


def geometry(e: DXFGraphic, nd: int, origin=(0.0, 0.0, 0.0)) -> tuple:
    """Hashable geometry signature, optionally relative to ``origin``."""
    t = e.dxftype()
    d = e.dxf
    ox, oy, oz = origin

    def rel(p):
        p = tuple(p) + (0.0,) * (3 - len(tuple(p)))
        return _pt((p[0] - ox, p[1] - oy, p[2] - oz), nd)

    if t == "LINE":
        return (t, *sorted([rel(d.start), rel(d.end)]))
    if t == "CIRCLE":
        return (t, rel(d.center), _r(d.radius, nd))
    if t == "ARC":
        return (t, rel(d.center), _r(d.radius, nd),
                _r(d.start_angle % 360, nd), _r(d.end_angle % 360, nd))
    if t == "ELLIPSE":
        return (t, rel(d.center), _pt(d.major_axis, nd), _r(d.ratio, nd),
                _r(d.start_param, nd), _r(d.end_param, nd))
    if t == "POINT":
        return (t, rel(d.location))
    if t == "LWPOLYLINE":
        pts = tuple((rel((x, y))[:2], _r(b, nd))
                    for x, y, b in e.get_points("xyb"))
        return (t, bool(e.closed), pts)
    if t == "TEXT":
        return (t, rel(d.insert), e.dxf.text, _r(d.get("height", 0), nd),
                _r(d.get("rotation", 0), nd))
    if t == "MTEXT":
        return (t, rel(d.insert), e.text, _r(d.get("char_height", 0), nd),
                _r(d.get("rotation", 0), nd))
    if t == "INSERT":
        attribs = tuple(sorted((a.dxf.tag, a.dxf.text) for a in e.attribs))
        return (t, d.name, rel(d.insert), _r(d.get("xscale", 1), nd),
                _r(d.get("yscale", 1), nd), _r(d.get("rotation", 0), nd),
                attribs)
    if t == "SPLINE":
        return (t, tuple(rel(p) for p in e.control_points),
                tuple(rel(p) for p in e.fit_points))
    if t == "HATCH":
        return (t, d.get("pattern_name", ""), len(e.paths),
                rel(_hatch_centroid(e)))
    if t == "DIMENSION":
        return (t, rel(d.get("defpoint", (0, 0, 0))), d.get("text", ""),
                _r(e.get_measurement() or 0, nd))
    # Fallback: all DXF attributes except handles / owners.
    attrs = {k: v for k, v in e.dxfattribs().items()
             if k not in ("handle", "owner", *PROPS)}
    return (t, tuple(sorted((k, repr(v)) for k, v in attrs.items())))


def _hatch_centroid(e) -> tuple[float, float, float]:
    xs, ys = [], []
    for p in e.paths:
        for v in getattr(p, "vertices", []):
            xs.append(v[0]); ys.append(v[1])
    if not xs:
        return (0.0, 0.0, 0.0)
    return (sum(xs) / len(xs), sum(ys) / len(ys), 0.0)


def _bbox(e: DXFGraphic):
    from ezdxf import bbox

    try:
        box = bbox.extents([e], fast=True)
    except Exception:
        return None
    return box if box.has_data else None


def props(e: DXFGraphic) -> dict[str, Any]:
    return {p: e.dxf.get(p) for p in PROPS if e.dxf.hasattr(p)} | {
        "layer": e.dxf.get("layer", "0")}


# --------------------------------------------------------------------------- #
# Result model
# --------------------------------------------------------------------------- #
@dataclass
class Item:
    entity: DXFGraphic
    geom: tuple
    shape: tuple | None
    props: dict

    @property
    def handle(self) -> str:
        return self.entity.dxf.handle

    @property
    def type(self) -> str:
        return self.entity.dxftype()


@dataclass
class Change:
    kind: str                      # added | removed | modified | moved
    type: str
    old: DXFGraphic | None = None
    new: DXFGraphic | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "type": self.type,
            "old_handle": self.old.dxf.handle if self.old is not None else None,
            "new_handle": self.new.dxf.handle if self.new is not None else None,
            "layer": (self.new or self.old).dxf.get("layer", "0"),
            "details": self.details,
        }


@dataclass
class DiffResult:
    old: Drawing
    new: Drawing
    changes: list[Change]
    unchanged: list[tuple[DXFGraphic, DXFGraphic]]

    def by_kind(self, kind: str) -> list[Change]:
        return [c for c in self.changes if c.kind == kind]

    @property
    def summary(self) -> dict[str, int]:
        s = {k: len(self.by_kind(k)) for k in CHANGE_KINDS}
        s["unchanged"] = len(self.unchanged)
        return s

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    def to_dict(self) -> dict:
        return {"summary": self.summary,
                "changes": [c.to_dict() for c in self.changes]}


# --------------------------------------------------------------------------- #
# Diff
# --------------------------------------------------------------------------- #
def _items(doc: Drawing, nd: int, ignore_layers: set[str]) -> list[Item]:
    out = []
    for e in doc.modelspace():
        if e.dxf.get("layer", "0") in ignore_layers:
            continue
        try:
            g = geometry(e, nd)
            a = _anchor(e)
            s = geometry(e, nd, origin=a) if a is not None else None
        except Exception:  # pragma: no cover - exotic/broken entity
            g = (e.dxftype(), e.dxf.handle)
            s = None
        out.append(Item(e, g, s, props(e)))
    return out


def _prop_delta(a: dict, b: dict) -> dict:
    keys = set(a) | set(b)
    return {k: [a.get(k), b.get(k)] for k in sorted(keys) if a.get(k) != b.get(k)}


def diff(old: Drawing | str | Path, new: Drawing | str | Path, *,
         precision: int = 4, match_handles: bool = True,
         detect_moves: bool = True, fuzzy: bool = True,
         ignore_layers: Iterable[str] = ()) -> DiffResult:
    """Compare two DXF drawings and return a :class:`DiffResult`."""
    if not isinstance(old, Drawing):
        old = load(old)
    if not isinstance(new, Drawing):
        new = load(new)
    ign = set(ignore_layers)
    A = _items(old, precision, ign)
    B = _items(new, precision, ign)
    used_a: set[int] = set()
    used_b: set[int] = set()
    changes: list[Change] = []
    unchanged: list[tuple[DXFGraphic, DXFGraphic]] = []

    def free(items, used):
        return [(i, it) for i, it in enumerate(items) if i not in used]

    # Pass 1: exact match (geometry + props)
    idx = defaultdict(list)
    for j, b in enumerate(B):
        idx[(b.geom, tuple(sorted(b.props.items())))].append(j)
    for i, a in enumerate(A):
        bucket = idx.get((a.geom, tuple(sorted(a.props.items()))))
        if bucket:
            j = bucket.pop(0)
            used_a.add(i); used_b.add(j)
            unchanged.append((a.entity, B[j].entity))

    # Pass 2a: same geometry, different properties
    idx = defaultdict(list)
    for j, b in free(B, used_b):
        idx[b.geom].append(j)
    for i, a in free(A, used_a):
        bucket = idx.get(a.geom)
        if bucket:
            j = bucket.pop(0)
            used_a.add(i); used_b.add(j)
            changes.append(Change("modified", a.type, a.entity, B[j].entity,
                                  {"properties": _prop_delta(a.props, B[j].props)}))

    # Pass 2b: same handle and type (AutoCAD keeps handles across saves)
    if match_handles:
        hb = {b.handle: j for j, b in free(B, used_b)}
        for i, a in free(A, used_a):
            j = hb.get(a.handle)
            if j is not None and B[j].type == a.type:
                used_a.add(i); used_b.add(j)
                d = {"geometry": True}
                pd = _prop_delta(a.props, B[j].props)
                if pd:
                    d["properties"] = pd
                changes.append(Change("modified", a.type, a.entity, B[j].entity, d))

    # Pass 3: moved (same shape, different position)
    if detect_moves:
        idx = defaultdict(list)
        for j, b in free(B, used_b):
            if b.shape is not None:
                idx[b.shape].append(j)
        for i, a in free(A, used_a):
            if a.shape is None:
                continue
            bucket = idx.get(a.shape)
            if bucket:
                j = bucket.pop(0)
                used_a.add(i); used_b.add(j)
                pa, pb = _anchor(a.entity), _anchor(B[j].entity)
                offset = [_r(pb[k] - pa[k], precision) for k in range(2)]
                d = {"offset": offset,
                     "distance": _r(math.hypot(*offset), precision)}
                pd = _prop_delta(a.props, B[j].props)
                if pd:
                    d["properties"] = pd
                changes.append(Change("moved", a.type, a.entity, B[j].entity, d))

    # Pass 4: fuzzy - same type and layer, overlapping bounding boxes
    if fuzzy:
        cand = []
        for i, a in free(A, used_a):
            ba = _bbox(a.entity)
            if ba is None:
                continue
            for j, b in free(B, used_b):
                if b.type != a.type or b.props["layer"] != a.props["layer"]:
                    continue
                bb = _bbox(b.entity)
                if bb is None or not ba.has_overlap(bb):
                    continue
                cand.append((ba.center.distance(bb.center), i, j))
        for _, i, j in sorted(cand):
            if i in used_a or j in used_b:
                continue
            used_a.add(i); used_b.add(j)
            d = {"geometry": True}
            pd = _prop_delta(A[i].props, B[j].props)
            if pd:
                d["properties"] = pd
            changes.append(Change("modified", A[i].type, A[i].entity, B[j].entity, d))

    for _, a in free(A, used_a):
        changes.append(Change("removed", a.type, old=a.entity))
    for _, b in free(B, used_b):
        changes.append(Change("added", b.type, new=b.entity))

    order = {k: n for n, k in enumerate(CHANGE_KINDS)}
    changes.sort(key=lambda c: (order[c.kind], c.type))
    return DiffResult(old, new, changes, unchanged)
