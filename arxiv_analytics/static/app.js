"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString();

const PRESETS = [
  "map matching", "road network extraction", "geospatial foundation model",
  "map data quality", "large language models", "retrieval augmented generation",
  "graph neural networks", "satellite imagery",
];
const PAGE = 25;

const state = {
  resultId: null,
  base: null,        // response of the last /api/search
  papers: [],        // currently refined papers
  analytics: null,
  filters: { text: "", author: "", categories: [], primary_only: false, year_from: "", year_to: "" },
  shown: PAGE,
  audit: [],       // newest first; see addAudit
};

// ---------- API ----------
async function api(path, body) {
  const res = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  // Searches and comparisons report the arXiv requests they made, even when they fail.
  if (Array.isArray(data.audit)) addAudit(data.audit, path);
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ---------- Audit log ----------
const AUDIT_MAX = 200;
const AUDIT_SOURCES = {
  arxiv: "Server → arXiv",
  relay: "Relay → arXiv",
  direct: "Browser → arXiv",
  demo: "Demo data, no request",
  sample: "Sample data fallback",
};
const AUDIT_STATUS = { ok: "OK", error: "Error", demo: "Demo", fallback: "Fallback" };
const isProblem = (e) => e.status === "error" || e.status === "fallback";

function addAudit(entries, path) {
  for (const e of entries) {
    e.action ||= path === "/api/compare" ? "compare" : "search";
    console.debug(`[arxiv] ${e.status} ${AUDIT_SOURCES[e.source] || e.source}: ${e.query}`, e.url || "", e);
  }
  state.audit = [...entries].reverse().concat(state.audit).slice(0, AUDIT_MAX);
  renderAudit();
}

function renderAudit() {
  const all = state.audit;
  const problems = all.filter(isProblem).length;
  const badge = $("#log-badge");
  badge.hidden = !all.length;
  badge.textContent = all.length;
  badge.classList.toggle("bad", problems > 0);
  $("#log-count").textContent = all.length
    ? `${fmt(all.length)} request${all.length === 1 ? "" : "s"}${problems ? `, ${problems} with problems` : ""}`
    : "No arXiv requests yet";
  const shown = $("#log-errors-only").checked ? all.filter(isProblem) : all;
  $("#log-list").innerHTML = shown.map((e) => {
    const meta = [
      e.start != null && `start ${e.start}`,
      e.max_results != null && `max ${e.max_results}`,
      e.returned != null && `returned ${fmt(e.returned)}${e.total != null ? ` of ${fmt(e.total)}` : ""}`,
      e.http_status && `HTTP ${e.http_status}`,
    ].filter(Boolean).join(" · ");
    return `<li class="log-entry ${esc(e.status)}">
      <div class="log-head">
        <span class="pill ${esc(e.status)}">${esc(AUDIT_STATUS[e.status] || e.status)}</span>
        <span class="log-src">${esc(AUDIT_SOURCES[e.source] || e.source)}</span>
        <span class="log-action">${esc(e.action)}</span>
        <span class="spacer"></span>
        <time datetime="${esc(e.time)}">${esc(new Date(e.time).toLocaleTimeString())}</time>
        <span class="log-ms">${e.duration_ms != null ? `${fmt(e.duration_ms)} ms` : ""}</span>
      </div>
      <code class="log-query">${esc(e.query)}</code>
      ${meta ? `<div class="log-meta">${esc(meta)}</div>` : ""}
      ${e.error ? `<div class="log-error">${esc(e.error)}</div>` : ""}
      ${e.note ? `<div class="log-note">${esc(e.note)}</div>` : ""}
      ${e.url ? `<a class="log-url" href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.url)}</a>` : ""}
    </li>`;
  }).join("") || `<li class="hint">${all.length ? "No problems logged." : "Run a search to see the arXiv queries here."}</li>`;
}

async function copyAudit() {
  const btn = $("#log-copy");
  try {
    await navigator.clipboard.writeText(JSON.stringify(state.audit, null, 2));
    btn.textContent = "Copied";
  } catch {
    btn.textContent = "Copy blocked";
  }
  setTimeout(() => (btn.textContent = "Copy log"), 1500);
}

