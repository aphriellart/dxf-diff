"""Command line interface: ``dxf-diff old.dxf new.dxf``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import diff
from .report import to_html, to_json, to_markdown, to_text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="dxf-diff",
        description="Visual diff for AutoCAD DXF/DWG drawings.")
    p.add_argument("old", help="original drawing (.dxf or .dwg)")
    p.add_argument("new", help="revised drawing (.dxf or .dwg)")
    p.add_argument("-o", "--image", help="write overlay image (.png/.svg/.pdf)")
    p.add_argument("--html", help="write a self-contained HTML report")
    p.add_argument("--json", help="write a JSON report ('-' for stdout)")
    p.add_argument("--markdown", help="write a Markdown summary (for PR comments)")
    p.add_argument("--precision", type=int, default=4,
                   help="decimal places used when comparing coordinates (default 4)")
    p.add_argument("--ignore-layer", action="append", default=[], metavar="LAYER",
                   help="skip entities on this layer (repeatable)")
    p.add_argument("--no-handles", action="store_true",
                   help="do not match entities by handle")
    p.add_argument("--no-moves", action="store_true",
                   help="report moves as remove + add")
    p.add_argument("--no-fuzzy", action="store_true",
                   help="do not pair overlapping entities of the same type/layer")
    p.add_argument("--hide-unchanged", action="store_true",
                   help="do not draw unchanged entities in the image")
    p.add_argument("--dark", action="store_true", help="dark background image")
    p.add_argument("-q", "--quiet", action="store_true", help="no text output")
    p.add_argument("--exit-zero", action="store_true",
                   help="exit 0 even when differences are found")
    p.add_argument("-V", "--version", action="version",
                   version=f"%(prog)s {__version__}")
    a = p.parse_args(argv)

    try:
        r = diff(a.old, a.new, precision=a.precision,
                 match_handles=not a.no_handles, detect_moves=not a.no_moves,
                 fuzzy=not a.no_fuzzy,
                 ignore_layers=a.ignore_layer)
    except (OSError, RuntimeError) as exc:
        print(f"dxf-diff: error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # ezdxf.DXFStructureError etc.
        print(f"dxf-diff: cannot read drawing: {exc}", file=sys.stderr)
        return 2

    if not a.quiet and a.json != "-":
        print(to_text(r))
    if a.image:
        from .render import render
        render(r, a.image, title=f"{Path(a.old).name} -> {Path(a.new).name}",
               show_unchanged=not a.hide_unchanged, dark=a.dark)
    if a.html:
        Path(a.html).write_text(
            to_html(r, old_name=Path(a.old).name, new_name=Path(a.new).name),
            encoding="utf-8")
    if a.json == "-":
        print(to_json(r))
    elif a.json:
        Path(a.json).write_text(to_json(r), encoding="utf-8")
    if a.markdown:
        Path(a.markdown).write_text(to_markdown(r), encoding="utf-8")

    return 0 if (a.exit_zero or not r.has_changes) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
