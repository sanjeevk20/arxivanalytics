"""Searching arXiv by a range of submission years."""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from arxiv_analytics import client, demo
from arxiv_analytics.server import App, make_handler, params_from


def query(**kw):
    return client.build_query(client.SearchParams(topic="electric vehicle", **kw))


class YearRangeQueryTest(unittest.TestCase):
    def test_from_and_to_year(self):
        self.assertEqual(query(year_from="2022", year_to="2024"),
                         'all:"electric vehicle" AND submittedDate:[202201010000 TO 202412312359]')

    def test_single_year(self):
        self.assertEqual(query(year_from="2023", year_to="2023"),
                         'all:"electric vehicle" AND submittedDate:[202301010000 TO 202312312359]')

    def test_open_ended(self):
        self.assertEqual(query(year_from="2020"),
                         'all:"electric vehicle" AND submittedDate:[202001010000 TO 209912312359]')
        self.assertEqual(query(year_to="2015"),
                         'all:"electric vehicle" AND submittedDate:[199101010000 TO 201512312359]')

    def test_exact_dates_override_years(self):
        self.assertEqual(
            query(year_from="2010", year_to="2012", date_from="2024-03-01", date_to="2024-06-30"),
            'all:"electric vehicle" AND submittedDate:[202403010000 TO 202406302359]')
        # Mixing is allowed: an exact start with a year end.
        self.assertEqual(query(date_from="2024-03-01", year_to="2025"),
                         'all:"electric vehicle" AND submittedDate:[202403010000 TO 202512312359]')

    def test_reversed_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ends before it starts"):
            query(year_from="2025", year_to="2020")
        with self.assertRaisesRegex(ValueError, "ends before it starts"):
            query(date_from="2024-06-01", date_to="2024-01-01")

    def test_invalid_years_are_rejected(self):
        for bad in ("1990", "2101", "20x4", "-1"):
            with self.assertRaisesRegex(ValueError, "between 1991 and 2100"):
                query(year_from=bad)

    def test_no_years_means_no_date_filter(self):
        self.assertEqual(query(year_from="", year_to=""), 'all:"electric vehicle"')

    def test_years_alone_search_everything_in_that_window(self):
        self.assertEqual(client.build_query(client.SearchParams(year_from="2020", year_to="2020")),
                         "submittedDate:[202001010000 TO 202012312359]")

    def test_years_reach_the_request_url(self):
        audit = []
        client.search(client.SearchParams(topic="ev", year_from="2021", year_to="2022"),
                      fetch=lambda *a: '<feed xmlns="http://www.w3.org/2005/Atom"/>',
                      delay=0, audit=audit)
        self.assertIn("submittedDate%3A%5B202101010000+TO+202212312359%5D", audit[0]["url"])


class YearRangeDemoAndApiTest(unittest.TestCase):
    def test_demo_search_respects_years(self):
        papers, total, _ = demo.search(client.SearchParams(
            topic="graph neural networks", year_from="2023", year_to="2024", max_results=500))
        self.assertGreater(total, 0)
        self.assertTrue(all(p["published"][:4] in ("2023", "2024") for p in papers))

    def test_params_from_reads_years(self):
        p = params_from({"topic": "x", "year_from": 2021, "year_to": None})
        self.assertEqual((p.year_from, p.year_to), ("2021", ""))

    def test_api_search_and_bad_range(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(demo_mode=True)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(body):
            req = urllib.request.Request(base + "/api/search", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())

        res = post({"topic": "satellite imagery", "year_from": "2025", "year_to": "2026"})
        self.assertTrue(res["query"].endswith("submittedDate:[202501010000 TO 202612312359]"))
        self.assertTrue(all(p["published"][:4] in ("2025", "2026") for p in res["papers"]))

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            post({"topic": "satellite imagery", "year_from": "2026", "year_to": "2020"})
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("ends before it starts", json.loads(ctx.exception.read())["error"])


if __name__ == "__main__":
    unittest.main()
