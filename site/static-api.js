"use strict";
// Browser-only stand-in for the Python server's JSON API (arxiv_analytics/server.py),
// used when the UI is hosted as a static site (GitHub Pages). Ports analytics.analyze /
// filter_papers and answers fetch("/api/...") itself. Searches go straight to the arXiv API
// from the browser; if that fails, it falls back to the embedded synthetic corpus.
(function () {
  const CORPUS = window.__CORPUS__;
  const GROUPS = window.__GROUPS__;
  const STOP = new Set(window.__STOPWORDS__);
  const NAMES = Object.assign({}, ...Object.values(GROUPS));
  const cache = new Map();
  const realFetch = window.fetch.bind(window);
  let nextId = 1;

  const tokenize = (text) => (text.toLowerCase().match(/[a-z][a-z0-9\-]{2,}/g) || [])
    .map((t) => t.replace(/^-+|-+$/g, "")).filter((t) => t && !STOP.has(t));

  function terms(p) {
    const tok = tokenize(`${p.title} ${p.summary}`);
    const bi = [];
    for (let i = 0; i + 1 < tok.length; i++) if (tok[i] !== tok[i + 1]) bi.push(`${tok[i]} ${tok[i + 1]}`);
    return [new Set(tok), new Set(bi)];
  }

  class Counter extends Map {
    add(k, n = 1) { this.set(k, (this.get(k) || 0) + n); }
    addAll(iter) { for (const k of iter) this.add(k); }
    top(n, key = "name") {
      return [...this.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
        .slice(0, n).map(([k, v]) => ({ [key]: k, count: v }));
    }
  }

  function fillMonths(c) {
    const months = [...c.keys()].sort();
    if (!months.length) return [];
    let [y, m] = months[0].split("-").map(Number);
    const [ey, em] = months[months.length - 1].split("-").map(Number);
    const out = [];
    while (y < ey || (y === ey && m <= em)) {
      const k = `${y}-${String(m).padStart(2, "0")}`;
      out.push({ period: k, count: c.get(k) || 0 });
      if (++m > 12) { y++; m = 1; }
    }
    return out;
  }

  function emerging(papers, n = 15, minCount = 3) {
    const dated = papers.filter((p) => p.published).sort((a, b) => a.published.localeCompare(b.published));
    if (dated.length < 10) return [];
    const mid = Math.floor(dated.length / 2);
    const old = dated.slice(0, mid), recent = dated.slice(mid);
    const oc = new Counter(), nc = new Counter();
    for (const [bucket, c] of [[old, oc], [recent, nc]]) {
      for (const p of bucket) { const [u, b] = terms(p); c.addAll(u); c.addAll(b); }
    }
    const scored = [];
    for (const [t, cnt] of nc) {
      if (cnt < minCount) continue;
      const lift = (cnt / recent.length + 0.01) / ((oc.get(t) || 0) / old.length + 0.01);
      scored.push({ term: t, lift: Math.round(lift * 100) / 100, recent: cnt, earlier: oc.get(t) || 0 });
    }
    return scored.sort((a, b) => b.lift - a.lift || b.recent - a.recent || (a.term < b.term ? 1 : -1)).slice(0, n);
  }

  function analyze(papers, topN = 20) {
    const months = new Counter(), years = new Counter(), primary = new Counter(), all = new Counter();
    const authors = new Counter(), kw = new Counter(), ph = new Counter(), pairs = new Counter();
    const sizes = [];
    let cross = 0;
    for (const p of papers) {
      const month = (p.published || "").slice(0, 7);
      if (month) { months.add(month); years.add(month.slice(0, 4)); }
      if (p.primary_category) primary.add(p.primary_category);
      const cats = [...new Set(p.categories || [])].sort();
      all.addAll(cats);
      if (cats.length > 1) cross++;
      for (let i = 0; i < cats.length; i++) for (let j = i + 1; j < cats.length; j++) pairs.add(`${cats[i]} + ${cats[j]}`);
      authors.addAll(new Set(p.authors || []));
      sizes.push((p.authors || []).length);
      const [u, b] = terms(p);
      kw.addAll(u); ph.addAll(b);
    }
    const total = papers.length;
    const dates = papers.filter((p) => p.published).map((p) => p.published.slice(0, 10)).sort();
    const label = (r) => ({ ...r, label: NAMES[r.name] || "" });
    return {
      summary: {
        papers: total,
        unique_authors: authors.size,
        avg_authors_per_paper: total ? Math.round((100 * sizes.reduce((a, b) => a + b, 0)) / total) / 100 : 0,
        solo_author_papers: sizes.filter((s) => s === 1).length,
        cross_listed_pct: total ? Math.round((1000 * cross) / total) / 10 : 0,
        categories: all.size,
        date_from: dates[0] || "",
        date_to: dates[dates.length - 1] || "",
      },
      timeline: fillMonths(months),
      by_year: [...years.keys()].sort().map((y) => ({ period: y, count: years.get(y) })),
      primary_categories: primary.top(topN).map(label),
      all_categories: all.top(topN).map(label),
      category_pairs: pairs.top(topN),
      top_authors: authors.top(topN),
      keywords: kw.top(topN * 2, "term"),
      phrases: ph.top(topN, "term"),
      emerging_terms: emerging(papers),
    };
  }

  function filterPapers(papers, f = {}) {
    const text = (f.text || "").toLowerCase().trim(), author = (f.author || "").toLowerCase().trim();
    const cats = new Set(f.categories || []);
    return papers.filter((p) => {
      const year = p.published ? Number(p.published.slice(0, 4)) : null;
      if (f.year_from && (year === null || year < Number(f.year_from))) return false;
      if (f.year_to && (year === null || year > Number(f.year_to))) return false;
      if (cats.size) {
        const pc = f.primary_only ? [p.primary_category] : p.categories || [];
        if (!pc.some((c) => cats.has(c))) return false;
      }
      if (text && !`${p.title} ${p.summary}`.toLowerCase().includes(text)) return false;
      if (author && !(p.authors || []).some((a) => a.toLowerCase().includes(author))) return false;
      return true;
    });
  }

  const asList = (v) => (typeof v === "string" ? v.split(",") : v || []).map((s) => s.trim()).filter(Boolean);

  function buildQuery(b) {
    const field = ["all", "ti", "abs", "au", "co", "jr"].includes(b.field) ? b.field : "all";
    const term = (f, t) => `${f}:${t.includes(" ") ? `"${t}"` : t}`;
    const group = (ts) => (ts.length > 1 ? `(${ts.join(" OR ")})` : ts[0] || "");
    const stamp = (d, end) => (d ? d.replace(/\D/g, "") + (end ? "2359" : "0000") : "");
    const parts = [
      group(asList(b.topic).map((t) => term(field, t))),
      group(asList(b.categories).map((c) => term("cat", c))),
      group(asList(b.authors).map((a) => term("au", a))),
    ];
    if (b.date_from || b.date_to) {
      parts.push(`submittedDate:[${stamp(b.date_from) || "199101010000"} TO ${stamp(b.date_to, true) || "209912312359"}]`);
    }
    const q = parts.filter(Boolean).join(" AND ");
    if (!q) throw new Error("Provide at least a topic, category, or author.");
    return q;
  }

  const ARXIV_URL = "https://export.arxiv.org/api/query";
  const ATOM = "http://www.w3.org/2005/Atom", AX = "http://arxiv.org/schemas/atom",
    OS = "http://a9.com/-/spec/opensearch/1.1/";
  const PAGE_SIZE = 200, MAX_RESULTS = 2000, REQUEST_DELAY_MS = 3000;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let lastRequest = 0;

  const textOf = (node, ns, tag) => {
    const el = node.getElementsByTagNameNS(ns, tag)[0];
    return el ? el.textContent.replace(/\s+/g, " ").trim() : "";
  };

  function parseFeed(xml) {
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error("arXiv returned an unreadable response");
    const total = Number(textOf(doc, OS, "totalResults") || 0);
    const papers = [];
    for (const e of doc.getElementsByTagNameNS(ATOM, "entry")) {
      const absUrl = textOf(e, ATOM, "id");
      if (!absUrl.includes("/abs/")) continue; // arXiv's error entry for malformed queries
      const pdf = [...e.getElementsByTagNameNS(ATOM, "link")].find((l) => l.getAttribute("title") === "pdf");
      const primary = e.getElementsByTagNameNS(AX, "primary_category")[0];
      papers.push({
        id: absUrl.split("/abs/").pop(),
        title: textOf(e, ATOM, "title"),
        summary: textOf(e, ATOM, "summary"),
        authors: [...e.getElementsByTagNameNS(ATOM, "author")].map((a) => textOf(a, ATOM, "name")),
        published: textOf(e, ATOM, "published"),
        updated: textOf(e, ATOM, "updated"),
        primary_category: primary ? primary.getAttribute("term") : "",
        categories: [...e.getElementsByTagNameNS(ATOM, "category")].map((c) => c.getAttribute("term")),
        pdf_url: pdf ? pdf.getAttribute("href") : "",
        abs_url: absUrl,
        comment: textOf(e, AX, "comment"),
        journal_ref: textOf(e, AX, "journal_ref"),
        doi: textOf(e, AX, "doi"),
        extra: {},
      });
    }
    return { papers, total };
  }

  async function fetchPage(query, start, size, b) {
    // arXiv asks clients to wait ~3 seconds between consecutive requests.
    const wait = lastRequest + REQUEST_DELAY_MS - Date.now();
    if (wait > 0) await sleep(wait);
    lastRequest = Date.now();
    const qs = new URLSearchParams({
      search_query: query, start, max_results: size,
      sortBy: ["relevance", "submittedDate", "lastUpdatedDate"].includes(b.sort_by) ? b.sort_by : "submittedDate",
      sortOrder: b.sort_order === "ascending" ? "ascending" : "descending",
    });
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000);
    try {
      const res = await realFetch(`${ARXIV_URL}?${qs}`, { signal: ctrl.signal });
      if (!res.ok) throw new Error(`arXiv responded with HTTP ${res.status}`);
      return parseFeed(await res.text());
    } finally {
      clearTimeout(timer);
    }
  }

  async function liveSearch(b) {
    const query = buildQuery(b);
    const limit = Math.max(1, Math.min(Number(b.max_results) || 200, MAX_RESULTS));
    const papers = [];
    let total = 0;
    for (let start = 0; start < limit; start += PAGE_SIZE) {
      const page = await fetchPage(query, start, Math.min(PAGE_SIZE, limit - start), b);
      total = page.total;
      papers.push(...page.papers);
      if (!page.papers.length || start + PAGE_SIZE >= total) break;
    }
    return { papers: papers.slice(0, limit), total, query, source: "arxiv" };
  }

  // Live first; after one failure, stay on sample data so each search isn't slowed by a timeout.
  let liveAvailable = true;
  async function search(b) {
    if (liveAvailable) {
      try {
        return await liveSearch(b);
      } catch (err) {
        if (err.message.startsWith("Provide at least")) throw err;
        liveAvailable = false;
        window.dispatchEvent(new CustomEvent("arxiv-fallback", { detail: err.message || String(err) }));
      }
    }
    return { ...demoSearch(b), source: "demo" };
  }

  function demoSearch(b) {
    const query = buildQuery(b);
    const topics = asList(b.topic).map((t) => t.toLowerCase());
    let matched = topics.length
      ? CORPUS.filter((p) => topics.some((t) => `${p.title} ${p.summary}`.toLowerCase().includes(t)))
      : CORPUS;
    matched = filterPapers(matched, {
      categories: asList(b.categories),
      year_from: b.date_from ? b.date_from.slice(0, 4) : "",
      year_to: b.date_to ? b.date_to.slice(0, 4) : "",
    });
    for (const a of asList(b.authors)) matched = filterPapers(matched, { author: a });
    return { papers: matched.slice(0, Number(b.max_results) || 200), total: matched.length, query };
  }

  const routes = {
    "/api/categories": () => ({ groups: GROUPS, demo: false }),
    "/api/search": async (b) => {
      const { papers, total, query, source } = await search(b);
      const id = String(nextId++);
      cache.set(id, papers);
      return { result_id: id, query, total_available: total, fetched: papers.length, source, papers, analytics: analyze(papers) };
    },
    "/api/analyze": (b) => {
      const base = cache.get(b.result_id);
      if (!base) throw new Error("Result set expired; run the search again.");
      const papers = filterPapers(base, b.filters || {});
      return { fetched: papers.length, papers, analytics: analyze(papers) };
    },
    "/api/compare": async (b) => {
      const topics = (b.topics || []).map((t) => t.trim()).filter(Boolean);
      if (topics.length < 2 || topics.length > 6) throw new Error("Compare needs 2–6 topics.");
      const series = [];
      let source = "arxiv";
      for (const topic of topics) {
        const r = await search({ ...b, topic });
        if (r.source === "demo") source = "demo";
        const s = analyze(r.papers);
        series.push({ topic, query: r.query, total_available: r.total, fetched: r.papers.length, by_year: s.by_year,
          timeline: s.timeline, top_categories: s.primary_categories.slice(0, 5), keywords: s.keywords.slice(0, 10) });
      }
      return { source, series };
    },
  };

  window.__exportRows__ = (resultId, filters) => filterPapers(cache.get(resultId) || [], filters);

  window.fetch = async (path, opts) => {
    const route = typeof path === "string" && routes[path.split("?")[0]];
    if (!route) return realFetch(path, opts);
    const json = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
    try {
      return json(200, await route(opts && opts.body ? JSON.parse(opts.body) : {}));
    } catch (err) {
      return json(400, { error: err.message });
    }
  };
})();
