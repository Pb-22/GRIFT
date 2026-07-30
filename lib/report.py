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
