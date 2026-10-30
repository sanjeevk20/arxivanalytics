"""End-to-end checks for a search on the topic "electric vehicle".

arXiv is never called: a fake fetch returns tests/fixtures/ev_feed.xml, a made-up
arXiv response with four EV papers, and records the query that would have been sent.
"""

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from arxiv_analytics import analytics, client, demo
from arxiv_analytics.server import App, make_handler

EV_FEED = (Path(__file__).parent / "fixtures" / "ev_feed.xml").read_text()


class FakeArxiv:
    """Stands in for client._fetch_page and remembers each request."""

    def __init__(self, feed=EV_FEED):
        self.feed, self.calls = feed, []

    def __call__(self, query, start, size, sort_by, sort_order, timeout):
        self.calls.append({"query": query, "start": start, "size": size, "sort_by": sort_by})
        return self.feed


def ev_search(**overrides):
    fake = FakeArxiv()
    params = client.SearchParams(topic="electric vehicle", **overrides)
    papers, total, query = client.search(params, fetch=fake, delay=0)
    return [p.to_dict() for p in papers], total, query, fake


class ElectricVehicleQueryTest(unittest.TestCase):
    def test_topic_is_sent_as_an_exact_phrase(self):
        query = client.build_query(client.SearchParams(topic="electric vehicle"))
        self.assertEqual(query, 'all:"electric vehicle"')

    def test_with_alternatives_category_and_dates(self):
        query = client.build_query(client.SearchParams(
            topic="electric vehicle, EV charging", field="ti",
            categories=["eess.SY"], date_from="2023-01-01", date_to="2024-12-31"))
        self.assertEqual(
            query,
            '(ti:"electric vehicle" OR ti:"EV charging") AND cat:eess.SY'
            " AND submittedDate:[202301010000 TO 202412312359]")


class ElectricVehicleSearchTest(unittest.TestCase):
    def test_search_sends_query_and_parses_results(self):
        papers, total, query, fake = ev_search(max_results=50)
        self.assertEqual(query, 'all:"electric vehicle"')
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["query"], 'all:"electric vehicle"')
        self.assertEqual(fake.calls[0]["size"], 50)
        self.assertEqual(total, 4)
        self.assertEqual(len(papers), 4)
        for paper in papers:
            text = f"{paper['title']} {paper['summary']}".lower()
            self.assertIn("electric vehicle", text, paper["id"])

    def test_paper_fields(self):
        papers, *_ = ev_search()
        first = papers[0]
        self.assertEqual(first["id"], "2301.10001v1")
        self.assertEqual(first["title"],
                         "Fixture: Electric Vehicle Charging Station Placement on Road Networks")
        self.assertEqual(first["authors"], ["Ada Fixture", "Ben Fixture"])
        self.assertEqual(first["primary_category"], "eess.SY")
        self.assertEqual(first["categories"], ["eess.SY", "math.OC"])
        self.assertEqual(first["pdf_url"], "http://arxiv.org/pdf/2301.10001v1")
        # Line breaks inside the abstract are collapsed to single spaces.
        self.assertNotIn("\n", first["summary"])

    def test_analytics(self):
        papers, *_ = ev_search()
        a = analytics.analyze(papers)
        self.assertEqual(a["summary"]["papers"], 4)
        self.assertEqual(a["summary"]["unique_authors"], 4)
        self.assertEqual(a["summary"]["cross_listed_pct"], 50.0)
        self.assertEqual(a["summary"]["date_from"], "2023-01-10")
        self.assertEqual(a["summary"]["date_to"], "2024-05-20")
        self.assertEqual(a["primary_categories"][0], {"name": "eess.SY", "count": 2,
                                                      "label": "Systems and Control"})
        self.assertEqual(a["phrases"][0], {"term": "electric vehicle", "count": 4})
        self.assertEqual(a["top_authors"][:2], [{"name": "Ada Fixture", "count": 2},
                                                {"name": "Ben Fixture", "count": 2}])
        self.assertEqual(a["by_year"], [{"period": "2023", "count": 2},
                                        {"period": "2024", "count": 2}])

    def test_refining_results(self):
        papers, *_ = ev_search()
        self.assertEqual(len(analytics.filter_papers(papers, categories=["eess.SY"])), 3)
        self.assertEqual(len(analytics.filter_papers(papers, categories=["eess.SY"],
                                                     primary_only=True)), 2)
        self.assertEqual(len(analytics.filter_papers(papers, text="battery")), 1)
        self.assertEqual(len(analytics.filter_papers(papers, year_from=2024)), 2)
        self.assertEqual(len(analytics.filter_papers(papers, author="ada")), 2)


class ElectricVehicleApiTest(unittest.TestCase):
    """Same search through the HTTP API the UI uses, with arXiv faked out."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakeArxiv()

        def search_fn(params):
            papers, total, query = client.search(params, fetch=cls.fake, delay=0)
            return [p.to_dict() for p in papers], total, query

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(search_fn=search_fn)))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def test_search_refine_and_export(self):
        res = self.post("/api/search", {"topic": "electric vehicle", "categories": ["eess.SY"],
                                        "max_results": 100})
        self.assertEqual(res["query"], 'all:"electric vehicle" AND cat:eess.SY')
        self.assertEqual(self.fake.calls[-1]["query"], res["query"])
        self.assertEqual(res["source"], "arxiv")
        self.assertEqual(res["fetched"], 4)
        self.assertEqual(res["analytics"]["phrases"][0]["term"], "electric vehicle")

        refined = self.post("/api/analyze", {"result_id": res["result_id"],
                                             "filters": {"text": "battery"}})
        self.assertEqual(refined["fetched"], 1)
        self.assertEqual(refined["papers"][0]["id"], "2306.10002v1")

        url = f"{self.base}/api/export?result_id={res['result_id']}&format=csv"
        with urllib.request.urlopen(url) as resp:
            rows = resp.read().decode().strip().splitlines()
        self.assertEqual(len(rows), 1 + 4)  # header + one row per paper
        self.assertIn("Electric Vehicle", rows[1])


class ElectricVehicleDemoModeTest(unittest.TestCase):
    def test_demo_corpus_has_no_ev_papers_and_returns_empty_cleanly(self):
        papers, total, query = demo.search(client.SearchParams(topic="electric vehicle"))
        self.assertEqual(query, 'all:"electric vehicle"')
        self.assertEqual((papers, total), ([], 0))
        self.assertEqual(analytics.analyze(papers)["summary"]["papers"], 0)


if __name__ == "__main__":
    unittest.main()
