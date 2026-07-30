"""Brand / software list load and update."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    raise RuntimeError(
        "PyYAML is required. Install with: pip install pyyaml\n"
        "Or: pip install -r requirements.txt"
    )


def parse_product_line(value: str | dict[str, Any]) -> dict[str, str]:
    """Parse product alias entries such as '"SQL Server Management Studio" SSMS'."""
    if isinstance(value, dict):
        full = str(value.get("full") or value.get("name") or "").strip()
        acronym = str(value.get("acronym") or "").strip()
        return {"full": full, "acronym": acronym}
    text = str(value).strip()
    m = re.match(r'^"([^"]+)"\s+([A-Za-z0-9_.+-]{2,16})$', text)
    if not m:
        m = re.match(r"^'([^']+)'\s+([A-Za-z0-9_.+-]{2,16})$", text)
    if m:
        return {"full": m.group(1).strip(), "acronym": m.group(2).strip()}
    return {"full": text, "acronym": ""}


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def normalize_brand_entry(b: dict[str, Any]) -> dict[str, Any]:
    """Derive queries and reasoning terms from full-name/acronym product aliases."""
    b.setdefault("official_orgs", [])
    b.setdefault("official_domains", [])
    queries = list(b.get("queries") or [])
    target_terms = list(b.get("target_context_terms") or [])
    aliases = []
    for item in b.get("products") or b.get("product_aliases") or []:
        alias = parse_product_line(item)
        full = alias.get("full") or ""
        acronym = alias.get("acronym") or ""
        if not full and not acronym:
            continue
        aliases.append(alias)
        if full:
            _append_unique(target_terms, full.lower())
            _append_unique(queries, f'"{full}" download')
        if acronym:
            _append_unique(queries, f"{acronym} download")
            _append_unique(queries, f"{acronym} in:name")
            # Acronyms are ambiguous until a full phrase or delivery context confirms them.
            b.setdefault("ambiguous_brand", True)
    if aliases:
        b["product_aliases"] = aliases
    b["queries"] = queries
    b["target_context_terms"] = target_terms
    b.setdefault("wrong_product_terms", [])
    return b


def load_brands(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        return _parse_simple_yaml(text)
    data = yaml.safe_load(text) or {}
    if "brands" not in data:
        data["brands"] = []
    if "defaults" not in data:
        data["defaults"] = {}
    for b in data.get("brands") or []:
        normalize_brand_entry(b)
    return data


def save_brands(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to save brands.yaml")
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def add_brand(
    path: Path,
    name: str,
    queries: list[str],
    official_orgs: list[str] | None = None,
    official_domains: list[str] | None = None,
    notes: str = "",
    products: list[str] | None = None,
    ambiguous_brand: bool | None = None,
) -> dict[str, Any]:
    data = load_brands(path)
    brands = data.setdefault("brands", [])
    for b in brands:
        if b.get("name", "").lower() == name.lower():
            existing_q = list(b.get("queries") or [])
            for q in queries:
                if q not in existing_q:
                    existing_q.append(q)
            b["queries"] = existing_q
            if official_orgs:
                orgs = list(b.get("official_orgs") or [])
                for o in official_orgs:
                    if o not in orgs:
                        orgs.append(o)
                b["official_orgs"] = orgs
            if official_domains:
                domains = list(b.get("official_domains") or [])
                for d in official_domains:
                    if d not in domains:
                        domains.append(d)
                b["official_domains"] = domains
            if notes:
                b["notes"] = notes
            if products:
                prod = list(b.get("products") or [])
                for item in products:
                    if item not in prod:
                        prod.append(item)
                b["products"] = prod
            if ambiguous_brand is not None:
                b["ambiguous_brand"] = ambiguous_brand
            normalize_brand_entry(b)
            save_brands(path, data)
            return b
    entry = {
        "name": name,
        "queries": queries,
        "official_orgs": official_orgs or [],
        "official_domains": official_domains or [],
        "notes": notes,
    }
    if products:
        entry["products"] = products
    if ambiguous_brand is not None:
        entry["ambiguous_brand"] = ambiguous_brand
    normalize_brand_entry(entry)
    brands.append(entry)
    save_brands(path, data)
    return entry
