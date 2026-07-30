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
When a key is present, GRIFT validates it before the run and prints a clear success or failure message:

- GitHub token validation uses the GitHub API rate-limit endpoint and reports remaining quota.
- tria.ge key validation runs only when Stage 2 flags are requested and confirms access before lookup, submit, or report pull.
- invalid required keys stop the run before any search or submission work starts.

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

To rebuild `brands.yaml` from the app list after editing `input/apps.txt`, reset the
brand file first and then import:

```bash
printf 'brands: []\ndefaults:\n  min_score_report: 4\n  per_query_results: 20\n' > brands.yaml && python grift.py --import-apps input/apps.txt
```

Input rules:

- plain line: app name
- multiword plain line: imported as the plain app name; GRIFT does not invent acronym targets such as `PC` for `PDF converter`
- quoted full product phrase plus acronym: use this when an acronym is important, such as `"SQL Server Management Studio" SSMS`
- blank lines ignored
- lines starting with `#` ignored

Examples:

```text
Audacity
SQL Server Management Studio
"SQL Server Management Studio" SSMS
```

The plain `SQL Server Management Studio` line imports that full phrase as the target name. The quoted `"SQL Server Management Studio" SSMS` line imports `SSMS` as an ambiguous acronym target with the full product phrase attached as context. Use the quoted form only when you intentionally want acronym queries.

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

### 0. First-time setup

```bash
cd /path/to/GRIFT
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python grift.py --init
python grift.py --set-github-token
python grift.py --set-triage-key
```

`GITHUB_TOKEN` is used for GitHub API rate limits. `TRIAGE_KEY` is used only when Stage 2 options are requested. Keys are stored in `.env`, masked in output, and ignored by git.

### 1. Import or review the app list

`input/apps.txt` is a simple editing surface for app names. It does not change searches until imported into `brands.yaml`.

```bash
python grift.py --import-apps input/apps.txt
python grift.py --list-brands
```

To regenerate the active app configuration from a clean app list:

```bash
printf 'brands: []\ndefaults:\n  min_score_report: 4\n  per_query_results: 20\n' > brands.yaml && python grift.py --import-apps input/apps.txt && python grift.py --list-brands
```

Interactive runs also show the configured app list before searching. At that prompt:

- press Enter to continue with the current `brands.yaml`
- type `import /absolute/path/to/apps.txt` to import a list immediately
- type `edit` to stop and fix the list before searching

### 2. Stage 1 only: GitHub candidate queue

Stage 1 searches GitHub, scores candidate repos, extracts README/download context, and writes the roll-up report. It does not contact tria.ge.

```bash
python grift.py --created-after 2026-07-01 --out out/run-$(date -u +%Y%m%dT%H%M%SZ)
```

Useful Stage 1 variant with payload URL probing:

```bash
python grift.py --skip-app-review --created-after 2026-07-01 --enrich-urls --out out/run-$(date -u +%Y%m%dT%H%M%SZ)
```

One target only:

```bash
python grift.py --brand Audacity --created-after 2026-07-01
```

Automation / cron:

```bash
python grift.py --cron --created-after 2026-07-01 --out out/cron-latest
```

In cron mode, `GITHUB_TOKEN` is required and prompts are disabled.

### 3. Stage 1 + Stage 2 lookup: read-only tria.ge context

This is the recommended full non-submitting run. It does Stage 1, enriches URLs, then checks tria.ge for existing reports tied to high-scoring candidate payload URLs.

```bash
python grift.py \
  --skip-app-review \
  --created-after 2026-07-01 \
  --enrich-urls \
  --triage-lookup \
  --triage-min-score 8 \
  --triage-max-urls 3 \
  --out out/run-$(date -u +%Y%m%dT%H%M%SZ)
```

Look first at:

```text
out/run-*/report_latest.md
out/run-*/candidates_latest.json
```

`report_latest.md` will include a compact tria.ge section when Stage 2 is enabled. `candidates_latest.json` keeps the structured lookup data.

