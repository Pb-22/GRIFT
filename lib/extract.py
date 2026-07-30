"""Extract download URLs and archive passwords from README text."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


URL_RE = re.compile(r"https?://[^\s\)\]\>\"']+", re.IGNORECASE)

# Prefer explicit labels. The older broad regex produced false positives such as
# "word" from prose like "password word".
PASSWORD_CODE_RE = re.compile(
    r"(?:archive\s+)?(?:password|passwd|pass)\s*(?:is|=|:|-|–)?\s*(?:`([^`\n]{3,64})`|\*\*([^*\n]{3,64})\*\*)",
    re.IGNORECASE,
)
PASSWORD_LABEL_RE = re.compile(
    r"(?:archive\s+)?(?:password|passwd|pass)\s*(?:is|=|:|-|–)\s*([A-Za-z0-9_\-]{3,32})",
    re.IGNORECASE,
)
COMMON_FALSE_PASSWORDS = {
    "password",
    "passwd",
    "pass",
    "word",
    "the",
    "this",
    "that",
    "archive",
    "file",
    "below",
    "above",
    "install",
    "installer",
    "download",
    "downloads",
    "button",
    "official",
}

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp")
PAYLOAD_EXTENSIONS = (".zip", ".exe", ".msi", ".rar", ".7z", ".dll", ".iso")
DECORATIVE_HOST_FRAGMENTS = (
    "img.shields.io",
    "camo.githubusercontent",
    "raw.githubusercontent.com",
    "user-images.githubusercontent",
    "wikipedia.org",
    "wikimedia.org",
    "cdn.intheloop.io",
    "forum.audacityteam.org",
)
LIKELY_PAYLOAD_HOST_FRAGMENTS = (
    "dropbox.com",
    "dropboxusercontent.com",
    "github.help",
    "git-launcher.com",
    "github.io",
)


def extract_from_readme(text: str) -> dict[str, Any]:
    if not text:
        return {
            "urls": [],
            "passwords": [],
            "has_password_language": False,
            "download_urls": classify_urls([]),
        }

    urls = []
    seen = set()
    for m in URL_RE.finditer(text):
        u = m.group(0).rstrip(".,);\"'")
        if u not in seen:
            seen.add(u)
            urls.append(u)

    passwords: list[str] = []
    for regex in (PASSWORD_CODE_RE, PASSWORD_LABEL_RE):
        for m in regex.finditer(text):
            p = (m.group(1) or (m.group(2) if len(m.groups()) > 1 else "") or "").strip()
            cleaned = p.strip("`* .,:;[](){}\"'")
            if not _valid_password_candidate(cleaned):
                continue
            if cleaned not in passwords:
                passwords.append(cleaned)

    has_pw_lang = bool(re.search(r"\b(password|passwd)\b", text, re.I) or re.search(r"\bpass\s*[:=]", text, re.I))

    return {
        "urls": urls,
        "passwords": passwords,
        "has_password_language": has_pw_lang,
        "download_urls": classify_urls(urls),
    }


def _valid_password_candidate(value: str) -> bool:
    if not value:
        return False
    if len(value) < 3 or len(value) > 32:
        return False
    if value.lower() in COMMON_FALSE_PASSWORDS:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", value):
        return False
    return True


def classify_urls(urls: list[str]) -> dict[str, list[str]]:
    out = {
        "payload": [],
        "decorative": [],
        "official_or_docs": [],
        "unknown_external": [],
        "local_dev": [],
        # Backward-compatible buckets used by older reports/scoring.
        "dropbox": [],
        "telegram": [],
        "github_release": [],
        "short_or_other": [],
        "github_other": [],
    }
    for u in urls:
        parsed = urlparse(u)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        url_l = u.lower()

        if _is_decorative(host, path):
            out["decorative"].append(u)
            continue

        if _is_local_dev_host(host):
            out["local_dev"].append(u)
            continue

        if "dropbox.com" in host or "dropboxusercontent.com" in host:
            out["dropbox"].append(u)
            out["payload"].append(u)
        elif host in ("t.me", "telegram.me") or "t.me/" in url_l:
            out["telegram"].append(u)
            out["payload"].append(u)
        elif "github.com" in host and "/releases/" in path:
            out["github_release"].append(u)
            out["payload"].append(u)
        elif "github.com" in host or "githubusercontent.com" in host:
            out["github_other"].append(u)
            if any(path.endswith(ext) for ext in PAYLOAD_EXTENSIONS):
                out["payload"].append(u)
            else:
                out["official_or_docs"].append(u)
        elif _is_likely_payload_url(host, path):
            out["short_or_other"].append(u)
            out["payload"].append(u)
        elif _looks_official_or_docs(host):
            out["official_or_docs"].append(u)
        else:
            out["unknown_external"].append(u)
            out["short_or_other"].append(u)
    return out


def _is_decorative(host: str, path: str) -> bool:
    if any(x in host for x in DECORATIVE_HOST_FRAGMENTS):
        return True
    return path.endswith(IMAGE_EXTENSIONS)


def _is_local_dev_host(host: str) -> bool:
    bare = host.split(":", 1)[0]
    return bare in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _is_likely_payload_url(host: str, path: str) -> bool:
    if any(x in host for x in LIKELY_PAYLOAD_HOST_FRAGMENTS):
        return True
    if any(path.endswith(ext) for ext in PAYLOAD_EXTENSIONS):
        return True
    return False


def _looks_official_or_docs(host: str) -> bool:
    return host.startswith("docs.") or "readthedocs" in host or host.endswith(".org")
