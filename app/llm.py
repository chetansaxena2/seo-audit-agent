"""Optional LLM assist (Anthropic Messages API).

Every call degrades gracefully: if no key is configured, the request fails, or
the model returns unparsable output, callers fall back to the deterministic
heuristics. Nothing in the audit depends on the LLM being available.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import settings

API_URL = "https://api.anthropic.com/v1/messages"


def available() -> bool:
    return bool(settings.anthropic_api_key)


async def complete(prompt: str, *, system: str = "", max_tokens: int = 1200,
                   tools: list[dict] | None = None, timeout: int = 90) -> str:
    if not available():
        return ""
    payload: dict[str, Any] = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = tools
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(API_URL, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return ""
    return "\n".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()


async def complete_json(prompt: str, *, system: str = "", max_tokens: int = 1500,
                        tools: list[dict] | None = None) -> Any:
    text = await complete(
        prompt + "\n\nReturn ONLY valid JSON. No markdown fences, no preamble.",
        system=system or "You are a senior SEO analyst. You reply with JSON only.",
        max_tokens=max_tokens, tools=tools,
    )
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    match = re.search(r"[\[{].*[\]}]", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


WEB_SEARCH_TOOL = [{"type": "web_search_20250305", "name": "web_search"}]
