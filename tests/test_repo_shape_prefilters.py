import unittest

from lib.score import score_candidate


BASE_EXTRACTED = {
    "passwords": [],
    "has_password_language": False,
    "download_urls": {"payload": [], "unknown_external": [], "dropbox": [], "telegram": [], "github_release": []},
}


class RepoShapePrefilterTests(unittest.TestCase):
    def test_three_contributors_hard_drop_even_when_name_matches_download(self):
        result = score_candidate(
            repo={
                "full_name": "SomeOrg/Audacity-Windows-Download",
                "name": "Audacity-Windows-Download",
                "description": "Audacity Windows Download",
                "size": 20,
                "stargazers_count": 0,
                "forks_count": 0,
                "created_at": "2026-07-16T08:55:07Z",
                "owner": {"login": "SomeOrg", "type": "Organization"},
            },
            owner={"login": "SomeOrg", "created_at": "2026-07-16T08:52:15Z", "followers": 0, "public_repos": 2},
            contents=[{"name": "README.md"}],
            releases=[],
            readme="Download for Windows",
            extracted=BASE_EXTRACTED,
            official_orgs=[],
            brand_name="Audacity",
            contributor_count_seen=3,
            skip_contributors_gte=3,
        )

        self.assertTrue(result["drop"])
        self.assertIn("repo_shape_suppressor", result["flags"])

    def test_six_top_level_files_hard_drop(self):
        contents = [{"name": name} for name in ["README.md", "src", "docs", "tests", "LICENSE", "CMakeLists.txt"]]
        result = score_candidate(
            repo={
                "full_name": "SomeOrg/Audacity-Windows-Download",
                "name": "Audacity-Windows-Download",
                "description": "Audacity Windows Download",
                "size": 20,
                "stargazers_count": 0,
                "forks_count": 0,
                "created_at": "2026-07-16T08:55:07Z",
                "owner": {"login": "SomeOrg", "type": "Organization"},
            },
            owner={"login": "SomeOrg", "created_at": "2026-07-16T08:52:15Z", "followers": 0, "public_repos": 2},
            contents=contents,
            releases=[],
            readme="Download for Windows",
            extracted=BASE_EXTRACTED,
            official_orgs=[],
            brand_name="Audacity",
            contributor_count_seen=1,
            skip_top_files_gte=6,
        )

        self.assertTrue(result["drop"])
        self.assertIn("top-level files", "\n".join(result["reasons"]))

    def test_zero_stars_one_contributor_readme_only_gets_strong_shape_score(self):
        result = score_candidate(
            repo={
                "full_name": "SomeOrg/Audacity-Windows-Download",
                "name": "Audacity-Windows-Download",
                "description": "Audacity Windows Download",
                "size": 3,
                "stargazers_count": 0,
                "forks_count": 0,
                "created_at": "2026-07-16T08:55:07Z",
                "owner": {"login": "SomeOrg", "type": "Organization"},
            },
            owner={"login": "SomeOrg", "created_at": "2026-07-16T08:52:15Z", "followers": 0, "public_repos": 2},
            contents=[{"name": "README.md"}],
            releases=[],
            readme="Download for Windows",
            extracted=BASE_EXTRACTED,
            official_orgs=[],
            brand_name="Audacity",
            contributor_count_seen=1,
        )

        self.assertFalse(result["drop"])
        joined = "\n".join(result["reasons"])
        self.assertIn("one contributor observed", joined)
        self.assertIn("repo is very young relative to owner", joined)


if __name__ == "__main__":
    unittest.main()
