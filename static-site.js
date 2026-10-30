"use strict";
// Adjustments to app.js for the static (GitHub Pages) build. Loaded after app.js.
(function () {
  const RELAY_SETUP = "https://github.com/sanjeevk20/arxivanalytics#arxiv-relay-needed-for-live-data-on-the-hosted-site";
  const badge = document.getElementById("mode-badge");
  const setBadge = (text, kind) => {
    badge.textContent = text;
    badge.classList.remove("live", "demo");
    badge.classList.add(kind);
  };
  const howToGoLive =
    `Browsers can't call arXiv directly, so this site needs its <a href="${RELAY_SETUP}" target="_blank" rel="noopener">arXiv relay</a>. ` +
    "Or run the app on your computer with <code>python3 -m arxiv_analytics</code>, which calls arXiv itself.";
  const sampleButton = '<button type="button" class="ghost status-action" data-use="sample">Use sample papers instead</button>';
  const liveButton = '<button type="button" class="ghost status-action" data-use="live">Try live arXiv again</button>';

  // A failed live search stays an error: no silent switch to made-up papers.
  window.addEventListener("arxiv-unreachable", () => setBadge("arXiv unreachable", "demo"));
  const baseSetStatus = setStatus;
  window.setStatus = (msg, kind) => {
    msg = String(msg);
    if (kind === "error" && msg.startsWith("Couldn&#39;t reach arXiv")) {
      msg += `<br><small>${howToGoLive}</small><br>${sampleButton}`;
      // Don't leave earlier sample results on screen under a failed live search.
      if (state.base?.source === "demo") {
        state.base = null;
        ["#overview", "#refine", "#compare-out"].forEach((sel) => (document.querySelector(sel).hidden = true));
        document.getElementById("empty").hidden = false;
        document.getElementById("paper-list").innerHTML = "";
        document.getElementById("paper-count").textContent = "";
      }
    } else if (window.__useSampleData__ && /^(Analysed|Compared|No papers)/.test(msg)) {
      msg += ` <br><small>These are <b>built-in sample papers</b>, not real arXiv results.</small> ${liveButton}`;
      kind = "warn";
    } else if (!window.__useSampleData__ && /^(Analysed|Compared|No papers)/.test(msg)) {
      setBadge("Live · arXiv API", "live");
    }
    baseSetStatus(msg, kind);
  };
  document.getElementById("status").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-use]");
    if (!btn) return;
    window.__useSampleData__ = btn.dataset.use === "sample";
    setBadge(window.__useSampleData__ ? "Sample data · not live" : "Live · arXiv API",
             window.__useSampleData__ ? "demo" : "live");
    const compareOpen = !document.getElementById("tab-compare").hidden;
    compareOpen ? runCompare() : runSearch();
  });

  // No server to stream exports from, so build the file in the browser.
  const CSV_FIELDS = ["id", "title", "authors", "published", "primary_category", "categories",
    "abs_url", "pdf_url", "doi", "journal_ref", "summary"];
  const toCsv = (rows) => {
    const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    return [CSV_FIELDS.join(",")].concat(rows.map((p) => CSV_FIELDS.map((f) =>
      cell(f === "authors" ? p.authors.join("; ") : f === "categories" ? p.categories.join(" ") : p[f])).join(","))).join("\n");
  };
  window.exportResults = (format) => {
    if (!state.resultId) return;
    const rows = window.__exportRows__(state.resultId, state.filters);
    const json = format === "json";
    const blob = new Blob([json ? JSON.stringify(rows, null, 2) : toCsv(rows)],
      { type: json ? "application/json" : "text/csv" });
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(blob), download: `arxiv_results.${json ? "json" : "csv"}`,
    });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  // Open in a working state: run an example live search when the relay is set up;
  // otherwise say up front why live search won't work rather than failing on load.
  document.getElementById("topic").value = "satellite imagery, road network extraction";
  // Wait for app.js to finish its own start-up (it sets the badge once categories load).
  const whenReady = (fn) => (document.querySelector(".cat-item") ? fn() : setTimeout(() => whenReady(fn), 50));
  whenReady(() => {
    if (window.__ARXIV_RELAY_URL__) return runSearch();
    setBadge("Live search not set up", "demo");
    baseSetStatus(`<b>Live arXiv search isn't connected yet.</b> ${howToGoLive}<br>${sampleButton}`, "warn");
  });
})();
