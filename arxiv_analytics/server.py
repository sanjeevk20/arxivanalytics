"""Local web server: serves the UI and a small JSON API over the arXiv client."""

import argparse
import csv
import io
import json
import mimetypes
import threading
import urllib.error
import uuid
import webbrowser
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import client, demo
from .analytics import analyze, filter_papers
from .categories import CATEGORY_GROUPS

STATIC_DIR = Path(__file__).parent / "static"
MAX_CACHED_RESULTS = 20
MAX_COMPARE_TOPICS = 6


class ResultCache:
    """Keeps recent result sets so the UI can refine/export without re-querying arXiv."""

    def __init__(self, size=MAX_CACHED_RESULTS):
        self.size, self._data, self._lock = size, OrderedDict(), threading.Lock()

    def put(self, papers):
        key = uuid.uuid4().hex[:12]
        with self._lock:
            self._data[key] = papers
            while len(self._data) > self.size:
                self._data.popitem(last=False)
        return key

    def get(self, key):
        with self._lock:
            return self._data.get(key)


def params_from(body):
    def as_list(value):
        if isinstance(value, str):
            value = value.split(",")
        return [v.strip() for v in value or [] if v and v.strip()]

    return client.SearchParams(
        topic=str(body.get("topic", "")),
        field=str(body.get("field", "all")),
        categories=as_list(body.get("categories")),
        authors=as_list(body.get("authors")),
        date_from=str(body.get("date_from", "")),
        date_to=str(body.get("date_to", "")),
        max_results=int(body.get("max_results") or 200),
        sort_by=str(body.get("sort_by", "submittedDate")),
        sort_order=str(body.get("sort_order", "descending")),
    )


def refine(papers, filters):
    return filter_papers(
        papers,
        text=filters.get("text", ""),
        categories=filters.get("categories") or [],
        primary_only=bool(filters.get("primary_only")),
        year_from=filters.get("year_from") or None,
        year_to=filters.get("year_to") or None,
        author=filters.get("author", ""),
    )


CSV_FIELDS = ["id", "title", "authors", "published", "primary_category", "categories",
              "abs_url", "pdf_url", "doi", "journal_ref", "summary"]


def to_csv(papers):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for p in papers:
        writer.writerow({**p, "authors": "; ".join(p["authors"]),
                         "categories": " ".join(p["categories"])})
    return buf.getvalue()


class App:
    def __init__(self, demo_mode=False, search_fn=None):
        self.demo_mode = demo_mode
        self.cache = ResultCache()
        self.search_fn = search_fn or (demo.search if demo_mode else self._live_search)

    @staticmethod
    def _live_search(params):
        papers, total, query = client.search(params)
        return [p.to_dict() for p in papers], total, query

    def search(self, body):
        papers, total, query = self.search_fn(params_from(body))
        return {
            "result_id": self.cache.put(papers),
            "query": query,
            "total_available": total,
            "fetched": len(papers),
            "source": "demo" if self.demo_mode else "arxiv",
            "papers": papers,
            "analytics": analyze(papers),
        }

    def _cached(self, result_id):
        papers = self.cache.get(result_id)
        if papers is None:
            raise LookupError("Result set expired; run the search again.")
        return papers

    def analyze(self, body):
        papers = refine(self._cached(body.get("result_id", "")), body.get("filters") or {})
        return {"fetched": len(papers), "papers": papers, "analytics": analyze(papers)}

    def compare(self, body):
        topics = [t.strip() for t in body.get("topics", []) if t and t.strip()]
        if not 2 <= len(topics) <= MAX_COMPARE_TOPICS:
            raise ValueError(f"Compare needs 2–{MAX_COMPARE_TOPICS} topics.")
        series = []
        for topic in topics:
            papers, total, query = self.search_fn(params_from({**body, "topic": topic}))
            stats = analyze(papers)
            series.append({
                "topic": topic,
                "query": query,
                "total_available": total,
                "fetched": len(papers),
                "by_year": stats["by_year"],
                "timeline": stats["timeline"],
                "top_categories": stats["primary_categories"][:5],
                "keywords": stats["keywords"][:10],
            })
        return {"source": "demo" if self.demo_mode else "arxiv", "series": series}

    def export(self, query):
        papers = refine(self._cached(query.get("result_id", "")),
                        json.loads(query.get("filters") or "{}"))
        if query.get("format") == "json":
            return "application/json", json.dumps(papers, indent=2), "arxiv_results.json"
        return "text/csv", to_csv(papers), "arxiv_results.csv"


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ArxivAnalytics/0.1"

        def log_message(self, fmt, *args):  # quieter default logging
            print(f"[{self.log_date_time_string()}] {fmt % args}")

        def _send(self, status, body, content_type="application/json", headers=None):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status, payload):
            self._send(status, json.dumps(payload))

        def _guard(self, fn):
            try:
                fn()
            except (ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
            except LookupError as exc:
                self._json(410, {"error": str(exc)})
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._json(502, {"error": f"Could not reach arXiv: {exc}. "
                                          "Try again, or start with --demo for offline data."})

        def do_GET(self):
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/categories":
                return self._json(200, {"groups": CATEGORY_GROUPS, "demo": app.demo_mode})
            if url.path == "/api/export":
                def run():
                    ctype, body, name = app.export(query)
                    self._send(200, body, f"{ctype}; charset=utf-8",
                               {"Content-Disposition": f'attachment; filename="{name}"'})
                return self._guard(run)
            self._static(url.path)

        def do_POST(self):
            routes = {"/api/search": app.search, "/api/analyze": app.analyze,
                      "/api/compare": app.compare}
            route = routes.get(urlparse(self.path).path)
            if not route:
                return self._json(404, {"error": "Not found"})

            def run():
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(200, route(body))
            self._guard(run)

        def _static(self, path):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() not in target.parents or not target.is_file():
                return self._json(404, {"error": "Not found"})
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description="arXiv research analytics dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--demo", action="store_true",
                        help="use bundled synthetic data instead of the live arXiv API")
    parser.add_argument("--open", action="store_true", help="open the UI in a browser")
    args = parser.parse_args(argv)

    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(App(demo_mode=args.demo)))
    url = f"http://{args.host}:{args.port}/"
    print(f"arXiv Analytics running at {url}  ({'DEMO data' if args.demo else 'live arXiv API'})")
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
