"""API key loading: env -> .env -> prompt; cron defaults and timeouts."""

from __future__ import annotations

import os
import sys
import select
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return "(empty)"
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}…{value[-keep:]}"


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (no extra dependency). Does not override existing env."""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def prompt_with_timeout(
    message: str,
    default: str,
    timeout: Optional[float],
    non_interactive: bool,
) -> str:
    """
    Prompt on stdin. If non_interactive or timeout expires with no input, return default.
    timeout=None means wait forever (interactive only).
    """
    if non_interactive or not sys.stdin.isatty():
        return default

    sys.stderr.write(message)
    sys.stderr.flush()

    if timeout is None:
        try:
            line = sys.stdin.readline()
        except EOFError:
            return default
        return line.strip() if line.strip() else default

    # timed wait for stdin
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        sys.stderr.write(f"[timeout {timeout:.0f}s → default: {default!r}]\n")
        sys.stderr.flush()
        return default
    try:
        line = sys.stdin.readline()
    except EOFError:
        return default
    return line.strip() if line.strip() else default


def prompt_yes_no(
    message: str,
    *,
    default_yes: bool,
    timeout: Optional[float],
    non_interactive: bool,
) -> bool:
    default = "y" if default_yes else "n"
    hint = "Y/n" if default_yes else "y/N"
    ans = prompt_with_timeout(
        f"{message} [{hint}]: ",
        default=default,
        timeout=timeout,
        non_interactive=non_interactive,
    ).lower()
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default_yes


@dataclass
class KeyBundle:
    github_token: Optional[str] = None
    triage_key: Optional[str] = None
    abusech_key: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    @property
    def has_github(self) -> bool:
        return bool(self.github_token)


def resolve_keys(
    *,
    non_interactive: bool,
    prompt_timeout: Optional[float],
    require_github: bool,
    need_triage: bool = False,
    env_file: Optional[Path] = None,
) -> KeyBundle:
    """
    Load keys and confirm with user (or cron defaults).

    Interactive:
      - If key present: ask "use this key?" default yes (timeout -> yes)
      - If missing and required: prompt to paste; empty fails if required
      - If missing and optional: ask skip or enter

    Cron / non-interactive:
      - If key present: use it (default yes, no prompt)
      - If required key missing: fail
      - If optional missing: continue without
    """
    if env_file:
        load_dotenv(env_file)

    bundle = KeyBundle()

    def handle_key(
        env_name: str,
        required: bool,
        label: str,
    ) -> Optional[str]:
        current = os.environ.get(env_name) or os.environ.get(env_name.lower())
        current = current.strip() if current else None

        if current:
            if non_interactive:
                bundle.notes.append(f"{label}: using env ({_mask(current)})")
                return current
            use = prompt_yes_no(
                f"Found {label} ({_mask(current)}). Use it?",
                default_yes=True,
                timeout=prompt_timeout,
                non_interactive=False,
            )
            if use:
                bundle.notes.append(f"{label}: confirmed ({_mask(current)})")
                return current
            # user declined — allow re-entry interactively
            if non_interactive:
                return None
            pasted = prompt_with_timeout(
                f"Enter new {label} (or empty to skip): ",
                default="",
                timeout=prompt_timeout,
                non_interactive=False,
            ).strip()
            if pasted:
                bundle.notes.append(f"{label}: entered interactively ({_mask(pasted)})")
                return pasted
            if required:
                raise SystemExit(
                    f"Required key {env_name} declined and no replacement given."
                )
            bundle.notes.append(f"{label}: skipped")
            return None

        # missing
        if non_interactive:
            if required:
                raise SystemExit(
                    f"Missing required key {env_name}. "
                    f"Set it in the environment or .env for cron/non-interactive runs."
                )
            bundle.notes.append(f"{label}: not set (optional)")
            return None

        # interactive missing
        if required:
            pasted = prompt_with_timeout(
                f"{label} not set. Paste {env_name} (required): ",
                default="",
                timeout=prompt_timeout,
                non_interactive=False,
            ).strip()
            if not pasted:
                raise SystemExit(f"Required key {env_name} not provided.")
            bundle.notes.append(f"{label}: entered interactively ({_mask(pasted)})")
            return pasted

        enter = prompt_yes_no(
            f"{label} not set (optional). Enter one now?",
            default_yes=False,
            timeout=prompt_timeout,
            non_interactive=False,
        )
        if not enter:
            bundle.notes.append(f"{label}: not set")
            return None
        pasted = prompt_with_timeout(
            f"Paste {env_name}: ",
            default="",
            timeout=prompt_timeout,
            non_interactive=False,
        ).strip()
        if pasted:
            bundle.notes.append(f"{label}: entered interactively ({_mask(pasted)})")
            return pasted
        bundle.notes.append(f"{label}: not set")
        return None

    # GitHub: required in cron; interactively preferred but can run limited without
    github_required = require_github or non_interactive
    bundle.github_token = handle_key(
        "GITHUB_TOKEN",
        required=github_required,
        label="GitHub token (GITHUB_TOKEN)",
    )

    if need_triage:
        bundle.triage_key = handle_key(
            "TRIAGE_KEY",
            required=True if non_interactive else False,
            label="tria.ge API key (TRIAGE_KEY)",
        )
        if non_interactive and not bundle.triage_key:
            raise SystemExit("TRIAGE_KEY required for triage submission in cron mode.")
    else:
        # still allow load if present for future, but don't require
        t = os.environ.get("TRIAGE_KEY")
        if t and t.strip():
            if non_interactive:
                bundle.triage_key = t.strip()
                bundle.notes.append(f"tria.ge key present ({_mask(t.strip())}), not used this run")
            else:
                use = prompt_yes_no(
                    f"Found tria.ge key ({_mask(t.strip())}). Remember for this session?",
                    default_yes=True,
                    timeout=prompt_timeout,
                    non_interactive=False,
                )
                if use:
                    bundle.triage_key = t.strip()

    abuse = os.environ.get("ABUSECH_AUTH_KEY")
    if abuse and abuse.strip():
        bundle.abusech_key = abuse.strip()
        bundle.notes.append(f"ABUSECH_AUTH_KEY present ({_mask(abuse.strip())})")

    return bundle
