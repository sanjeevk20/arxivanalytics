// Cloudflare Worker: a CORS relay for the arXiv API, used by the GitHub Pages build.
//
// arXiv's API sends no CORS headers, so browsers block calls from other websites.
// This forwards query parameters to export.arxiv.org and adds the header for the
// allowed origins. It only ever calls the arXiv API, and caches answers for an hour
// to go easy on arXiv's rate limits.

const UPSTREAM = "https://export.arxiv.org/api/query";
const PARAMS = ["search_query", "id_list", "start", "max_results", "sortBy", "sortOrder"];
const MAX_RESULTS = 500;
const CACHE_SECONDS = 3600;
// Override with a comma-separated ALLOWED_ORIGINS variable in the Worker's settings.
const DEFAULT_ORIGINS = "https://sanjeevk20.github.io,http://localhost:8000,http://127.0.0.1:8000";

export default {
  async fetch(request, env, ctx) {
    const allowed = (env.ALLOWED_ORIGINS || DEFAULT_ORIGINS).split(",").map((o) => o.trim());
    const origin = request.headers.get("Origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": allowed.includes(origin) ? origin : allowed[0],
      "Vary": "Origin",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: { ...cors, "Access-Control-Allow-Methods": "GET", "Access-Control-Max-Age": "86400" },
      });
    }
    if (request.method !== "GET") {
      return new Response("Only GET is supported", { status: 405, headers: cors });
    }

    const incoming = new URL(request.url).searchParams;
    const query = new URLSearchParams();
    for (const name of PARAMS) {
      if (incoming.has(name)) query.set(name, incoming.get(name));
    }
    if (!query.has("search_query") && !query.has("id_list")) {
      return new Response("Pass search_query or id_list, as for the arXiv API", { status: 400, headers: cors });
    }
    if (Number(query.get("max_results") || 10) > MAX_RESULTS) query.set("max_results", String(MAX_RESULTS));

    const upstreamUrl = `${UPSTREAM}?${query}`;
    const cacheKey = new Request(upstreamUrl);
    let response = await caches.default.match(cacheKey);
    if (!response) {
      const upstream = await fetch(upstreamUrl, { headers: { "User-Agent": "arxiv-analytics-relay/1.0" } });
      response = new Response(upstream.body, upstream);
      response.headers.set("Cache-Control", `public, max-age=${CACHE_SECONDS}`);
      if (upstream.ok) ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
    }

    response = new Response(response.body, response);
    for (const [name, value] of Object.entries(cors)) response.headers.set(name, value);
    return response;
  },
};
