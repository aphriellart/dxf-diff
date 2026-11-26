"""Render a :class:`DiffResult` as an overlay image (PNG / SVG / PDF)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from ezdxf import path as ezpath  # noqa: E402

from .core import DiffResult  # noqa: E402

COLORS = {
    "unchanged": "#b8b8b8",
    "removed": "#d62728",
    "added": "#2ca02c",
    "modified": "#ff7f0e",
    "moved": "#1f77b4",
}
LABELS = {
    "unchanged": "Unchanged",
    "removed": "Removed",
    "added": "Added",
    "modified": "Modified",
    "moved": "Moved",
}


def _draw(ax, entity, color, lw, ls="-", alpha=1.0, depth=0):
    t = entity.dxftype()
    if t in ("TEXT", "MTEXT", "ATTRIB"):
        p = entity.dxf.insert
        text = entity.plain_text() if t == "MTEXT" else entity.dxf.text
        h = entity.dxf.get("char_height" if t == "MTEXT" else "height", 1.0)
        ax.text(p[0], p[1], text, color=color, alpha=alpha,
                fontsize=max(4, min(14, h * 2)),
                rotation=entity.dxf.get("rotation", 0), va="bottom")
        return [(p[0], p[1])]
    if t == "INSERT" and depth < 8:
        pts = []
        try:
            for v in entity.virtual_entities():
                pts += _draw(ax, v, color, lw, ls, alpha, depth + 1)
        except Exception:
            pass
        for a in entity.attribs:
            pts += _draw(ax, a, color, lw, ls, alpha, depth + 1)
        return pts
    if t == "POINT":
        p = entity.dxf.location
        ax.plot([p[0]], [p[1]], "o", color=color, ms=3, alpha=alpha)
        return [(p[0], p[1])]
    try:
        p = ezpath.make_path(entity)
    except Exception:
        return []
    pts = []
    for sub in p.sub_paths() if p.has_sub_paths else [p]:
        v = list(sub.flattening(0.01))
        if len(v) < 2:
            continue
        xs, ys = [q.x for q in v], [q.y for q in v]
        ax.plot(xs, ys, color=color, lw=lw, ls=ls, alpha=alpha,
                solid_capstyle="round")
        pts += list(zip(xs, ys))
    return pts


def render(result: DiffResult, out: str | Path, *, title: str | None = None,
           show_unchanged: bool = True, dpi: int = 150,
           size: tuple[float, float] = (12, 9), dark: bool = False) -> Path:
    """Draw the diff overlay and save it. Format follows the file suffix."""
    out = Path(out)
    fig, ax = plt.subplots(figsize=size)
    bg = "#111418" if dark else "white"
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    if show_unchanged:
        for _, e in result.unchanged:
            _draw(ax, e, "#555b63" if dark else COLORS["unchanged"], 0.8)
    for c in result.changes:
        col = COLORS[c.kind]
        if c.kind == "removed":
            _draw(ax, c.old, col, 1.6, "--")
        elif c.kind == "added":
            _draw(ax, c.new, col, 1.8)
        elif c.kind in ("modified", "moved"):
            _draw(ax, c.old, col, 1.0, ":", alpha=0.45)
            _draw(ax, c.new, col, 1.8)

    ax.set_aspect("equal", adjustable="datalim")
    ax.axis("off")
    s = result.summary
    handles = [Line2D([0], [0], color=COLORS[k], lw=2.5,
                      ls="--" if k == "removed" else "-",
                      label=f"{LABELS[k]} ({s[k]})")
               for k in ("added", "removed", "modified", "moved", "unchanged")]
    leg = ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.0, 1.0),
                    frameon=False, labelcolor="#e6e6e6" if dark else "#222")
    if title:
        ax.set_title(title, color="#e6e6e6" if dark else "#222")
    fig.savefig(out, dpi=dpi, bbox_inches="tight", bbox_extra_artists=[leg],
                facecolor=bg)
    plt.close(fig)
    return out
