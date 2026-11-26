"""Build two revisions of a small floor plan and render their diff."""

from pathlib import Path

import ezdxf

from dxfdiff import diff
from dxfdiff.render import render
from dxfdiff.report import to_text

HERE = Path(__file__).parent


def plan(rev: int):
    doc = ezdxf.new()
    for name in ("WALL", "FURN", "TEXT"):
        doc.layers.add(name)
    chair = doc.blocks.new("CHAIR")
    chair.add_lwpolyline([(-0.25, -0.25), (0.25, -0.25), (0.25, 0.25), (-0.25, 0.25)], close=True)
    msp = doc.modelspace()
    walls = [(0, 0), (12, 0), (12, 8), (0, 8)]
    msp.add_lwpolyline(walls, close=True, dxfattribs={"layer": "WALL"})
    msp.add_line((6, 0), (6, 5 if rev == 1 else 3.5), dxfattribs={"layer": "WALL"})
    msp.add_circle((3, 4), 1.2, dxfattribs={"layer": "FURN"})            # table
    for i, (x, y) in enumerate([(3, 5.6), (3, 2.4), (1.4, 4), (4.6, 4)]):
        if rev == 2 and i == 3:
            x += 0.8                                                     # moved
        msp.add_blockref("CHAIR", (x, y), dxfattribs={"layer": "FURN"})
    msp.add_text("OFFICE", dxfattribs={"insert": (1, 7), "height": 0.4, "layer": "TEXT"})
    if rev == 1:
        msp.add_circle((9, 6), 0.6, dxfattribs={"layer": "FURN"})       # removed
        msp.add_text("STORAGE", dxfattribs={"insert": (7, 7), "height": 0.4, "layer": "TEXT"})
    else:
        msp.add_lwpolyline([(8, 5), (11, 5), (11, 7), (8, 7)], close=True,
                           dxfattribs={"layer": "FURN"})                 # added
        msp.add_text("MEETING ROOM", dxfattribs={"insert": (7, 7.3), "height": 0.4, "layer": "TEXT"})
    return doc


if __name__ == "__main__":
    a, b = plan(1), plan(2)
    a.saveas(HERE / "rev1.dxf")
    b.saveas(HERE / "rev2.dxf")
    r = diff(HERE / "rev1.dxf", HERE / "rev2.dxf", match_handles=False)
    print(to_text(r))
    render(r, HERE / "diff.png", title="rev1.dxf -> rev2.dxf")
