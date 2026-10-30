"""Descriptive analytics over a set of arXiv papers."""

import re
from collections import Counter
from itertools import combinations

from .categories import CATEGORY_NAMES

STOPWORDS = set(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can could did do does doing down during each
    few for from further had has have having he her here hers herself him himself his how
    i if in into is it its itself just me more most my myself no nor not now of off on once
    only or other our ours ourselves out over own same she should so some such than that the
    their theirs them themselves then there these they this those through to too under until
    up very was we were what when where which while who whom why will with would you your
    yours yourself yourselves via within without upon across among however thus therefore
    may might must shall one two three new using use used based show shows shown paper
    propose proposed present presents approach approaches method methods result results
    work study studies problem problems also well first second many much several often
    achieve achieves provide provides existing recent recently different various large
    furthermore moreover address demonstrate demonstrates significantly significant
    performance however novel framework task tasks data model models et al etc e g i e
    accuracy baseline baselines dataset datasets improve improves improving improved
    evaluate evaluated evaluation combine combines combining outperform outperforms
    """.split()
)

TOKEN_RE = re.compile(r"[a-z][a-z0-9\-]{2,}")


def tokenize(text):
    return [t.strip("-") for t in TOKEN_RE.findall(text.lower()) if t.strip("-") not in STOPWORDS]


def _month(ts):
    return ts[:7] if len(ts) >= 7 else ""


def _terms(paper):
    tokens = tokenize(f"{paper['title']} {paper['summary']}")
    bigrams = [f"{a} {b}" for a, b in zip(tokens, tokens[1:]) if a != b]
    # Count each term once per paper so long abstracts don't dominate.
    return set(tokens), set(bigrams)


def _fill_months(counter):
    if not counter:
        return []
    months = sorted(counter)
    y, m = map(int, months[0].split("-"))
    end_y, end_m = map(int, months[-1].split("-"))
    series = []
    while (y, m) <= (end_y, end_m):
        key = f"{y:04d}-{m:02d}"
        series.append({"period": key, "count": counter.get(key, 0)})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return series


def _ranked(counter, n, key="name"):
    # Ties break alphabetically so rankings don't depend on set iteration order
    # (which changes between runs) and match the browser port in site/static-api.js.
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{key: k, "count": v} for k, v in ranked[:n]]


def emerging_terms(papers, n=15, min_count=3):
    """Terms whose document share grew most between the older and newer half of the set."""
    dated = sorted((p for p in papers if p.get("published")), key=lambda p: p["published"])
    if len(dated) < 10:
        return []
    mid = len(dated) // 2
    old, new = dated[:mid], dated[mid:]
    old_c, new_c = Counter(), Counter()
    for bucket, counter in ((old, old_c), (new, new_c)):
        for p in bucket:
            uni, bi = _terms(p)
            counter.update(uni | bi)
    scored = []
    for term, cnt in new_c.items():
        if cnt < min_count:
            continue
        new_share = cnt / len(new)
        old_share = old_c.get(term, 0) / len(old)
        # Additive smoothing keeps brand-new terms from scoring infinitely.
        lift = (new_share + 0.01) / (old_share + 0.01)
        scored.append((lift, cnt, term, old_c.get(term, 0)))
    scored.sort(reverse=True)
    return [
        {"term": t, "lift": round(l, 2), "recent": c, "earlier": o}
        for l, c, t, o in scored[:n]
    ]


def analyze(papers, top_n=20):
    """Compute summary stats, trends, and rankings for a list of paper dicts."""
    months, primary, all_cats, authors = Counter(), Counter(), Counter(), Counter()
    years, keywords, phrases, cat_pairs = Counter(), Counter(), Counter(), Counter()
    team_sizes, cross_listed = [], 0

    for p in papers:
        month = _month(p.get("published", ""))
        if month:
            months[month] += 1
            years[month[:4]] += 1
        if p.get("primary_category"):
            primary[p["primary_category"]] += 1
        cats = sorted(set(p.get("categories") or []))
        all_cats.update(cats)
        if len(cats) > 1:
            cross_listed += 1
        cat_pairs.update(f"{a} + {b}" for a, b in combinations(cats, 2))
        authors.update(set(p.get("authors") or []))
        team_sizes.append(len(p.get("authors") or []))
        uni, bi = _terms(p)
        keywords.update(uni)
        phrases.update(bi)

    total = len(papers)
    dates = sorted(p["published"][:10] for p in papers if p.get("published"))
    return {
        "summary": {
            "papers": total,
            "unique_authors": len(authors),
            "avg_authors_per_paper": round(sum(team_sizes) / total, 2) if total else 0,
            "solo_author_papers": sum(1 for s in team_sizes if s == 1),
            "cross_listed_pct": round(100 * cross_listed / total, 1) if total else 0,
            "categories": len(all_cats),
            "date_from": dates[0] if dates else "",
            "date_to": dates[-1] if dates else "",
        },
        "timeline": _fill_months(months),
        "by_year": [{"period": y, "count": years[y]} for y in sorted(years)],
        "primary_categories": [
            {**row, "label": CATEGORY_NAMES.get(row["name"], "")}
            for row in _ranked(primary, top_n)
        ],
        "all_categories": [
            {**row, "label": CATEGORY_NAMES.get(row["name"], "")}
            for row in _ranked(all_cats, top_n)
        ],
        "category_pairs": _ranked(cat_pairs, top_n),
        "top_authors": _ranked(authors, top_n),
        "keywords": _ranked(keywords, top_n * 2, key="term"),
        "phrases": _ranked(phrases, top_n, key="term"),
        "emerging_terms": emerging_terms(papers),
    }


def filter_papers(papers, text="", categories=None, primary_only=False,
                  year_from=None, year_to=None, author=""):
    """Client-side refinement over an already-fetched result set."""
    text, author = (text or "").lower().strip(), (author or "").lower().strip()
    categories = set(categories or [])
    out = []
    for p in papers:
        year = int(p["published"][:4]) if p.get("published") else None
        if year_from and (year is None or year < int(year_from)):
            continue
        if year_to and (year is None or year > int(year_to)):
            continue
        if categories:
            cats = {p.get("primary_category")} if primary_only else set(p.get("categories") or [])
            if not cats & categories:
                continue
        if text and text not in f"{p['title']} {p['summary']}".lower():
            continue
        if author and not any(author in a.lower() for a in p.get("authors") or []):
            continue
        out.append(p)
    return out
