"""Build the static (GitHub Pages) version of the UI.

The Python server isn't available on a static host, so the page ships site/static-api.js,
which answers the UI's /api/* calls in the browser: live searches go straight to the arXiv
API, with the synthetic demo corpus as a fallback.

Usage: python3 scripts/build_site.py [OUTPUT_DIR]   (default: build/site)
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arxiv_analytics import analytics, demo  # noqa: E402
from arxiv_analytics.categories import CATEGORY_GROUPS  # noqa: E402

STATIC = ROOT / "arxiv_analytics" / "static"
SITE = ROOT / "site"


def build(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    html = (STATIC / "index.html").read_text()
    scripts = ["config.js", "data.js", "static-api.js", "app.js", "static-site.js"]
    html = html.replace('<script src="app.js"></script>',
                        "\n".join(f'<script src="{s}"></script>' for s in scripts))
    (out / "index.html").write_text(html)

    for name in ("app.js", "style.css"):
        shutil.copy(STATIC / name, out / name)
    for name in ("config.js", "static-api.js", "static-site.js"):
        shutil.copy(SITE / name, out / name)
    (out / "data.js").write_text(
        "window.__CORPUS__=" + json.dumps(demo.generate(), separators=(",", ":")) + ";\n"
        "window.__GROUPS__=" + json.dumps(CATEGORY_GROUPS) + ";\n"
        "window.__STOPWORDS__=" + json.dumps(sorted(analytics.STOPWORDS)) + ";\n"
    )
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    target = build(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build" / "site")
    print(f"Static site written to {target}")
