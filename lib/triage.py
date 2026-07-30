"""tria.ge Stage 2 enrichment for GRIFT.

The client intentionally keeps Stage 2 optional and explicit. Stage 1 never
requires a tria.ge key. Lookup mode searches existing tria.ge reports for
candidate payload URLs. Submit mode is only called by the CLI after the user
passes the explicit malware-submission safety flag.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

DEFAULT_BASE_URL = "https://tria.ge/api"
USER_AGENT = "GRIFT/1.0 (defensive research)"

UrlOpener = Callable[..., Any]


def collect_candidate_urls(candidate: dict[str, Any], *, limit: int = 8) -> list[str]:
    """Return candidate payload URLs in priority order, deduped."""
    score_result = candidate.get("score_result") or {}
    download_urls = score_result.get("download_urls") or {}
    buckets = (
        "payload",
        "github_release",
        "telegram",
        "dropbox",
        "unknown_external",
    )
    seen: set[str] = set()
    out: list[str] = []
    for bucket in buckets:
        for url in download_urls.get(bucket) or []:
            if not isinstance(url, str):
                continue
            url = url.strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(url)
            if len(out) >= limit:
                return out
    return out


def collect_candidate_targets(candidate: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    """Return candidate payload URLs with archive password context."""
    score_result = candidate.get("score_result") or {}
    passwords = [str(p).strip() for p in (score_result.get("passwords") or []) if str(p).strip()]
    return [
        {"url": url, "passwords": passwords}
        for url in collect_candidate_urls(candidate, limit=limit)
    ]


class TriageClient:
    """Small urllib based tria.ge API client.

    The request transport is injectable for tests. Results never include the API
    key. HTTP/API errors are returned as structured dictionaries so a bad URL or
    rate limit does not abort the whole hunt.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        opener: Optional[UrlOpener] = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.context = ssl.create_default_context()

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[dict[str, str]] = None,
        body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener(req, timeout=self.timeout, context=self.context) as resp:
                raw = resp.read().decode("utf-8", "replace")
                payload = json.loads(raw) if raw.strip() else {}
                return {"ok": True, "status": getattr(resp, "status", None), "data": payload}
        except urllib.error.HTTPError as e:
            raw = ""
            try:
                raw = e.read().decode("utf-8", "replace") if e.fp else ""
            except Exception:
                raw = ""
            err: dict[str, Any] = {
                "ok": False,
                "status": e.code,
                "error": f"HTTPError: {e.reason}",
            }
            if raw:
                try:
                    err["data"] = json.loads(raw)
                except json.JSONDecodeError:
                    err["body"] = raw[:500]
            return err
        except Exception as e:
            return {"ok": False, "status": None, "error": f"{type(e).__name__}: {e}"}

    def lookup_url(self, url: str, *, passwords: Optional[list[str]] = None) -> dict[str, Any]:
        """Search existing tria.ge reports for a URL indicator and retain password context."""
        passwords = [p for p in (passwords or []) if p]
        query = f'url:"{url}"'
        response = self._request("GET", "/v0/search", query={"query": query})
        result: dict[str, Any] = {
            "url": url,
            "mode": "lookup",
            "ok": bool(response.get("ok")),
            "status": response.get("status"),
            "query": query,
        }
        if passwords:
            result["passwords"] = passwords
        if response.get("ok"):
            payload = response.get("data") or {}
            data = payload.get("data") if isinstance(payload, dict) else None
            items = data if isinstance(data, list) else []
            result["matches"] = len(items)
            result["results"] = [_summarize_search_hit(x) for x in items[:5] if isinstance(x, dict)]
        else:
            result["matches"] = 0
            result["error"] = response.get("error") or "lookup failed"
            if "data" in response:
                result["details"] = response["data"]
        return result

    def submit_url(
        self,
        url: str,
        *,
        password: Optional[str] = None,
        profile: str = "default",
        timeout: int = 200,
        network: str = "internet",
        interactive: bool = False,
    ) -> dict[str, Any]:
        """Submit a remote URL fetch to tria.ge, including archive password if known.

        Notes from the original research bundle used `kind=fetch`, archive
        password, `interactive=false`, 200 second timeout, and internet network.
        """
        body: dict[str, Any] = {
            "kind": "fetch",
            "url": url,
            "profile": profile,
            "timeout": timeout,
            "network": network,
            "interactive": interactive,
        }
        if password:
            body["password"] = password
        response = self._request(
            "POST",
            "/v0/samples",
            body=body,
        )
        result: dict[str, Any] = {
            "url": url,
            "mode": "submit_fetch",
            "ok": bool(response.get("ok")),
            "status": response.get("status"),
        }
        if password:
            result["password"] = password
        payload = response.get("data") if isinstance(response.get("data"), dict) else {}
        if response.get("ok"):
            result["sample_id"] = payload.get("id") or payload.get("sample") or payload.get("task_id")
            result["response"] = _safe_small_payload(payload)
        else:
            result["error"] = response.get("error") or "submit failed"
            if payload:
                result["details"] = _safe_small_payload(payload)
        return result


def enrich_candidates_with_triage(
    candidates: list[dict[str, Any]],
    client: TriageClient,
    *,
    min_score: int,
    submit: bool = False,
    max_urls_per_candidate: int = 3,
    submit_profile: str = "default",
) -> dict[str, Any]:
    """Attach tria.ge lookup/submit results to candidates above a score threshold."""
    summary = {
        "enabled": True,
        "min_score": min_score,
        "submit": bool(submit),
        "candidates_considered": 0,
        "lookups_attempted": 0,
        "submits_attempted": 0,
        "lookup_matches": 0,
        "errors": 0,
    }
    for candidate in candidates:
        score_result = candidate.get("score_result") or {}
        if score_result.get("drop"):
            continue
        if (score_result.get("score") or 0) < min_score:
            continue
        targets = collect_candidate_targets(candidate, limit=max_urls_per_candidate)
        if not targets:
            continue
        summary["candidates_considered"] += 1
        triage_block = candidate.setdefault("triage", {"lookups": [], "submissions": []})
        for target in targets:
            url = target["url"]
            passwords = target.get("passwords") or []
            password = passwords[0] if passwords else None
            lookup = client.lookup_url(url, passwords=passwords)
            triage_block["lookups"].append(lookup)
            summary["lookups_attempted"] += 1
            summary["lookup_matches"] += int(lookup.get("matches") or 0)
            if not lookup.get("ok"):
                summary["errors"] += 1
            if submit:
                if lookup.get("ok") and int(lookup.get("matches") or 0) == 0:
                    submitted = client.submit_url(url, password=password, profile=submit_profile)
                    triage_block["submissions"].append(submitted)
                    summary["submits_attempted"] += 1
                    if not submitted.get("ok"):
                        summary["errors"] += 1
                else:
                    triage_block["submissions"].append(
                        {
                            "url": url,
                            "mode": "submit_url",
                            "ok": False,
                            "skipped": True,
                            "reason": "existing_match_or_lookup_error",
                        }
                    )
    return summary


def _summarize_search_hit(hit: dict[str, Any]) -> dict[str, Any]:
    fields = ("id", "sample", "target", "kind", "score", "created", "completed", "status")
    return {k: hit.get(k) for k in fields if k in hit}


def _safe_small_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep response context small and avoid storing arbitrary blobs in reports."""
    keep = ("id", "sample", "task_id", "status", "kind", "target", "created")
    return {k: payload.get(k) for k in keep if k in payload}
