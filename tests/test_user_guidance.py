import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hunt import import_apps_file, review_configured_brands
from lib.brands import add_brand, load_brands, validate_brands
from lib.github_client import GitHubClient
from lib.triage import write_triage_report_outputs


class UserGuidanceTests(unittest.TestCase):
    def test_import_multiword_app_generates_acronym_alias_and_queries(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            brands = root / "brands.yaml"
            brands.write_text("brands: []\n", encoding="utf-8")
            apps = root / "apps.txt"
            apps.write_text("SQL Server Management Studio\n", encoding="utf-8")

            imported = import_apps_file(apps, brands)
            data = load_brands(brands)
            entry = data["brands"][0]

            self.assertEqual(imported[0]["name"], "SSMS")
            self.assertEqual(entry["product_aliases"][0], {"full": "SQL Server Management Studio", "acronym": "SSMS"})
            self.assertIn('"SQL Server Management Studio" download', entry["queries"])
            self.assertIn("SSMS download", entry["queries"])
            self.assertIn("SSMS in:name", entry["queries"])
            self.assertTrue(entry["ambiguous_brand"])

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
            apps.write_text("SQL Server Management Studio\n", encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
