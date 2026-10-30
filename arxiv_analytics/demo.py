"""Synthetic papers for offline demo mode and UI development.

These records are generated, not real arXiv papers; the UI labels them as such.
"""

import random

from .analytics import filter_papers
from .client import audit_entry, build_query

_THEMES = {
    "cs.LG": ["graph neural networks", "self-supervised learning", "federated learning",
              "diffusion models", "reinforcement learning", "contrastive learning"],
    "cs.CV": ["semantic segmentation", "object detection", "satellite imagery",
              "vision transformers", "3d reconstruction", "point clouds"],
    "cs.CL": ["large language models", "retrieval augmented generation",
              "instruction tuning", "machine translation", "named entity recognition"],
    "cs.AI": ["knowledge graphs", "planning", "agentic workflows", "causal inference"],
    "cs.RO": ["autonomous driving", "slam", "motion planning"],
    "physics.geo-ph": ["remote sensing", "geospatial data", "terrain modeling"],
    "stat.ML": ["uncertainty quantification", "bayesian optimization", "gaussian processes"],
    "cs.DB": ["spatial indexing", "data quality", "map matching"],
}
_ADJ = ["Scalable", "Robust", "Efficient", "Interpretable", "Self-Correcting", "Lightweight",
        "Hierarchical", "Adaptive", "Multi-Scale", "Probabilistic"]
_NOUN = ["Framework", "Benchmark", "Approach", "Pipeline", "Model", "Analysis", "Survey"]
_FOR = ["road network extraction", "map validation", "anomaly detection", "change detection",
        "data repair", "trajectory prediction", "semantic search", "question answering",
        "building footprint extraction", "label noise correction"]
_FIRST = ["A.", "B.", "C.", "D.", "E.", "F.", "G.", "H.", "J.", "K.", "L.", "M.", "N.", "P.",
          "R.", "S.", "T.", "V.", "W.", "Y."]
_LAST = ["Demo", "Sample", "Example", "Placeholder", "Fixture", "Synth", "Mock", "Stub",
         "Testcase", "Prototype", "Draft", "Specimen"]


def generate(n=600, seed=7):
    rng = random.Random(seed)
    authors_pool = [f"{f} {l}{i}" for i in range(1, 6) for f in _FIRST for l in _LAST][:400]
    papers = []
    for i in range(n):
        primary = rng.choice(list(_THEMES))
        others = rng.sample([c for c in _THEMES if c != primary], k=rng.choice([0, 0, 1, 1, 2]))
        theme = rng.choice(_THEMES[primary])
        # Bias later dates toward newer themes to give trend charts some shape.
        year = rng.choices([2021, 2022, 2023, 2024, 2025, 2026], weights=[1, 2, 3, 4, 5, 4])[0]
        month = rng.randint(1, 10 if year == 2026 else 12)
        day = rng.randint(1, 28)
        task = rng.choice(_FOR)
        title = f"{rng.choice(_ADJ)} {theme.title()} {rng.choice(_NOUN)} for {task.title()}"
        extra_theme = rng.choice(_THEMES[rng.choice(others)]) if others else theme
        summary = (
            f"[Synthetic demo record] We study {theme} for {task}. Our method combines "
            f"{theme} with {extra_theme} and is evaluated on {rng.randint(2, 6)} datasets, "
            f"improving accuracy by {rng.randint(2, 18)}% over baselines in {task}."
        )
        pid = f"demo.{year % 100:02d}{month:02d}.{i:05d}"
        stamp = f"{year}-{month:02d}-{day:02d}T12:00:00Z"
        papers.append({
            "id": pid,
            "title": title,
            "summary": summary,
            "authors": rng.sample(authors_pool, k=rng.choice([1, 2, 3, 3, 4, 5, 6, 8])),
            "published": stamp,
            "updated": stamp,
            "primary_category": primary,
            "categories": [primary] + others,
            "pdf_url": "",
            "abs_url": "",
            "comment": "Synthetic demo record",
            "journal_ref": "",
            "doi": "",
            "extra": {},
        })
    papers.sort(key=lambda p: p["published"], reverse=True)
    return papers


_CORPUS = None


def search(params, audit=None):
    """Mimic client.search() against the synthetic corpus."""
    global _CORPUS
    if _CORPUS is None:
        _CORPUS = generate()
    query = build_query(params)  # validates input the same way as live mode
    year_from = params.date_from[:4] if params.date_from else None
    year_to = params.date_to[:4] if params.date_to else None
    matched = _CORPUS
    topics = [t.strip().lower() for t in params.topic.split(",") if t.strip()]
    if topics:
        matched = [p for p in matched
                   if any(t in f"{p['title']} {p['summary']}".lower() for t in topics)]
    matched = filter_papers(matched, categories=params.categories,
                            year_from=year_from, year_to=year_to)
    for author in params.authors:
        matched = filter_papers(matched, author=author)
    if params.sort_order == "ascending":
        matched = list(reversed(matched))
    papers = matched[: params.max_results]
    if audit is not None:
        audit.append(audit_entry("demo", query, status="demo", returned=len(papers),
                                 total=len(matched), duration_ms=0,
                                 note="Synthetic demo corpus; no request sent to arXiv."))
    return papers, len(matched), query
