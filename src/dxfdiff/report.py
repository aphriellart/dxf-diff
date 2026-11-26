"""Text, Markdown, JSON and HTML reports for a :class:`DiffResult`."""

from __future__ import annotations

import base64
import html
import json
import tempfile
from pathlib import Path

from .core import CHANGE_KINDS, Change, DiffResult

ICON = {"added": "+", "removed": "-", "modified": "~", "moved": ">"}


def describe(c: Change) -> str:
    d = c.details
    parts = []
    if c.kind == "moved":
        dx, dy = d["offset"]
        parts.append(f"moved by ({dx:g}, {dy:g})")
    if d.get("geometry"):
        parts.append("geometry changed")
    for k, (a, b) in d.get("properties", {}).items():
        parts.append(f"{k}: {a} -> {b}")
    e = c.new if c.new is not None else c.old
    label = c.type
    if c.type in ("TEXT", "MTEXT"):
        txt = e.plain_text() if c.type == "MTEXT" else e.dxf.text
        label += f' "{txt[:40]}"'
    elif c.type == "INSERT":
        label += f" <{e.dxf.name}>"
    layer = e.dxf.get("layer", "0")
    return f"{label} on layer '{layer}'" + (f" - {', '.join(parts)}" if parts else "")


def to_text(r: DiffResult) -> str:
    s = r.summary
    lines = [
        f"dxf-diff: {s['added']} added, {s['removed']} removed, "
        f"{s['modified']} modified, {s['moved']} moved, "
        f"{s['unchanged']} unchanged"
    ]
    for c in r.changes:
        lines.append(f"  {ICON[c.kind]} {describe(c)}")
    return "\n".join(lines)


def to_json(r: DiffResult) -> str:
    return json.dumps(r.to_dict(), indent=2, default=str)


def to_markdown(r: DiffResult, image_url: str | None = None,
                title: str = "CAD drawing diff", limit: int = 50) -> str:
    s = r.summary
    out = [f"### {title}", "",
           "| Added | Removed | Modified | Moved | Unchanged |",
           "|---:|---:|---:|---:|---:|",
           f"| {s['added']} | {s['removed']} | {s['modified']} | "
           f"{s['moved']} | {s['unchanged']} |", ""]
    if image_url:
        out += [f"![diff]({image_url})", ""]
    if r.changes:
        out += ["<details><summary>Changes</summary>", ""]
        for c in r.changes[:limit]:
            out.append(f"- `{ICON[c.kind]}` {describe(c)}")
        if len(r.changes) > limit:
            out.append(f"- ... and {len(r.changes) - limit} more")
        out += ["", "</details>"]
    else:
        out.append("No changes.")
    return "\n".join(out)


def to_html(r: DiffResult, title: str = "dxf-diff report",
            old_name: str = "old", new_name: str = "new") -> str:
    from .render import COLORS, render

    with tempfile.TemporaryDirectory() as tmp:
        svg = Path(tmp) / "diff.svg"
        render(r, svg)
        img = base64.b64encode(svg.read_bytes()).decode()
    s = r.summary
    cards = "".join(
        f'<div class="card"><b style="color:{COLORS[k]}">{s[k]}</b>'
        f"<span>{k}</span></div>" for k in (*CHANGE_KINDS, "unchanged"))
    rows = "".join(
        f'<tr><td><span class="pill" style="background:{COLORS[c.kind]}">'
        f"{c.kind}</span></td><td>{html.escape(c.type)}</td>"
        f"<td>{html.escape((c.new if c.new is not None else c.old).dxf.get('layer', '0'))}</td>"
        f"<td>{html.escape(describe(c))}</td></tr>" for c in r.changes)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px;color:#1d2125;background:#f6f7f9}}
main{{max-width:1100px;margin:auto}} h1{{font-size:22px;margin:0 0 4px}}
.sub{{color:#5b636b;margin-bottom:18px}}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}}
.card{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:10px 16px;min-width:90px}}
.card b{{display:block;font-size:24px}} .card span{{color:#5b636b;text-transform:capitalize}}
figure{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;margin:0 0 18px;padding:12px}}
figure img{{width:100%;height:auto}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e6ea;border-radius:10px;overflow:hidden}}
th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid #eef0f2;vertical-align:top}}
th{{background:#fafbfc;font-weight:600}}
.pill{{color:#fff;border-radius:99px;padding:2px 10px;font-size:12px}}
</style></head><body><main>
<h1>{html.escape(title)}</h1>
<div class="sub">{html.escape(old_name)} &rarr; {html.escape(new_name)}</div>
<div class="cards">{cards}</div>
<figure><img alt="Diff overlay" src="data:image/svg+xml;base64,{img}"></figure>
<table><thead><tr><th>Change</th><th>Type</th><th>Layer</th><th>Details</th></tr></thead>
<tbody>{rows or '<tr><td colspan="4">No changes.</td></tr>'}</tbody></table>
</main></body></html>"""