function setStatus(msg, kind = "") {
  const el = $("#status");
  el.hidden = !msg;
  el.className = `status ${kind}`;
  el.innerHTML = msg;
}

// ---------- Search panel ----------
async function initCategories() {
  const { groups, demo } = await api("/api/categories");
  const badge = $("#mode-badge");
  badge.textContent = demo ? "Demo mode · synthetic data" : "Live · arXiv API";
  badge.classList.add(demo ? "demo" : "live");
  if (demo) setStatus("Running in <b>demo mode</b>: results come from a generated sample set, not real arXiv papers. Restart without <code>--demo</code> for live data.", "warn");

  $("#category-picker").innerHTML = Object.entries(groups).map(([group, cats]) => `
    <details class="cat-group" ${group === "Computer Science" ? "open" : ""}>
      <summary>${esc(group)} <a href="#" class="group-all" data-group="${esc(group)}">all</a></summary>
      ${Object.entries(cats).map(([code, name]) => `
        <label class="cat-item" data-text="${esc((code + " " + name).toLowerCase())}">
          <input type="checkbox" name="cat" value="${esc(code)}">
          <span>${esc(name)} <code>${esc(code)}</code></span>
        </label>`).join("")}
    </details>`).join("");

  $("#category-picker").addEventListener("change", updateCatCount);
  $("#category-picker").addEventListener("click", (e) => {
    const link = e.target.closest(".group-all");
    if (!link) return;
    e.preventDefault();
    const boxes = [...link.closest("details").querySelectorAll("input")];
    const allOn = boxes.every((b) => b.checked);
    boxes.forEach((b) => (b.checked = !allOn));
    updateCatCount();
  });
  $("#cat-search").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll(".cat-item").forEach((el) => (el.hidden = q && !el.dataset.text.includes(q)));
    if (q) document.querySelectorAll(".cat-group").forEach((d) => (d.open = true));
  });
}

function updateCatCount() {
  const n = selectedCategories().length;
  $("#cat-count").textContent = n ? `(${n} selected)` : "";
}
const selectedCategories = () =>
  [...document.querySelectorAll('input[name="cat"]:checked')].map((b) => b.value);

function searchBody() {
  return {
    topic: $("#topic").value,
    field: $("#field").value,
    categories: selectedCategories(),
    authors: $("#authors").value,
    date_from: $("#date_from").value,
    date_to: $("#date_to").value,
    max_results: Number($("#max_results").value),
    sort_by: $("#sort_by").value,
  };
}

