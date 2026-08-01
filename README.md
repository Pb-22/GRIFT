# GRIFT — GitHub README Impostor Fakeware Tracker

GRIFT hunts short-lived GitHub README impostor fakeware: SEO-facing fake application or download repositories, often README-only, zero-reputation, and pointing to passworded or offsite payloads.

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

GRIFT uses `brands.yaml` as the active target list. The optional `input/apps.txt` file is a simple source list for rebuilding that target list.

Create one target per line:

```text
Audacity
TeamViewer
PDF converter
"SQL Server Management Studio" SSMS
```

Import `input/apps.txt` into `brands.yaml`:

```bash
python grift.py --import-apps input/apps.txt
```

Input rules:

- one application, product, or lure theme per line
- quoted full-product plus acronym entries create acronym searches, for example `"SQL Server Management Studio" SSMS`
- unquoted entries use the written phrase as the search target
- blank lines and lines starting with `#` are ignored

Use the quoted acronym form only for products where the acronym is a useful hunt target.

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

`GITHUB_TOKEN` is used for GitHub API rate limits. `TRIAGE_KEY` is used when Stage 2 options are requested. Keys are stored in `.env`, masked in output, and ignored by git.

### 1. Build the target list

```bash
python grift.py --import-apps input/apps.txt
```

### 2. Full pipeline: weekly scheduled run

The full pipeline runs GitHub search, candidate scoring, payload URL enrichment, tria.ge lookup, tria.ge URL submission for new or lookup-error targets, report pull, and final IoC output. Passwords found in repository instructions are passed with submitted URL jobs.

```bash
python grift.py --cron --full-run --skip-app-review --lookback-days 7 --min-score 4 --triage-min-score 8 --triage-max-urls 3 --triage-timeout 10 --out out/cron-latest
```

The threshold values match the tested hunt settings. `--lookback-days 7` computes the GitHub `created:>` search bound from UTC today minus seven days. `--min-score 4` is the candidate reporting and URL-enrichment threshold. `--triage-min-score 8` limits tria.ge lookup and submission to the strongest candidates. `--triage-max-urls 3` checks up to three payload URLs per candidate. `--triage-timeout 10` gives each tria.ge API request ten seconds before the run moves on.

### 3. Full pipeline: fixed historical date

Use a fixed date when reproducing a known hunt window.

```bash
python grift.py --full-run --skip-app-review --created-after 2026-07-01 --min-score 4 --triage-min-score 8 --triage-max-urls 3 --triage-timeout 10 --out out/run-$(date -u +%Y%m%dT%H%M%SZ)
```

`--created-after` and `--lookback-days` are mutually exclusive.

### 4. Stage 1 only: GitHub candidate queue

Stage 1 searches GitHub, scores candidate repos, extracts README/download context, and writes the roll-up report. Use this mode for manual review, separate sandboxing, or malware-team handoff.

```bash
python grift.py --created-after 2026-07-01 --min-score 4 --out out/run-$(date -u +%Y%m%dT%H%M%SZ)
```

Stage 1 with payload URL probing:

```bash
python grift.py --skip-app-review --created-after 2026-07-01 --min-score 4 --enrich-urls --out out/run-$(date -u +%Y%m%dT%H%M%SZ)
```

### 5. One target app full pipeline

Use this when one app or lure family needs an isolated report.

```bash
python grift.py --full-run --brand Audacity --lookback-days 7 --min-score 4 --triage-min-score 8 --triage-max-urls 3 --triage-timeout 10 --out out/audacity-full
```

### 6. Pull reports for known tria.ge sample IDs

```bash
python grift.py --skip-app-review --out out/triage-report-$(date -u +%Y%m%dT%H%M%SZ) --triage-report SAMPLE_ID
```

Example:

```bash
python grift.py --skip-app-review --out out/triage-report-260730-e21nrscp71 --triage-report 260730-e21nrscp71
```

This writes `triage_report_<sample_id>.json` and `triage_report_<sample_id>.md`.

## Manpage

