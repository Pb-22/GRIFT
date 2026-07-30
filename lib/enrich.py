"""Optional lightweight HTTP enrichment (redirect / content-type)."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from typing import Any, Optional
from urllib.parse import urlparse


def check_url(url: str, timeout: float = 12.0) -> dict[str, Any]:
    ctx = ssl.create_default_context()
    headers = {"User-Agent": "github-seo-hunt/1.0 (defensive research)"}
    result: dict[str, Any] = {"url": url, "ok": False}
    try:
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            result.update(
                {
                    "ok": True,
                    "status": resp.status,
                    "final_url": resp.geturl(),
                    "content_type": resp.headers.get("Content-Type"),
                    "content_length": resp.headers.get("Content-Length"),
                }
            )
            return result
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, method="GET", headers={**headers, "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            result.update(
                {
                    "ok": True,
                    "status": resp.status,
                    "final_url": resp.geturl(),
                    "content_type": resp.headers.get("Content-Type"),
                    "content_disposition": resp.headers.get("Content-Disposition"),
                    "content_length": resp.headers.get("Content-Length"),
                }
            )
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def enrich_top_urls(urls: list[str], limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for u in urls[:limit]:
        host = urlparse(u).netloc
        if not host:
            continue
        out.append(check_url(u))
    return out