async function runSearch(e) {
  e?.preventDefault();
  const btn = $("#search-btn");
  btn.disabled = true;
  btn.textContent = "Analysing…";
  setStatus('<span class="spinner"></span>Querying arXiv and computing analytics…');
  try {
    const data = await api("/api/search", searchBody());
    state.resultId = data.result_id;
    state.base = data;
    resetFilters(false);
    applyResult(data);
    $("#query-preview").textContent = `Query: ${data.query}`;
    if (narrow()) { setSheet(false); window.scrollTo({ top: 0 }); }
    const capped = data.total_available > data.fetched
      ? ` (of ${fmt(data.total_available)} matching — raise “Max papers” to analyse more)` : "";
    setStatus(data.fetched
      ? `Analysed <b>${fmt(data.fetched)}</b> papers${capped}.${data.source === "demo" ? " <i>Synthetic demo data.</i>" : ""}`
      : "No papers matched. Try broader keywords or fewer categories.", data.fetched ? "" : "warn");
  } catch (err) {
    setStatus(esc(err.message), "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyse";
  }
}

// ---------- Mobile search sheet ----------
function setSheet(open) {
  document.body.classList.toggle("sheet-open", open);
  $("#sheet-backdrop").hidden = !open;
  $("#tab-search-btn").setAttribute("aria-expanded", String(open));
  if (!open && document.activeElement?.closest("#search-panel")) document.activeElement.blur();
}

// ---------- Refine ----------
let refineTimer;
function scheduleRefine() {
  clearTimeout(refineTimer);
  refineTimer = setTimeout(runRefine, 250);
}

async function runRefine() {
  if (!state.resultId) return;
  try {
    const data = await api("/api/analyze", { result_id: state.resultId, filters: state.filters });
    applyResult(data);
  } catch (err) {
    setStatus(esc(err.message), "error");
  }
}

function readFilterInputs() {
  Object.assign(state.filters, {
    text: $("#f-text").value,
    author: $("#f-author").value,
    year_from: $("#f-year-from").value,
    year_to: $("#f-year-to").value,
    primary_only: $("#f-primary").checked,
  });
  scheduleRefine();
}

function resetFilters(refresh = true) {
  state.filters = { text: "", author: "", categories: [], primary_only: false, year_from: "", year_to: "" };
  ["#f-text", "#f-author", "#f-year-from", "#f-year-to"].forEach((s) => ($(s).value = ""));
  $("#f-primary").checked = false;
  if (refresh) runRefine();
}

function toggleCategoryFilter(code) {
  const cats = state.filters.categories;
  const i = cats.indexOf(code);
  i >= 0 ? cats.splice(i, 1) : cats.push(code);
  runRefine();
}

function setTextFilter(term) {
  $("#f-text").value = term;
  readFilterInputs();
}

function setAuthorFilter(name) {
  $("#f-author").value = name;
  readFilterInputs();
}

function renderChips() {
  const cats = state.base?.analytics.all_categories || [];
  const on = new Set(state.filters.categories);
  $("#f-chips").innerHTML = cats.map((c) => `
    <button type="button" class="chip ${on.has(c.name) ? "on" : ""}" data-cat="${esc(c.name)}"
      title="${esc(c.label)}">${esc(c.name)}<span class="n">${fmt(c.count)}</span></button>`).join("");
}

function renderRefineCount() {
  const f = state.filters;
  const n = f.categories.length + [f.text, f.author, f.year_from, f.year_to, f.primary_only].filter(Boolean).length;
  $("#refine-count").textContent = n ? `(${n} active)` : "";
}

// ---------- Rendering ----------
function applyResult(data) {
  state.papers = data.papers;
  state.analytics = data.analytics;
  state.shown = PAGE;
  const has = !!state.base?.fetched;
  $("#empty").hidden = has;
  $("#overview").hidden = !has;
  $("#refine").hidden = !has;
  renderChips();
  renderRefineCount();
  renderOverview(data.analytics);
  renderPapers();
}

function renderOverview(a) {
  const s = a.summary;
  const kpis = [
    [fmt(s.papers), "Papers"],
    [fmt(s.unique_authors), "Unique authors"],
    [s.avg_authors_per_paper, "Avg authors / paper"],
    [`${s.cross_listed_pct}%`, "Cross-listed"],
    [fmt(s.categories), "Categories"],
    [s.date_from ? `${s.date_from.slice(0, 7)} → ${s.date_to.slice(0, 7)}` : "—", "Date span"],
  ];
  $("#kpis").innerHTML = kpis.map(([v, l]) => `<div class="kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");

  // Long spans read better per year; short spans per month.
  const series = a.timeline.length > (narrow() ? 24 : 48) ? a.by_year : a.timeline;
  $("#chart-timeline").innerHTML = columnChart(series, chartWidth("#chart-timeline"));

  $("#chart-primary").innerHTML = hbars(a.primary_categories.slice(0, 12), "name", "cat", (r) => r.label);
  $("#chart-allcats").innerHTML = hbars(a.all_categories.slice(0, 12), "name", "cat", (r) => r.label);
  $("#chart-authors").innerHTML = hbars(a.top_authors.slice(0, 12), "name", "author");
  $("#chart-phrases").innerHTML = hbars(a.phrases.slice(0, 12), "term", "term");
  $("#chart-pairs").innerHTML = hbars(a.category_pairs.slice(0, 10), "name", null);

  const kw = a.keywords;
  const max = kw[0]?.count || 1, min = kw[kw.length - 1]?.count || 0;
  $("#cloud").innerHTML = kw.length ? [...kw].sort((x, y) => x.term.localeCompare(y.term)).map((k) => {
    const size = 12 + Math.round(((k.count - min) / Math.max(1, max - min)) * 14);
    return `<button type="button" data-term="${esc(k.term)}" style="font-size:${size}px" title="${fmt(k.count)} papers">${esc(k.term)}</button>`;
  }).join("") : '<p class="hint">No keywords.</p>';

  $("#emerging").innerHTML = a.emerging_terms.length ? `
    <table><thead><tr><th>Term</th><th class="num">Earlier</th><th class="num">Recent</th><th class="num">Lift</th></tr></thead>
    <tbody>${a.emerging_terms.slice(0, 10).map((t) => `
      <tr><td><a href="#" data-term="${esc(t.term)}">${esc(t.term)}</a></td>
      <td class="num">${t.earlier}</td><td class="num">${t.recent}</td>
      <td class="num up">×${t.lift}</td></tr>`).join("")}</tbody></table>`
    : '<p class="hint">Need at least 10 dated papers to detect emerging terms.</p>';
}

function hbars(rows, key, action, sub) {
  if (!rows.length) return '<p class="hint">No data.</p>';
  const max = Math.max(...rows.map((r) => r.count));
  const on = new Set(state.filters.categories);
  return `<div class="hbars">${rows.map((r) => {
    const label = r[key];
    const attr = action ? `data-${action}="${esc(label)}"` : "";
    const tag = action ? "button" : "div";
    const active = action === "cat" && on.has(label) ? ' style="font-weight:600"' : "";
    return `<${tag} type="button" class="hbar ${action ? "clickable" : ""}" ${attr}${active} title="${esc(label)}${sub ? " — " + esc(sub(r)) : ""}">
      <span class="name">${esc(label)}${sub && sub(r) ? ` <small>${esc(sub(r))}</small>` : ""}</span>
      <span class="track"><span class="fill" style="width:${(100 * r.count) / max}%"></span></span>
      <span class="num">${fmt(r.count)}</span></${tag}>`;
  }).join("")}</div>`;
}

function niceMax(v) {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 4, 5, 8, 10].map((m) => m * p).find((m) => m >= v);
}

// Integer gridline values: quarters when they divide evenly, otherwise fifths.
const ticksFor = (max) => {
  const n = max % 4 === 0 ? 4 : 5;
  return Array.from({ length: n + 1 }, (_, i) => (max * i) / n);
};

// Charts are drawn at the container's real width so text keeps its size on small screens.
const chartWidth = (sel) => Math.max(280, $(sel).clientWidth || 860);
const narrow = () => window.matchMedia("(max-width: 900px)").matches;

function columnChart(series, W = 860) {
  if (!series.length) return '<p class="hint">No dated papers.</p>';
  const H = W < 600 ? 200 : 240, L = 36, R = 8, T = 10, B = 34;
  const max = niceMax(Math.max(...series.map((d) => d.count)));
  const bw = (W - L - R) / series.length;
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const ticks = ticksFor(max);
  const every = Math.ceil(series.length / Math.max(2, Math.floor((W - L - R) / 58)));
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Publications over time">
    ${ticks.map((t) => `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>
      <text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${t}</text>`).join("")}
    ${series.map((d, i) => `<rect class="bar" x="${L + i * bw + bw * 0.12}" y="${y(d.count)}"
        width="${Math.max(1, bw * 0.76)}" height="${H - B - y(d.count)}" rx="2">
        <title>${esc(d.period)}: ${fmt(d.count)}</title></rect>
      ${i % every === 0 ? `<text x="${L + i * bw + bw / 2}" y="${H - B + 16}" text-anchor="middle">${esc(d.period)}</text>` : ""}`).join("")}
  </svg>`;
}

function lineChart(seriesList, W = 860) {
  const periods = [...new Set(seriesList.flatMap((s) => s.by_year.map((d) => d.period)))].sort();
  if (!periods.length) return '<p class="hint">No dated papers.</p>';
  const H = W < 600 ? 220 : 260, L = 36, R = 16, T = 12, B = 30;
  const every = Math.ceil(periods.length / Math.max(2, Math.floor((W - L - R) / 44)));
  const max = niceMax(Math.max(1, ...seriesList.flatMap((s) => s.by_year.map((d) => d.count))));
  const x = (i) => L + (periods.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (periods.length - 1));
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const ticks = ticksFor(max);
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Papers per year by topic">
    ${ticks.map((t) => `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>
      <text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${t}</text>`).join("")}
    ${periods.map((p, i) => (i % every ? "" : `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${esc(p)}</text>`)).join("")}
    ${seriesList.map((s, si) => {
      const m = Object.fromEntries(s.by_year.map((d) => [d.period, d.count]));
      const pts = periods.map((p, i) => [x(i), y(m[p] || 0), p, m[p] || 0]);
      const c = `var(--series-${(si % 6) + 1})`;
      return `<polyline fill="none" stroke="${c}" stroke-width="2.5" points="${pts.map((q) => q.slice(0, 2).join(",")).join(" ")}"/>
        ${pts.map((q) => `<circle cx="${q[0]}" cy="${q[1]}" r="3.5" fill="${c}"><title>${esc(s.topic)} · ${q[2]}: ${q[3]}</title></circle>`).join("")}`;
    }).join("")}
  </svg>`;
}

function sortedPapers() {
  const list = [...state.papers];
  const mode = $("#paper-sort").value;
  if (mode === "date-asc") list.sort((a, b) => a.published.localeCompare(b.published));
  else if (mode === "title") list.sort((a, b) => a.title.localeCompare(b.title));
  else if (mode === "authors") list.sort((a, b) => b.authors.length - a.authors.length);
  else list.sort((a, b) => b.published.localeCompare(a.published));
  return list;
}

function renderPapers() {
  const list = sortedPapers();
  $("#paper-count").textContent = `${fmt(list.length)} papers`;
  $("#paper-list").innerHTML = list.slice(0, state.shown).map((p) => {
    const authors = p.authors.length > 6 ? p.authors.slice(0, 6).join(", ") + ` +${p.authors.length - 6}` : p.authors.join(", ");
    const title = p.abs_url ? `<a href="${esc(p.abs_url)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title);
    return `<article class="paper">
      <h4>${title}</h4>
      <div class="meta"><span>${esc(authors)}</span><span>${esc(p.published.slice(0, 10))}</span><span>${esc(p.id)}</span>
        ${p.pdf_url ? `<a href="${esc(p.pdf_url)}" target="_blank" rel="noopener">PDF</a>` : ""}
        ${p.doi ? `<span>DOI ${esc(p.doi)}</span>` : ""}</div>
      <div class="cats">${p.categories.map((c) => `<span class="${c === p.primary_category ? "primary" : ""}">${esc(c)}</span>`).join("")}</div>
      <details><summary>Abstract</summary><p>${esc(p.summary)}</p></details>
    </article>`;
  }).join("") || '<p class="hint">No papers match the current filters.</p>';
  $("#more-btn").hidden = list.length <= state.shown;
}

