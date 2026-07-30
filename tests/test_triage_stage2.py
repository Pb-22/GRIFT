import json
import unittest
from urllib.error import HTTPError

from lib.triage import TriageClient, collect_candidate_urls, enrich_candidates_with_triage


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

    def test_submit_url_posts_json_and_returns_sample_id(self):
        opener = FakeOpener([FakeResponse(status=201, payload={"id": "submitted-1"})])
        client = TriageClient("secret-key", opener=opener)

        result = client.submit_url("https://payload.example/a.zip")

        self.assertTrue(result["ok"])
        self.assertEqual(result["sample_id"], "submitted-1")
        req = opener.requests[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.headers.get("Content-type"), "application/json")
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["url"], "https://payload.example/a.zip")

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
    def test_submit_mode_skips_existing_matches_and_lookup_errors(self):
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


if __name__ == "__main__":
    unittest.main()
