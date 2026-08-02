"""Renders the audit payload into a single self-contained HTML file.

Screenshots are inlined as base64 so the report can be emailed, hosted or
printed to PDF without any external dependencies.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import settings

TEMPLATES = Path(__file__).parent / "templates"
LIMITS = {"critical": 30, "high": 30, "medium": 25, "low": 20}

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _color(value: float) -> str:
    if value >= 80:
        return "#0E9F6E"
    if value >= 60:
        return "#00A6A6"
    if value >= 40:
        return "#D98200"
    return "#C3222B"


def _inline_image(path: str | None, kind: str = "png") -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or p.stat().st_size > 6_000_000:
        return None
    return f"data:image/{kind};base64," + base64.b64encode(p.read_bytes()).decode()


def _shortpath(url: str) -> str:
    from urllib.parse import urlparse
    path = urlparse(url).path or "/"
    return "homepage" if path in ("", "/") else path


def render(result: dict, style: str | None = None) -> str:
    """style: "client" (a consultant's letter, the default) or "technical"."""
    style = style or os.getenv("REPORT_STYLE", "client")
    data = json.loads(json.dumps(result))  # deep copy, JSON-safe

    if style == "client" and data.get("client_view"):
        for group in data["client_view"]["issue_groups"]:
            group["screenshot_data"] = _inline_image(group.get("screenshot"))
        c = data["client_view"]["consultant"]
        template = _env.get_template("client_report.html.j2")
        return template.render(
            r=data, c=c, color=_color,
            photo=_inline_image(c.get("photo"), "jpeg"),
            counts=data["scores"]["issue_counts"],
            shortpath=_shortpath)

    for sev, items in data.get("roadmap", {}).items():
        for issue in items:
            issue["screenshot_data"] = _inline_image(issue.get("screenshot"))
    template = _env.get_template("report.html.j2")
    return template.render(r=data, color=_color, limits=LIMITS)


def write(result: dict, audit_id: str, out_dir: str | Path | None = None,
          style: str | None = None) -> str:
    out_dir = Path(out_dir) if out_dir else Path(settings.data_dir) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{audit_id}.html"
    path.write_text(render(result, style), encoding="utf-8")
    return str(path)