function exportResults(format) {
  if (!state.resultId) return;
  const qs = new URLSearchParams({ result_id: state.resultId, format, filters: JSON.stringify(state.filters) });
  window.location = `/api/export?${qs}`;
}

// ---------- Compare ----------
async function runCompare() {
  const topics = $("#compare-topics").value.split("\n").map((t) => t.trim()).filter(Boolean);
  const btn = $("#compare-btn");
  btn.disabled = true;
  setStatus(`<span class="spinner"></span>Comparing ${topics.length} topics…`);
  try {
    const body = { ...searchBody(), topics };
    delete body.topic;
    const data = await api("/api/compare", body);
    state.compare = data;
    $("#compare-out").hidden = false;
    $("#chart-compare").innerHTML = lineChart(data.series, chartWidth("#chart-compare"));
    $("#compare-legend").innerHTML = data.series.map((s, i) => `<span style="--c:var(--series-${(i % 6) + 1})">${esc(s.topic)}</span>`).join("");
    $("#compare-table").innerHTML = `<table><thead><tr><th>Topic</th><th class="num">Matching on arXiv</th>
      <th class="num">Analysed</th><th>Top categories</th><th>Top keywords</th></tr></thead><tbody>
      ${data.series.map((s) => `<tr><td><b>${esc(s.topic)}</b></td><td class="num">${fmt(s.total_available)}</td>
        <td class="num">${fmt(s.fetched)}</td>
        <td>${s.top_categories.map((c) => esc(c.name)).join(", ")}</td>
        <td>${s.keywords.slice(0, 6).map((k) => esc(k.term)).join(", ")}</td></tr>`).join("")}</tbody></table>`;
    setStatus(`Compared ${data.series.length} topics.${data.source === "demo" ? " <i>Synthetic demo data.</i>" : ""}`);
  } catch (err) {
    setStatus(esc(err.message), "error");
  } finally {
    btn.disabled = false;
  }
}

