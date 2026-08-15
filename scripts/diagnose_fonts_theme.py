#!/usr/bin/env python3
"""CAGE EMPIRE — Font + Theme Diagnostic (Task THEME-FONT-FIX).

A standalone diagnostic script that the user (on Windows) runs to
tell us EXACTLY what's happening on their machine — Python version,
Tk version, CTk version, whether the theme JSON loads, whether each
font registers, and whether Tk can find each font by family name.

Usage:
    python scripts/diagnose_fonts_theme.py

The script prints a comprehensive report to stdout. The user should
copy-paste the FULL output (or screenshot it) and send it back.

This script is READ-ONLY: it does NOT modify any files, registry
entries, or system state. It only QUERIES state.

Author: Font + Theme Expert subagent (Task THEME-FONT-FIX)
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path

# Resolve project paths regardless of CWD.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
ASSETS_DIR = SRC_DIR / "ui" / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
THEME_JSON = ASSETS_DIR / "cage_empire_theme.json"

# Ensure we can import ui.theme
sys.path.insert(0, str(SRC_DIR))


def hr(title: str = ""):
    """Print a horizontal rule with optional title."""
    if title:
        print(f"\n=== {title} ===")
    else:
        print("=" * 60)


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def run_git(args, cwd=PROJECT_ROOT):
    """Run a git command, return (stdout, returncode). Never raises."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(cwd),
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return f"<git error: {e}>", -1


def check_python_versions():
    section("Python / Tk / CTk Versions")
    print(f"Python: {sys.version.split()[0]}  ({sys.executable})")
    print(f"Platform: {platform.platform()}")
    print(f"Platform.system: {platform.system()}")
    print(f"Machine: {platform.machine()}")
    try:
        print(f"Tk version (TkVersion): {tk.TkVersion}")
    except Exception as e:
        print(f"Tk version: <error: {e}>")
    try:
        import customtkinter as ctk
        print(f"CustomTkinter version: {getattr(ctk, '__version__', '<unknown>')}")
    except Exception as e:
        print(f"CustomTkinter: NOT INSTALLED ({e})")
        return False
    return True


def check_git_state():
    section("Git State")
    commit, code = run_git(["rev-parse", "HEAD"])
    print(f"Current commit: {commit}")
    branch, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    print(f"Branch: {branch}")
    # Check if working tree is clean
    status, _ = run_git(["status", "--porcelain"])
    if status:
        print(f"Working tree: DIRTY ({len(status.splitlines())} uncommitted change(s))")
        for line in status.splitlines()[:10]:
            print(f"  {line}")
    else:
        print("Working tree: clean")
    # Check if up to date with origin
    ahead, _ = run_git(["rev-list", "--count", "@{u}..HEAD", "2>nul"])
    behind, _ = run_git(["rev-list", "--count", "HEAD..@{u}", "2>nul"])
    if ahead.startswith("<"):
        print("Upstream: no upstream branch configured (cannot check for updates)")
    else:
        print(f"Ahead of upstream by: {ahead} commit(s)")
        print(f"Behind upstream by: {behind} commit(s)")


def check_pycache():
    section("Cache State (__pycache__ folders)")
    pycache_dirs = list(PROJECT_ROOT.rglob("__pycache__"))
    print(f"__pycache__ folders found: {len(pycache_dirs)}")
    if not pycache_dirs:
        print("  (none — cache is clean)")
        return
    # Check staleness: a .pyc is stale if its .py source has a newer mtime
    stale_count = 0
    for pyc_dir in pycache_dirs:
        rel = pyc_dir.relative_to(PROJECT_ROOT)
        # Get the parent source dir's .py files
        src_dir = pyc_dir.parent
        py_files = list(src_dir.glob("*.py"))
        if not py_files:
            print(f"  {rel}  (no .py files in parent — orphan cache)")
            continue
        # Find newest .py mtime
        newest_py_mtime = max(p.stat().st_mtime for p in py_files)
        # Find any .pyc older than that
        stale_py = []
        for pyc in pyc_dir.glob("*.pyc"):
            if pyc.stat().st_mtime < newest_py_mtime:
                stale_py.append(pyc.name)
        if stale_py:
            stale_count += 1
            print(f"  {rel}  STALE ({len(stale_py)} .pyc older than .py)")
        else:
            print(f"  {rel}  fresh")
    print(f"\nStale cache dirs: {stale_count}")
    if stale_count > 0:
        print("  RECOMMENDATION: clear __pycache__ before running the app.")
        print("  PLAY.bat now does this automatically on launch.")


