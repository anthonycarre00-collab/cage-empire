"""Generate a full-app preview HTML (shell + dashboard) using a mock
pywebview API backed by the real Api class.

Usage:
    cd /home/z/my-project/cage_empire
    python3 scripts/generate_full_preview.py [promo_id]

Output: full_app_preview.html in project root. Open in any browser.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from app_web import Api  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "src" / "web"
OUTPUT = PROJECT_ROOT / "full_app_preview.html"


def main():
    promo_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    api = Api()
    # Pre-select the promo so the app skips the selection screen
    api.select_promotion(promo_id)
    dash = api.get_dashboard_data(promo_id)
    clock = api.get_clock()
    cash = api.get_player_cash()
    promos = api.get_promotion_list()

    if "error" in dash:
        print(f"ERROR: {dash['error']}")
        sys.exit(1)

    # Read the real index.html
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # Build a mock pywebview API object that returns the pre-fetched data
    # as Promises. The bridge.js waitForApi() will find window.pywebview.api
    # immediately + call the right methods.
    mock_script = f"""
<script>
// Mock pywebview API — returns pre-fetched data as resolved Promises.
window.pywebview = {{
  api: {{
    get_player_promotion: function() {{ return Promise.resolve({promo_id}); }},
    get_player_cash: function() {{ return Promise.resolve({json.dumps(cash)}); }},
    get_clock: function() {{ return Promise.resolve({json.dumps(clock)}); }},
    get_promotion_list: function() {{ return Promise.resolve({json.dumps(promos)}); }},
    select_promotion: function(pid) {{ return Promise.resolve({{ok: true, promo_id: pid}}); }},
    get_dashboard_data: function(pid) {{ return Promise.resolve({json.dumps(dash)}); }},
    advance_day: function() {{
      // Mock: just re-return the same clock (preview can't actually advance)
      return Promise.resolve({json.dumps(clock)});
    }},
    clearErrors: function() {{}},
    list_saves: function() {{ return Promise.resolve({{saves: []}}); }},
    save_game: function(n) {{ return Promise.resolve({{ok: true, name: n}}); }},
    load_game: function(n) {{ return Promise.resolve({{ok: true, name: n}}); }},
    get_roster_data: function(p,page,f) {{ return Promise.resolve({{placeholder: true}}); }},
    get_fighter_profile: function(fid) {{ return Promise.resolve({{placeholder: true}}); }},
    get_free_agents: function(page,f) {{ return Promise.resolve({{placeholder: true}}); }}
  }}
}};
</script>
"""
    # Inject the mock right before </body> (after the real scripts load,
    # but the real scripts call window.CE.bridge.ready() which waits for
    # window.pywebview.api — since we set it synchronously here, ready()
    # resolves immediately on first check).
    # Actually, we need to inject it BEFORE the real scripts so the mock
    # is in place when bridge.js's waitForApi first checks. Let me inject
    # it in <head> instead.
    mock_in_head = mock_script.replace("<script>", "<script>\n// Injected mock pywebview API (preview only)")
    full_html = index_html.replace("</head>", mock_in_head + "\n</head>")

    # Rewrite CSS/JS paths from relative (css/theme.css) to absolute
    # (file:///.../src/web/css/theme.css) so the browser can load them
    # when opening the preview via file://.
    web_prefix = str(WEB_DIR) + "/"
    full_html = full_html.replace('href="css/', f'href="{web_prefix}css/')
    full_html = full_html.replace('src="js/', f'src="{web_prefix}js/')
    full_html = full_html.replace('src="assets/', f'src="{web_prefix}assets/')

    OUTPUT.write_text(full_html, encoding="utf-8")
    print(f"Generated {OUTPUT} ({len(full_html)} bytes)")
    print(f"Promotion: {dash['promo_name']} | Cash: ${dash['cash']/1e6:.1f}M | "
          f"Roster: {dash['roster_count']} | Champions: {dash['champ_count']}")


if __name__ == "__main__":
    main()
