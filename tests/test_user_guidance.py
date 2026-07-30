import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hunt import attach_triage_reports, import_apps_file, review_configured_brands
from lib.brands import add_brand, load_brands, validate_brands
from lib.github_client import GitHubClient
from lib.report import write_final_ioc_outputs, write_outputs
from lib.triage import write_triage_report_outputs


class UserGuidanceTests(unittest.TestCase):
    def test_import_explicit_multiword_alias_generates_acronym_alias_and_queries(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            brands = root / "brands.yaml"
            brands.write_text("brands: []\n", encoding="utf-8")
            apps = root / "apps.txt"
            apps.write_text('"SQL Server Management Studio" SSMS\n', encoding="utf-8")

            imported = import_apps_file(apps, brands)
            data = load_brands(brands)
            entry = data["brands"][0]

            self.assertEqual(imported[0]["name"], "SSMS")
            self.assertEqual(entry["product_aliases"][0], {"full": "SQL Server Management Studio", "acronym": "SSMS"})
            self.assertIn('"SQL Server Management Studio" download', entry["queries"])
            self.assertIn("SSMS download", entry["queries"])
            self.assertIn("SSMS in:name", entry["queries"])
            self.assertTrue(entry["ambiguous_brand"])

    def test_import_plain_multiword_app_does_not_invent_acronym_alias(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            brands = root / "brands.yaml"
            brands.write_text("brands: []\n", encoding="utf-8")
            apps = root / "apps.txt"
            apps.write_text("PDF converter\nOBS Studio\n", encoding="utf-8")

            import_apps_file(apps, brands)
            data = load_brands(brands)
            by_name = {b["name"]: b for b in data["brands"]}

            self.assertIn("PDF converter", by_name)
            self.assertIn("OBS Studio", by_name)
            self.assertNotIn("PC", by_name)
            self.assertNotIn("OS", by_name)
            self.assertNotIn("PC download", by_name["PDF converter"]["queries"])
            self.assertNotIn("OS download", by_name["OBS Studio"]["queries"])

    def test_validate_brands_reports_invalid_entries_before_run(self):
        data = {
            "brands": [
                {"name": "", "queries": []},
                {"name": "Bad", "queries": []},
                {"name": "Good", "queries": ["Good download"]},
            ]
        }

        issues = validate_brands(data)

        self.assertIn("brand #1 is missing name", issues)
        self.assertIn("brand 'Bad' has no queries", issues)
        self.assertNotIn("Good", "\n".join(issues))

    def test_review_configured_brands_shows_list_and_can_import_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            brands = root / "brands.yaml"
            brands.write_text("brands:\n- name: Audacity\n  queries:\n  - Audacity download windows\n", encoding="utf-8")
            apps = root / "apps.txt"
            apps.write_text('"SQL Server Management Studio" SSMS\n', encoding="utf-8")
            out = io.StringIO()

            with patch("hunt.prompt_with_timeout", return_value=f"import {apps}"), redirect_stdout(out):
                review_configured_brands(brands, non_interactive=False, prompt_timeout=1)

            text = out.getvalue()
            self.assertIn("Configured GRIFT app targets", text)
            self.assertIn("Audacity", text)
            self.assertIn("Imported 1 app seed", text)
            loaded = load_brands(brands)
            self.assertTrue(any(b.get("name") == "SSMS" for b in loaded["brands"]))

    def test_add_brand_multiword_generates_acronym_alias(self):
        with tempfile.TemporaryDirectory() as d:
            brands = Path(d) / "brands.yaml"
            brands.write_text("brands: []\n", encoding="utf-8")

            entry = add_brand(brands, "SQL Server Management Studio", [])

            self.assertEqual(entry["name"], "SSMS")
            self.assertEqual(entry["products"], ['"SQL Server Management Studio" SSMS'])

    def test_clients_validate_keys_without_exposing_secret(self):
        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"resources":{"core":{"limit":5000}}}'
        seen = []
        def opener(req, **kwargs):
            seen.append(req)
            return Resp()

        result = GitHubClient(token="ghp_secretvalue", opener=opener).validate_token()

        self.assertTrue(result["ok"])
        self.assertNotIn("secretvalue", str(result))
        self.assertEqual(seen[0].full_url, "https://api.github.com/rate_limit")

    def test_triage_report_lists_file_hash_reference_up_top_and_bulk_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            report = {
                "sample": {"id": "sample-1", "status": "reported", "sha256": "a" * 64, "filename": "payload.zip"},
                "summary": {
                    "score": 5,
                    "target": "payload.zip",
                    "tasks": {
                        "sample-1-behavioral1": {"kind": "behavioral", "score": 5, "target": "Install.exe", "sigs": 2, "os": "windows10"},
                        "sample-1-behavioral2": {"kind": "behavioral", "score": 5, "target": "Install.exe", "sigs": 2, "os": "windows11"},
                    },
                },
                "static": {
                    "files": [
                        {"filename": "Install.exe", "sha256": "b" * 64, "sha1": "c" * 40, "md5": "d" * 32}
                    ]
                },
            }
            paths = write_triage_report_outputs(Path(d), "sample-1", report)
            text = paths["md"].read_text(encoding="utf-8")

            self.assertIn("`Install.exe` — sha256 `" + "b" * 64 + "`", text)
            self.assertIn("### SHA256\n- `" + "a" * 64 + "`\n- `" + "b" * 64 + "`", text)
    def test_final_ioc_report_groups_repos_by_app_and_excludes_empty_triage(self):
        with tempfile.TemporaryDirectory() as d:
            candidates = [
                {
                    "brand": "TeamViewer",
                    "full_name": "owner/dangerous-repo",
                    "html_url": "https://github.com/owner/dangerous-repo",
                    "score_result": {
                        "score": 9,
                        "reasons": ["README mentions password", "payload/download URL(s)"],
                        "download_urls": {"payload": ["https://github.com/stage/repo/releases/download/v/SoftwareSetup.zip"]},
                    },
                    "triage": {
                        "reports": [
                            {
                                "sample_id": "sample-1",
                                "summary_iocs": {
                                    "selected_file_hashes": [
                                        {"filename": "Setup.exe", "sha256": "a" * 64, "md5": "b" * 32, "sha1": "c" * 40}
                                    ],
                                    "iocs": {
                                        "sha256": ["d" * 64],
                                        "md5": [],
                                        "sha1": [],
                                        "domains": ["c2.example"],
                                        "urls": ["http://192.0.2.10/payload.exe"],
                                    },
                                },
                            }
                        ]
                    },
                },
                {
                    "brand": "TeamViewer",
                    "full_name": "owner/no-triage-hit",
                    "html_url": "https://github.com/owner/no-triage-hit",
                    "score_result": {"score": 9, "reasons": ["shape only"], "download_urls": {}},
                    "triage": {"reports": []},
                },
            ]

            paths = write_final_ioc_outputs(Path(d), candidates=candidates, meta={"generated_at": "now", "brands": ["TeamViewer"]})
            text = paths["final_txt_latest"].read_text(encoding="utf-8")

            self.assertIn("TeamViewer", text)
            self.assertIn("owner/dangerous-repo", text)
            self.assertIn("Setup.exe sha256=" + "a" * 64, text)
            self.assertIn("c2.example", text)
            self.assertIn("http://192.0.2.10/payload.exe", text)
            self.assertNotIn("owner/no-triage-hit", text)

    def test_attach_triage_reports_pulls_lookup_and_submission_sample_ids(self):
        class FakeTriageClient:
            def __init__(self):
                self.pulled = []
            def collect_report(self, sample_id):
                self.pulled.append(sample_id)
                return {"sample_id": sample_id, "summary_iocs": {"selected_file_hashes": []}}

        candidates = [
            {
                "full_name": "owner/repo-a",
                "triage": {
                    "lookups": [{"results": [{"id": "sample-a"}]}],
                    "submissions": [{"sample_id": "sample-b"}],
                },
            },
            {
                "full_name": "owner/repo-b",
                "triage": {
                    "lookups": [{"results": [{"id": "sample-a"}]}],
                    "submissions": [],
                },
            },
        ]
        client = FakeTriageClient()

        pulled = attach_triage_reports(candidates, client)

        self.assertEqual(pulled, 2)
        self.assertEqual(client.pulled, ["sample-a", "sample-b"])
        self.assertEqual([r["sample_id"] for r in candidates[0]["triage"]["reports"]], ["sample-a", "sample-b"])
        self.assertEqual([r["sample_id"] for r in candidates[1]["triage"]["reports"]], ["sample-a"])

    def test_markdown_report_always_states_stage2_status_summary(self):
        with tempfile.TemporaryDirectory() as d:
            paths = write_outputs(
                Path(d),
                candidates=[],
                meta={
                    "generated_at": "2026-07-30T00:00:00Z",
                    "created_after": "2026-07-01",
                    "brands": ["Audacity"],
                    "min_score": 4,
                    "triage_lookup_requested": True,
                    "triage_stage2_status": "completed",
                    "triage": {
                        "status": "completed",
                        "eligible_candidates": 2,
                        "candidates_considered": 1,
                        "candidates_without_targets": 1,
                        "static_targets_skipped": 2,
                        "targets_considered": 3,
                        "lookups_attempted": 3,
                        "duplicate_targets_reused": 1,
                        "submits_attempted": 2,
                        "duplicate_submissions_reused": 1,
                        "lookup_matches": 0,
                        "errors": 0,
                    },
                },
            )

            text = paths["md_latest"].read_text(encoding="utf-8")
            self.assertIn("- tria.ge Stage 2: `completed`", text)
            self.assertIn("eligible candidates: `2`", text)
            self.assertIn("lookups attempted: `3`", text)
            self.assertIn("static/decorative targets skipped: `2`", text)
            self.assertIn("duplicate target lookups reused: `1`", text)
            self.assertIn("submissions attempted: `2`", text)
            self.assertIn("duplicate submissions reused: `1`", text)


if __name__ == "__main__":
    unittest.main()
