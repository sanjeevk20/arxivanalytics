"use strict";
// Adjustments to app.js for the static (GitHub Pages) build. Loaded after app.js.
(function () {
  let fallbackReason = "";

  // Explain the switch to sample data once, next to the result summary.
  const baseSetStatus = setStatus;
  window.setStatus = (msg, kind) => {
    if (fallbackReason && /^(Analysed|Compared|No papers)/.test(String(msg))) {
      msg += ` <br><small>The browser couldn't reach arXiv (${esc(fallbackReason)}), so these results use built-in sample papers. ` +
        "Reload to try arXiv again, or run the app locally with <code>python3 -m arxiv_analytics</code>.</small>";
      kind = "warn";
    }
    baseSetStatus(msg, kind);
  };

  window.addEventListener("arxiv-fallback", (e) => {
    fallbackReason = e.detail;
    const badge = document.getElementById("mode-badge");
    badge.textContent = "Sample data · arXiv unreachable";
    badge.classList.remove("live");
    badge.classList.add("demo");
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

  // Open in a working state with an example search already run.
  document.getElementById("topic").value = "satellite imagery, road network extraction";
  setTimeout(() => runSearch(), 0);
})();
