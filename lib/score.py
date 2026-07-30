"""Heuristic scoring for GitHub SEO malware candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def score_candidate(
    *,
    repo: dict[str, Any],
    owner: dict[str, Any],
    contents: Any,
    releases: list,
    readme: str,
    extracted: dict[str, Any],
    official_orgs: list[str],
    brand_name: str,
    official_domains: Optional[list[str]] = None,
    contributor_count_seen: Optional[int] = None,
    skip_contributors_gte: int = 3,
    skip_top_files_gte: int = 6,
    skip_stars_gte: int = 10,
    skip_forks_gte: int = 3,
    wrong_product_terms: Optional[list[str]] = None,
    target_context_terms: Optional[list[str]] = None,
    ambiguous_brand: bool = False,
    product_aliases: Optional[list[dict[str, str]]] = None,
) -> dict[str, Any]:
    """
    Return score, reasons, and flags. Higher = more like SEO malware lure.
    Negative reasons reduce score (likely benign / official).
    """
    official_domains = official_domains or []
    wrong_product_terms = wrong_product_terms or []
    target_context_terms = target_context_terms or []
    product_aliases = product_aliases or []
    reasons: list[str] = []
    score = 0

    owner_login = (repo.get("owner") or {}).get("login") or owner.get("login") or ""
    owner_type = (repo.get("owner") or {}).get("type") or owner.get("type") or ""
    full_name = repo.get("full_name") or ""

    # Official allowlists are hard suppressors.
    if owner_login.lower() in {o.lower() for o in official_orgs}:
        return {
            "score": -20,
            "reasons": [f"[-20] official org allowlist: {owner_login}"],
            "flags": ["official"],
            "drop": True,
        }
    if full_name.lower() in {d.lower().replace("https://", "").replace("http://", "").strip("/") for d in official_domains}:
        return {
            "score": -20,
            "reasons": [f"[-20] official repository/domain allowlist: {full_name}"],
            "flags": ["official"],
            "drop": True,
        }

    context_blob = " ".join(
        [
            full_name,
            repo.get("name") or "",
            repo.get("description") or "",
            (readme or "")[:4000],
        ]
    ).lower()
    wrong_hits = [t for t in wrong_product_terms if t.lower() in context_blob]
    if wrong_hits:
        return {
            "score": -20,
            "reasons": [f"[-20] wrong product/context term(s): {', '.join(wrong_hits[:5])}"],
            "flags": ["wrong_product"],
            "drop": True,
        }

    # Contents shape
    file_names: list[str] = []
    meaningful: list[str] = []
    if isinstance(contents, list):
        file_names = [c.get("name", "") for c in contents if isinstance(c, dict)]
    elif isinstance(contents, dict) and contents.get("message"):
        reasons.append("[+0] empty or inaccessible tree")

    if file_names:
        meaningful = [f for f in file_names if f not in (".gitattributes", ".gitignore")]

    stars = repo.get("stargazers_count") or 0
    forks = repo.get("forks_count") or 0

    # Generic repo-shape hard suppressors for short-lived SEO malware hunting.
    if contributor_count_seen is not None and contributor_count_seen >= skip_contributors_gte:
        return {
            "score": -20,
            "reasons": [f"[-20] repo-shape suppressor: {contributor_count_seen} contributors observed"],
            "flags": ["repo_shape_suppressor"],
            "drop": True,
            "contributor_count_seen": contributor_count_seen,
            "top_level_file_count": len(meaningful),
        }
    if meaningful and len(meaningful) >= skip_top_files_gte:
        return {
            "score": -20,
            "reasons": [f"[-20] repo-shape suppressor: {len(meaningful)} top-level files"],
            "flags": ["repo_shape_suppressor"],
            "drop": True,
            "contributor_count_seen": contributor_count_seen,
            "top_level_file_count": len(meaningful),
        }
    if stars >= skip_stars_gte:
        return {
            "score": -20,
            "reasons": [f"[-20] repo-shape suppressor: {stars} stars"],
            "flags": ["repo_shape_suppressor"],
            "drop": True,
            "contributor_count_seen": contributor_count_seen,
            "top_level_file_count": len(meaningful),
        }
    if forks >= skip_forks_gte:
        return {
            "score": -20,
            "reasons": [f"[-20] repo-shape suppressor: {forks} forks"],
            "flags": ["repo_shape_suppressor"],
            "drop": True,
            "contributor_count_seen": contributor_count_seen,
            "top_level_file_count": len(meaningful),
        }

    only_readme = False
    if meaningful:
        if meaningful == ["README.md"] or meaningful == ["README"]:
            only_readme = True
            score += 3
            reasons.append("[+3] tree is README-only")
        elif len(meaningful) <= 2 and any("readme" in f.lower() for f in meaningful):
            score += 2
            reasons.append(f"[+2] very thin tree ({len(meaningful)} items)")
        elif len(meaningful) >= 8:
            score -= 2
            reasons.append(f"[-2] substantial tree ({len(meaningful)} top-level items)")

    size = repo.get("size") or 0  # KB
    if size is not None and size <= 20 and only_readme:
        score += 1
        reasons.append(f"[+1] tiny repo size ({size} KB)")
    elif size and size > 5000:
        score -= 1
        reasons.append(f"[-1] large repo size ({size} KB)")

    if contributor_count_seen == 1:
        score += 2
        reasons.append("[+2] one contributor observed")
    elif contributor_count_seen == 2:
        score -= 3
        reasons.append("[-3] two contributors observed")

    if len(meaningful) in (4, 5):
        score -= 3
        reasons.append(f"[-3] medium top-level file count ({len(meaningful)})")

    if stars == 0:
        score += 1
        reasons.append("[+1] zero stars")
    elif 3 <= stars < skip_stars_gte:
        score -= 2
        reasons.append(f"[-2] non-zero stars ({stars})")

    if forks == 0:
        score += 1
        reasons.append("[+1] zero forks")
    elif 1 <= forks < skip_forks_gte:
        score -= 2
        reasons.append(f"[-2] non-zero forks ({forks})")

    followers = owner.get("followers") or 0
    public_repos = owner.get("public_repos") or 0
    if followers == 0:
        score += 1
        reasons.append("[+1] owner has 0 followers")

    repo_created = _parse_ts(repo.get("created_at"))
    owner_created = _parse_ts(owner.get("created_at"))
    if repo_created and owner_created:
        delta = abs((repo_created - owner_created).total_seconds())
        if delta <= 48 * 3600:
            score += 2
            reasons.append("[+2] owner created within 48h of repo")
            if delta <= 24 * 3600:
                score += 1
                reasons.append("[+1] repo is very young relative to owner / same-day creation")
        elif delta <= 14 * 86400:
            score += 1
            reasons.append("[+1] owner created within 14d of repo")

    # Description / name SEO language
    desc = (repo.get("description") or "") + " " + (repo.get("name") or "")
    desc_l = desc.lower()
    brand_l = brand_name.lower()
    seo_words = ("download", "windows", "free", "installer", "crack", "activator", "full")
    hits = sum(1 for w in seo_words if w in desc_l)
    if hits >= 2:
        score += 2
        reasons.append(f"[+2] SEO-ish description/name ({hits} keywords)")
    elif "download" in desc_l:
        score += 1
        reasons.append("[+1] 'download' in name/description")

    if brand_l and brand_l in (repo.get("name") or "").lower().replace("-", " "):
        if "download" in (repo.get("name") or "").lower():
            score += 2
            reasons.append("[+2] brand + Download in repo name")

    dl = extracted.get("download_urls") or {}
    passwords = extracted.get("passwords") or []
    if extracted.get("has_password_language"):
        score += 2
        reasons.append("[+2] README mentions password")
    if passwords:
        score += 2
        reasons.append(f"[+2] password candidate(s): {', '.join(passwords[:3])}")
        if any(p.lower() == "github" for p in passwords):
            score += 1
            reasons.append("[+1] password is classic 'github'")

    payload_urls = list(dl.get("payload") or [])
    unknown_urls = [u for u in (dl.get("unknown_external") or []) if not _is_official_url(u, official_domains)]
    alias_full_hits = []
    alias_acronym_hits = []
    for alias in product_aliases:
        full = (alias.get("full") or "").lower()
        acronym = (alias.get("acronym") or "").lower()
        if full and full in context_blob:
            alias_full_hits.append(alias.get("full") or full)
        if acronym and _wordish_contains(context_blob, acronym):
            alias_acronym_hits.append(alias.get("acronym") or acronym)
    target_hits = [t for t in target_context_terms if t.lower() in context_blob]
    lure_has_delivery_signal = bool(payload_urls or passwords or extracted.get("has_password_language"))
    if alias_full_hits:
        phrase_score = 3 if lure_has_delivery_signal or hits >= 2 else 1
        score += phrase_score
        reasons.append(f"[+{phrase_score}] full product phrase matched: {', '.join(alias_full_hits[:2])}")
    elif alias_acronym_hits and ambiguous_brand:
        score -= 2
        reasons.append(f"[-2] acronym-only ambiguous match: {', '.join(alias_acronym_hits[:2])}")
    if ambiguous_brand and target_context_terms and not target_hits and not alias_full_hits and not lure_has_delivery_signal:
        score -= 10
        reasons.append("[-10] ambiguous brand lacks target context or delivery signal")
    elif target_hits:
        score += 1
        reasons.append(f"[+1] target context term(s): {', '.join(target_hits[:3])}")
    if payload_urls:
        score += 3
        reasons.append(f"[+3] payload/download URL(s) ({len(payload_urls)}) e.g. {payload_urls[0][:80]}")
    elif unknown_urls:
        score += 1
        reasons.append(f"[+1] unknown external URL(s) ({len(unknown_urls)}) e.g. {unknown_urls[0][:80]}")

    # Keep specific reasons for high-signal payload classes.
    if dl.get("dropbox"):
        reasons.append(f"[+0] payload host is Dropbox ({len(dl['dropbox'])})")
    if dl.get("telegram"):
        reasons.append(f"[+0] payload host is Telegram ({len(dl['telegram'])})")
    if dl.get("github_release"):
        reasons.append("[+0] payload is GitHub Releases asset")

    asset_count = 0
    for rel in releases or []:
        for a in rel.get("assets") or []:
            asset_count += 1
            name = (a.get("name") or "").lower()
            if name.endswith((".zip", ".exe", ".rar", ".7z", ".msi")):
                score += 1
                reasons.append(f"[+1] binary release asset: {a.get('name')}")
                break

    if public_repos and public_repos <= 2:
        score += 1
        reasons.append(f"[+1] owner has only {public_repos} public repo(s)")
    elif public_repos and public_repos >= 20:
        score -= 1
        reasons.append(f"[-1] owner has many repos ({public_repos})")

    if ambiguous_brand and not lure_has_delivery_signal and score >= 8:
        score = 7
        reasons.append("[-cap] ambiguous brand without delivery signal capped below high")

    student_words = ("school management", "student management", "assignment", "coursework", "semester")
    blob = (desc + " " + (readme or "")[:2000]).lower()
    if any(w in blob for w in student_words):
        score -= 3
        reasons.append("[-3] student/homework language")

    flags = []
    if score >= 8:
        flags.append("high")
    elif score >= 4:
        flags.append("medium")
    elif score >= 1:
        flags.append("low")
    else:
        flags.append("benign_leaning")

    return {
        "score": score,
        "reasons": reasons,
        "flags": flags,
        "drop": False,
        "only_readme": only_readme,
        "file_names": file_names[:30],
        "owner_login": owner_login,
        "owner_type": owner_type,
        "stars": stars,
        "forks": forks,
        "passwords": passwords,
        "download_urls": dl,
        "asset_count": asset_count,
        "contributor_count_seen": contributor_count_seen,
        "top_level_file_count": len(meaningful),
    }


def _wordish_contains(text: str, term: str) -> bool:
    return bool(__import__("re").search(r"(?<![A-Za-z0-9])" + __import__("re").escape(term) + r"(?![A-Za-z0-9])", text, __import__("re").IGNORECASE))


def _is_official_url(url: str, official_domains: list[str]) -> bool:
    if not official_domains:
        return False
    parsed = urlparse(url)
    host_path = ((parsed.netloc or "") + (parsed.path or "")).lower().strip("/")
    for d in official_domains:
        d_norm = d.lower().replace("https://", "").replace("http://", "").strip("/")
        if host_path.startswith(d_norm) or (parsed.netloc or "").lower() == d_norm:
            return True
    return False
