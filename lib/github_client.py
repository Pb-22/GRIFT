"""GitHub REST helpers for SEO hunt."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


class GitHubRateLimitError(RuntimeError):
    def __init__(self, message: str, reset_epoch: Optional[int] = None):
        super().__init__(message)
        self.reset_epoch = reset_epoch


class GitHubClient:
    def __init__(self, token: Optional[str] = None, user_agent: str = "github-seo-hunt/1.0"):
        self.token = token
        self.user_agent = user_agent
        self._last_request = 0.0

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _throttle(self, min_interval: float = 0.8) -> None:
        interval = 0.35 if self.token else min_interval
        now = time.time()
        wait = interval - (now - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def get_json(self, url: str, params: Optional[dict] = None) -> Any:
        self._throttle()
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            reset = e.headers.get("X-RateLimit-Reset")
            reset_epoch = int(reset) if reset and reset.isdigit() else None
            if e.code in (403, 429) and ("rate limit" in err_body.lower() or e.headers.get("X-RateLimit-Remaining") == "0"):
                raise GitHubRateLimitError(
                    f"GitHub rate limit for {url}: {err_body}", reset_epoch=reset_epoch
                ) from e
            raise RuntimeError(f"GitHub HTTP {e.code} for {url}: {err_body}") from e

    def search_repositories(
        self,
        query: str,
        *,
        sort: str = "updated",
        order: str = "desc",
        per_page: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        return self.get_json(
            "https://api.github.com/search/repositories",
            {
                "q": query,
                "sort": sort,
                "order": order,
                "per_page": str(per_page),
                "page": str(page),
            },
        )

    def search_code(
        self,
        query: str,
        *,
        sort: str = "indexed",
        order: str = "desc",
        per_page: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("GitHub code search requires GITHUB_TOKEN")
        return self.get_json(
            "https://api.github.com/search/code",
            {
                "q": query,
                "sort": sort,
                "order": order,
                "per_page": str(per_page),
                "page": str(page),
            },
        )

    def repo(self, full_name: str) -> dict[str, Any]:
        return self.get_json(f"https://api.github.com/repos/{full_name}")

    def contents(self, full_name: str, path: str = "") -> Any:
        p = f"https://api.github.com/repos/{full_name}/contents"
        if path:
            p += f"/{path.lstrip('/')}"
        return self.get_json(p)

    def releases(self, full_name: str, per_page: int = 5) -> list:
        data = self.get_json(
            f"https://api.github.com/repos/{full_name}/releases",
            {"per_page": str(per_page)},
        )
        return data if isinstance(data, list) else []

    def user(self, login: str) -> dict[str, Any]:
        return self.get_json(f"https://api.github.com/users/{login}")

    def user_repos(self, login: str, per_page: int = 15) -> list:
        data = self.get_json(
            f"https://api.github.com/users/{login}/repos",
            {"sort": "created", "per_page": str(per_page)},
        )
        return data if isinstance(data, list) else []

    def contributors_count(self, full_name: str, cap: int = 3) -> int:
        """Return observed contributor count up to cap; cap is enough for suppressors."""
        data = self.get_json(
            f"https://api.github.com/repos/{full_name}/contributors",
            {"per_page": str(max(1, min(cap, 100))), "anon": "false"},
        )
        return len(data) if isinstance(data, list) else 0

    def raw_readme(self, full_name: str, branch: str = "main") -> str:
        self._throttle()
        for b in (branch, "master", "main"):
            url = f"https://raw.githubusercontent.com/{full_name}/{b}/README.md"
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError:
                continue
            except Exception:
                continue
        return ""
