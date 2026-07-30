"""tria.ge Stage 2 enrichment for GRIFT.

The client intentionally keeps Stage 2 optional and explicit. Stage 1 never
requires a tria.ge key. Lookup mode searches existing tria.ge reports for
candidate payload URLs. Submit mode is only called by the CLI after the user
passes the explicit malware-submission safety flag.
"""

from __future__ import annotations

import ipaddress
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_BASE_URL = "https://tria.ge/api"
USER_AGENT = "GRIFT/1.0 (defensive research)"
CERTIFICATE_INFRASTRUCTURE_HOSTS = {
    "c.pki.goog",
    "timestamp.digicert.com",
    "timestamp.intel.com",
    "www.digicert.com",
    "www.microsoft.com",
    "pki.intel.com",
}
BENIGN_REPORT_HOSTS = {
    "api.ipify.org",
    "ax-0002.ax-msedge.net",
    "bing.com",
    "copilot.microsoft.com",
    "dns.google",
    "dual.part-0036.t-0009.fb-t-msedge.net",
    "edge-cloud-resource-static.afd.azureedge.net",
    "edge-cloud-resource-static.azureedge.net",
    "edge-consumer-static.afd.azureedge.net",
    "edge-consumer-static.azureedge.net",
    "edge-mobile-static.afd.azureedge.net",
    "edge-mobile-static.azureedge.net",
    "edge.microsoft.com",
    "g.bing.com",
    "icanhazip.com",
    "ifconfig.me",
    "ipinfo.io",
    "ipwho.is",
    "microsoft.com",
    "mr-afd-azuredge.tm-azurefd.net",
    "part-0036.t-0009.fb-t-msedge.net",
    "pki-goog.l.google.com",
    "res-1.public.onecdn.static.microsoft",
    "res-ocdi-public.trafficmanager.net",
    "res-ocdi-stls-prod.edgesuite.net",
    "res.public.onecdn.static.microsoft",
    "static.edge.microsoftapp.net",
    "www.bing.com",
}
BENIGN_REPORT_DOMAIN_SUFFIXES = (
    ".akadns.net",
    ".akamai.net",
    ".akamaiedge.net",
    ".azureedge.net",
    ".cloudapp.azure.com",
    ".edgekey.net",
    ".l.google.com",
    ".microsoft.com",
    ".msedge.net",
    ".trafficmanager.net",
    ".windows.com",
)
IMPORTANT_URL_EXTENSIONS = (".exe", ".dll", ".zip", ".rar", ".7z", ".msi", ".ps1", ".vbs", ".bat", ".cmd", ".scr")

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


_STATIC_URL_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
}
_STATIC_URL_HOSTS = {
    "encrypted-tbn0.gstatic.com",
    "encrypted-tbn1.gstatic.com",
    "encrypted-tbn2.gstatic.com",
    "encrypted-tbn3.gstatic.com",
    "github-readme-activity-graph.vercel.app",
    "gstatic.com",
    "i.postimg.cc",
    "imagedelivery.net",
    "postimg.cc",
    "streak-stats.demolab.com",
    "www.youtube.com",
    "youtube.com",
    "youtu.be",
}


