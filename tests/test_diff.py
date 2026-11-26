import json

import ezdxf
import pytest

from dxfdiff import diff
from dxfdiff.cli import main
from dxfdiff.report import to_markdown, to_text


def base_doc():
    doc = ezdxf.new()
    doc.layers.add("WALL")
    doc.layers.add("FURN")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "WALL"})
    msp.add_line((10, 0), (10, 8), dxfattribs={"layer": "WALL"})
    msp.add_circle((5, 4), 1, dxfattribs={"layer": "FURN"})
    msp.add_text("ROOM A", dxfattribs={"insert": (1, 1), "height": 0.5})
    msp.add_lwpolyline([(2, 2), (4, 2), (4, 3), (2, 3)], close=True)
    return doc


def test_identical():
    r = diff(base_doc(), base_doc())
    assert not r.has_changes
    assert r.summary["unchanged"] == 5


def test_added_removed():
    a, b = base_doc(), base_doc()
    b.modelspace().add_line((0, 8), (10, 8), dxfattribs={"layer": "WALL"})
    for e in b.modelspace().query("CIRCLE"):
        b.modelspace().delete_entity(e)
    r = diff(a, b, match_handles=False)
    assert r.summary["added"] == 1
    assert r.summary["removed"] == 1
    assert r.by_kind("added")[0].type == "LINE"
    assert r.by_kind("removed")[0].type == "CIRCLE"


def test_property_change_is_modified():
    a, b = base_doc(), base_doc()
    b.modelspace().query("CIRCLE")[0].dxf.layer = "WALL"
    r = diff(a, b)
    (c,) = r.changes
    assert c.kind == "modified"
    assert c.details["properties"]["layer"] == ["FURN", "WALL"]


def test_move_detected():
    a, b = base_doc(), base_doc()
    b.modelspace().query("CIRCLE")[0].dxf.center = (7, 6)
    r = diff(a, b, match_handles=False)
    (c,) = r.changes
    assert c.kind == "moved"
    assert c.details["offset"] == [2.0, 2.0]


def test_text_edit_with_handles_is_modified(tmp_path):
    base_doc().saveas(tmp_path / "a.dxf")
    a = ezdxf.readfile(tmp_path / "a.dxf")
    b = ezdxf.readfile(tmp_path / "a.dxf")  # same handles, like an AutoCAD re-save
    b.modelspace().query("TEXT")[0].dxf.text = "ROOM B"
    r = diff(a, b)
    (c,) = r.changes
    assert c.kind == "modified" and c.details.get("geometry")


def test_line_direction_ignored():
    a, b = ezdxf.new(), ezdxf.new()
    a.modelspace().add_line((0, 0), (5, 5))
    b.modelspace().add_line((5, 5), (0, 0))
    assert not diff(a, b).has_changes


def test_precision_tolerance():
    a, b = ezdxf.new(), ezdxf.new()
    a.modelspace().add_circle((0, 0), 1.0)
    b.modelspace().add_circle((0.00001, 0), 1.0)
    assert not diff(a, b, precision=3).has_changes
    assert diff(a, b, precision=6, detect_moves=False,
                match_handles=False).has_changes


def test_ignore_layer():
    a, b = base_doc(), base_doc()
    b.modelspace().add_circle((9, 9), 1, dxfattribs={"layer": "FURN"})
    assert not diff(a, b, ignore_layers=["FURN"]).has_changes


def test_reports_and_cli(tmp_path):
    a, b = base_doc(), base_doc()
    b.modelspace().add_circle((8, 6), 0.5)
    pa, pb = tmp_path / "a.dxf", tmp_path / "b.dxf"
    a.saveas(pa); b.saveas(pb)
    r = diff(pa, pb)
    assert "1 added" in to_text(r)
    assert "| 1 |" in to_markdown(r)

    out = tmp_path / "out"
    code = main([str(pa), str(pb), "-q", "-o", str(out) + ".png",
                 "--html", str(out) + ".html", "--json", str(out) + ".json",
                 "--markdown", str(out) + ".md"])
    assert code == 1
    assert (tmp_path / "out.png").stat().st_size > 1000
    assert "<svg" not in (tmp_path / "out.html").read_text()[:50]
    assert "data:image/svg+xml" in (tmp_path / "out.html").read_text()
    data = json.loads((tmp_path / "out.json").read_text())
    assert data["summary"]["added"] == 1
    assert main([str(pa), str(pa), "-q"]) == 0
    assert main([str(pa), str(pb), "-q", "--exit-zero"]) == 0


def test_missing_file(tmp_path):
    assert main([str(tmp_path / "nope.dxf"), str(tmp_path / "x.dxf")]) == 2


def test_blocks_render(tmp_path):
    a, b = ezdxf.new(), ezdxf.new()
    for d in (a, b):
        blk = d.blocks.new("CHAIR")
        blk.add_circle((0, 0), 0.3)
    a.modelspace().add_blockref("CHAIR", (1, 1))
    b.modelspace().add_blockref("CHAIR", (2, 1))
    r = diff(a, b, match_handles=False)
    assert r.by_kind("moved")
    from dxfdiff.render import render
    assert render(r, tmp_path / "x.svg").exists()


def test_fuzzy_shortened_wall():
    a, b = ezdxf.new(), ezdxf.new()
    a.modelspace().add_line((6, 0), (6, 5), dxfattribs={"layer": "WALL"})
    b.modelspace().add_line((6, 0), (6, 3.5), dxfattribs={"layer": "WALL"})
    r = diff(a, b, match_handles=False)
    (c,) = r.changes
    assert c.kind == "modified" and c.details["geometry"]
    r = diff(a, b, match_handles=False, fuzzy=False)
    assert r.summary["added"] == 1 and r.summary["removed"] == 1
