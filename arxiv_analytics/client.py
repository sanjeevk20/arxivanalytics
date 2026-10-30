"""Thin client for the public arXiv Atom API (https://info.arxiv.org/help/api/)."""

import logging
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from datetime import datetime, timezone

API_URL = "https://export.arxiv.org/api/query"
PAGE_SIZE = 200
MAX_RESULTS_CAP = 2000
# arXiv asks clients to wait ~3 seconds between consecutive requests.
REQUEST_DELAY_S = 3.0

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

SEARCH_FIELDS = {"all", "ti", "abs", "au", "co", "jr"}
SORT_BY = {"relevance", "submittedDate", "lastUpdatedDate"}
FIRST_YEAR, LAST_YEAR = 1991, 2100  # arXiv opened in August 1991

log = logging.getLogger(__name__)


@dataclass
class Paper:
    id: str
    title: str
    summary: str
    authors: list
    published: str
    updated: str
    primary_category: str
    categories: list
    pdf_url: str = ""
    abs_url: str = ""
    comment: str = ""
    journal_ref: str = ""
    doi: str = ""
    extra: dict = dc_field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class SearchParams:
    topic: str = ""
    field: str = "all"
    categories: list = dc_field(default_factory=list)
    authors: list = dc_field(default_factory=list)
    date_from: str = ""  # YYYY-MM-DD
    date_to: str = ""  # YYYY-MM-DD
    year_from: str = ""  # YYYY; used when date_from is empty
    year_to: str = ""  # YYYY; used when date_to is empty
    max_results: int = 200
    sort_by: str = "submittedDate"
    sort_order: str = "descending"


def _term(field_name, text):
    text = text.strip()
    if not text:
        return ""
    # Quote multi-word phrases so arXiv treats them as a phrase.
    if " " in text and not (text.startswith('"') and text.endswith('"')):
        text = f'"{text}"'
    return f"{field_name}:{text}"


def _or_group(terms):
    terms = [t for t in terms if t]
    if not terms:
        return ""
    return terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"


def _date_stamp(value, end_of_day):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 8:
        return ""
    return digits + ("2359" if end_of_day else "0000")


def _year_stamp(value, end_of_year):
    value = str(value or "").strip()
    if not value:
        return ""
    if not value.isdigit() or not FIRST_YEAR <= int(value) <= LAST_YEAR:
        raise ValueError(f"Year must be between {FIRST_YEAR} and {LAST_YEAR}, got {value!r}.")
    return value + ("12312359" if end_of_year else "01010000")


def submitted_range(params: SearchParams):
    """(start, end) stamps for arXiv's submittedDate filter; exact dates win over years."""
    start = _date_stamp(params.date_from, end_of_day=False) or _year_stamp(params.year_from, False)
    end = _date_stamp(params.date_to, end_of_day=True) or _year_stamp(params.year_to, True)
    if start and end and start > end:
        raise ValueError("The date range ends before it starts.")
    return start, end


def build_query(params: SearchParams) -> str:
    """Translate SearchParams into an arXiv `search_query` expression."""
    field_name = params.field if params.field in SEARCH_FIELDS else "all"
    # Topic may be a comma-separated list of alternatives ("GNN, graph neural network").
    topics = [t for t in (params.topic or "").split(",") if t.strip()]
    parts = [
        _or_group([_term(field_name, t) for t in topics]),
        _or_group([_term("cat", c) for c in params.categories]),
        _or_group([_term("au", a) for a in params.authors]),
    ]
    start, end = submitted_range(params)
    if start or end:
        parts.append(f"submittedDate:[{start or '199101010000'} TO {end or '209912312359'}]")
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError("Provide at least a topic, category, or author.")
    return " AND ".join(parts)


def _text(node, path):
    found = node.find(path, NS)
    return re.sub(r"\s+", " ", found.text).strip() if found is not None and found.text else ""


def parse_feed(xml_text):
    """Parse an arXiv Atom feed into (papers, total_results)."""
    root = ET.fromstring(xml_text)
    total = int(_text(root, "opensearch:totalResults") or 0)
    papers = []
    for entry in root.findall("atom:entry", NS):
        abs_url = _text(entry, "atom:id")
        if not abs_url or "/abs/" not in abs_url:
            continue  # arXiv returns a single error entry for malformed queries
        pdf_url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
        primary = entry.find("arxiv:primary_category", NS)
        papers.append(
            Paper(
                id=abs_url.rsplit("/abs/", 1)[-1],
                title=_text(entry, "atom:title"),
                summary=_text(entry, "atom:summary"),
                authors=[_text(a, "atom:name") for a in entry.findall("atom:author", NS)],
                published=_text(entry, "atom:published"),
                updated=_text(entry, "atom:updated"),
                primary_category=primary.get("term", "") if primary is not None else "",
                categories=[c.get("term", "") for c in entry.findall("atom:category", NS)],
                pdf_url=pdf_url,
                abs_url=abs_url,
                comment=_text(entry, "arxiv:comment"),
                journal_ref=_text(entry, "arxiv:journal_ref"),
                doi=_text(entry, "arxiv:doi"),
            )
        )
    return papers, total


def request_url(query, start, size, sort_by, sort_order):
    qs = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": start,
            "max_results": size,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
    )
    return f"{API_URL}?{qs}"


def _fetch_page(query, start, size, sort_by, sort_order, timeout):
    req = urllib.request.Request(
        request_url(query, start, size, sort_by, sort_order),
        headers={"User-Agent": "arxiv-analytics/0.1"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def audit_entry(source, query, **fields):
    """One row of the UI's audit log (see renderAudit in static/app.js)."""
    return {"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": source, "query": query, **fields}


def search(params: SearchParams, fetch=_fetch_page, timeout=30, delay=REQUEST_DELAY_S, audit=None):
    """Run a search, paging through results. Returns (papers, total, query).

    If `audit` is a list, one entry per arXiv request is appended to it, failures included.
    """
    query = build_query(params)
    limit = max(1, min(int(params.max_results or 0), MAX_RESULTS_CAP))
    sort_by = params.sort_by if params.sort_by in SORT_BY else "submittedDate"
    sort_order = "ascending" if params.sort_order == "ascending" else "descending"

    papers, total, start = [], 0, 0
    while start < limit:
        if start:
            time.sleep(delay)
        size = min(PAGE_SIZE, limit - start)
        url = request_url(query, start, size, sort_by, sort_order)
        entry = audit_entry("arxiv", query, url=url, start=start, max_results=size)
        log.debug("arXiv request: %s", url)
        began = time.monotonic()
        try:
            page, total = parse_feed(fetch(query, start, size, sort_by, sort_order, timeout))
        except Exception as exc:
            entry.update(status="error", http_status=getattr(exc, "code", None), error=str(exc),
                         duration_ms=round((time.monotonic() - began) * 1000))
            log.debug("arXiv request failed after %d ms: %s", entry["duration_ms"], exc)
            if audit is not None:
                audit.append(entry)
            raise
        entry.update(status="ok", http_status=200, returned=len(page), total=total,
                     duration_ms=round((time.monotonic() - began) * 1000))
        log.debug("arXiv response: %d entries of %d total in %d ms",
                  len(page), total, entry["duration_ms"])
        if audit is not None:
            audit.append(entry)
        papers.extend(page)
        start += size
        if not page or start >= total:
            break
    return papers[:limit], total, query