```text
usage: grift.py [-h] [--brands BRANDS] [--out OUT]
                [--created-after CREATED_AFTER]
                [--lookback-days LOOKBACK_DAYS] [--brand BRANDS_FILTER]
                [--per-query PER_QUERY] [--max-pages MAX_PAGES]
                [--max-candidates MAX_CANDIDATES] [--min-score MIN_SCORE]
                [--enrich-urls] [--max-enrich MAX_ENRICH]
                [--sleep-on-rate-limit]
                [--skip-contributors-gte SKIP_CONTRIBUTORS_GTE]
                [--skip-top-files-gte SKIP_TOP_FILES_GTE]
                [--skip-stars-gte SKIP_STARS_GTE]
                [--skip-forks-gte SKIP_FORKS_GTE] [--defang-report]
                [--raw-report] [--full-run] [--triage-lookup]
                [--triage-submit] [--triage-min-score TRIAGE_MIN_SCORE]
                [--triage-max-urls TRIAGE_MAX_URLS]
                [--triage-profile TRIAGE_PROFILE]
                [--triage-timeout TRIAGE_TIMEOUT]
                [--triage-submit-on-lookup-error]
                [--triage-report TRIAGE_REPORTS]
                [--i-understand-this-submits-malware] [--cron] [--yes]
                [--prompt-timeout PROMPT_TIMEOUT] [--env-file ENV_FILE]
                [--require-github-token] [--init] [--set-github-token]
                [--set-triage-key] [--import-apps IMPORT_APPS]
                [--skip-app-review] [--validate-only] [--list-brands]
                [--add-brand NAME] [--query ADD_QUERIES] [--product PRODUCTS]
                [--official-org OFFICIAL_ORGS]
                [--official-domain OFFICIAL_DOMAINS] [--notes NOTES]
```

