import json
import unittest
from urllib.error import HTTPError

from lib.triage import (
    TriageClient,
    collect_candidate_targets,
    collect_candidate_urls,
    enrich_candidates_with_triage,
    summarize_triage_report,
)


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status = status
        self._payload = payload or {}
        self.headers = headers or {}

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout=0, context=None):
        self.requests.append(req)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TriageStage2Tests(unittest.TestCase):
    def test_collect_candidate_urls_prefers_payload_buckets_and_dedupes(self):
        candidate = {
            "score_result": {
                "download_urls": {
                    "payload": ["https://payload.example/a.zip"],
                    "telegram": ["https://t.me/example"],
                    "unknown_external": ["https://payload.example/a.zip", "https://other.example/"],
                }
            }
        }
        self.assertEqual(
            collect_candidate_urls(candidate),
            ["https://payload.example/a.zip", "https://t.me/example", "https://other.example/"],
        )

    def test_collect_candidate_targets_pairs_urls_with_archive_passwords(self):
        candidate = {
            "score_result": {
                "passwords": ["github"],
                "download_urls": {
                    "payload": ["https://payload.example/a.zip"],
                    "unknown_external": ["https://other.example/"],
                },
            }
        }

        self.assertEqual(
            collect_candidate_targets(candidate),
            [
                {"url": "https://payload.example/a.zip", "passwords": ["github"]},
                {"url": "https://other.example/", "passwords": ["github"]},
            ],
        )

    def test_lookup_uses_bearer_key_without_exposing_key_in_result(self):
        opener = FakeOpener([FakeResponse(payload={"data": [{"id": "sample-1"}]})])
        client = TriageClient("secret-key", opener=opener)

        result = client.lookup_url("https://payload.example/a.zip")

        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], 1)
        req = opener.requests[0]
        self.assertIn("/v0/search?", req.full_url)
        self.assertEqual(req.headers.get("Authorization"), "Bearer secret-key")
        self.assertNotIn("secret-key", json.dumps(result))

    def test_lookup_records_archive_password_context_without_exposing_key(self):
        opener = FakeOpener([FakeResponse(payload={"data": []})])
        client = TriageClient("secret-key", opener=opener)

        result = client.lookup_url("https://payload.example/a.zip", passwords=["github"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["passwords"], ["github"])
        self.assertNotIn("secret-key", json.dumps(result))

    def test_submit_url_posts_fetch_json_and_returns_sample_id(self):
        opener = FakeOpener([FakeResponse(status=201, payload={"id": "submitted-1", "kind": "file"})])
        client = TriageClient("secret-key", opener=opener)

        result = client.submit_url("https://payload.example/a.zip", password="github")

        self.assertTrue(result["ok"])
        self.assertEqual(result["sample_id"], "submitted-1")
        req = opener.requests[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.headers.get("Content-type"), "application/json")
        self.assertIn("/v0/samples", req.full_url)
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["kind"], "fetch")
        self.assertEqual(body["url"], "https://payload.example/a.zip")
        self.assertEqual(body["password"], "github")
        self.assertFalse(body["interactive"])
        self.assertEqual(body["timeout"], 200)

    def test_candidate_enrichment_respects_score_threshold_and_records_errors(self):
        opener = FakeOpener([
            FakeResponse(payload={"data": []}),
            HTTPError("https://tria.ge/api/v0/search", 429, "rate limited", {}, None),
        ])
        client = TriageClient("secret-key", opener=opener)
        candidates = [
            {
                "full_name": "owner/high",
                "score_result": {"score": 9, "download_urls": {"payload": ["https://one.example/a.zip"]}},
            },
            {
                "full_name": "owner/low",
                "score_result": {"score": 3, "download_urls": {"payload": ["https://two.example/a.zip"]}},
            },
            {
                "full_name": "owner/error",
                "score_result": {"score": 9, "download_urls": {"payload": ["https://err.example/a.zip"]}},
            },
        ]

        summary = enrich_candidates_with_triage(candidates, client, min_score=8, submit=False)

        self.assertEqual(summary["candidates_considered"], 2)
        self.assertEqual(summary["lookups_attempted"], 2)
        self.assertEqual(summary["errors"], 1)
        self.assertIn("triage", candidates[0])
        self.assertNotIn("triage", candidates[1])
        self.assertFalse(candidates[2]["triage"]["lookups"][0]["ok"])

    def test_submit_mode_skips_existing_matches_and_lookup_errors_by_default(self):
        opener = FakeOpener([
            FakeResponse(payload={"data": [{"id": "existing"}]}),
            HTTPError("https://tria.ge/api/v0/search", 401, "unauthorized", {}, None),
        ])
        client = TriageClient("secret-key", opener=opener)
        candidates = [
            {"full_name": "owner/existing", "score_result": {"score": 9, "download_urls": {"payload": ["https://one.example/a.zip"]}}},
            {"full_name": "owner/error", "score_result": {"score": 9, "download_urls": {"payload": ["https://two.example/a.zip"]}}},
        ]

        summary = enrich_candidates_with_triage(candidates, client, min_score=8, submit=True)

        self.assertEqual(summary["submits_attempted"], 0)
        self.assertTrue(candidates[0]["triage"]["submissions"][0]["skipped"])
        self.assertTrue(candidates[1]["triage"]["submissions"][0]["skipped"])
        self.assertEqual(len(opener.requests), 2)

    def test_submit_mode_can_submit_after_lookup_error_when_explicitly_allowed(self):
        opener = FakeOpener([
            HTTPError("https://tria.ge/api/v0/search", 504, "timeout", {}, None),
            FakeResponse(status=201, payload={"id": "submitted-1"}),
        ])
        client = TriageClient("secret-key", opener=opener)
        candidates = [
            {"full_name": "owner/error", "score_result": {"score": 9, "passwords": ["2026"], "download_urls": {"payload": ["https://two.example/a.zip"]}}},
        ]

        summary = enrich_candidates_with_triage(
            candidates,
            client,
            min_score=8,
            submit=True,
            submit_on_lookup_error=True,
        )

        self.assertEqual(summary["submits_attempted"], 1)
        self.assertEqual(candidates[0]["triage"]["submissions"][0]["password"], "2026")

    def test_summarize_triage_report_formats_hashes_signatures_and_urls(self):
        report = {
            "sample": {"id": "sample-1", "status": "reported", "sha256": "a" * 64, "filename": "payload.zip"},
            "summary": {
                "score": 5,
                "target": "payload.zip",
                "tasks": {
                    "behavioral1": {"kind": "behavioral", "status": "reported", "score": 5, "target": "Install.exe", "sigs": 2},
                    "behavioral2": {"kind": "behavioral", "status": "reported", "score": 1, "target": "low.dll", "sigs": 0},
                },
            },
            "static": {
                "signatures": [{"name": "High confidence malicious behavior", "score": 7}],
                "files": [
                    {"filename": "payload.zip", "sha256": "b" * 64, "md5": "c" * 32},
                    {"filename": "Install.exe", "sha256": "d" * 64, "sha1": "e" * 40, "md5": "f" * 32, "selected": True},
                    {"filename": "low.dll", "sha256": "1" * 64, "selected": True},
                ],
                "strings": ["https://c2.example/a", "192.0.2.10"],
            },
        }

        summary = summarize_triage_report(report)

        self.assertEqual(summary["sample_id"], "sample-1")
        self.assertIn("High confidence malicious behavior", summary["signatures"])
        self.assertEqual(summary["high_score_tasks"][0]["target"], "Install.exe")
        self.assertIn("a" * 64, summary["iocs"]["sha256"])
        self.assertIn("d" * 64, summary["iocs"]["sha256"])
        self.assertIn("e" * 40, summary["iocs"]["sha1"])
        self.assertIn("f" * 32, summary["iocs"]["md5"])
        self.assertNotIn("1" * 64, summary["iocs"]["sha256"])
        self.assertNotIn("https://c2.example/a", summary["iocs"]["urls"])
        self.assertNotIn("192.0.2.10", summary["iocs"]["ips"])
        self.assertIn("Install.exe", summary["selected_files"])

    def test_summarize_triage_report_filters_certificate_revocation_noise(self):
        report = {
            "sample": {"id": "sample-1", "status": "reported", "filename": "payload.zip"},
            "summary": {"score": 5},
            "static": {
                "strings": [
                    "http://crl.comodoca.com/COMODORSACertificationAuthority.crl",
                    "http://crl3.digicert.com/DigiCertTrustedRootG4.crl",
                    "http://pki.intel.com/crl/IntelCA7B.crl",
                    "crl.usertrust.com",
                    "timestamp.intel.com",
                    "www.digicert.com",
                    "SDK5App.pdb",
                    "freebl3.pdb",
                    "https://payload.example/c2",
                    "fe-hpt-04168b48dafbce6b7.recfut.net",
                    "pro.su",
                    "192.0.2.10",
                    "1.3.6.1",
                    "2.5.4.15",
                ],
            },
        }

        summary = summarize_triage_report(report)

        self.assertNotIn("https://payload.example/c2", summary["iocs"]["urls"])
        self.assertNotIn("fe-hpt-04168b48dafbce6b7.recfut.net", summary["iocs"]["domains"])
        self.assertNotIn("pro.su", summary["iocs"]["domains"])
        self.assertNotIn("192.0.2.10", summary["iocs"]["ips"])
        self.assertNotIn("1.3.6.1", summary["iocs"]["ips"])
        self.assertNotIn("2.5.4.15", summary["iocs"]["ips"])

        self.assertNotIn("http://crl3.digicert.com/DigiCertTrustedRootG4.crl", summary["iocs"]["urls"])
        self.assertNotIn("http://pki.intel.com/crl/IntelCA7B.crl", summary["iocs"]["urls"])
        for noisy in ("crl.usertrust.com", "timestamp.intel.com", "www.digicert.com", "SDK5App.pdb", "freebl3.pdb"):
            self.assertNotIn(noisy, summary["iocs"]["domains"])


if __name__ == "__main__":
    unittest.main()