def is_static_or_decorative_url(url: str) -> bool:
    """Return True for image/static URLs that are not useful tria.ge lookup targets."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    path = parsed.path.lower()
    if host in _STATIC_URL_HOSTS or host.endswith(".gstatic.com"):
        return True
    return any(path.endswith(ext) for ext in _STATIC_URL_EXTENSIONS)


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

    def validate_key(self) -> dict[str, Any]:
        """Validate the tria.ge API key without returning the key."""
        response = self._request("GET", "/v0/profiles")
        if response.get("ok"):
            return {"ok": True, "service": "tria.ge", "status": "valid"}
        return {
            "ok": False,
            "service": "tria.ge",
            "status": "invalid",
            "error": response.get("error") or "validation failed",
            "http_status": response.get("status"),
        }

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

    def get_json(self, path: str) -> dict[str, Any]:
        """Fetch an arbitrary tria.ge JSON API path."""
        response = self._request("GET", path)
        if response.get("ok"):
            return {"ok": True, "status": response.get("status"), "data": response.get("data") or {}}
        return {
            "ok": False,
            "status": response.get("status"),
            "error": response.get("error") or "request failed",
            "data": response.get("data") or {},
        }

    def get_public_page_data(self, sample_id: str) -> dict[str, Any]:
        """Fetch and parse public tria.ge page data when the API omits browser-visible fields."""
        public_base = self.base_url[:-4] if self.base_url.endswith("/api") else self.base_url
        url = f"{public_base}/{urllib.parse.quote(sample_id.strip())}"
        req = urllib.request.Request(url, headers={"Accept": "text/html", "User-Agent": USER_AGENT})
        try:
            with self.opener(req, timeout=self.timeout, context=self.context) as resp:
                raw = resp.read().decode("utf-8", "replace")
            data = _extract_page_data_from_public_html(raw)
            if data:
                return {"ok": True, "status": getattr(resp, "status", None), "data": data}
            return {"ok": False, "status": getattr(resp, "status", None), "error": "page data not found in public page"}
        except Exception as e:
            return {"ok": False, "status": None, "error": f"{type(e).__name__}: {e}"}

    def get_public_overview(self, sample_id: str) -> dict[str, Any]:
        """Fetch and parse public tria.ge overview data."""
        page = self.get_public_page_data(sample_id)
        if page.get("ok"):
            raw_data = page.get("data")
            data = raw_data if isinstance(raw_data, dict) else {}
            overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
            if overview:
                return {"ok": True, "status": page.get("status"), "data": overview}
        return page

    def collect_report(self, sample_id: str, *, include_static: bool = True) -> dict[str, Any]:
        """Pull the useful available report surfaces for a sample id."""
        sample_id = sample_id.strip()
        report: dict[str, Any] = {"sample_id": sample_id, "sample": {}, "summary": {}, "overview": {}, "static": {}, "errors": []}
        quoted_id = urllib.parse.quote(sample_id)
        sample = self.get_json(f"/v0/samples/{quoted_id}")
        if sample.get("ok"):
            report["sample"] = sample.get("data") or {}
        else:
            report["errors"].append({"surface": "sample", "error": sample})
        summary = self.get_json(f"/v0/samples/{quoted_id}/summary")
        if summary.get("ok"):
            report["summary"] = summary.get("data") or {}
        else:
            report["errors"].append({"surface": "summary", "error": summary})
        overview = self.get_json(f"/v0/samples/{quoted_id}/overview")
        if overview.get("ok"):
            report["overview"] = overview.get("data") or {}
        else:
            public_page = self.get_public_page_data(sample_id)
            if public_page.get("ok"):
                raw_page_data = public_page.get("data")
                page_data = raw_page_data if isinstance(raw_page_data, dict) else {}
                report["overview"] = page_data.get("overview") or {}
                report["thirdparty"] = page_data.get("thirdparty") or {}
            else:
                report["errors"].append({"surface": "overview", "error": overview})
                report["errors"].append({"surface": "public_page", "error": public_page})
        if include_static:
            static = self.get_json(f"/v0/samples/{quoted_id}/static")
            if static.get("ok"):
                report["static"] = static.get("data") or {}
            else:
                report["errors"].append({"surface": "static", "error": static})
        report["summary_iocs"] = summarize_triage_report(report)
        return report

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
    submit_on_lookup_error: bool = False,
    progress: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Attach tria.ge lookup/submit results to candidates above a score threshold."""
    summary = {
        "enabled": True,
        "min_score": min_score,
        "submit": bool(submit),
        "eligible_candidates": 0,
        "candidates_considered": 0,
        "candidates_without_targets": 0,
        "static_targets_skipped": 0,
        "targets_considered": 0,
        "duplicate_targets_reused": 0,
        "duplicate_submissions_reused": 0,
        "lookups_attempted": 0,
        "submits_attempted": 0,
        "lookup_matches": 0,
        "errors": 0,
    }
    planned: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for candidate in candidates:
        score_result = candidate.get("score_result") or {}
        if score_result.get("drop"):
            continue
        if (score_result.get("score") or 0) < min_score:
            continue
        summary["eligible_candidates"] += 1
        targets = collect_candidate_targets(candidate, limit=max_urls_per_candidate)
        filtered_targets = []
        for target in targets:
            if is_static_or_decorative_url(str(target.get("url") or "")):
                summary["static_targets_skipped"] += 1
                continue
            filtered_targets.append(target)
        targets = filtered_targets
        if not targets:
            summary["candidates_without_targets"] += 1
            continue
        planned.append((candidate, targets))
        summary["candidates_considered"] += 1
        summary["targets_considered"] += len(targets)

    if progress:
        progress(
            {
                "event": "start",
                "eligible_candidates": summary["eligible_candidates"],
                "candidates_considered": summary["candidates_considered"],
                "candidates_without_targets": summary["candidates_without_targets"],
                "static_targets_skipped": summary["static_targets_skipped"],
                "total_targets": summary["targets_considered"],
                "submit": bool(submit),
            }
        )

    index = 0
    lookup_cache: dict[str, dict[str, Any]] = {}
    submission_cache: dict[tuple[str, Optional[str]], dict[str, Any]] = {}
    for candidate, targets in planned:
        triage_block = candidate.setdefault("triage", {"lookups": [], "submissions": []})
        for target in targets:
            index += 1
            url = target["url"]
            passwords = target.get("passwords") or []
            password = passwords[0] if passwords else None
            if progress:
                progress(
                    {
                        "event": "lookup_start",
                        "index": index,
                        "total": summary["targets_considered"],
                        "candidate": candidate.get("full_name"),
                        "url": url,
                    }
                )
            if url in lookup_cache:
                lookup = dict(lookup_cache[url])
                lookup["deduped_from_cache"] = True
                if passwords:
                    lookup["passwords"] = passwords
                triage_block["lookups"].append(lookup)
                summary["duplicate_targets_reused"] += 1
                if progress:
                    progress(
                        {
                            "event": "lookup_done",
                            "index": index,
                            "total": summary["targets_considered"],
                            "candidate": candidate.get("full_name"),
                            "url": url,
                            "ok": bool(lookup.get("ok")),
                            "status": lookup.get("status"),
                            "matches": int(lookup.get("matches") or 0),
                            "deduped_from_cache": True,
                        }
                    )
            else:
                lookup = client.lookup_url(url, passwords=passwords)
                lookup_cache[url] = dict(lookup)
                triage_block["lookups"].append(lookup)
                summary["lookups_attempted"] += 1
                summary["lookup_matches"] += int(lookup.get("matches") or 0)
                if not lookup.get("ok"):
                    summary["errors"] += 1
                if progress:
                    progress(
                        {
                            "event": "lookup_done",
                            "index": index,
                            "total": summary["targets_considered"],
                            "candidate": candidate.get("full_name"),
                            "url": url,
                            "ok": bool(lookup.get("ok")),
                            "status": lookup.get("status"),
                            "matches": int(lookup.get("matches") or 0),
                            "error": lookup.get("error"),
                        }
                    )
            if submit:
                submit_key = (url, password)
                should_submit = bool(lookup.get("ok") and int(lookup.get("matches") or 0) == 0)
                if not lookup.get("ok") and submit_on_lookup_error:
                    should_submit = True
                if should_submit and submit_key in submission_cache:
                    submitted = dict(submission_cache[submit_key])
                    submitted["deduped_from_cache"] = True
                    triage_block["submissions"].append(submitted)
                    summary["duplicate_submissions_reused"] += 1
                    if progress:
                        progress(
                            {
                                "event": "submit_done",
                                "candidate": candidate.get("full_name"),
                                "url": url,
                                "ok": bool(submitted.get("ok")),
                                "status": submitted.get("status"),
                                "sample_id": submitted.get("sample_id"),
                                "error": submitted.get("error"),
                                "deduped_from_cache": True,
                            }
                        )
                elif should_submit:
                    if progress:
                        progress(
                            {
                                "event": "submit_start",
                                "candidate": candidate.get("full_name"),
                                "url": url,
                            }
                        )
                    submitted = client.submit_url(url, password=password, profile=submit_profile)
                    submission_cache[submit_key] = dict(submitted)
                    triage_block["submissions"].append(submitted)
                    summary["submits_attempted"] += 1
                    if not submitted.get("ok"):
                        summary["errors"] += 1
                    if progress:
                        progress(
                            {
                                "event": "submit_done",
                                "candidate": candidate.get("full_name"),
                                "url": url,
                                "ok": bool(submitted.get("ok")),
                                "status": submitted.get("status"),
                                "sample_id": submitted.get("sample_id"),
                                "error": submitted.get("error"),
                            }
                        )
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
    if progress:
        progress({"event": "done", "summary": dict(summary)})
    return summary


