"""The audit log: every arXiv request a search makes is reported back to the UI."""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from arxiv_analytics import client, demo
from arxiv_analytics.server import App, make_handler

FEED = (Path(__file__).parent / "fixtures" / "ev_feed.xml").read_text()


def fake_fetch(*_args):
    return FEED


def failing_fetch(*_args):
    raise urllib.error.URLError("connection refused")


class ClientAuditTest(unittest.TestCase):
    def test_one_entry_per_request(self):
        audit = []
        client.search(client.SearchParams(topic="electric vehicle", max_results=10),
                      fetch=fake_fetch, delay=0, audit=audit)
        self.assertEqual(len(audit), 1)
        entry = audit[0]
        self.assertEqual(entry["source"], "arxiv")
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["query"], 'all:"electric vehicle"')
        self.assertEqual(entry["url"], client.request_url('all:"electric vehicle"', 0, 10,
                                                          "submittedDate", "descending"))
        self.assertIn("search_query=all%3A%22electric+vehicle%22", entry["url"])
        self.assertEqual((entry["start"], entry["max_results"]), (0, 10))
        self.assertEqual((entry["returned"], entry["total"], entry["http_status"]), (4, 4, 200))
        self.assertIsInstance(entry["duration_ms"], int)
        self.assertTrue(entry["time"].endswith("+00:00"))

    def test_paged_search_logs_each_page(self):
        audit = []
        big = FEED.replace("<opensearch:totalResults>4", "<opensearch:totalResults>1000")
        client.search(client.SearchParams(topic="ev", max_results=450),
                      fetch=lambda *a: big, delay=0, audit=audit)
        self.assertEqual([(e["start"], e["max_results"]) for e in audit],
                         [(0, 200), (200, 200), (400, 50)])

    def test_failed_request_is_logged_then_raised(self):
        audit = []
        with self.assertRaises(urllib.error.URLError):
            client.search(client.SearchParams(topic="ev"), fetch=failing_fetch, delay=0, audit=audit)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["status"], "error")
        self.assertIn("connection refused", audit[0]["error"])

    def test_debug_logging(self):
        with self.assertLogs("arxiv_analytics.client", level="DEBUG") as logs:
            client.search(client.SearchParams(topic="electric vehicle"), fetch=fake_fetch, delay=0)
        self.assertTrue(any("arXiv request: https://export.arxiv.org/api/query?search_query=all%3A"
                            in line for line in logs.output))
        self.assertTrue(any("4 entries of 4 total" in line for line in logs.output))

    def test_demo_search_logs_no_request(self):
        audit = []
        demo.search(client.SearchParams(topic="graph neural networks"), audit=audit)
        self.assertEqual(len(audit), 1)
        self.assertEqual((audit[0]["source"], audit[0]["status"]), ("demo", "demo"))
        self.assertNotIn("url", audit[0])


class ApiAuditTest(unittest.TestCase):
    def serve(self, fetch):
        def search_fn(params, audit):
            papers, total, query = client.search(params, fetch=fetch, delay=0, audit=audit)
            return [p.to_dict() for p in papers], total, query

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(search_fn=search_fn)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(self, base, path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def test_search_response_carries_audit(self):
        base = self.serve(fake_fetch)
        res = self.post(base, "/api/search", {"topic": "electric vehicle", "categories": ["eess.SY"]})
        self.assertEqual(len(res["audit"]), 1)
        self.assertEqual(res["audit"][0]["query"], 'all:"electric vehicle" AND cat:eess.SY')

    def test_compare_tags_entries_with_topic(self):
        base = self.serve(fake_fetch)
        res = self.post(base, "/api/compare", {"topics": ["electric vehicle", "battery"]})
        self.assertEqual([e["action"] for e in res["audit"]],
                         ["compare: electric vehicle", "compare: battery"])

    def test_failed_search_still_returns_audit(self):
        base = self.serve(failing_fetch)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(base, "/api/search", {"topic": "electric vehicle"})
        self.assertEqual(ctx.exception.code, 502)
        body = json.loads(ctx.exception.read())
        self.assertEqual(body["audit"][0]["status"], "error")
        self.assertEqual(body["audit"][0]["query"], 'all:"electric vehicle"')


if __name__ == "__main__":
    unittest.main()
