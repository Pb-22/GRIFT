"""Write hunt outputs (JSON, CSV, Markdown)."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def defang_text(text: str) -> str:
    """Defang URLs/domains for analyst Markdown reports."""
    text = text.replace("https://", "hxxps://").replace("http://", "hxxp://")
    text = re.sub(r"(?<=\w)\.(?=\w)", "[.]", text)
    # Preserve common prose abbreviations that are not indicators.
    text = text.replace("e[.]g.", "e.g.").replace("i[.]e.", "i.e.")
    return text


def maybe_defang(text: Any, enabled: bool) -> str:
    s = "" if text is None else str(text)
    return defang_text(s) if enabled else s


def write_outputs(
    out_dir: Path,
    *,
    candidates: list[dict[str, Any]],
    meta: dict[str, Any],
    defang_markdown: bool = True,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    paths = {}

    json_path = out_dir / f"candidates_{ts}.json"
    json_path.write_text(
        json.dumps({"meta": meta, "candidates": candidates}, indent=2),
        encoding="utf-8",
    )
    paths["json"] = json_path

    latest = out_dir / "candidates_latest.json"
    latest.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    paths["json_latest"] = latest

    csv_path = out_dir / f"candidates_{ts}.csv"
    fields = [
        "score",
        "brand",
        "full_name",
        "html_url",
        "created_at",
        "stars",
        "flags",
        "passwords",
        "top_reasons",
        "payload",
        "dropbox",
        "telegram",
        "offsite",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in candidates:
            sc = c.get("score_result") or {}
            dl = sc.get("download_urls") or {}
            w.writerow(
                {
                    "score": sc.get("score"),
                    "brand": c.get("brand"),
                    "full_name": c.get("full_name"),
                    "html_url": c.get("html_url"),
                    "created_at": c.get("created_at"),
                    "stars": sc.get("stars"),
                    "flags": ",".join(sc.get("flags") or []),
                    "passwords": "|".join(sc.get("passwords") or []),
                    "top_reasons": " ; ".join((sc.get("reasons") or [])[:6]),
                    "payload": "|".join((dl.get("payload") or [])[:3]),
                    "dropbox": "|".join((dl.get("dropbox") or [])[:3]),
                    "telegram": "|".join((dl.get("telegram") or [])[:3]),
                    "offsite": "|".join((dl.get("unknown_external") or [])[:3]),
                }
            )
    paths["csv"] = csv_path

    md_path = out_dir / f"report_{ts}.md"
    lines = [
        "# GitHub SEO hunt report",
        "",
        f"- Generated (UTC): `{meta.get('generated_at')}`",
        f"- Created filter: `{meta.get('created_after')}`",
        f"- Brands: {', '.join(meta.get('brands') or [])}",
        f"- Candidates scored: **{len(candidates)}**",
        f"- Min score in report filter: `{meta.get('min_score')}`",
        f"- Markdown URLs defanged: `{defang_markdown}`",
    ]
    triage_meta = meta.get("triage") if isinstance(meta.get("triage"), dict) else {}
    if triage_meta:
        lines.extend(
            [
                f"- tria.ge Stage 2: `{triage_meta.get('status')}`",
                f"  - eligible candidates: `{triage_meta.get('eligible_candidates', 0)}`",
                f"  - candidates with payload targets: `{triage_meta.get('candidates_considered', 0)}`",
                f"  - candidates without payload targets: `{triage_meta.get('candidates_without_targets', 0)}`",
                f"  - static/decorative targets skipped: `{triage_meta.get('static_targets_skipped', 0)}`",
                f"  - targets considered: `{triage_meta.get('targets_considered', 0)}`",
                f"  - lookups attempted: `{triage_meta.get('lookups_attempted', 0)}`",
                f"  - duplicate target lookups reused: `{triage_meta.get('duplicate_targets_reused', 0)}`",
                f"  - submissions attempted: `{triage_meta.get('submits_attempted', 0)}`",
                f"  - duplicate submissions reused: `{triage_meta.get('duplicate_submissions_reused', 0)}`",
                f"  - lookup matches: `{triage_meta.get('lookup_matches', 0)}`",
                f"  - errors: `{triage_meta.get('errors', 0)}`",
            ]
        )
    elif meta.get("triage_lookup_requested") or meta.get("triage_submit_requested"):
        lines.append(f"- tria.ge Stage 2: `{meta.get('triage_stage2_status') or 'requested_no_summary'}`")
    else:
        lines.append("- tria.ge Stage 2: `not requested`")
    lines.extend(
        [
            "",
            "## Top candidates",
            "",
        ]
    )
    ranked = sorted(
        candidates,
        key=lambda x: (x.get("score_result") or {}).get("score") or 0,
        reverse=True,
    )
    for c in ranked:
        sc = c.get("score_result") or {}
        if (sc.get("score") or 0) < (meta.get("min_score") or 0):
            continue
        if sc.get("drop"):
            continue
        lines.append(f"### score {sc.get('score')} — `{maybe_defang(c.get('full_name'), defang_markdown)}`")
        lines.append("")
        lines.append(f"- Brand: **{c.get('brand')}**")
        lines.append(f"- URL: {maybe_defang(c.get('html_url'), defang_markdown)}")
        lines.append(f"- Created: `{c.get('created_at')}`")
        lines.append(f"- Flags: {', '.join(sc.get('flags') or [])}")
        if sc.get("passwords"):
            lines.append(f"- Passwords seen: `{', '.join(sc.get('passwords'))}`")
        lines.append("- Reasons:")
        for r in sc.get("reasons") or []:
            lines.append(f"  - {maybe_defang(r, defang_markdown)}")
        dl = sc.get("download_urls") or {}
        for kind in ("payload", "dropbox", "telegram", "github_release", "unknown_external"):
            for u in (dl.get(kind) or [])[:5]:
                lines.append(f"  - [{kind}] {maybe_defang(u, defang_markdown)}")
        triage = c.get("triage") or {}
        if triage:
            lines.append("- tria.ge Stage 2:")
            for item in (triage.get("lookups") or [])[:5]:
                status = "ok" if item.get("ok") else "error"
                matches = item.get("matches", 0)
                lines.append(
                    f"  - lookup {status}, matches={matches}: {maybe_defang(item.get('url'), defang_markdown)}"
                )
                for hit in item.get("results") or []:
                    sample_id = hit.get("id") or hit.get("sample") or "unknown"
                    lines.append(f"    - sample: `{maybe_defang(sample_id, defang_markdown)}`")
            for item in (triage.get("submissions") or [])[:5]:
                if item.get("skipped"):
                    lines.append(
                        f"  - submit skipped ({item.get('reason', 'not submitted')}): {maybe_defang(item.get('url'), defang_markdown)}"
                    )
                    continue
                status = "ok" if item.get("ok") else "error"
                sample_id = item.get("sample_id") or "unknown"
                lines.append(
                    f"  - submit {status}, sample={maybe_defang(sample_id, defang_markdown)}: {maybe_defang(item.get('url'), defang_markdown)}"
                )
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["md"] = md_path

    latest_md = out_dir / "report_latest.md"
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    paths["md_latest"] = latest_md

    return paths


def _dedupe(values: list[Any]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _repo_final_iocs(candidate: dict[str, Any]) -> dict[str, Any] | None:
    sc = candidate.get("score_result") or {}
    triage = candidate.get("triage") or {}
    reports = triage.get("reports") or []
    files = []
    sha256s = []
    sha1s = []
    md5s = []
    urls = []
    domains = []
    samples = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        sample_id = report.get("sample_id")
        if sample_id:
            samples.append(sample_id)
        summary = report.get("summary_iocs") or {}
        for file_ref in summary.get("selected_file_hashes") or []:
            if not isinstance(file_ref, dict):
                continue
            item = {
                "filename": file_ref.get("filename"),
                "sha256": file_ref.get("sha256"),
                "md5": file_ref.get("md5"),
                "sha1": file_ref.get("sha1"),
            }
            if item not in files:
                files.append(item)
            if item.get("sha256"):
                sha256s.append(item["sha256"])
            if item.get("sha1"):
                sha1s.append(item["sha1"])
            if item.get("md5"):
                md5s.append(item["md5"])
        iocs = summary.get("iocs") or {}
        sha256s.extend(iocs.get("sha256") or [])
        sha1s.extend(iocs.get("sha1") or [])
        md5s.extend(iocs.get("md5") or [])
        urls.extend(iocs.get("urls") or [])
        domains.extend(iocs.get("domains") or [])
    sha256s = _dedupe(sha256s)
    sha1s = _dedupe(sha1s)
    md5s = _dedupe(md5s)
    urls = _dedupe(urls)
    domains = _dedupe(domains)
    samples = _dedupe(samples)
    # Only include repositories with dangerous-looking sandbox output.
    if not (files or urls or domains):
        return None
    dl = sc.get("download_urls") or {}
    return {
        "repo": candidate.get("full_name"),
        "repo_url": candidate.get("html_url"),
        "score": sc.get("score"),
        "score_summary": (sc.get("reasons") or [])[:8],
        "payload_urls": _dedupe((dl.get("payload") or []) + (dl.get("github_release") or []) + (dl.get("dropbox") or []) + (dl.get("telegram") or [])),
        "tria_ge_samples": samples,
        "files": files,
        "hashes": {"sha256": sha256s, "md5": md5s, "sha1": sha1s},
        "domains": domains,
        "urls": urls,
    }


def build_final_ioc_report(*, candidates: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    apps: dict[str, list[dict[str, Any]]] = {}
    for c in sorted(candidates, key=lambda x: (x.get("score_result") or {}).get("score") or 0, reverse=True):
        sc = c.get("score_result") or {}
        if sc.get("drop"):
            continue
        repo = _repo_final_iocs(c)
        if not repo:
            continue
        app = str(c.get("brand") or "Unknown")
        apps.setdefault(app, []).append(repo)
    return {
        "meta": {
            "generated_at": meta.get("generated_at"),
            "created_after": meta.get("created_after"),
            "brands": meta.get("brands") or [],
            "triage": meta.get("triage") or {},
            "note": "Analyst-prioritized IoCs only. Routine tria.ge/browser/OS background traffic is intentionally suppressed.",
        },
        "apps": [{"app": app, "repos": repos} for app, repos in apps.items()],
    }


def write_final_ioc_outputs(out_dir: Path, *, candidates: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = build_final_ioc_report(candidates=candidates, meta=meta)
    json_path = out_dir / f"final_iocs_{ts}.json"
    txt_path = out_dir / f"final_iocs_{ts}.txt"
    json_latest = out_dir / "final_iocs_latest.json"
    txt_latest = out_dir / "final_iocs_latest.txt"
    json_text = json.dumps(report, indent=2) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    json_latest.write_text(json_text, encoding="utf-8")
    lines = [
        "GRIFT final IoC report",
        "Analyst-prioritized tria.ge IoCs only; routine browser/OS background traffic suppressed.",
        "",
    ]
    if not report["apps"]:
        lines.append("No repositories with dangerous-looking tria.ge output were found.")
    for app in report["apps"]:
        lines.append(app["app"])
        lines.append("=" * len(app["app"]))
        lines.append("")
        for repo in app["repos"]:
            lines.append(repo["repo"] or "unknown repo")
            lines.append("-" * len(lines[-1]))
            lines.append(f"Score: {repo.get('score')} — " + "; ".join(repo.get("score_summary") or []))
            if repo.get("repo_url"):
                lines.append(f"Repo: {repo['repo_url']}")
            if repo.get("payload_urls"):
                lines.append("Payload URLs:")
                for value in repo["payload_urls"]:
                    lines.append(f"  - {value}")
            if repo.get("tria_ge_samples"):
                lines.append("tria.ge samples: " + ", ".join(repo["tria_ge_samples"]))
            lines.append("Files:")
            if repo.get("files"):
                for f in repo["files"]:
                    parts = [str(f.get("filename") or "unknown")]
                    for key in ("sha256", "md5", "sha1"):
                        if f.get(key):
                            parts.append(f"{key}={f.get(key)}")
                    lines.append("  - " + " ".join(parts))
            else:
                lines.append("  - none")
            for key, label in (("sha256", "SHA256"), ("md5", "MD5"), ("sha1", "SHA1")):
                lines.append(f"{label}:")
                values = repo.get("hashes", {}).get(key) or []
                if values:
                    for value in values:
                        lines.append(f"  - {value}")
                else:
                    lines.append("  - none")
            lines.append("Domains:")
            if repo.get("domains"):
                for value in repo["domains"]:
                    lines.append(f"  - {value}")
            else:
                lines.append("  - none")
            lines.append("URLs:")
            if repo.get("urls"):
                for value in repo["urls"]:
                    lines.append(f"  - {value}")
            else:
                lines.append("  - none")
            lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    txt_path.write_text(text, encoding="utf-8")
    txt_latest.write_text(text, encoding="utf-8")
    return {"final_json": json_path, "final_txt": txt_path, "final_json_latest": json_latest, "final_txt_latest": txt_latest}
