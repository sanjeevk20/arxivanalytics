# arXiv Research Analytics

A local web tool for searching, filtering and analysing [arXiv](https://arxiv.org) research by
topic and category. It needs only the Python standard library: no packages to install and no build step.

## Quick start

```bash
python3 -m arxiv_analytics --open          # live arXiv API at http://127.0.0.1:8765
python3 -m arxiv_analytics --demo --open   # offline, synthetic sample data
```

Options: `--host`, `--port` (default 8765), `--demo`, `--open`, and `--debug` to print every arXiv
request and response in the terminal.

The **Audit log** tab lists every request a search or comparison sent to arXiv: the query, the full
request URL, the route (server, relay, direct or sample data), HTTP status, timing and result counts,
failures included. Each entry is also written to the browser console with `console.debug`.
You can also run `pip install .` and then `arxiv-analytics`.

## Features

**Search panel (sent to the arXiv API)**
- Topic / keywords. Separate alternatives with commas to OR them; multi-word phrases match exactly.
- Search field: all fields, title, abstract, author, comments or journal ref.
- Category picker: about 50 arXiv categories grouped by archive (CS, Stats, EESS, Math, Physics,
  q-bio, q-fin, econ). You can search the list and select a whole group at once.
- Year range (From/To year, or This year / Last 3, 5, 10 years). An exact date range under
  **Exact dates** overrides the years. Both become arXiv's `submittedDate` filter.
- Author filter, max papers (up to 2,000, fetched in pages) and sort order.
- One-click topic presets.

**Refine bar (filters the fetched results without calling arXiv again)**
- Free-text, author and year-range filters.
- Category chips, with a "primary category only" toggle.
- Click any category bar, author, key phrase, keyword or emerging term to drill into it.

**Overview analytics**
- KPIs: papers, unique authors, average team size, share of cross-listed papers, date span.
- Publications over time, by month (or by year for spans over 4 years).
- Primary category and all-category (including cross-lists) distributions.
- Top authors, key phrases (bigrams) and a keyword cloud.
- **Emerging terms**: terms whose share of papers grew most between the earlier and the more
  recent half of the result set.
- Category co-occurrence: which fields are cross-listed together.

**Papers tab**: sortable list with abstracts, links to the abstract and PDF, and **CSV / JSON export**
of the filtered set.

**Compare topics**: run 2–6 topics with the same category and date filters and see papers per year as
overlaid trend lines, plus a summary table (total matches on arXiv, top categories, top keywords).

## Architecture

Diagrams of the runtime and deploy pipeline: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
arxiv_analytics/
  client.py      arXiv Atom API: query builder, paging (3 s between requests), feed parser
  analytics.py   stats, trends, rankings, emerging terms, result filtering
  categories.py  arXiv taxonomy subset
  server.py      stdlib HTTP server + JSON API, caches recent result sets
  demo.py        synthetic corpus for --demo (clearly labelled in the UI)
  static/        index.html, app.js, style.css (no external libraries; charts are hand-drawn SVG)
```

JSON API: `GET /api/categories`, `POST /api/search`, `POST /api/analyze` (refine a cached result),
`POST /api/compare`, `GET /api/export?result_id=…&format=csv|json&filters=…`.

## Hosted version (GitHub Pages)

`scripts/build_site.py` builds a static copy of the UI into `build/site`. A static host can't run the
Python server, so the site includes `site/static-api.js`, which handles the UI's `/api/*` calls in the
browser:

- Searches go to arXiv through the relay below (or directly, which browsers block) and are paged with
  the same 3-second spacing.
- Results are always live. If arXiv can't be reached, the search fails with an error that says why.
  Built-in sample papers appear only if you press **Use sample papers instead**, and they're labelled
  as such until you switch back to live.
- Analytics, filters, Compare and CSV/JSON export all run in the browser.

`.github/workflows/pages.yml` runs the tests, builds the site and publishes it to the `gh-pages` branch
on every push to `main`. To turn it on, open **Settings → Pages**, choose **Deploy from a branch**,
and select `gh-pages` / `(root)`. The site is then served at
`https://<owner>.github.io/<repo>/`.

To preview locally: `python3 scripts/build_site.py && python3 -m http.server -d build/site`.

### arXiv relay (needed for live data on the hosted site)

arXiv's API sends no CORS headers, so browsers block it when it's called from another website. Without
the relay, the hosted site can't search arXiv. `relay/worker.js` is a small Cloudflare Worker that forwards
arXiv API queries and adds those headers. It only calls `export.arxiv.org/api/query`, caps a request at
500 results, and caches answers for an hour.

1. Sign in at https://dash.cloudflare.com (the free plan is enough).
2. Go to **Workers & Pages → Create → Create Worker**, name it `arxiv-relay`, and click **Deploy**.
3. Click **Edit code**, replace everything with the contents of `relay/worker.js`, and click **Deploy**.
4. Copy the Worker's URL (`https://arxiv-relay.<your-subdomain>.workers.dev`) into `site/config.js`
   and push to `main`.

Browsers are only allowed through for `https://sanjeevk20.github.io` and localhost:8000. To change
that, set an `ALLOWED_ORIGINS` variable (comma-separated) in the Worker's settings.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## Notes

- arXiv's API terms ask clients to wait about 3 seconds between requests. Large fetches (e.g.
  2,000 papers = 10 pages) and topic comparisons therefore take a while.
- `totalResults` is arXiv's count of all matches. The analytics cover only the papers fetched, up to
  "Max papers".