// ---------- Wiring ----------
function initTabs() {
  const tabs = document.querySelectorAll(".tabs button[data-tab]");
  tabs.forEach((b) => b.addEventListener("click", () => {
    tabs.forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.hidden = p.id !== `tab-${b.dataset.tab}`));
    $("#refine").hidden = ["compare", "log"].includes(b.dataset.tab) || !state.base?.fetched;
    // Panels hidden while charts were drawn have no width, so redraw on show.
    if (b.dataset.tab === "overview" && state.analytics) renderOverview(state.analytics);
    if (b.dataset.tab === "compare" && state.compare) {
      $("#chart-compare").innerHTML = lineChart(state.compare.series, chartWidth("#chart-compare"));
    }
    if (narrow()) window.scrollTo({ top: 0 });
  }));
}

function init() {
  $("#presets").innerHTML = PRESETS.map((p) => `<button type="button">${esc(p)}</button>`).join("");
  $("#presets").addEventListener("click", (e) => {
    if (e.target.tagName === "BUTTON") $("#topic").value = e.target.textContent;
  });
  $("#search-form").addEventListener("submit", runSearch);
  $("#reset-btn").addEventListener("click", () => {
    $("#search-form").reset();
    document.querySelectorAll('input[name="cat"]').forEach((b) => (b.checked = false));
    updateCatCount();
  });

  ["#f-text", "#f-author", "#f-year-from", "#f-year-to"].forEach((s) => $(s).addEventListener("input", readFilterInputs));
  $("#f-primary").addEventListener("change", readFilterInputs);
  $("#f-clear").addEventListener("click", () => resetFilters());
  $("#f-chips").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-cat]");
    if (chip) toggleCategoryFilter(chip.dataset.cat);
  });
  $("#overview").addEventListener("click", (e) => {
    const el = e.target.closest("[data-cat],[data-term],[data-author]");
    if (!el) return;
    e.preventDefault();
    if (el.dataset.cat) toggleCategoryFilter(el.dataset.cat);
    else if (el.dataset.term) setTextFilter(el.dataset.term);
    else if (el.dataset.author) setAuthorFilter(el.dataset.author);
  });

  $("#paper-sort").addEventListener("change", renderPapers);
  $("#more-btn").addEventListener("click", () => { state.shown += PAGE; renderPapers(); });
  $("#export-csv").addEventListener("click", () => exportResults("csv"));
  $("#export-json").addEventListener("click", () => exportResults("json"));
  $("#compare-btn").addEventListener("click", runCompare);
  $("#log-errors-only").addEventListener("change", renderAudit);
  $("#log-copy").addEventListener("click", copyAudit);
  $("#log-clear").addEventListener("click", () => { state.audit = []; renderAudit(); });

  $("#tab-search-btn").addEventListener("click", () => setSheet(!document.body.classList.contains("sheet-open")));
  $("#empty-search").addEventListener("click", () => setSheet(true));
  $("#close-search").addEventListener("click", () => setSheet(false));
  $("#sheet-backdrop").addEventListener("click", () => setSheet(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setSheet(false); });
  $("#refine-toggle").addEventListener("click", () => {
    const open = $("#refine").classList.toggle("open");
    $("#refine-toggle").setAttribute("aria-expanded", String(open));
  });

  // Redraw charts when the width changes (rotation, resizing); mobile scrolling only changes height.
  let lastWidth = window.innerWidth, resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (window.innerWidth === lastWidth) return;
      lastWidth = window.innerWidth;
      if (!narrow()) setSheet(false);
      if (state.analytics) renderOverview(state.analytics);
      if (state.compare && !$("#tab-compare").hidden) {
        $("#chart-compare").innerHTML = lineChart(state.compare.series, chartWidth("#chart-compare"));
      }
    }, 150);
  });

  initTabs();
  initCategories().catch((err) => setStatus(esc(err.message), "error"));
}

init();