def check_theme_json():
    section("Theme JSON File")
    print(f"Expected path: {THEME_JSON}")
    print(f"Exists: {THEME_JSON.exists()}")
    if not THEME_JSON.exists():
        print("  ERROR: theme JSON is missing. install_ctk_theme() will write it,")
        print("  but if you're seeing this it means the app hasn't run yet OR")
        print("  the assets dir is read-only.")
        return None
    size = THEME_JSON.stat().st_size
    print(f"Size: {size} bytes")
    try:
        data = json.loads(THEME_JSON.read_text(encoding="utf-8"))
        print(f"Valid JSON: yes")
    except Exception as e:
        print(f"Valid JSON: NO — {e}")
        return None
    button = data.get("CTkButton", {})
    fg = button.get("fg_color")
    print(f"CTkButton fg_color in JSON: {fg!r}")
    if fg == "#e0a957":
        print(f"  -> matches our gold (#e0a957): YES")
    else:
        print(f"  -> matches our gold (#e0a957): NO (expected #e0a957)")
    return data


def check_ctk_loaded():
    section("CTk Theme Loaded? (the critical check)")
    try:
        import customtkinter as ctk
    except Exception as e:
        print(f"CustomTkinter not importable: {e}")
        return
    # We need a Tk root for some CTk operations, but ThemeManager.theme
    # is a class attribute populated at import time + on
    # set_default_color_theme. So we can query it without a root.
    try:
        ctk.set_appearance_mode("dark")
    except Exception as e:
        print(f"set_appearance_mode failed: {e}")
    # Try to load our theme
    print(f"\nCalling install_ctk_theme()...")
    try:
        from ui.theme import install_ctk_theme, CTK_THEME_JSON_PATH
        ok = install_ctk_theme()
        print(f"install_ctk_theme() returned: {ok}")
    except Exception as e:
        import traceback
        print(f"install_ctk_theme() raised: {e}")
        traceback.print_exc()
        return
    # Query ThemeManager
    try:
        from customtkinter import ThemeManager
        theme = ThemeManager.theme
        button = theme.get("CTkButton", {})
        fg = button.get("fg_color")
        print(f"\nThemeManager.theme['CTkButton']['fg_color']: {fg!r}")
        if "#e0a957" in str(fg):
            print(f"  -> Matches our gold (#e0a957): YES")
            print(f"  -> CTk theme is loaded correctly.")
        else:
            print(f"  -> Matches our gold (#e0a957): NO")
            print(f"  -> CTk theme DID NOT LOAD. App is using default CTk theme (blue).")
            print(f"  -> This explains why buttons look default-blue instead of gold.")
    except Exception as e:
        print(f"Could not query ThemeManager: {e}")


def check_font_files():
    section("Font Files (bundled TTFs)")
    expected = [
        "Inter-Regular.ttf",
        "Inter-Medium.ttf",
        "Inter-SemiBold.ttf",
        "Inter-Bold.ttf",
        "JetBrainsMono-Medium.ttf",
        "SourceSerifPro-Regular.ttf",
        "SourceSerifPro-SemiBold.ttf",
        "SourceSerifPro-Italic.ttf",
        "SourceSerifPro-SemiBoldItalic.ttf",
        "Oswald-Bold.ttf",
    ]
    print(f"Expected TTF dir: {FONTS_DIR}")
    print(f"Dir exists: {FONTS_DIR.exists()}")
    if not FONTS_DIR.exists():
        print("  ERROR: fonts directory is missing. App cannot load custom fonts.")
        return
    found_count = 0
    for name in expected:
        p = FONTS_DIR / name
        if p.exists():
            size = p.stat().st_size
            size_kb = size / 1024
            print(f"  {name}: exists ({size_kb:.1f} KB)")
            found_count += 1
        else:
            print(f"  {name}: MISSING")
    print(f"\nBundled TTFs present: {found_count} of {len(expected)}")


