import unittest

from lib.extract import extract_from_readme
from lib.score import score_candidate
from lib.report import defang_text


FAKE_AUDACITY_README = """
# Audacity – Digital Audio Recording & Editing Platform

![Audacity logo](https://forum.audacityteam.org/uploads/default/original/3X/5/b/logo.jpeg)
[![Download for Windows](https://cdn.intheloop.io/wp-content/uploads/2020/08/windows-button.png)](https://getgithub.help)

Password: `github`

Click the button above to access the official download page.
"""

ALT_AUDACITY_AI_README = """
# 🚀 Free Download Audacity-AI for Windows 2025: AI Audio Editing Software

[Download Now](https://t.me/fsdfwerqwe/4?84B9214FA8264C2D87B3D9936164AE3E)
"""

REAL_AUDACITY_README = """
# Audacity

Audacity is an easy-to-use, multi-track audio editor and recorder.

More details at https://www.audacityteam.org/ and docs at https://support.audacityteam.org/.
"""


class ExtractAndScoreTests(unittest.TestCase):
    def test_extract_separates_payload_from_decorative_urls_and_password(self):
        extracted = extract_from_readme(FAKE_AUDACITY_README)

        self.assertEqual(extracted["passwords"], ["github"])
        self.assertIn("https://getgithub.help", extracted["download_urls"]["payload"])
        self.assertIn(
            "https://cdn.intheloop.io/wp-content/uploads/2020/08/windows-button.png",
            extracted["download_urls"]["decorative"],
        )
        self.assertIn(
            "https://forum.audacityteam.org/uploads/default/original/3X/5/b/logo.jpeg",
            extracted["download_urls"]["decorative"],
        )
        self.assertNotIn("word", extracted["passwords"])

    def test_extract_classifies_telegram_download_as_payload(self):
        extracted = extract_from_readme(ALT_AUDACITY_AI_README)

        self.assertIn(
            "https://t.me/fsdfwerqwe/4?84B9214FA8264C2D87B3D9936164AE3E",
            extracted["download_urls"]["payload"],
        )

    def test_fake_repo_scores_high_without_decorative_url_points(self):
        repo = {
            "full_name": "Audacity-Audio-Editing/Audacity-Windows-Download",
            "name": "Audacity-Windows-Download",
            "description": "Audacity Windows Download",
            "size": 3,
            "stargazers_count": 0,
            "forks_count": 0,
            "created_at": "2026-07-16T08:55:07Z",
            "owner": {"login": "Audacity-Audio-Editing", "type": "Organization"},
        }
        owner = {
            "login": "Audacity-Audio-Editing",
            "type": "Organization",
            "created_at": "2026-07-16T08:52:15Z",
            "followers": 0,
            "public_repos": 2,
        }
        contents = [{"name": "README.md"}]
        extracted = extract_from_readme(FAKE_AUDACITY_README)

        result = score_candidate(
            repo=repo,
            owner=owner,
            contents=contents,
            releases=[],
            readme=FAKE_AUDACITY_README,
            extracted=extracted,
            official_orgs=["audacity"],
            official_domains=["audacityteam.org", "github.com/audacity/audacity"],
            brand_name="Audacity",
        )

        self.assertGreaterEqual(result["score"], 10)
        joined = "\n".join(result["reasons"])
        self.assertIn("payload/download URL", joined)
        self.assertNotIn("cdn.intheloop", joined)
        self.assertNotIn("forum.audacityteam", joined)

    def test_real_official_repo_is_dropped(self):
        repo = {
            "full_name": "audacity/audacity",
            "name": "audacity",
            "description": "Audio Editor",
            "size": 500000,
            "stargazers_count": 17800,
            "forks_count": 3200,
            "created_at": "2015-05-28T00:00:00Z",
            "owner": {"login": "audacity", "type": "Organization"},
        }
        owner = {
            "login": "audacity",
            "type": "Organization",
            "created_at": "2015-05-28T00:00:00Z",
            "followers": 1000,
            "public_repos": 20,
        }
        contents = [{"name": name} for name in ["src", "lib-src", "README.md", "LICENSE.txt", "CMakeLists.txt", "docs", "images", "tests"]]
        extracted = extract_from_readme(REAL_AUDACITY_README)

        result = score_candidate(
            repo=repo,
            owner=owner,
            contents=contents,
            releases=[{"assets": [{"name": "audacity-win.exe"}]}],
            readme=REAL_AUDACITY_README,
            extracted=extracted,
            official_orgs=["audacity"],
            official_domains=["audacityteam.org", "github.com/audacity/audacity"],
            brand_name="Audacity",
        )

        self.assertTrue(result["drop"])
        self.assertIn("official", result["flags"])

    def test_markdown_defanging_defangs_domains_without_touching_json_requirement(self):
        text = "https://getgithub.help and https://t.me/fsdfwerqwe and github.com/Audacity-Audio"
        self.assertEqual(
            defang_text(text),
            "hxxps://getgithub[.]help and hxxps://t[.]me/fsdfwerqwe and github[.]com/Audacity-Audio",
        )


if __name__ == "__main__":
    unittest.main()