def summarize_triage_report(report: dict[str, Any], *, min_report_score: int = 5) -> dict[str, Any]:
    """Produce a compact summary from tria.ge-scored report surfaces.

    tria.ge uses report/task/signature scores as the confidence signal. Do not
    scrape every URL/domain-looking string out of static metadata: that promotes
    benign certificate infrastructure such as CRL and timestamp URLs into fake
    IoCs. Only promote artifacts tied to tasks/signatures at or above
    ``min_report_score``.
    """
    sample = report.get("sample") or {}
    summary_doc = report.get("summary") or {}
    overview = report.get("overview") or {}
    thirdparty = report.get("thirdparty") or {}
    static = report.get("static") or {}
    sample_id = report.get("sample_id") or sample.get("id") or summary_doc.get("sample") or _dig(overview, "sample", "id")
    out: dict[str, Any] = {
        "sample_id": sample_id,
        "status": sample.get("status") or summary_doc.get("status"),
        "score": summary_doc.get("score") or _dig(static, "analysis", "score"),
        "target": sample.get("filename") or summary_doc.get("target") or _dig(static, "sample", "target"),
        "sha256": sample.get("sha256") or summary_doc.get("sha256") or _dig(static, "sample", "sha256"),
        "min_report_score": min_report_score,
        "signatures": [],
        "high_score_tasks": [],
        "selected_files": [],
        "selected_file_hashes": [],
        "iocs": {"sha256": [], "sha1": [], "md5": [], "urls": [], "domains": [], "ips": []},
    }

    if out.get("sha256"):
        out["iocs"]["sha256"].append(str(out["sha256"]))

    high_targets: set[str] = set()
    tasks = summary_doc.get("tasks") if isinstance(summary_doc.get("tasks"), dict) else {}
    for task_id, task in (tasks or {}).items():
        if not isinstance(task, dict):
            continue
        score = int(task.get("score") or 0)
        if score < min_report_score:
            continue
        target = task.get("target") or task.get("task") or task.get("pick")
        out["high_score_tasks"].append(
            {
                "id": str(task_id),
                "kind": task.get("kind"),
                "score": score,
                "target": target,
                "sigs": task.get("sigs"),
                "os": task.get("os"),
            }
        )
        if target:
            high_targets.add(str(target).split("/")[-1])
            if str(target) not in out["selected_files"]:
                out["selected_files"].append(str(target))

    for sig in (overview.get("signatures") or []) + (static.get("signatures") or []):
        if not isinstance(sig, dict):
            continue
        score = int(sig.get("score") or 0)
        if score < min_report_score:
            continue
        name = sig.get("name") or sig.get("label")
        if name and name not in out["signatures"]:
            out["signatures"].append(str(name))
        for indicator in sig.get("indicators") or []:
            if isinstance(indicator, dict):
                resource = indicator.get("resource") or indicator.get("ioc")
                if resource:
                    high_targets.add(str(resource).split("/")[-1])

    for target in overview.get("targets") or []:
        if not isinstance(target, dict):
            continue
        score = int(target.get("score") or 0)
        if score < min_report_score:
            continue
        target_name = target.get("target") or target.get("name")
        if target_name:
            out["high_score_tasks"].append(
                {
                    "id": str(target.get("task") or target.get("id") or target_name),
                    "kind": target.get("kind"),
                    "score": score,
                    "target": target_name,
                    "sigs": [s.get("label") or s.get("name") for s in target.get("signatures") or [] if isinstance(s, dict)],
                    "os": target.get("os"),
                }
            )
            if str(target_name) not in out["selected_files"]:
                out["selected_files"].append(str(target_name))
            high_targets.add(str(target_name).split("/")[-1])
        for sig in target.get("signatures") or []:
            if not isinstance(sig, dict):
                continue
            name = sig.get("name") or sig.get("label")
            if name and name not in out["signatures"]:
                out["signatures"].append(str(name))
        raw_iocs = target.get("iocs")
        iocs = raw_iocs if isinstance(raw_iocs, dict) else {}
        for url in iocs.get("urls") or []:
            url_s = str(url)
            if _is_likely_important_url(url_s) and url_s not in out["iocs"]["urls"]:
                out["iocs"]["urls"].append(url_s)
        for domain in iocs.get("domains") or []:
            domain_s = str(domain).strip().strip(".")
            if _is_likely_important_domain(domain_s) and domain_s not in out["iocs"]["domains"]:
                out["iocs"]["domains"].append(domain_s)
        for ip in iocs.get("ips") or []:
            ip_s = str(ip).strip()
            if ip_s and _is_likely_important_ip(ip_s, out["iocs"]["urls"]) and ip_s not in out["iocs"]["ips"]:
                out["iocs"]["ips"].append(ip_s)

    requested = _dig(thirdparty, "risk_scores", "data", "requested")
    if isinstance(requested, dict):
        # tria.ge risk-score requested lists include browser/OS background traffic.
        # Promote only values that look like payload, campaign, or suspicious staging infrastructure.
        for url in requested.get("url") or []:
            url_s = str(url)
            if _is_likely_important_url(url_s) and url_s not in out["iocs"]["urls"]:
                out["iocs"]["urls"].append(url_s)
        for domain in requested.get("domain") or []:
            domain_s = str(domain).strip().strip(".")
            if _is_likely_important_domain(domain_s) and domain_s not in out["iocs"]["domains"]:
                out["iocs"]["domains"].append(domain_s)

    for f in static.get("files") or []:
        if not isinstance(f, dict):
            continue
        filename = str(f.get("filename") or f.get("relpath") or "")
        if not filename or filename.split("/")[-1] not in high_targets:
            continue
        if filename not in out["selected_files"]:
            out["selected_files"].append(filename)
        hash_ref = {"filename": filename}
        for key in ("sha256", "sha1", "md5"):
            val = f.get(key)
            if val:
                hash_ref[key] = str(val)
            if val and val not in out["iocs"][key]:
                out["iocs"][key].append(str(val))
        if any(k in hash_ref for k in ("sha256", "sha1", "md5")) and hash_ref not in out["selected_file_hashes"]:
            out["selected_file_hashes"].append(hash_ref)

    for key, limit in (("sha256", 30), ("sha1", 30), ("md5", 30), ("urls", 30), ("domains", 50), ("ips", 50)):
        out["iocs"][key] = out["iocs"][key][:limit]
    out["signatures"] = out["signatures"][:20]
    out["high_score_tasks"] = out["high_score_tasks"][:30]
    out["selected_files"] = out["selected_files"][:30]
    return out