### 4. Stage 1 + Stage 2 submit: intentionally send candidate URLs to tria.ge

Use this only when you intentionally want tria.ge to fetch/analyze candidate payload URLs. GRIFT requires the explicit safety flag.

```bash
python grift.py \
  --skip-app-review \
  --created-after 2026-07-01 \
  --enrich-urls \
  --triage-lookup \
  --triage-submit \
  --triage-submit-on-lookup-error \
  --i-understand-this-submits-malware \
  --triage-min-score 8 \
  --triage-max-urls 3 \
  --out out/run-$(date -u +%Y%m%dT%H%M%SZ)
```

Submission notes:

- `--triage-submit` never runs without `--i-understand-this-submits-malware`.
- By default, lookup errors do not force submissions. Add `--triage-submit-on-lookup-error` when you want submission despite lookup timeout/failure.
- Remote samples are submitted as tria.ge `kind=fetch` URL jobs with the extracted archive password when present.
- The run report and JSON output contain submission status and sample IDs when tria.ge returns them.

### 5. Pull full IoC reports for known tria.ge sample IDs

Stage 2 lookup/submission data in `report_latest.md` is compact. Full IoC summaries are pulled separately by sample ID:

```bash
python grift.py \
  --skip-app-review \
  --out out/triage-report-$(date -u +%Y%m%dT%H%M%SZ) \
  --triage-report SAMPLE_ID
```

Example:

```bash
python grift.py --skip-app-review --out out/triage-report-260730-e21nrscp71 --triage-report 260730-e21nrscp71
```

This writes:

```text
triage_report_<sample_id>.json
triage_report_<sample_id>.md
```

The Markdown report includes high-scoring tasks, high-scoring files, and bulk-copy SHA256/SHA1/MD5 blocks.

## Command-line options

### Workspace, keys, and validation

| Option | Meaning |
|---|---|
| `--init` | Create `input/`, `out/`, `logs/`, `.env`, and seed files. |
| `--env-file PATH` | Load keys from a specific `.env` file instead of the default local `.env`. |
| `--set-github-token` | Prompt for `GITHUB_TOKEN` and store it in `.env` with restrictive permissions. |
| `--set-triage-key` | Prompt for `TRIAGE_KEY` and store it in `.env` with restrictive permissions. |
| `--validate-only` | Validate app list, arguments, and required keys for the selected options, then exit without searching. |
| `--require-github-token` | Fail if `GITHUB_TOKEN` is missing. Useful before large or automated searches. |
| `--cron` | Non-interactive mode for scheduled runs. Disables prompts and requires `GITHUB_TOKEN`. |
| `--yes`, `--non-interactive` | Skip interactive prompts without enabling every cron behavior. |
| `--prompt-timeout SECONDS` | Wait only this long at interactive prompts before using the default answer. |

### App target management

| Option | Meaning |
|---|---|
| `--import-apps input/apps.txt` | Import simple app seeds into `brands.yaml`. Plain multiword app names stay plain; quoted full-product plus acronym lines create acronym aliases. |
| `--list-brands` | Show configured targets, product aliases, derived queries, official org/domain suppressors, and notes. |
| `--skip-app-review` | Do not show the interactive configured-app review prompt before searching. |
| `--add-brand NAME` | Add or update a target in `brands.yaml`. |
| `--query TEXT` | With `--add-brand`: add a GitHub search query. Repeatable. |
| `--product TEXT` | With `--add-brand`: add a product alias such as `'"SQL Server Management Studio" SSMS'`. Repeatable. |
| `--official-org ORG` | With `--add-brand`: add a GitHub org suppressor. Repeatable. |
| `--official-domain DOMAIN` | With `--add-brand`: add a domain/repo suppressor. Repeatable. |
| `--notes TEXT` | With `--add-brand`: store analyst notes for the target. |

### Stage 1 GitHub search and scoring

