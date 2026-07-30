import unittest

from lib.extract import extract_from_readme
from lib.score import score_candidate


EMPTY_EXTRACTED = {
    "passwords": [],
    "has_password_language": False,
    "download_urls": {
        "payload": [],
        "unknown_external": [],
        "dropbox": [],
        "telegram": [],
        "github_release": [],
        "local_dev": [],
    },
}


class BrandReasoningTests(unittest.TestCase):
    def test_ssms_school_management_wrong_product_is_dropped(self):
        result = score_candidate(
            repo={
                "full_name": "fatheen-se/School-Management-System-using-C-sharp-and-SSMS",
                "name": "School-Management-System-using-C-sharp-and-SSMS",
                "description": "School Management System using C# and SSMS",
                "size": 0,
                "stargazers_count": 0,
                "forks_count": 0,
                "created_at": "2026-07-12T03:07:24Z",
                "owner": {"login": "fatheen-se", "type": "User"},
            },
            owner={"login": "fatheen-se", "created_at": "2024-01-01T00:00:00Z", "followers": 0, "public_repos": 2},
            contents=[{"name": "README.md"}],
            releases=[],
            readme="# School Management System\nA student records app using SQL Server Management Studio.",
            extracted=EMPTY_EXTRACTED,
            official_orgs=[],
            brand_name="SSMS",
            contributor_count_seen=1,
            wrong_product_terms=["school management", "student management"],
            target_context_terms=["sql server management studio", "mssql", "installer", "download", "setup"],
            ambiguous_brand=True,
        )

        self.assertTrue(result["drop"])
        self.assertIn("wrong_product", result["flags"])

    def test_ambiguous_ssms_without_download_payload_or_target_context_is_suppressed(self):
        result = score_candidate(
            repo={
                "full_name": "example/ssms",
                "name": "ssms",
                "description": "",
                "size": 0,
                "stargazers_count": 0,
                "forks_count": 0,
                "created_at": "2026-07-12T03:07:24Z",
                "owner": {"login": "example", "type": "User"},
            },
            owner={"login": "example", "created_at": "2026-07-12T01:00:00Z", "followers": 0, "public_repos": 1},
            contents=[{"name": "README.md"}],
            releases=[],
            readme="# SSMS\nempty placeholder",
            extracted=EMPTY_EXTRACTED,
            official_orgs=[],
            brand_name="SSMS",
            contributor_count_seen=1,
            target_context_terms=["sql server management studio", "mssql", "installer", "download", "setup"],
            ambiguous_brand=True,
        )

        self.assertLess(result["score"], 4)
        self.assertIn("ambiguous brand lacks target context", "\n".join(result["reasons"]))

    def test_localhost_urls_are_not_external_payload_signal(self):
        extracted = extract_from_readme("Run UI at http://localhost:3000 and API at http://127.0.0.1:5000")
        self.assertEqual(extracted["download_urls"]["unknown_external"], [])
        self.assertEqual(len(extracted["download_urls"]["local_dev"]), 2)


if __name__ == "__main__":
    unittest.main()