def write_triage_report_outputs(out_dir: Path, sample_id: str, report: dict[str, Any]) -> dict[str, Path]:
    """Write tria.ge report JSON and IOC Markdown summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", sample_id)
    json_path = out_dir / f"triage_report_{safe_id}.json"
    md_path = out_dir / f"triage_report_{safe_id}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    s = report.get("summary_iocs") or summarize_triage_report(report)
    lines = [
        f"# tria.ge report summary — `{safe_id}`",
        "",
        f"- Status: `{s.get('status')}`",
        f"- Score: `{s.get('score')}`",
        f"- Target: `{s.get('target')}`",
        f"- SHA256: `{s.get('sha256')}`",
        "",
        "## High-scoring tria.ge tasks",
    ]
    for task in s.get("high_score_tasks") or []:
        lines.append(
            f"- score `{task.get('score')}` `{task.get('kind')}` target `{task.get('target')}`"
            f" os `{task.get('os')}` sigs `{task.get('sigs')}`"
        )
    if not s.get("high_score_tasks"):
        lines.append(f"- none at or above score `{s.get('min_report_score')}`")
    lines.extend(["", "## Signatures at threshold"])
    for sig in s.get("signatures") or []:
        lines.append(f"- {sig}")
    if not s.get("signatures"):
        lines.append(f"- none at or above score `{s.get('min_report_score')}`")
    lines.extend(["", "## Selected / high-scoring files"])
    file_hashes = s.get("selected_file_hashes") or []
    if file_hashes:
        for f in file_hashes:
            parts = [f"`{f.get('filename')}`"]
            for key in ("sha256", "sha1", "md5"):
                if f.get(key):
                    parts.append(f"{key} `{f.get(key)}`")
            lines.append("- " + " — ".join(parts))
    else:
        for f in s.get("selected_files") or []:
            lines.append(f"- `{f}`")
    if not s.get("selected_files") and not file_hashes:
        lines.append(f"- none at or above score `{s.get('min_report_score')}`")
    lines.extend(["", "## IoCs"])
    labels = [("sha256", "SHA256"), ("sha1", "SHA1"), ("md5", "MD5"), ("urls", "URLs"), ("domains", "Domains"), ("ips", "IPs")]
    for key, label in labels:
        vals = (s.get("iocs") or {}).get(key) or []
        lines.append(f"### {label}")
        if vals:
            for val in vals:
                lines.append(f"- `{val}`")
        else:
            lines.append("- none observed in pulled report surfaces")
        lines.append("")
    if report.get("errors"):
        lines.append("## Pull errors")
        for err in report.get("errors") or []:
            lines.append(f"- `{err.get('surface')}`: `{(err.get('error') or {}).get('status')}` `{(err.get('error') or {}).get('error')}`")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"json": json_path, "md": md_path}


def _extract_js_object_after_marker(html: str, marker: str) -> dict[str, Any]:
    start = html.find(marker)
    if start < 0:
        return {}
    brace = html.find("{", start + len(marker))
    if brace < 0:
        return {}
    depth = 0
    in_string = False
    quote = ""
    escape = False
    end = -1
    for idx in range(brace, len(html)):
        ch = html[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_string = False
            continue
        if ch in ("'", '"'):
            in_string = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    if end < 0:
        return {}
    block = html[brace:end]
    block = re.sub(r"(?<=[{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", r'"\1":', block)
    try:
        parsed = json.loads(block)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_page_data_from_public_html(html: str) -> dict[str, Any]:
    """Extract browser-visible page data embedded in tria.ge's public report page."""
    data = {}
    overview = _extract_js_object_after_marker(html, "overview:")
    thirdparty = _extract_js_object_after_marker(html, "thirdparty:")
    if overview:
        data["overview"] = overview
    if thirdparty:
        data["thirdparty"] = thirdparty
    return data