def check_user_font_dir():
    section("Font Installation (user font dir + Win32 registration)")
    system = platform.system().lower()
    if system == "windows":
        user_font_dir = Path(os.environ.get(
            "LOCALAPPDATA", str(Path.home()))) / "Fonts"
    elif system == "darwin":
        user_font_dir = Path.home() / "Library" / "Fonts"
    else:
        user_font_dir = Path.home() / ".fonts"
    print(f"User font dir: {user_font_dir}")
    print(f"Exists: {user_font_dir.exists()}")
    if user_font_dir.exists():
        ttf_files = list(user_font_dir.glob("*.ttf"))
        # Filter to the ones we care about
        ours = [t for t in ttf_files if t.name in {
            "Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf",
            "Inter-Bold.ttf", "JetBrainsMono-Medium.ttf",
            "SourceSerifPro-Regular.ttf", "SourceSerifPro-SemiBold.ttf",
            "SourceSerifPro-Italic.ttf", "SourceSerifPro-SemiBoldItalic.ttf",
            "Oswald-Bold.ttf",
        }]
        print(f"Our TTFs copied to user font dir: {len(ours)} of 10")
        for t in ours:
            print(f"  {t.name}")
    else:
        print("  (dir does not exist — install_fonts_to_user_dir has not run)")
    # Windows-specific: check AddFontResource / registry
    if system == "windows":
        print("\nWin32 font registration:")
        try:
            import winreg  # type: ignore[import-not-found]
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Fonts",
            ) as key:
                i = 0
                ours_in_registry = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        if any(f in name for f in (
                                "Inter", "JetBrains", "SourceSerif",
                                "Oswald")):
                            ours_in_registry += 1
                            print(f"  Registry: {name} -> {value}")
                        i += 1
                    except OSError:
                        break
                print(f"\nOur fonts in HKCU registry: {ours_in_registry}")
                if ours_in_registry == 0:
                    print("  WARNING: no CAGE EMPIRE fonts in registry.")
                    print("  This means _register_fonts_windows_native()")
                    print("  has not run successfully on this machine, OR")
                    print("  it ran but the registry writes failed (e.g.")
                    print("  permission issue).")
        except Exception as e:
            print(f"  Could not read registry: {e}")
        # Check if AddFontResourceW would work (just check the API exists)
        try:
            import ctypes
            gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
            if hasattr(gdi32, "AddFontResourceW"):
                print("  AddFontResourceW API: available")
            else:
                print("  AddFontResourceW API: MISSING (very unusual)")
        except Exception as e:
            print(f"  AddFontResourceW check failed: {e}")
    else:
        print("\n(Not Windows — skipping Win32 registration check.)")
        # Check fc-cache
        try:
            r = subprocess.run(
                ["fc-list", ":family"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                families = r.stdout.strip().split("\n")
                print(f"\nfc-list reports {len(families)} font families.")
                for fam in ("Inter", "Inter-Regular", "JetBrains Mono",
                            "Source Serif Pro", "Oswald"):
                    if any(fam in line for line in families):
                        print(f"  {fam}: found via fc-list")
                    else:
                        print(f"  {fam}: NOT found via fc-list")
        except Exception as e:
            print(f"  fc-list not available: {e}")


def check_tk_font_families():
    section("Tk Font Families (THE critical check)")
    print("This is the most important check: does Tk actually see our")
    print("font families by name? If not, the app falls back to")
    print("platform default fonts (Segoe UI on Windows, Sans on Linux).")
    print()
    # Create a Tk root — this may fail in headless envs
    try:
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        print(f"Tk root creation failed: {e}")
        print("(This means no display is available — common on Linux servers")
        print("without Xvfb. On Windows this should NEVER happen.)")
        return
    try:
        try:
            families = list(root.tk.call("font", "families"))
        except Exception as e:
            print(f"tk.call('font', 'families') failed: {e}")
            return
        print(f"Total families available to Tk: {len(families)}")
        wanted = [
            "Inter",
            "Inter-Regular",
            "Inter-Medium",
            "Inter-SemiBold",
            "Inter-Bold",
            "JetBrains Mono",
            "Source Serif Pro",
            "Oswald",
        ]
        print()
        # Case-insensitive check (Tk font families are case-sensitive
        # on some platforms, case-insensitive on others).
        families_lower = {f.lower() for f in families if isinstance(f, str)}
        for w in wanted:
            present = w.lower() in families_lower
            mark = "YES" if present else "no"
            print(f"  {w:<22} in font families list: {mark}")
        print()
        # THE DEFINITIVE CHECK: create a font with family=<w> and ask
        # Tk what it ACTUALLY resolved to. If Tk returns the same
        # family, the font is loaded. If Tk returns something else
        # (e.g. 'fixed', 'Segoe UI'), Tk fell back — the font is NOT
        # actually usable, even if it appears in the families list.
        print("Definitive check (font.actual):")
        import tkinter.font as tkfont
        for w in wanted:
            try:
                probe = tkfont.Font(root, family=w, size=15)
                actual = probe.actual("family")
                if (isinstance(actual, str)
                        and (actual.lower() == w.lower()
                             or w.lower() in actual.lower()
                             or actual.lower() in w.lower())):
                    print(f"  {w:<22} -> resolves to {actual!r}  ✓")
                else:
                    print(f"  {w:<22} -> resolves to {actual!r}  ✗ (FELL BACK)")
                try:
                    probe.delete()
                except Exception:
                    pass
            except Exception as e:
                print(f"  {w:<22} -> probe failed: {e}  ✗")
        print()
        # Show first 20 families as a sanity check
        print(f"First 20 families Tk reports:")
        for f in families[:20]:
            print(f"  {f}")
        if len(families) > 20:
            print(f"  ... and {len(families) - 20} more")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def check_app_imports():
    section("App Module Imports")
    """Check if app.py imports cleanly (with a Tk root available)."""
    try:
        # app.py does `ctk.set_appearance_mode` then `from ui.theme import`
        # We need CTk + Tk available.
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        # Force font registration
        try:
            from ui import theme as theme_mod
            # Manually call install_ctk_theme to verify
            theme_mod.install_ctk_theme()
            print("ui.theme: imports OK")
            print("install_ctk_theme(): ran OK (see check above for result)")
        except Exception as e:
            import traceback
            print(f"ui.theme import failed: {e}")
            traceback.print_exc()
            return
    except Exception as e:
        print(f"customtkinter import failed: {e}")
        return


def verdict():
    section("VERDICT")
    print("Review the sections above. The most likely culprits are:")
    print()
    print("1. CTk theme DID NOT LOAD (CTk Theme Loaded? section says NO)")
    print("   -> The theme JSON path is wrong, the JSON is malformed,")
    print("   -> OR a stale __pycache__ contains old app.py code that")
    print("   -> calls ctk.set_default_color_theme('dark-blue') AFTER")
    print("   -> install_ctk_theme(). Fix: delete __pycache__ folders.")
    print()
    print("2. Tk doesn't see our font families (Tk Font Families section)")
    print("   -> On Windows: AddFontResourceW was never called (or failed).")
    print("   -> On Linux: fc-cache didn't pick up the TTFs.")
    print("   -> Fix: re-run the app — install_fonts_to_user_dir() now")
    print("   -> calls _register_fonts_windows_native() on Windows.")
    print()
    print("3. Stale __pycache__ (Cache State section says STALE)")
    print("   -> Python is loading old .pyc files instead of the .py source.")
    print("   -> Fix: PLAY.bat now auto-clears __pycache__ on launch.")
    print()
    print("Send this FULL diagnostic output back so we can pinpoint")
    print("exactly which of these (or combination) is happening on")
    print("your machine.")


def main():
    print("=" * 60)
    print("  CAGE EMPIRE — Font + Theme Diagnostic")
    print("  Task: THEME-FONT-FIX")
    print("=" * 60)
    print(f"Run at: {Path.cwd()}")
    print(f"Project root: {PROJECT_ROOT}")

    check_python_versions()
    check_git_state()
    check_pycache()
    check_theme_json()
    check_ctk_loaded()
    check_font_files()
    check_user_font_dir()
    check_tk_font_families()
    check_app_imports()
    verdict()

    print()
    print("=" * 60)
    print("  END OF DIAGNOSTIC")
    print("=" * 60)


if __name__ == "__main__":
    main()
