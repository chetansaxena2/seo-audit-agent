"""MCP server wrapper.

Exposes the running audit service as MCP tools so Claude Desktop, Claude Code,
Cursor or any MCP client can trigger audits and read results conversationally.

    pip install "mcp[cli]" httpx
    SEO_AGENT_URL=http://localhost:8000 SEO_AGENT_KEY=your-key python integrations/mcp_server.py

Claude Desktop config:
{
  "mcpServers": {
    "seo-audit": {
      "command": "python",
      "args": ["/abs/path/integrations/mcp_server.py"],
      "env": {"SEO_AGENT_URL": "http://localhost:8000", "SEO_AGENT_KEY": "your-key"}
    }
  }
}
"""
from __future__ import annotations

import asyncio
import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE = os.getenv("SEO_AGENT_URL", "http://localhost:8000").rstrip("/")
KEY = os.getenv("SEO_AGENT_KEY", "demo-key")
HEADERS = {"X-API-Key": KEY, "Content-Type": "application/json"}

mcp = FastMCP("seo-audit-agent")


async def _call(method: str, path: str, **kwargs) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.request(method, f"{BASE}{path}", headers=HEADERS, **kwargs)
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def run_seo_audit(url: str, max_pages: int = 10, wait: bool = True,
                        target_keywords: str = "", competitors: str = "") -> dict:
    """Audit a website: crawl, on-page, technical, schema, AI visibility, speed,
    authority and competitors. Returns the headline scores and top issues."""
    body = {
        "url": url,
        "max_pages": max_pages,
        "target_keywords": [k.strip() for k in target_keywords.split(",") if k.strip()] or None,
        "competitors": [c.strip() for c in competitors.split(",") if c.strip()] or None,
    }
    accepted = await _call("POST", "/audits", json=body)
    audit_id = accepted["audit_id"]
    if not wait:
        return accepted

    for _ in range(120):
        await asyncio.sleep(5)
        status = await _call("GET", f"/audits/{audit_id}")
        if status["status"] in ("completed", "failed"):
            break
    result = await _call("GET", f"/audits/{audit_id}/result")
    return {
        "audit_id": audit_id,
        "url": result.get("site", {}).get("url"),
        "scores": result.get("scores", {}).get("headline"),
        "overall_score": result.get("scores", {}).get("overall_score"),
        "grade": result.get("scores", {}).get("grade"),
        "summary": result.get("summary"),
        "top_issues": result.get("issues", [])[:15],
        "report_url": accepted["share_url"],
        "pdf_url": accepted["share_url"] + "/pdf",
    }


@mcp.tool()
async def get_audit_result(audit_id: str, section: str = "all") -> dict:
    """Read a finished audit. section: all | scores | issues | keywords |
    ai_visibility | competitors | page_speed | recommended_fixes."""
    result = await _call("GET", f"/audits/{audit_id}/result")
    return result if section == "all" else {section: result.get(section)}


@mcp.tool()
async def list_recent_audits(limit: int = 20, domain: str = "") -> dict:
    """List recent audits with their scores."""
    return await _call("GET", f"/audits?limit={limit}" + (f"&domain={domain}" if domain else ""))


@mcp.tool()
async def agent_stats() -> dict:
    """Throughput, daily quota use and queue depth."""
    return await _call("GET", "/stats")


if __name__ == "__main__":
    mcp.run()
