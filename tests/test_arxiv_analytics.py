import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from arxiv_analytics import analytics, client, demo
from arxiv_analytics.server import App, make_handler, to_csv

FEED = (Path(__file__).parent / "fixtures" / "feed.xml").read_text()


def fixture_papers():
    papers, _ = client.parse_feed(FEED)
    return [p.to_dict() for p in papers]


class BuildQueryTest(unittest.TestCase):
    def test_combines_topic_categories_authors_and_dates(self):
        q = client.build_query(client.SearchParams(
            topic="map matching, GNN", categories=["cs.LG", "cs.CV"], authors=["Smith"],
            date_from="2023-01-01", date_to="2024-12-31"))
        self.assertEqual(
            q, '(all:"map matching" OR all:GNN) AND (cat:cs.LG OR cat:cs.CV) AND au:Smith'
               " AND submittedDate:[202301010000 TO 202412312359]")

    def test_field_and_open_ended_date(self):
        q = client.build_query(client.SearchParams(topic="lidar", field="ti", date_from="2020-05-01"))
        self.assertEqual(q, "ti:lidar AND submittedDate:[202005010000 TO 209912312359]")

    def test_unknown_field_falls_back_to_all(self):
        self.assertEqual(client.build_query(client.SearchParams(topic="x", field="bogus")), "all:x")

    def test_requires_some_criterion(self):
        with self.assertRaises(ValueError):
            client.build_query(client.SearchParams())


class ParseFeedTest(unittest.TestCase):
    def test_parses_entries(self):
        papers, total = client.parse_feed(FEED)
        self.assertEqual(total, 3)
        p = papers[0]
        self.assertEqual(p.id, "2401.00001v1")
        self.assertEqual(p.title, "Fixture Paper on Map Matching")
        self.assertEqual(p.authors, ["Alice Fixture", "Bob Fixture"])
        self.assertEqual(p.primary_category, "cs.LG")
        self.assertEqual(p.categories, ["cs.LG", "cs.CV"])
        self.assertEqual(p.pdf_url, "http://arxiv.org/pdf/2401.00001v1")
        self.assertEqual(p.doi, "10.0000/fixture.1")


class SearchPagingTest(unittest.TestCase):
    def test_pages_until_limit(self):
        calls = []

        def fake_fetch(query, start, size, sort_by, sort_order, timeout):
            calls.append((start, size))
            return FEED.replace("<opensearch:totalResults>3", "<opensearch:totalResults>1000")

        papers, total, _ = client.search(
            client.SearchParams(topic="x", max_results=450), fetch=fake_fetch, delay=0)
        self.assertEqual(calls, [(0, 200), (200, 200), (400, 50)])
        self.assertEqual(total, 1000)
        self.assertEqual(len(papers), 9)  # 3 fixture entries per fake page


class AnalyticsTest(unittest.TestCase):
    def test_summary_and_rankings(self):
        a = analytics.analyze(fixture_papers())
        s = a["summary"]
        self.assertEqual(s["papers"], 3)
        self.assertEqual(s["unique_authors"], 3)
        self.assertEqual(s["cross_listed_pct"], 66.7)
        self.assertEqual(a["top_authors"][0], {"name": "Alice Fixture", "count": 2})
        # Months are gap-filled: Jan..Apr 2024.
        self.assertEqual([m["count"] for m in a["timeline"]], [1, 1, 0, 1])
        self.assertEqual(a["all_categories"][0]["name"], "cs.CV")
        self.assertIn({"name": "cs.CV + cs.LG", "count": 1}, a["category_pairs"])

    def test_empty(self):
        a = analytics.analyze([])
        self.assertEqual(a["summary"]["papers"], 0)
        self.assertEqual(a["timeline"], [])

    def test_filter_papers(self):
        papers = fixture_papers()
        self.assertEqual(len(analytics.filter_papers(papers, categories=["cs.LG"])), 2)
        self.assertEqual(len(analytics.filter_papers(papers, categories=["cs.LG"], primary_only=True)), 1)
        self.assertEqual(len(analytics.filter_papers(papers, text="satellite")), 1)
        self.assertEqual(len(analytics.filter_papers(papers, author="carol")), 1)
        self.assertEqual(len(analytics.filter_papers(papers, year_from=2025)), 0)

    def test_emerging_terms_detects_growth(self):
        papers = demo.generate(n=300)
        terms = analytics.emerging_terms(papers)
        self.assertTrue(terms)
        self.assertTrue(all(t["lift"] >= terms[-1]["lift"] for t in terms))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(demo_mode=True)))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_index_and_categories(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b"arXiv Research Analytics", r.read())
        with urllib.request.urlopen(self.base + "/api/categories") as r:
            data = json.loads(r.read())
        self.assertIn("cs.LG", data["groups"]["Computer Science"])
        self.assertTrue(data["demo"])

    def test_search_refine_export(self):
        res = self.post("/api/search", {"topic": "graph neural networks", "max_results": 100})
        self.assertGreater(res["fetched"], 0)
        self.assertEqual(res["source"], "demo")
        refined = self.post("/api/analyze", {"result_id": res["result_id"],
                                             "filters": {"categories": ["cs.LG"], "primary_only": True}})
        self.assertTrue(all(p["primary_category"] == "cs.LG" for p in refined["papers"]))
        with urllib.request.urlopen(f"{self.base}/api/export?result_id={res['result_id']}&format=csv") as r:
            self.assertTrue(r.read().decode().startswith("id,title,authors"))

    def test_compare(self):
        res = self.post("/api/compare", {"topics": ["diffusion models", "slam"], "max_results": 50})
        self.assertEqual([s["topic"] for s in res["series"]], ["diffusion models", "slam"])

    def test_bad_request(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/search", {})
        self.assertEqual(ctx.exception.code, 400)

    def test_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/../server.py")
        self.assertEqual(ctx.exception.code, 404)


class BuildSiteTest(unittest.TestCase):
    def test_build_writes_static_site(self):
        import tempfile
        from scripts.build_site import build
        with tempfile.TemporaryDirectory() as tmp:
            out = build(Path(tmp) / "site")
            html = (out / "index.html").read_text()
            for name in ("config.js", "data.js", "static-api.js", "app.js", "static-site.js", "style.css", ".nojekyll"):
                self.assertTrue((out / name).exists(), name)
            self.assertLess(html.index("static-api.js"), html.index('src="app.js"'))
            self.assertLess(html.index('src="app.js"'), html.index("static-site.js"))


class CsvTest(unittest.TestCase):
    def test_csv_joins_lists(self):
        out = to_csv(fixture_papers())
        self.assertIn("Alice Fixture; Bob Fixture", out)
        self.assertIn("cs.LG cs.CV", out)


if __name__ == "__main__":
    unittest.main()
