#!/usr/bin/env python3
"""GRIFT — GitHub README Impostor Fakeware Tracker."""

from __future__ import annotations

import argparse
import getpass
import os
import stat
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.brands import add_brand, load_brands, parse_product_line, validate_brands  # noqa: E402
from lib.enrich import enrich_top_urls  # noqa: E402
from lib.extract import extract_from_readme  # noqa: E402
from lib.github_client import GitHubClient, GitHubRateLimitError  # noqa: E402
from lib.keys import prompt_with_timeout, resolve_keys  # noqa: E402
from lib.report import write_final_ioc_outputs, write_outputs  # noqa: E402
from lib.score import score_candidate  # noqa: E402
from lib.triage import TriageClient, enrich_candidates_with_triage, write_triage_report_outputs  # noqa: E402


def build_query(base: str, created_after: Optional[str]) -> str:
    q = base.strip()
    if created_after and "created:" not in q:
        q = f"{q} created:>{created_after}"
    return q


def created_after_from_lookback_days(days: int, now: Optional[datetime] = None) -> str:
    """Return a UTC YYYY-MM-DD created-after date for a lookback window."""
    if days <= 0:
        raise ValueError("lookback days must be greater than zero")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current.astimezone(timezone.utc).date() - timedelta(days=days)).isoformat()


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _write_secret(env_file: Path, key: str, value: str) -> None:
    """Store one secret in a local dotenv file with owner-only permissions."""
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not line.startswith(f"{key}=")]
    kept.append(f"{key}={value.strip()}")
    env_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.chmod(env_file, stat.S_IRUSR | stat.S_IWUSR)


def import_apps_file(path: Path, brands_path: Path) -> list[dict[str, Any]]:
    """Import simple app seeds. Lines may be `App Name` or `'"Full Product" ACRONYM'`."""
    imported = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        alias = parse_product_line(line)
        explicit_alias = line.startswith(('"', "'")) and bool(alias.get("acronym"))
        if explicit_alias:
            full = alias.get("full") or line
            acronym = alias["acronym"]
            seed = f'"{full}" {acronym}'
            entry = add_brand(
                brands_path,
                seed,
                queries=[],
                products=[seed],
                ambiguous_brand=True,
                notes="imported from apps file",
            )
        else:
            name = line
            queries = [
                f"{name} download windows",
                f"{name} Windows Download",
                f"{name} in:name",
            ]
            entry = add_brand(
                brands_path,
                name,
                queries=queries,
                notes="imported from apps file",
            )
        imported.append(entry)
    return imported


def review_configured_brands(
    brands_path: Path,
    *,
    non_interactive: bool,
    prompt_timeout: Optional[float],
) -> None:
    """Show the configured app list and allow quick import before a run."""
    data = load_brands(brands_path)
    print("\nConfigured GRIFT app targets")
    print(f"  file: {brands_path}")
    for b in data.get("brands") or []:
        queries = b.get("queries") or []
        products = b.get("product_aliases") or b.get("products") or []
        print(f"  - {b.get('name')} ({len(queries)} quer{'y' if len(queries) == 1 else 'ies'})")
        for product in products:
            if isinstance(product, dict):
                full = product.get("full")
                acronym = product.get("acronym")
                if full and acronym:
                    print(f"      product: \"{full}\" {acronym}")
            else:
                print(f"      product: {product}")
        for q in queries[:4]:
            print(f"      q: {q}")
        if len(queries) > 4:
            print(f"      ... {len(queries) - 4} more")
    if non_interactive:
        return
    print("  To add multiword apps, put one per line in input/apps.txt; GRIFT derives an acronym.")
    print("  Example: SQL Server Management Studio -> \"SQL Server Management Studio\" SSMS")
    ans = prompt_with_timeout(
        "Review app list: press Enter to continue, type 'import /path/apps.txt', or 'edit' to stop and edit: ",
        default="",
        timeout=prompt_timeout,
        non_interactive=False,
    ).strip()
    if not ans:
        return
    if ans.lower() == "edit":
        raise SystemExit(f"Stopped for edits. Update {brands_path} or run --import-apps input/apps.txt, then rerun GRIFT.")
    if ans.lower().startswith("import "):
        src = Path(ans.split(None, 1)[1]).expanduser()
        if not src.is_absolute():
            src = (ROOT / src).resolve()
        imported = import_apps_file(src, brands_path)
        print(f"Imported {len(imported)} app seed(s) from {src}")
        for entry in imported:
            print(f"  - {entry.get('name')}")
        return
    raise SystemExit("Unrecognized app-list response. Press Enter, type 'edit', or type 'import /path/apps.txt'.")


