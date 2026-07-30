import unittest

from lib.brands import parse_product_line, normalize_brand_entry
from lib.score import score_candidate


class ProductAliasReasoningTests(unittest.TestCase):
    def test_parse_quoted_full_name_followed_by_acronym(self):
        self.assertEqual(
            parse_product_line('"SQL Server Management Studio" SSMS'),
            {"full": "SQL Server Management Studio", "acronym": "SSMS"},
        )

    def test_normalize_derives_queries_and_context_from_product_alias(self):
        brand = normalize_brand_entry(
            {
                "name": "SSMS",
                "products": ['"SQL Server Management Studio" SSMS'],
                "queries": [],
            }
        )

        self.assertIn('"SQL Server Management Studio" download', brand["queries"])
        self.assertIn("SSMS download", brand["queries"])
        self.assertIn("SSMS in:name", brand["queries"])
        self.assertNotIn('"SQL Server Management Studio" in:readme', brand["queries"])
        self.assertIn("sql server management studio", brand["target_context_terms"])
        self.assertTrue(brand["ambiguous_brand"])

    def test_spelled_out_product_match_boosts_acronym_candidate(self):
        result = score_candidate(
            repo={
                "full_name": "x/SSMS-Windows-Download",
                "name": "SSMS-Windows-Download",
                "description": "SQL Server Management Studio Windows Download",
                "size": 3,
                "stargazers_count": 0,
                "forks_count": 0,
                "created_at": "2026-07-16T08:55:07Z",
                "owner": {"login": "x", "type": "User"},
            },
            owner={"login": "x", "created_at": "2026-07-16T08:00:00Z", "followers": 0, "public_repos": 1},
            contents=[{"name": "README.md"}],
            releases=[],
            readme="# SQL Server Management Studio\nDownload SSMS for Windows",
            extracted={
                "passwords": [],
                "has_password_language": False,
                "download_urls": {"payload": [], "unknown_external": [], "dropbox": [], "telegram": [], "github_release": []},
            },
            official_orgs=[],
            brand_name="SSMS",
            contributor_count_seen=1,
            product_aliases=[{"full": "SQL Server Management Studio", "acronym": "SSMS"}],
            target_context_terms=["sql server management studio"],
            ambiguous_brand=True,
        )

        self.assertEqual(result["score"], 7)
        joined = "\n".join(result["reasons"])
        self.assertIn("full product phrase matched", joined)
        self.assertIn("capped below high", joined)


if __name__ == "__main__":
    unittest.main()
