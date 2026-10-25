"""Thin client for the public arXiv Atom API (https://info.arxiv.org/help/api/)."""

import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field

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
    start = _date_stamp(params.date_from, end_of_day=False)
    end = _date_stamp(params.date_to, end_of_day=True)
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


def _fetch_page(query, start, size, sort_by, sort_order, timeout):
    qs = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": start,
            "max_results": size,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
    )
    req = urllib.request.Request(
        f"{API_URL}?{qs}", headers={"User-Agent": "arxiv-analytics/0.1"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def search(params: SearchParams, fetch=_fetch_page, timeout=30, delay=REQUEST_DELAY_S):
    """Run a search, paging through results. Returns (papers, total, query)."""
    query = build_query(params)
    limit = max(1, min(int(params.max_results or 0), MAX_RESULTS_CAP))
    sort_by = params.sort_by if params.sort_by in SORT_BY else "submittedDate"
    sort_order = "ascending" if params.sort_order == "ascending" else "descending"

    papers, total, start = [], 0, 0
    while start < limit:
        if start:
            time.sleep(delay)
        size = min(PAGE_SIZE, limit - start)
        page, total = parse_feed(fetch(query, start, size, sort_by, sort_order, timeout))
        papers.extend(page)
        start += size
        if not page or start >= total:
            break
    return papers[:limit], total, query