| Option | Meaning |
|---|---|
| `--brand NAME` | Run only one configured target. Repeat the flag for multiple targets. |
| `--created-after YYYY-MM-DD` | Add a GitHub `created:>` filter to favor fresh lures. |
| `--per-query N` | GitHub results per search page, 1 to 100. |
| `--max-pages N` | Search pages per query. |
| `--max-candidates N` | Hard cap on unique repos enriched. |
| `--min-score N` | Minimum score included in Markdown reports. Lower keeps more noise; higher is stricter. |
| `--skip-contributors-gte N` | Drop likely real projects with at least this many contributors. |
| `--skip-top-files-gte N` | Drop likely real projects with at least this many top-level files. |
| `--skip-stars-gte N` | Drop repos with too much social proof. |
| `--skip-forks-gte N` | Drop repos with too many forks. |
| `--enrich-urls` | Probe top payload URLs for high-scoring candidates. Helpful before Stage 2. |
| `--max-enrich N` | Maximum URL-enrichment attempts. |
| `--sleep-on-rate-limit` | Sleep and retry when GitHub rate limits are encountered. |
| `--out DIR` | Output directory for JSON, CSV, and Markdown reports. |
| `--raw-report` | Do not defang URLs in Markdown. JSON and CSV always keep raw URLs. |

### Stage 2 tria.ge lookup, submission, and report pulls

| Option | Meaning |
|---|---|
| `--triage-lookup` | Read-only Stage 2: look up payload URLs in tria.ge for candidates at or above `--triage-min-score`. |
| `--triage-submit` | Submit candidate payload URLs to tria.ge. Requires `--i-understand-this-submits-malware`. |
| `--triage-submit-on-lookup-error` | Submit even when lookup times out or fails. Still requires the submit safety flag. |
| `--i-understand-this-submits-malware` | Explicit safety acknowledgement required for submissions. |
| `--triage-min-score N` | Minimum candidate score for Stage 2 lookup/submission. Default is `8`. |
| `--triage-max-urls N` | Maximum candidate payload URLs sent to Stage 2 per candidate. Default is `3`. |
| `--triage-profile NAME` | tria.ge analysis profile for URL submissions. Default is `default`. |
| `--triage-report SAMPLE_ID` | Pull and summarize an existing tria.ge sample ID. Repeatable. Writes `triage_report_<sample_id>.*`. |

## Stage 2 tria.ge behavior

Stage 1 always runs without tria.ge. Stage 2 only runs when a Stage 2 flag is requested and a `TRIAGE_KEY` is available.

Stage 2:

- collects payload, GitHub Release, Telegram, Dropbox, and unknown external URLs from candidates
- carries extracted archive passwords such as `github` or `2026` with each URL
- submits remote samples as tria.ge `kind=fetch` URL jobs with archive password, `interactive=false`, `timeout=200`, and `network=internet`
- only considers candidates at or above `--triage-min-score`
- stores lookup and submission results inside `candidates_*.json`
- adds a compact tria.ge section to the run Markdown report
- never stores or prints the tria.ge API key

## Outputs

Each normal Stage 1 or Stage 1+Stage 2 run writes to the selected output directory:

```text
candidates_<timestamp>.json
candidates_latest.json
candidates_<timestamp>.csv
report_<timestamp>.md
report_latest.md
```

`report_latest.md` is the roll-up summary for the run. It lists candidates meeting the configured score threshold, explains why they scored, includes payload URL buckets, and includes Stage 2 tria.ge lookup/submission status when enabled.

Full tria.ge report pulls write one IoC summary per sample:

```text
triage_report_<sample_id>.json
triage_report_<sample_id>.md
```

The tria.ge IoC Markdown is score-led. It lists high-scoring tasks first, then high-scoring files with hashes beside filenames for quick reference, then repeats SHA256/SHA1/MD5 in separate bulk-copy blocks. It does not scrape random certificate/CRL/timestamp URLs from static metadata into the IoC list.

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