def _extract_overview_from_public_html(html: str) -> dict[str, Any]:
    """Extract the overview object embedded in tria.ge's public report page."""
    return _extract_page_data_from_public_html(html).get("overview") or {}


def _is_benign_report_domain(domain: str) -> bool:
    d = domain.lower().strip(".")
    if not d or _is_certificate_noise_domain(d) or _is_certificate_oid_token(d):
        return True
    if d in BENIGN_REPORT_HOSTS:
        return True
    if any(d == suffix.lstrip(".") or d.endswith(suffix) for suffix in BENIGN_REPORT_DOMAIN_SUFFIXES):
        return True
    if d.endswith(".ip6.arpa") or d.endswith(".in-addr.arpa"):
        return True
    return False


def _is_likely_important_domain(domain: str) -> bool:
    d = domain.lower().strip(".")
    if not d or _is_benign_report_domain(d):
        return False
    try:
        ipaddress.ip_address(d)
        return False
    except ValueError:
        pass
    if any(token in d for token in ("microsoft", "msedge", "azure", "bing", "copilot", "windows", "akamaiedge", "cloudflare")):
        return False
    suspicious_tokens = ("c2", "ggr", "sro", "m36", "akasia", "pelors", "peluang", "telegram", "steamcommunity", "dropbox", "github", "launcher", "download", "setup", "payload")
    if any(token in d for token in suspicious_tokens):
        return True
    return False


