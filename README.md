# GRIFT — GitHub README Impostor Fakeware Tracker

GRIFT hunts short-lived GitHub README impostor fakeware: SEO-facing fake application or download repositories, often README-only, zero-reputation, and pointing to passworded or offsite payloads.

It does not replace sandbox detonation or human review. It produces an explainable candidate queue for defensive research.

## What GRIFT looks for

Positive signals include:

- README-only or README plus one small file
- one contributor
- zero stars and zero forks
- newly created owner and repo
- brand plus download language
- password language in the README
- offsite, Telegram, Dropbox, or GitHub Releases payload links
- fake app landing-page shape rather than real source code

Suppressors include:

- official GitHub orgs or official domains
- many contributors
- many top-level source files
- stars, forks, and mature project shape
- wrong expansion of ambiguous acronyms
- localhost-only development links

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python grift.py --init
```

`--init` creates:

- `.env` for local secrets, mode 600, gitignored
- `input/apps.txt` seed template
- `out/` for run output
- `logs/` for optional cron logs

## Keys

GRIFT loads secrets in this order:

1. environment variables
2. local `.env`
3. interactive prompt when needed

Supported keys:

- `GITHUB_TOKEN`: recommended for reliable GitHub API search and rate limits
- `TRIAGE_KEY`: only needed when Stage 2 tria.ge flags are used

Store keys safely in the local `.env` file:

```bash
python grift.py --set-github-token
python grift.py --set-triage-key
```

The values are hidden while typing, stored with file mode 600, ignored by git, and masked in console output.

## App inputs

GRIFT uses `brands.yaml` as the durable target list.

For simple user input, create a text file such as `input/apps.txt`:

```text
Audacity
TeamViewer
"SQL Server Management Studio" SSMS
```

Then import it:

```bash
python grift.py --import-apps input/apps.txt
```

Input rules:

- plain line: app name
- quoted full product phrase plus acronym: ambiguous acronym product
- blank lines ignored
- lines starting with `#` ignored

For acronym products, use:

```text
"SQL Server Management Studio" SSMS
```

GRIFT treats the full phrase as target identity and the acronym as ambiguous. Acronym-only hits are weaker unless the full phrase or delivery behavior appears.

## `brands.yaml` format

Example:

```yaml
brands:
- name: Audacity
  queries:
  - Audacity download windows
  - Audacity Windows Download
  official_orgs:
  - audacity
  official_domains:
  - audacityteam.org
  - github.com/audacity/audacity

- name: SSMS
  products:
  - '"SQL Server Management Studio" SSMS'
  ambiguous_brand: true
  wrong_product_terms:
  - school management
  - student management
  - management system
  official_orgs:
  - microsoft
  - MicrosoftDocs
```

Product aliases generate safe query and scoring context. GRIFT does not auto-add broad full phrase `in:readme` searches because they can produce large amounts of benign project noise.

## Run

Interactive:

```bash
python grift.py --created-after 2026-07-01
```

All current targets with a stronger output directory name:

```bash
python grift.py --created-after 2026-07-01 --out out/run-$(date -u +%Y%m%dT%H%M%SZ)
```

One target:

```bash
python grift.py --brand Audacity --created-after 2026-07-01
```

Automation:

```bash
python grift.py --cron --created-after 2026-07-01 --out out/cron-latest
```

In cron mode, `GITHUB_TOKEN` is required and prompts are disabled.

## Useful flags

| Flag | Meaning |
|---|---|
| `--init` | Create local workspace files and directories |
| `--set-github-token` | Prompt and store GitHub token in `.env` |
| `--set-triage-key` | Prompt and store tria.ge key in `.env` |
| `--import-apps input/apps.txt` | Import app seeds into `brands.yaml` |
| `--list-brands` | Show configured targets and derived queries |
| `--brand Audacity` | Only run one target, repeatable |
| `--created-after YYYY-MM-DD` | Add a GitHub created date filter |
| `--min-score 4` | Minimum score included in Markdown report |
| `--per-query 30` | Results per GitHub search page, 1 to 100 |
| `--max-pages 3` | Search pages per query |
| `--max-candidates 500` | Hard cap on unique repos enriched |
| `--skip-contributors-gte 3` | Drop likely real projects with at least this many contributors |
| `--skip-top-files-gte 6` | Drop likely real projects with at least this many top-level files |
| `--skip-stars-gte 10` | Drop repos with too much social proof |
| `--skip-forks-gte 3` | Drop repos with too many forks |
| `--enrich-urls` | Probe top payload URLs for high-scoring candidates |
| `--raw-report` | Do not defang URLs in Markdown output |
| `--triage-lookup` | Stage 2: search tria.ge for high-scoring candidate payload URLs |
| `--triage-submit` | Stage 2: submit candidate payload URLs to tria.ge, gated by explicit safety flag |
| `--triage-min-score 8` | Minimum score for tria.ge Stage 2 |
| `--triage-max-urls 3` | Max payload URLs per candidate for tria.ge Stage 2 |
| `--triage-profile default` | tria.ge analysis profile for URL submissions |

## Stage 2 tria.ge enrichment

Stage 1 always runs without tria.ge. Stage 2 only runs when requested and a `TRIAGE_KEY` is available.

Lookup existing tria.ge reports for payload URLs from high-scoring candidates:

```bash
python grift.py --triage-lookup --triage-min-score 8 --created-after 2026-07-01
```

Submit candidate payload URLs to tria.ge only when you intentionally want detonation or URL analysis:

```bash
python grift.py --triage-submit --i-understand-this-submits-malware --triage-min-score 8
```

Stage 2 behavior:

- collects payload, GitHub Release, Telegram, Dropbox, and unknown external URLs from candidates
- carries extracted archive passwords such as `github` or `2026` with each URL
- submits remote samples as tria.ge `kind=fetch` URL jobs with archive password, `interactive=false`, `timeout=200`, and `network=internet`, matching the original research bundle notes
- only considers candidates at or above `--triage-min-score`
- stores lookup and submission results inside `candidates_*.json`
- adds a compact tria.ge section to the Markdown report
- never stores or prints the tria.ge API key

## Outputs

Each run writes to the selected output directory:

- `candidates_<timestamp>.json`
- `candidates_latest.json`
- `candidates_<timestamp>.csv`
- `report_<timestamp>.md`
- `report_latest.md`

Markdown reports are defanged by default. JSON and CSV preserve raw URLs for tooling.

## Safety

GRIFT is for defensive research. Do not execute downloaded files or click live candidate links on production hosts. Treat output as a triage queue, not attribution or verdict.

`--triage-submit` is intentionally gated and refuses to run without `--i-understand-this-submits-malware`.

## Development checks

```bash
python -m unittest discover -s tests -v
python -m py_compile grift.py hunt.py lib/*.py
python grift.py --help
python grift.py --list-brands
```
