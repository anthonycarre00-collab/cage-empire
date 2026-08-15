"""Generate a standalone preview HTML of the Dashboard using the new
pywebview frontend's CSS (local @font-face, offline) + live DB data
via the Api class.

Usage:
    cd /home/z/my-project/cage_empire
    python3 scripts/generate_dashboard_preview.py [promo_id]

Default promo_id=1. Output: dashboard_preview.html in project root.
Open in any browser to preview what the pywebview app will render.
"""
import sys
import json
from pathlib import Path

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app_web import Api  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "src" / "web"
OUTPUT = PROJECT_ROOT / "dashboard_preview.html"


def main():
    promo_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    api = Api()
    data = api.get_dashboard_data(promo_id)

    if "error" in data:
        print(f"ERROR: {data['error']}")
        sys.exit(1)

    # Inline the CSS files (so the preview is a single standalone HTML)
    css_blocks = []
    for css_name in ["theme.css", "shell.css", "components.css", "dashboard.css"]:
        css_path = WEB_DIR / "css" / css_name
        if css_path.exists():
            # Rewrite ../assets/ paths to absolute file paths for browser preview
            css_text = css_path.read_text(encoding="utf-8")
            # For browser preview: point font URLs at the actual file paths
            css_text = css_text.replace(
                "../assets/", str(WEB_DIR / "assets") + "/"
            ).replace(
                "assets/", str(WEB_DIR / "assets") + "/"
            )
            css_blocks.append(f"/* === {css_name} === */\n{css_text}")

    # Inline the dashboard.js render logic by calling it via a tiny shim:
    # we load the actual dashboard.js + feed it the data.
    dashboard_js_path = WEB_DIR / "js" / "dashboard.js"
    dashboard_js = dashboard_js_path.read_text(encoding="utf-8") if dashboard_js_path.exists() else ""

    # The dashboard.js expects window.CE.bridge + a #screen-content div.
    # We provide a mock bridge that returns the pre-fetched data, then
    # call window.CE.dashboard.render(data).
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>CAGE EMPIRE — Dashboard Preview (promo {promo_id})</title>
<style>
{"".join(css_blocks)}
/* Preview-only: show the screen-content as a full-page dashboard */
html, body {{ height: auto; overflow: auto; }}
.ce-screen {{ overflow: visible; }}
</style>
</head>
<body>
<div id="screen-content"></div>
<script>
{dashboard_js}
</script>
<script>
// Mock the bridge — the data is already embedded.
window.CE = window.CE || {{}};
window.CE.bridge = window.CE.bridge || {{
  getDashboardData: function() {{ return Promise.resolve({json.dumps(data)}); }},
  clearErrors: function() {{}}
}};
// Render the dashboard.
window.CE.dashboard.render({json.dumps(data)});
</script>
</body>
</html>"""

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Generated {OUTPUT} ({len(html)} bytes)")
    print(f"Promotion: {data['promo_name']} | Cash: ${data['cash']/1e6:.1f}M | "
          f"Roster: {data['roster_count']} | Champions: {data['champ_count']}")
    print(f"Fighter Watch: {len(data['fighter_watch'])} | "
          f"News: {len(data['recent_news'])} | "
          f"Results: {len(data['recent_results'])}")


if __name__ == "__main__":
    main()