| Option | Value | Meaning |
|---|---|---|
| `--full-run` | none | Run the full pipeline: GitHub hunt, URL enrichment, tria.ge lookup, tria.ge submission for new or lookup-error targets, report pull, and final IoC output. |
| `-h`, `--help` | none | Show help and exit. |
| `--brands` | BRANDS | Path to `brands.yaml`. |
| `--out` | OUT | Output directory. |
| `--created-after` | CREATED_AFTER | Append `created:>YYYY-MM-DD` to GitHub queries. Use for fixed historical reproduction. |
| `--lookback-days` | LOOKBACK_DAYS | Append `created:>DATE` using UTC today minus this many days. Use for scheduled runs. |
| `--brand` | BRANDS_FILTER | Run only the named configured target. Can be repeated. |
| `--per-query` | PER_QUERY | Results per GitHub search query, 1 to 100. |
| `--max-pages` | MAX_PAGES | Search result pages per query. |
| `--max-candidates` | MAX_CANDIDATES | Stop after this many unique repositories. |
| `--min-score` | MIN_SCORE | Minimum score for Markdown reporting and URL enrichment. Tested value: 4. |
| `--enrich-urls` | none | HEAD/Range probe payload URLs for candidates at or above `--min-score`. |
| `--max-enrich` | MAX_ENRICH | Maximum URLs to enrich per candidate. Default: 3. |
| `--sleep-on-rate-limit` | none | Sleep until GitHub rate-limit reset instead of stopping. |
| `--skip-contributors-gte` | SKIP_CONTRIBUTORS_GTE | Drop candidates with at least this many observed contributors. Default: 3. |
| `--skip-top-files-gte` | SKIP_TOP_FILES_GTE | Drop candidates with at least this many meaningful top-level files. Default: 6. |
| `--skip-stars-gte` | SKIP_STARS_GTE | Drop candidates with at least this many stars. Default: 10. |
| `--skip-forks-gte` | SKIP_FORKS_GTE | Drop candidates with at least this many forks. Default: 3. |
| `--defang-report` | none | Defang URLs in Markdown output. This is the default. |
| `--raw-report` | none | Do not defang URLs in Markdown output. |
| `--triage-lookup` | none | Look up candidate payload URLs in tria.ge for candidates at or above `--triage-min-score`. |
| `--triage-submit` | none | Submit candidate payload URLs to tria.ge. Use `--full-run` for the normal full-pipeline workflow. Direct use requires `--i-understand-this-submits-malware`. |
| `--triage-min-score` | TRIAGE_MIN_SCORE | Minimum candidate score for tria.ge lookup/submission. Tested value: 8. |
| `--triage-max-urls` | TRIAGE_MAX_URLS | Maximum candidate payload URLs checked per candidate. Tested value: 3. |
| `--triage-profile` | TRIAGE_PROFILE | tria.ge analysis profile for URL submissions. Default: `default`. |
| `--triage-timeout` | TRIAGE_TIMEOUT | Seconds to wait for each tria.ge API request. Tested value: 10. |
| `--triage-submit-on-lookup-error` | none | Submit when tria.ge lookup times out or fails. Direct use requires submission mode and the acknowledgement flag. |
| `--triage-report` | TRIAGE_REPORTS | Pull and summarize an existing tria.ge sample ID. Can be repeated. |
| `--i-understand-this-submits-malware` | none | Required acknowledgement for direct `--triage-submit` usage. `--full-run` is the preferred full-pipeline switch. |
| `--cron` | none | Non-interactive mode for scheduled runs. Disables prompts and requires `GITHUB_TOKEN`. |
| `--yes`, `--non-interactive` | none | Same prompt behavior as `--cron`. |
| `--prompt-timeout` | PROMPT_TIMEOUT | Seconds to wait for key prompts before defaulting. |
| `--env-file` | ENV_FILE | Optional `.env` path. |
| `--require-github-token` | none | Fail if `GITHUB_TOKEN` is missing. |
| `--init` | none | Create input/out/logs directories and a chmod 600 `.env` placeholder. |
| `--set-github-token` | none | Prompt for and store `GITHUB_TOKEN` in `.env`. |
| `--set-triage-key` | none | Prompt for and store `TRIAGE_KEY` in `.env`. |
| `--import-apps` | IMPORT_APPS | Import app seeds from a text file into `brands.yaml`. |
| `--skip-app-review` | none | Do not show the configured app list before interactive runs. |
| `--validate-only` | none | Validate `brands.yaml`, keys, and arguments, then exit. |
| `--list-brands` | none | Print configured brand targets and related query context. |
| `--add-brand` | NAME | Add or update a brand. |
| `--query` | ADD_QUERIES | With `--add-brand`, add a search query. Can be repeated. |
| `--product` | PRODUCTS | With `--add-brand`, add a product seed, for example `'"SQL Server Management Studio" SSMS'`. Can be repeated. |
| `--official-org` | OFFICIAL_ORGS | With `--add-brand`, add an official GitHub organization suppressor. Can be repeated. |
| `--official-domain` | OFFICIAL_DOMAINS | With `--add-brand`, add an official domain or repository suppressor. Can be repeated. |
| `--notes` | NOTES | With `--add-brand`, store a notes string. |

## Stage 2 tria.ge behavior

Stage 1 always runs without tria.ge. Stage 2 runs when `--full-run` or another Stage 2 flag is requested and a `TRIAGE_KEY` is available.

Stage 2:

- collects payload, GitHub Release, Telegram, Dropbox, and unknown external URLs from candidates
- carries extracted archive passwords such as `github` or `2026` with each URL
- submits remote samples as tria.ge `kind=fetch` URL jobs with archive password, `interactive=false`, `timeout=200`, and `network=internet`
- only considers candidates at or above `--triage-min-score`
- stores lookup and submission results inside `candidates_*.json`
- pulls referenced tria.ge reports for lookup hits and successful submissions
- writes concise final IoC reports as `final_iocs_latest.json` and `final_iocs_latest.txt`
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
final_iocs_<timestamp>.json
final_iocs_latest.json
final_iocs_<timestamp>.txt
final_iocs_latest.txt
```

`report_latest.md` is the roll-up summary for the run. It lists candidates meeting the configured score threshold, explains why they scored, includes payload URL buckets, and includes Stage 2 tria.ge lookup/submission status when enabled.

`final_iocs_latest.json` and `final_iocs_latest.txt` are the analyst-facing IoC reports. They are grouped by app name and repository, include a short score summary, list high-scoring filenames beside SHA256/MD5/SHA1, then provide bulk hash, domain, and URL lists. They only include repositories with dangerous-looking tria.ge report output; routine browser, OS, certificate, CDN, and public IP-check traffic is suppressed.

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
