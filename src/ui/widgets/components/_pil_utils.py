"""CAGE EMPIRE — Phase 2 component library: PIL compositing helpers.

Shared, cached PIL primitives for the 9 visual-richness components
(GradientCard, TrendIndicator, FormMeter, MomentumRing, AttributeBar,
Sparkline, StatTile, BeatBar, GradientHeader). Keeping these here
centralises:

  - Color parsing (hex → RGBA tuple, RGBA tuple → hex)
  - Linear / diagonal / radial gradient rendering (cached)
  - Sparkline rendering (cached, anti-aliased)
  - Momentum-ring arc rendering (cached)
  - Form-meter block rendering (cached)

Caching:
  Every primitive caches its result in a module-level dict keyed by
  the args tuple. Subsequent calls with the same args are dict
  lookups (microseconds). The cache survives for the process lifetime;
  there's no eviction (the working set is tiny — a few hundred small
  images at most).

PIL fallback:
  If PIL is not installed (the user's environment doesn't have it),
  every primitive returns None. Callers must handle None (typically
  by rendering a flat color instead of a gradient, or by skipping the
  sparkline). The Phase 2 components are designed to gracefully
  degrade — none CRASH if PIL is missing.

Theme awareness:
  Helpers do NOT call get_theme() themselves — callers pass in the
  colors they want. This keeps the helpers pure + testable.
  Components read theme.colors at construction time and pass the
  resolved hex values here.

CONVENTIONS compliance:
  §14 — Voice Layer: nothing here displays text. All text rendering
        happens in the components themselves, using voice phrases.
  §17 — UI Snapshot Rule: no DB reads. Pure functions of (args) →
        CTkImage / PIL Image / None.
"""

from __future__ import annotations

# ============================================================
# PIL AVAILABILITY
# ============================================================
# Defensive import — every helper must handle PIL missing.

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:  # pragma: no cover — defensive
    HAS_PIL = False
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]

import customtkinter as ctk
import math
import re


# ============================================================
# COLOR PARSING
# ============================================================

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGBA_RE = re.compile(
    r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)$"
)


def hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Parse a hex color string (#rgb or #rrggbb) → RGBA tuple.

    Args:
        hex_str: hex color like "#e0a957", "e0a957", "#1c2028".
        alpha: alpha channel value (0-255). Defaults to 255 (opaque).

    Returns:
        (r, g, b, a) tuple of ints 0-255.

    Raises:
        ValueError if the hex string is malformed.
    """
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        r = int(h[0] * 2, 16)
        g = int(h[1] * 2, 16)
        b = int(h[2] * 2, 16)
    elif len(h) == 6:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    else:
        raise ValueError(f"Bad hex color: {hex_str!r}")
    return (r, g, b, alpha)


def rgba_to_hex(rgba: tuple[int, int, int, int]) -> str:
    """Convert an (r, g, b, a) tuple → "#rrggbb" hex string.

    Alpha is dropped (the result is always opaque hex — use the
    RGBA tuple directly for PIL operations that need alpha).
    """
    r, g, b = rgba[0], rgba[1], rgba[2]
    return f"#{r:02x}{g:02x}{b:02x}"


def parse_color(color) -> tuple[int, int, int, int]:
    """Parse any supported color format → RGBA tuple.

    Supported:
      - hex "#rrggbb" or "#rgb"
      - "rgba(r,g,b,a)" or "rgb(r,g,b)" (alpha optional, 0-1 or 0-255)

    Args:
        color: hex string, rgba() string, or already-an-RGBA-tuple.

    Returns:
        (r, g, b, a) tuple of ints.
    """
    if isinstance(color, (tuple, list)):
        if len(color) == 4:
            return tuple(int(c) for c in color)  # type: ignore[return-value]
        if len(color) == 3:
            return (int(color[0]), int(color[1]), int(color[2]), 255)
    if isinstance(color, str):
        s = color.strip()
        m = _RGBA_RE.match(s)
        if m:
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            a_raw = m.group(4)
            if a_raw is None:
                a = 255
            else:
                a_float = float(a_raw)
                a = int(round(a_float * 255)) if a_float <= 1.0 else int(a_float)
            return (r, g, b, a)
        if _HEX_RE.match(s):
            return hex_to_rgba(s)
    raise ValueError(f"Unparseable color: {color!r}")


def lighten(rgba: tuple[int, int, int, int], amount: float) -> tuple[int, int, int, int]:
    """Lighten an RGBA color by `amount` (0.0 = no change, 1.0 = white)."""
    r, g, b, a = rgba
    r = int(r + (255 - r) * amount)
    g = int(g + (255 - g) * amount)
    b = int(b + (255 - b) * amount)
    return (r, g, b, a)


def darken(rgba: tuple[int, int, int, int], amount: float) -> tuple[int, int, int, int]:
    """Darken an RGBA color by `amount` (0.0 = no change, 1.0 = black)."""
    r, g, b, a = rgba
    return (int(r * (1 - amount)), int(g * (1 - amount)), int(b * (1 - amount)), a)


# ============================================================
# GRADIENT CACHE
# ============================================================
# Key: (width, height, top_rgba, bottom_rgba, direction)
#   direction: "vertical" / "horizontal" / "diagonal"
# Value: PIL.Image (RGBA). Caller wraps in CTkImage.
# Cache survives process lifetime; no eviction (working set tiny).

_GRADIENT_CACHE: dict[tuple, "Image.Image"] = {}


def make_gradient(
    width: int,
    height: int,
    top_color,
    bottom_color,
    direction: str = "vertical",
) -> "Image.Image | None":
    """Create a linear gradient PIL Image (RGBA).

    Args:
        width, height: pixel dimensions.
        top_color: starting color (hex / rgba string / RGBA tuple).
        bottom_color: ending color.
        direction: "vertical" (top→bottom), "horizontal" (left→right),
            "diagonal" (top-left → bottom-right).

    Returns:
        PIL.Image (RGBA mode), or None if PIL is missing.

    Caching:
        Results are cached by (width, height, top_rgba, bottom_rgba,
        direction). Repeated calls with identical args return the same
        PIL Image (instant).
    """
    if not HAS_PIL:
        return None
    top_rgba = parse_color(top_color)
    bot_rgba = parse_color(bottom_color)
    key = (width, height, top_rgba, bot_rgba, direction)
    cached = _GRADIENT_CACHE.get(key)
    if cached is not None:
        return cached

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px = img.load()

    if direction == "vertical":
        for y in range(height):
            t = y / max(1, height - 1)
            r = int(top_rgba[0] + (bot_rgba[0] - top_rgba[0]) * t)
            g = int(top_rgba[1] + (bot_rgba[1] - top_rgba[1]) * t)
            b = int(top_rgba[2] + (bot_rgba[2] - top_rgba[2]) * t)
            a = int(top_rgba[3] + (bot_rgba[3] - top_rgba[3]) * t)
            for x in range(width):
                px[x, y] = (r, g, b, a)
    elif direction == "horizontal":
        for x in range(width):
            t = x / max(1, width - 1)
            r = int(top_rgba[0] + (bot_rgba[0] - top_rgba[0]) * t)
            g = int(top_rgba[1] + (bot_rgba[1] - top_rgba[1]) * t)
            b = int(top_rgba[2] + (bot_rgba[2] - top_rgba[2]) * t)
            a = int(top_rgba[3] + (bot_rgba[3] - top_rgba[3]) * t)
            for y in range(height):
                px[x, y] = (r, g, b, a)
    elif direction == "diagonal":
        # Anti-diagonal: t = (x + y) / (w + h - 2)
        denom = max(1, width + height - 2)
        for y in range(height):
            for x in range(width):
                t = (x + y) / denom
                r = int(top_rgba[0] + (bot_rgba[0] - top_rgba[0]) * t)
                g = int(top_rgba[1] + (bot_rgba[1] - top_rgba[1]) * t)
                b = int(top_rgba[2] + (bot_rgba[2] - top_rgba[2]) * t)
                a = int(top_rgba[3] + (bot_rgba[3] - top_rgba[3]) * t)
                px[x, y] = (r, g, b, a)
    else:
        raise ValueError(f"Bad direction: {direction!r}")

    _GRADIENT_CACHE[key] = img
    return img


def make_ctk_gradient(
    width: int,
    height: int,
    top_color,
    bottom_color,
    direction: str = "vertical",
) -> "ctk.CTkImage | None":
    """Create a gradient CTkImage (cached).

    Wraps make_gradient() + converts to CTkImage. CTkImages are cached
    separately from PIL Images so callers don't pay the CTkImage
    construction cost twice.

    Returns None if PIL is missing.
    """
    if not HAS_PIL:
        return None
    pil = make_gradient(width, height, top_color, bottom_color, direction)
    if pil is None:
        return None
    # CTkImage cache key (distinct from PIL cache so we don't re-wrap).
    top_rgba = parse_color(top_color)
    bot_rgba = parse_color(bottom_color)
    key = (width, height, top_rgba, bot_rgba, direction, "ctk")
    cached = _GRADIENT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        ctk_img = ctk.CTkImage(
            light_image=pil, dark_image=pil, size=(width, height)
        )
    except Exception:
        return None
    _GRADIENT_CACHE[key] = ctk_img
    return ctk_img


# ============================================================
# SPARKLINE CACHE
# ============================================================

_SPARKLINE_CACHE: dict[tuple, "Image.Image"] = {}


def make_sparkline(
    data: list[float] | tuple[float, ...],
    width: int = 120,
    height: int = 32,
    line_color="#e0a957",
    fill_color="rgba(224,169,87,0.20)",
    bg_color="rgba(0,0,0,0)",
    show_min_max: bool = False,
    line_width: int = 2,
) -> "Image.Image | None":
    """Render a mini line chart (sparkline) as a PIL Image.

    Args:
        data: list of numeric values (any length ≥ 2). If < 2, returns
            a blank image (the sparkline needs at least 2 points to
            draw a line).
        width, height: pixel dimensions.
        line_color: line stroke color.
        fill_color: fill color UNDER the line (semi-transparent).
        bg_color: background color (transparent by default — the
            sparkline composites onto whatever surface the caller
            places it on).
        show_min_max: if True, draw small filled circles at the min
            and max data points.
        line_width: line stroke width in px.

    Returns:
        PIL.Image (RGBA), or None if PIL missing / data < 2 points.

    Caching:
        Results cached by (tuple(data), width, height, line_color,
        fill_color, bg_color, show_min_max, line_width).
    """
    if not HAS_PIL:
        return None
    if data is None or len(data) < 2:
        return None
    # Normalize to floats + freeze as tuple for hashing.
    try:
        data_t = tuple(float(v) for v in data)
    except (TypeError, ValueError):
        return None

    key = (data_t, width, height, line_color, fill_color, bg_color,
           bool(show_min_max), line_width)
    cached = _SPARKLINE_CACHE.get(key)
    if cached is not None:
        return cached

    img = Image.new("RGBA", (width, height), parse_color(bg_color))
    draw = ImageDraw.Draw(img)

    line_rgba = parse_color(line_color)
    fill_rgba = parse_color(fill_color)

    # Normalize data → pixel coords.
    dmin = min(data_t)
    dmax = max(data_t)
    drange = dmax - dmin
    if drange < 1e-9:
        drange = 1.0  # Avoid divide-by-zero when all values equal.

    # Vertical padding so the line doesn't kiss the edges.
    pad_y = max(2, line_width)
    inner_h = height - 2 * pad_y
    inner_w = width - 2
    n = len(data_t)
    points = []
    for i, v in enumerate(data_t):
        if n == 1:
            x = inner_w // 2
        else:
            x = 2 + int(i * inner_w / (n - 1))
        y = pad_y + int(inner_h * (1 - (v - dmin) / drange))
        points.append((x, y))

    # Fill polygon under the line (semi-transparent).
    if fill_rgba[3] > 0:
        fill_pts = [(points[0][0], height - 1)] + points + \
                   [(points[-1][0], height - 1)]
        try:
            draw.polygon(fill_pts, fill=fill_rgba)
        except Exception:
            pass

    # Line stroke. PIL's draw.line supports width + joint="curve"
    # for smoother lines (Pillow ≥ 5.1).
    try:
        draw.line(points, fill=line_rgba, width=line_width, joint="curve")
    except TypeError:
        # Older Pillow: no joint kwarg.
        draw.line(points, fill=line_rgba, width=line_width)

    # Min/max markers.
    if show_min_max:
        min_idx = data_t.index(dmin)
        max_idx = data_t.index(dmax)
        marker_r = max(2, line_width)
        for idx, rgba in ((min_idx, parse_color("#d63a3f")),
                          (max_idx, line_rgba)):
            x, y = points[idx]
            draw.ellipse(
                [(x - marker_r, y - marker_r),
                 (x + marker_r, y + marker_r)],
                fill=rgba, outline=None,
            )

    _SPARKLINE_CACHE[key] = img
    return img


def make_ctk_sparkline(
    data, width=120, height=32,
    line_color="#e0a957", fill_color="rgba(224,169,87,0.20)",
    bg_color="rgba(0,0,0,0)", show_min_max=False, line_width=2,
):
    """Render a sparkline CTkImage (cached).

    Caches at two levels:
      1. The underlying PIL Image (in _SPARKLINE_CACHE).
      2. The CTkImage wrapping that PIL Image (in _SPARKLINE_CTK_CACHE).
    Two calls with identical args return the SAME CTkImage instance.
    """
    if not HAS_PIL:
        return None
    if data is None or len(data) < 2:
        return None
    try:
        data_t = tuple(float(v) for v in data)
    except (TypeError, ValueError):
        return None
    key = (data_t, width, height, line_color, fill_color, bg_color,
           bool(show_min_max), line_width, "ctk")
    cached = _SPARKLINE_CACHE.get(key)
    if cached is not None:
        return cached
    pil = make_sparkline(
        data, width, height, line_color, fill_color, bg_color,
        show_min_max, line_width,
    )
    if pil is None:
        return None
    try:
        ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil,
                               size=(width, height))
    except Exception:
        return None
    _SPARKLINE_CACHE[key] = ctk_img
    return ctk_img


# ============================================================
# MOMENTUM RING CACHE
# ============================================================

_RING_CACHE: dict[tuple, "Image.Image"] = {}


def make_momentum_ring(
    size: int = 64,
    fill_pct: float = 0.75,
    color="#e0a957",
    bg_color="#2a2f38",
    track_color="rgba(0,0,0,0)",
    thickness: int = 6,
    start_angle: float = -90.0,
) -> "Image.Image | None":
    """Render a circular ring that fills clockwise by `fill_pct`.

    Args:
        size: pixel width=height of the square image.
        fill_pct: 0.0-1.0. Fraction of the ring that's filled.
        color: the fill color (the filled arc).
        bg_color: the unfilled track color (visible where the ring
            isn't filled).
        track_color: optional transparent halo behind the ring
            (rarely used — pass transparent to skip).
        thickness: ring stroke thickness in px.
        start_angle: degrees, -90 = top of circle. The arc fills
            clockwise from this angle.

    Returns:
        PIL.Image (RGBA), or None if PIL missing.

    Notes:
        Anti-aliased via supersampling 4× + LANCZOS downsample. The
        supersampling is the same trick used by gym_icon.py for the
        octagonal icons.
    """
    if not HAS_PIL:
        return None
    fill_pct = max(0.0, min(1.0, float(fill_pct)))
    key = (size, round(fill_pct, 4), color, bg_color, track_color,
           thickness, start_angle)
    cached = _RING_CACHE.get(key)
    if cached is not None:
        return cached

    # 4× supersample for anti-aliasing.
    ss = 4
    big = size * ss
    big_thick = thickness * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Bounding box for the ring (centered, accounting for thickness).
    margin = big_thick // 2 + 1
    bbox = [margin, margin, big - margin - 1, big - margin - 1]

    # Track (unfilled portion).
    track_rgba = parse_color(bg_color)
    if track_rgba[3] > 0:
        draw.arc(bbox, start=0, end=360, fill=track_rgba, width=big_thick)

    # Filled arc — clockwise from start_angle.
    if fill_pct > 0:
        fill_rgba = parse_color(color)
        sweep = 360.0 * fill_pct
        end_angle = start_angle + sweep
        draw.arc(bbox, start=start_angle, end=end_angle,
                 fill=fill_rgba, width=big_thick)

    # Downsample.
    img = img.resize((size, size), Image.LANCZOS)

    _RING_CACHE[key] = img
    return img


def make_ctk_momentum_ring(
    size=64, fill_pct=0.75, color="#e0a957", bg_color="#2a2f38",
    track_color="rgba(0,0,0,0)", thickness=6, start_angle=-90.0,
):
    """Render a momentum ring CTkImage (cached).

    Caches at two levels: the PIL Image (in _RING_CACHE) and the
    CTkImage wrapper (also in _RING_CACHE, with a "ctk" suffix).
    """
    if not HAS_PIL:
        return None
    fill_pct_clamped = max(0.0, min(1.0, float(fill_pct)))
    key = (size, round(fill_pct_clamped, 4), color, bg_color, track_color,
           thickness, start_angle, "ctk")
    cached = _RING_CACHE.get(key)
    if cached is not None:
        return cached
    pil = make_momentum_ring(
        size, fill_pct, color, bg_color, track_color,
        thickness, start_angle,
    )
    if pil is None:
        return None
    try:
        ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil,
                               size=(size, size))
    except Exception:
        return None
    _RING_CACHE[key] = ctk_img
    return ctk_img


# ============================================================
# FORM-METER BLOCK CACHE
# ============================================================

_FORM_BLOCK_CACHE: dict[tuple, "Image.Image"] = {}


def make_form_block(
    size: int = 24,
    color: str = "#e0a957",
    border_color: str = "rgba(0,0,0,0)",
    border_width: int = 0,
    radius: int = 3,
) -> "Image.Image | None":
    """Render a single rounded-rect block for the FormMeter.

    Args:
        size: pixel width=height of the square block.
        color: fill color.
        border_color: optional border.
        border_width: border thickness in px.
        radius: corner radius in px.

    Returns:
        PIL.Image (RGBA), or None if PIL missing.
    """
    if not HAS_PIL:
        return None
    key = (size, color, border_color, border_width, radius)
    cached = _FORM_BLOCK_CACHE.get(key)
    if cached is not None:
        return cached

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill_rgba = parse_color(color)
    # Rounded-rect via rounded_rectangle (Pillow ≥ 5.3).
    bbox = [0, 0, size - 1, size - 1]
    try:
        draw.rounded_rectangle(
            bbox, radius=radius, fill=fill_rgba,
            outline=parse_color(border_color) if border_color else None,
            width=border_width if border_color else 0,
        )
    except AttributeError:
        # Pillow < 5.3 — fall back to plain rectangle.
        draw.rectangle(bbox, fill=fill_rgba)

    _FORM_BLOCK_CACHE[key] = img
    return img


def make_ctk_form_block(size=24, color="#e0a957",
                        border_color="rgba(0,0,0,0)", border_width=0,
                        radius=3):
    """Render a single form-meter block as a CTkImage (cached).

    Caches at two levels: the PIL Image (in _FORM_BLOCK_CACHE) and
    the CTkImage wrapper (also in _FORM_BLOCK_CACHE, with "ctk" suffix).
    """
    if not HAS_PIL:
        return None
    key = (size, color, border_color, border_width, radius, "ctk")
    cached = _FORM_BLOCK_CACHE.get(key)
    if cached is not None:
        return cached
    pil = make_form_block(size, color, border_color, border_width, radius)
    if pil is None:
        return None
    try:
        ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil,
                               size=(size, size))
    except Exception:
        return None
    _FORM_BLOCK_CACHE[key] = ctk_img
    return ctk_img


# ============================================================
# CACHE STATS (for smoke test + worklog)
# ============================================================

def cache_stats() -> dict[str, int]:
    """Return counts of cached entries per primitive.

    Used by the smoke test to verify the cache is actually populated.
    """
    return {
        "gradient": len(_GRADIENT_CACHE),
        "sparkline": len(_SPARKLINE_CACHE),
        "ring": len(_RING_CACHE),
        "form_block": len(_FORM_BLOCK_CACHE),
    }


def clear_caches() -> None:
    """Clear all PIL caches. Mainly for tests."""
    _GRADIENT_CACHE.clear()
    _SPARKLINE_CACHE.clear()
    _RING_CACHE.clear()
    _FORM_BLOCK_CACHE.clear()