def _is_likely_important_url(url: str) -> bool:
    if _is_certificate_noise_url(url):
        return False
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().strip(".")
    path = (parsed.path or "").lower()
    if not host or _is_benign_report_domain(host):
        return False
    if is_static_or_decorative_url(url):
        return False
    if host in {"t.me", "telegram.me"} or host.endswith(".t.me"):
        return True
    if host == "steamcommunity.com" and "/profiles/" in path:
        return True
    if any(path.endswith(ext) for ext in IMPORTANT_URL_EXTENSIONS):
        return True
    if any(token in host for token in ("ggr", "launcher", "download", "github")):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _is_likely_important_ip(ip: str, urls: list[str]) -> bool:
    if _is_certificate_oid_token(ip):
        return False
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved:
        return False
    return any((urllib.parse.urlparse(u).hostname or "") == ip for u in urls)


def _is_certificate_noise_url(url: str) -> bool:
    """Return True for routine certificate/CRL/OCSP infrastructure URLs."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if path.endswith(".crl") or "/crl/" in path:
        return True
    if host.startswith(("crl.", "crl3.", "crl4.", "ocsp.", "ocsp2.")):
        return True
    if host in CERTIFICATE_INFRASTRUCTURE_HOSTS:
        return True
    return False


def _is_certificate_noise_domain(domain: str) -> bool:
    """Return True for certificate infrastructure hosts and extracted CRL/PDB filenames."""
    d = domain.lower().strip(".")
    if d.endswith((".crl", ".pdb")):
        return True
    if d.startswith(("crl.", "crl3.", "crl4.", "ocsp.", "ocsp2.")):
        return True
    if d in CERTIFICATE_INFRASTRUCTURE_HOSTS:
        return True
    return False


def _is_certificate_oid_token(token: str) -> bool:
    """Filter ASN.1/X.509 OID prefixes that are often scraped as IPv4-looking IoCs."""
    return token.startswith(("1.2.840.", "1.3.6.", "2.5.4."))


def _dig(obj: dict[str, Any], *path: str) -> Any:
    cur: Any = obj
    for item in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(item)
    return cur


def _summarize_search_hit(hit: dict[str, Any]) -> dict[str, Any]:
    fields = ("id", "sample", "target", "kind", "score", "created", "completed", "status")
    return {k: hit.get(k) for k in fields if k in hit}


def _safe_small_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep response context small and avoid storing arbitrary blobs in reports."""
    keep = ("id", "sample", "task_id", "status", "kind", "target", "created")
    return {k: payload.get(k) for k in keep if k in payload}