def validate_or_exit(brands_path: Path) -> None:
    """Validate brands before a run and provide corrective guidance."""
    issues = validate_brands(load_brands(brands_path))
    if not issues:
        print("  app list: valid")
        return
    print("Invalid app list:", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    print("Fix the list with --list-brands, --add-brand, or --import-apps input/apps.txt before running.", file=sys.stderr)
    raise SystemExit(2)


def attach_triage_reports(candidates: list[dict[str, Any]], client: Any, *, progress: Optional[Callable[[dict[str, Any]], None]] = None) -> int:
    """Pull tria.ge reports referenced by lookup/submission results and attach them to candidates."""
    cache: dict[str, dict[str, Any]] = {}
    count = 0
    for candidate in candidates:
        triage = candidate.get("triage") if isinstance(candidate.get("triage"), dict) else None
        if not triage:
            continue
        sample_ids: list[str] = []
        for lookup in triage.get("lookups") or []:
            for hit in lookup.get("results") or []:
                sample_id = hit.get("id") or hit.get("sample")
                if sample_id and sample_id not in sample_ids:
                    sample_ids.append(str(sample_id))
        for submitted in triage.get("submissions") or []:
            sample_id = submitted.get("sample_id")
            if sample_id and sample_id not in sample_ids:
                sample_ids.append(str(sample_id))
        reports = []
        for sample_id in sample_ids:
            if sample_id not in cache:
                if progress:
                    progress({"event": "report_pull_start", "candidate": candidate.get("full_name"), "sample_id": sample_id})
                cache[sample_id] = client.collect_report(sample_id)
                count += 1
                if progress:
                    s = cache[sample_id].get("summary_iocs") or {}
                    progress({"event": "report_pull_done", "candidate": candidate.get("full_name"), "sample_id": sample_id, "score": s.get("score"), "target": s.get("target")})
            reports.append(cache[sample_id])
        if reports:
            triage["reports"] = reports
    return count


def init_project(root: Path) -> None:
    """Create local input/output directories and secret placeholders."""
    for d in (root / "input", root / "out", root / "logs"):
        d.mkdir(exist_ok=True)
    env = root / ".env"
    if not env.exists():
        env.write_text("# Local GRIFT secrets. Do not commit.\n# GITHUB_TOKEN=\n# TRIAGE_KEY=\n", encoding="utf-8")
        os.chmod(env, stat.S_IRUSR | stat.S_IWUSR)
    apps = root / "input" / "apps.txt"
    if not apps.exists():
        apps.write_text(
            "# One app per line. Use quoted full name plus acronym when needed.\n"
            "# Audacity\n"
            "# \"SQL Server Management Studio\" SSMS\n",
            encoding="utf-8",
        )


def hunt(
    *,
    brands_path: Path,
    created_after: Optional[str],
    brand_filter: Optional[list[str]],
    per_query: int,
    min_score: int,
    github: GitHubClient,
    enrich: bool,
    max_enrich: int,
    max_pages: int,
    max_candidates: int,
    sleep_on_rate_limit: bool,
    skip_contributors_gte: int,
    skip_top_files_gte: int,
    skip_stars_gte: int,
    skip_forks_gte: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = load_brands(brands_path)
    brands = data.get("brands") or []
    if brand_filter:
        want = {b.lower() for b in brand_filter}
        brands = [b for b in brands if (b.get("name") or "").lower() in want]
        if not brands:
            raise SystemExit(f"No brands matched filter: {brand_filter}")

    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []

    for brand in brands:
        if len(candidates) >= max_candidates:
            break
        name = brand.get("name") or "unknown"
        official_orgs = list(brand.get("official_orgs") or [])
        official_domains = list(brand.get("official_domains") or [])
        wrong_product_terms = list(brand.get("wrong_product_terms") or [])
        target_context_terms = list(brand.get("target_context_terms") or [])
        product_aliases = list(brand.get("product_aliases") or [])
        ambiguous_brand = bool(brand.get("ambiguous_brand"))
        queries = list(brand.get("queries") or [])
        print(f"\n== Brand: {name} ({len(queries)} quer{'y' if len(queries)==1 else 'ies'}) ==")

        for raw_q in queries:
            if len(candidates) >= max_candidates:
                print(f"  max candidates reached: {max_candidates}")
                break
            q = build_query(raw_q, created_after)
            print(f"  search: {q}")

            for page in range(1, max_pages + 1):
                if len(candidates) >= max_candidates:
                    break
                try:
                    result = github.search_repositories(
                        q,
                        per_page=per_query,
                        sort="updated",
                        page=page,
                    )
                except GitHubRateLimitError as e:
                    msg = f"rate limited for {q!r} page {page}: {e}"
                    print(f"  ! {msg}")
                    errors.append(msg)
                    if sleep_on_rate_limit and e.reset_epoch:
                        wait = max(0, e.reset_epoch - int(time.time()) + 2)
                        print(f"  sleeping {wait}s for GitHub rate limit reset")
                        time.sleep(wait)
                        continue
                    break
                except Exception as e:
                    msg = f"search failed for {q!r} page {page}: {e}"
                    print(f"  ! {msg}")
                    errors.append(msg)
                    break

                items = result.get("items") or []
                total = result.get("total_count")
                print(f"  page {page}: {len(items)} hits (api total_count={total})")
                if not items:
                    break

                for item in items:
                    if len(candidates) >= max_candidates:
                        break
                    full_name = item.get("full_name")
                    if not full_name or full_name in seen:
                        continue
                    seen.add(full_name)

                    print(f"  enrich: {full_name} ...", end=" ", flush=True)
                    try:
                        repo = github.repo(full_name)
                        owner_login = (repo.get("owner") or {}).get("login") or ""
                        owner = github.user(owner_login) if owner_login else {}
                        try:
                            contents = github.contents(full_name)
                        except Exception:
                            contents = []
                        try:
                            releases = github.releases(full_name)
                        except Exception:
                            releases = []
                        try:
                            contributor_count_seen = github.contributors_count(full_name, cap=skip_contributors_gte)
                        except Exception:
                            contributor_count_seen = None
                        branch = repo.get("default_branch") or "main"
                        readme = github.raw_readme(full_name, branch=branch)
                        extracted = extract_from_readme(readme)
                        score_result = score_candidate(
                            repo=repo,
                            owner=owner,
                            contents=contents,
                            releases=releases,
                            readme=readme,
                            extracted=extracted,
                            official_orgs=official_orgs,
                            official_domains=official_domains,
                            brand_name=name,
                            contributor_count_seen=contributor_count_seen,
                            skip_contributors_gte=skip_contributors_gte,
                            skip_top_files_gte=skip_top_files_gte,
                            skip_stars_gte=skip_stars_gte,
                            skip_forks_gte=skip_forks_gte,
                            wrong_product_terms=wrong_product_terms,
                            target_context_terms=target_context_terms,
                            ambiguous_brand=ambiguous_brand,
                            product_aliases=product_aliases,
                        )
                        print(f"score={score_result.get('score')}")

                        if enrich and score_result.get("score", 0) >= min_score:
                            urls = list((score_result.get("download_urls") or {}).get("payload") or [])
                            if urls:
                                score_result["url_checks"] = enrich_top_urls(urls, limit=max_enrich)

                        candidates.append(
                            {
                                "brand": name,
                                "query": q,
                                "page": page,
                                "full_name": full_name,
                                "html_url": repo.get("html_url") or item.get("html_url"),
                                "description": repo.get("description"),
                                "created_at": repo.get("created_at"),
                                "pushed_at": repo.get("pushed_at"),
                                "score_result": score_result,
                                "readme_excerpt": (readme or "")[:1500],
                            }
                        )
                    except Exception as e:
                        print(f"ERROR {e}")
                        errors.append(f"{full_name}: {e}")

                if len(items) < per_query:
                    break

    candidates.sort(
        key=lambda c: (c.get("score_result") or {}).get("score") or 0,
        reverse=True,
    )

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "created_after": created_after,
        "brands": [b.get("name") for b in brands],
        "min_score": min_score,
        "candidate_count": len(candidates),
        "per_query": per_query,
        "max_pages": max_pages,
        "max_candidates": max_candidates,
        "skip_contributors_gte": skip_contributors_gte,
        "skip_top_files_gte": skip_top_files_gte,
        "skip_stars_gte": skip_stars_gte,
        "skip_forks_gte": skip_forks_gte,
        "errors": errors,
    }
    return candidates, meta


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="GRIFT — GitHub README Impostor Fakeware Tracker.")
    p.add_argument("--brands", type=Path, default=ROOT / "brands.yaml", help="Path to brands.yaml")
    p.add_argument("--out", type=Path, default=ROOT / "out", help="Output directory")
    p.add_argument("--created-after", default=None, help="Append created:>YYYY-MM-DD to queries")
    p.add_argument("--lookback-days", type=int, default=None, help="Append created:>DATE using UTC today minus this many days; useful for weekly cron/systemd runs")
    p.add_argument("--brand", action="append", dest="brands_filter", help="Only these brand names")
    p.add_argument("--per-query", type=int, default=None, help="Results per search query, 1-100")
    p.add_argument("--max-pages", type=int, default=None, help="Search result pages per query")
    p.add_argument("--max-candidates", type=int, default=None, help="Stop after this many unique repos")
    p.add_argument("--min-score", type=int, default=None, help="Min score for MD highlight / enrich")
    p.add_argument("--enrich-urls", action="store_true", help="HEAD/Range probe payload URLs for candidates >= min-score")
    p.add_argument("--max-enrich", type=int, default=3)
    p.add_argument("--sleep-on-rate-limit", action="store_true", help="Sleep until GitHub rate-limit reset instead of stopping")
    p.add_argument("--skip-contributors-gte", type=int, default=3, help="Drop candidates with at least this many observed contributors")
    p.add_argument("--skip-top-files-gte", type=int, default=6, help="Drop candidates with at least this many meaningful top-level files")
    p.add_argument("--skip-stars-gte", type=int, default=10, help="Drop candidates with at least this many stars")
    p.add_argument("--skip-forks-gte", type=int, default=3, help="Drop candidates with at least this many forks")
    p.add_argument("--defang-report", action="store_true", default=True, help="Defang URLs in Markdown output (default)")
    p.add_argument("--raw-report", action="store_true", help="Do not defang URLs in Markdown output")
    p.add_argument("--full-run", action="store_true", help="Run the full pipeline: GitHub hunt, URL enrichment, tria.ge lookup, tria.ge submission for new/error lookup targets, report pull, and final IoC output")

    # Optional Stage 2 tria.ge enrichment. Lookup searches existing tria.ge
    # reports. Submit sends candidate URL fetch jobs with password context.
    p.add_argument("--triage-lookup", action="store_true", help="Stage 2: look up payload URLs in tria.ge for candidates at or above --triage-min-score")
    p.add_argument("--triage-submit", action="store_true", help="Stage 2: submit candidate payload URLs to tria.ge as fetch jobs with password context when available")
    p.add_argument("--triage-min-score", type=int, default=8)
    p.add_argument("--triage-max-urls", type=int, default=3, help="Stage 2: max payload URLs per candidate")
    p.add_argument("--triage-profile", default="default", help="Stage 2: tria.ge analysis profile for URL submissions")
    p.add_argument("--triage-timeout", type=float, default=10.0, help="Stage 2: seconds to wait for each tria.ge API request")
    p.add_argument("--triage-submit-on-lookup-error", action="store_true", help="Stage 2: submit even when lookup times out/fails")
    p.add_argument("--triage-report", action="append", dest="triage_reports", help="Stage 2: pull and summarize an existing tria.ge sample id")

    # mode / keys
    p.add_argument("--cron", action="store_true", help="Non-interactive: no prompts; require GITHUB_TOKEN")
    p.add_argument("--yes", "--non-interactive", action="store_true", dest="non_interactive", help="Same prompt behavior as --cron")
    p.add_argument("--prompt-timeout", type=float, default=20.0, help="Seconds to wait for key prompts before default")
    p.add_argument("--env-file", type=Path, default=ROOT / ".env", help="Optional .env path")
    p.add_argument("--require-github-token", action="store_true", help="Fail if GITHUB_TOKEN missing")
    p.add_argument("--init", action="store_true", help="Create input/out/logs directories and a chmod 600 .env placeholder")
    p.add_argument("--set-github-token", action="store_true", help="Prompt for and store GITHUB_TOKEN in the local .env file")
    p.add_argument("--set-triage-key", action="store_true", help="Prompt for and store TRIAGE_KEY in the local .env file")
    p.add_argument("--import-apps", type=Path, help="Import app seeds from a text file into brands.yaml")
    p.add_argument("--skip-app-review", action="store_true", help="Do not show/prompt the configured app list before interactive runs")
    p.add_argument("--validate-only", action="store_true", help="Validate brands.yaml, keys, and arguments, then exit")

    # brand maintenance
    p.add_argument("--list-brands", action="store_true")
    p.add_argument("--add-brand", metavar="NAME", help="Add or update a brand")
    p.add_argument("--query", action="append", dest="add_queries", help="With --add-brand: search query")
    p.add_argument("--product", action="append", dest="products", help="With --add-brand: product seed, e.g. '\"SQL Server Management Studio\" SSMS'")
    p.add_argument("--official-org", action="append", dest="official_orgs", help="With --add-brand: official GitHub org")
    p.add_argument("--official-domain", action="append", dest="official_domains", help="With --add-brand: official domain/repo suppressor")
    p.add_argument("--notes", default="", help="With --add-brand: notes string")

    args = p.parse_args(argv)

    if args.created_after and args.lookback_days is not None:
        print("Use either --created-after or --lookback-days, not both", file=sys.stderr)
        return 2
    if args.lookback_days is not None:
        try:
            args.created_after = created_after_from_lookback_days(args.lookback_days)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
    if args.full_run:
        args.enrich_urls = True
        args.triage_lookup = True
        args.triage_submit = True
        args.triage_submit_on_lookup_error = True

    non_interactive = bool(args.cron or args.non_interactive)
    prompt_timeout: Optional[float]
    if args.prompt_timeout <= 0:
        prompt_timeout = None if not non_interactive else 0.0
    else:
        prompt_timeout = args.prompt_timeout
    if non_interactive:
        prompt_timeout = 0.0


    if args.init:
        init_project(ROOT)
        print(f"Initialized GRIFT workspace under {ROOT}")
        print(f"  apps seed file: {ROOT / 'input' / 'apps.txt'}")
        print(f"  secrets file:   {ROOT / '.env'} (mode 600)")
        return 0

    if args.set_github_token:
        token = getpass.getpass("Paste GITHUB_TOKEN: ").strip()
        if not token:
            print("No token entered.", file=sys.stderr)
            return 2
        _write_secret(args.env_file, "GITHUB_TOKEN", token)
        print(f"Stored GITHUB_TOKEN in {args.env_file} with mode 600")
        return 0

    if args.set_triage_key:
        token = getpass.getpass("Paste TRIAGE_KEY: ").strip()
        if not token:
            print("No key entered.", file=sys.stderr)
            return 2
        _write_secret(args.env_file, "TRIAGE_KEY", token)
        print(f"Stored TRIAGE_KEY in {args.env_file} with mode 600")
        return 0

    if args.import_apps:
        imported = import_apps_file(args.import_apps, args.brands)
        print(f"Imported {len(imported)} app seed(s) into {args.brands}")
        for entry in imported:
            print(f"  - {entry.get('name')}")
            for product in entry.get("product_aliases") or []:
                if product.get("full") and product.get("acronym"):
                    print(f"      product: \"{product['full']}\" {product['acronym']}")
            for q in entry.get("queries") or []:
                print(f"      q: {q}")
        issues = validate_brands(load_brands(args.brands))
        if issues:
            print("Imported list needs attention:", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
            return 2
        print("App list validation: OK")
        return 0

    if args.list_brands:
        data = load_brands(args.brands)
        for b in data.get("brands") or []:
            print(f"- {b.get('name')}")
            for product in b.get("product_aliases") or []:
                if isinstance(product, dict) and product.get("full") and product.get("acronym"):
                    print(f"    product: \"{product['full']}\" {product['acronym']}")
            for q in b.get("queries") or []:
                print(f"    q: {q}")
            if b.get("official_orgs"):
                print(f"    official orgs: {', '.join(b['official_orgs'])}")
            if b.get("official_domains"):
                print(f"    official domains: {', '.join(b['official_domains'])}")
            if b.get("notes"):
                print(f"    notes: {b['notes']}")
        return 0

    if args.add_brand:
        entry = add_brand(
            args.brands,
            args.add_brand,
            args.add_queries or [],
            official_orgs=args.official_orgs,
            official_domains=args.official_domains,
            notes=args.notes,
            products=args.products,
            ambiguous_brand=True if args.products else None,
        )
        print(f"Saved brand: {entry.get('name')}")
        print(f"  queries: {entry.get('queries')}")
        return 0

    data = load_brands(args.brands)
    validate_or_exit(args.brands)
    if not args.skip_app_review and not args.brands_filter and not args.triage_reports:
        review_configured_brands(
            args.brands,
            non_interactive=non_interactive,
            prompt_timeout=prompt_timeout,
        )
        validate_or_exit(args.brands)
    data = load_brands(args.brands)
    defaults = data.get("defaults") or {}
    per_query = clamp(args.per_query or int(defaults.get("per_query_results") or 20), 1, 100)
    max_pages = clamp(args.max_pages or int(defaults.get("max_pages") or 3), 1, 10)
    max_candidates = clamp(args.max_candidates or int(defaults.get("max_candidates") or 500), 1, 2000)
    min_score = args.min_score if args.min_score is not None else int(defaults.get("min_score_report") or 4)
    need_triage = bool(args.triage_lookup or args.triage_submit or args.triage_reports)

    print("GitHub SEO malware hunt")
    print(f"  brands file: {args.brands}")
    print(f"  mode: {'cron/non-interactive' if non_interactive else 'interactive'}")
    if args.created_after:
        print(f"  created_after: {args.created_after}")

    try:
        keys = resolve_keys(
            non_interactive=non_interactive,
            prompt_timeout=prompt_timeout if not non_interactive else 0.0,
            require_github=bool(args.require_github_token or non_interactive),
            need_triage=need_triage,
            env_file=args.env_file if args.env_file.exists() else None,
        )
    except SystemExit as e:
        print(str(e) or "Key resolution failed.", file=sys.stderr)
        return 2

    for note in keys.notes:
        print(f"  key: {note}")
    if keys.github_token:
        github_check = GitHubClient(token=keys.github_token).validate_token()
        if github_check.get("ok"):
            remain = github_check.get("remaining")
            limit = github_check.get("limit")
            suffix = f" (rate limit remaining {remain}/{limit})" if remain is not None and limit is not None else ""
            print(f"  GitHub token: valid{suffix}")
        else:
            print(f"GitHub token validation failed: {github_check.get('error')}", file=sys.stderr)
            return 2
    if keys.triage_key and need_triage:
        triage_check = TriageClient(keys.triage_key).validate_key()
        if triage_check.get("ok"):
            print("  tria.ge key: valid")
        else:
            print(f"tria.ge key validation failed: {triage_check.get('error')}", file=sys.stderr)
            return 2
    if args.validate_only:
        print("Validation complete: app list and required keys are OK")
        return 0
    if keys.triage_key and need_triage:
        print("  tria.ge: key resolved for Stage 2 option")
    if not keys.github_token and not non_interactive:
        print("  warning: no GITHUB_TOKEN — unauthenticated API (low rate limits).")

    if args.triage_reports and not (args.triage_lookup or args.triage_submit):
        if not keys.triage_key:
            print("tria.ge key not provided; cannot pull report", file=sys.stderr)
            return 2
        triage_client = TriageClient(keys.triage_key)
        for sample_id in args.triage_reports:
            print(f"  tria.ge: pulling report for {sample_id}")
            report = triage_client.collect_report(sample_id)
            paths = write_triage_report_outputs(args.out, sample_id, report)
            s = report.get("summary_iocs") or {}
            print(f"  sample: {sample_id}")
            print(f"    status: {s.get('status')}")
            print(f"    score: {s.get('score')}")
            print(f"    target: {s.get('target')}")
            print(f"    IOC markdown: {paths['md']}")
            print(f"    raw JSON: {paths['json']}")
        return 0

    gh = GitHubClient(token=keys.github_token)

    try:
        candidates, meta = hunt(
            brands_path=args.brands,
            created_after=args.created_after,
            brand_filter=args.brands_filter,
            per_query=per_query,
            min_score=min_score,
            github=gh,
            enrich=bool(args.enrich_urls),
            max_enrich=args.max_enrich,
            max_pages=max_pages,
            max_candidates=max_candidates,
            sleep_on_rate_limit=bool(args.sleep_on_rate_limit or (args.cron and keys.github_token)),
            skip_contributors_gte=args.skip_contributors_gte,
            skip_top_files_gte=args.skip_top_files_gte,
            skip_stars_gte=args.skip_stars_gte,
            skip_forks_gte=args.skip_forks_gte,
        )
    except SystemExit:
        raise
    except Exception as e:
        print(f"Hunt failed: {e}", file=sys.stderr)
        return 1

    triage_summary = {"enabled": False, "status": "not_requested"}
    if need_triage:
        if not keys.triage_key:
            triage_summary = {"enabled": False, "status": "missing_key"}
            print("  tria.ge: key not provided; Stage 2 skipped")
        else:
            print("  tria.ge: running Stage 2 lookup" + (" + submit" if args.triage_submit else ""), flush=True)

            def show_triage_progress(event: dict[str, Any]) -> None:
                kind = event.get("event")
                if kind == "start":
                    print(
                        "  tria.ge Stage 2 plan: "
                        f"eligible={event.get('eligible_candidates', 0)}, "
                        f"with_urls={event.get('candidates_considered', 0)}, "
                        f"without_urls={event.get('candidates_without_targets', 0)}, "
                        f"url_lookups={event.get('total_targets', 0)}, "
                        f"static_skipped={event.get('static_targets_skipped', 0)}",
                        flush=True,
                    )
                elif kind == "lookup_start":
                    print(
                        f"  tria.ge lookup {event.get('index')}/{event.get('total')}: "
                        f"{event.get('candidate')} -> {event.get('url')}",
                        flush=True,
                    )
                elif kind == "lookup_done":
                    status = "ok" if event.get("ok") else "error"
                    detail = f"matches={event.get('matches', 0)}"
                    if event.get("error"):
                        detail = f"error={event.get('error')}"
                    print(
                        f"  tria.ge lookup {event.get('index')}/{event.get('total')} {status}: "
                        f"status={event.get('status')} {detail}",
                        flush=True,
                    )
                elif kind == "submit_start":
                    print(f"  tria.ge submit: {event.get('candidate')} -> {event.get('url')}", flush=True)
                elif kind == "submit_done":
                    status = "ok" if event.get("ok") else "error"
                    sample = event.get("sample_id") or event.get("error") or "unknown"
                    print(f"  tria.ge submit {status}: status={event.get('status')} sample={sample}", flush=True)
                elif kind == "done":
                    s = event.get("summary") or {}
                    print(
                        "  tria.ge Stage 2 done: "
                        f"lookups={s.get('lookups_attempted', 0)}, "
                        f"deduped={s.get('duplicate_targets_reused', 0)}, "
                        f"matches={s.get('lookup_matches', 0)}, "
                        f"errors={s.get('errors', 0)}",
                        flush=True,
                    )
                elif kind == "report_pull_start":
                    print(f"  tria.ge report pull: {event.get('candidate')} sample={event.get('sample_id')}", flush=True)
                elif kind == "report_pull_done":
                    print(f"  tria.ge report done: sample={event.get('sample_id')} score={event.get('score')} target={event.get('target')}", flush=True)

            triage_client = TriageClient(keys.triage_key, timeout=args.triage_timeout)
            triage_summary = enrich_candidates_with_triage(
                candidates,
                triage_client,
                min_score=args.triage_min_score,
                submit=bool(args.triage_submit),
                max_urls_per_candidate=args.triage_max_urls,
                submit_profile=args.triage_profile,
                submit_on_lookup_error=bool(args.triage_submit_on_lookup_error),
                progress=show_triage_progress,
            )
            triage_summary["status"] = "completed"
            pulled_reports = attach_triage_reports(candidates, triage_client, progress=show_triage_progress)
            triage_summary["reports_pulled"] = pulled_reports

    meta["triage_lookup_requested"] = bool(args.triage_lookup)
    meta["triage_submit_requested"] = bool(args.triage_submit)
    meta["triage_stage2_status"] = triage_summary.get("status")
    meta["triage"] = triage_summary
    paths = write_outputs(
        args.out,
        candidates=candidates,
        meta=meta,
        defang_markdown=not args.raw_report,
    )
    final_paths = write_final_ioc_outputs(args.out, candidates=candidates, meta=meta)
    paths.update(final_paths)

    print("\n== Done ==")
    print(f"  candidates: {len(candidates)}")
    high = [
        c
        for c in candidates
        if ((c.get("score_result") or {}).get("score") or 0) >= min_score
        and not (c.get("score_result") or {}).get("drop")
    ]
    print(f"  score >= {min_score}: {len(high)}")
    for c in high[:15]:
        sc = c.get("score_result") or {}
        print(f"    [{sc.get('score'):>3}] {c.get('full_name')}  {c.get('html_url')}")
    print(f"  JSON: {paths['json']}")
    print(f"  CSV:  {paths['csv']}")
    print(f"  MD:   {paths['md']}")
    print(f"  latest MD: {paths['md_latest']}")
    print(f"  final IoC JSON: {paths['final_json_latest']}")
    print(f"  final IoC TXT:  {paths['final_txt_latest']}")
    if triage_summary.get("status") != "not_requested":
        print(f"  tria.ge Stage 2: {triage_summary.get('status')}")
        print(f"    candidates considered: {triage_summary.get('candidates_considered', 0)}")
        print(f"    lookups attempted: {triage_summary.get('lookups_attempted', 0)}")
        print(f"    duplicate lookups reused: {triage_summary.get('duplicate_targets_reused', 0)}")
        if triage_summary.get("submit"):
            print(f"    submissions attempted: {triage_summary.get('submits_attempted', 0)}")
            print(f"    duplicate submissions reused: {triage_summary.get('duplicate_submissions_reused', 0)}")
        print(f"    lookup matches: {triage_summary.get('lookup_matches', 0)}")
        print(f"    errors: {triage_summary.get('errors', 0)}")
    if meta.get("errors"):
        print(f"  errors: {len(meta['errors'])} (see JSON meta.errors)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
