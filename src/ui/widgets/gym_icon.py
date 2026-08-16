"""CAGE EMPIRE — Gym icon widget (UI Fix Plan 2 — Phase 3, Fix 17).

Procedurally generates octagonal gym icons on-demand. Per AD-4 in
docs/UI_FIX_PLAN_2.md:

  300 gyms → procedurally generated via PIL. Octagonal shape
  (matches CAGE EMPIRE brand), deterministic color from gym_id
  hash, white initials. NOT image-gen (would take 5+ hours,
  inconsistent, illegible at 24×24).

CONVENTIONS compliance:
  §13 — Design Law: the octagonal shape echoes the CAGE EMPIRE
        brand (the cage is octagonal). The 8-color palette is drawn
        from the Office theme so the icons feel branded.
  §17 — UI Snapshot Rule: this module reads nothing from the DB.
        Callers pass (gym_id, gym_name, size); the module returns a
        CTkImage. The gym_id + gym_name come from game state (gyms
        table — names are OK per §14).

Architecture:
  - get_gym_icon(gym_id, gym_name, size=24) → CTkImage
  - Procedurally generates a PIL image with:
      * Octagonal mask (clips the colored background to the octagon)
      * Solid color background (deterministic from gym_id hash)
      * White initials centered (first letters of gym_name words,
        up to 2 chars)
  - Cached in module-level dict _ICON_CACHE[(gym_id, size)] →
    CTkImage. Subsequent calls return the cached image (avoids
    re-rendering for the same gym on every screen refresh).
  - 8-color palette (crimson, gold, steel, success, warning, danger,
    + blue + purple for variety). The gym_id hash picks one
    deterministically.

DESIGN DECISIONS (D-numbers):
  D1  Octagonal shape. The CAGE EMPIRE brand is built around the
      octagonal MMA cage. Every gym icon uses an octagonal mask
      so the icons feel branded + visually consistent (vs. circle
      or square which would feel generic).
  D2  Deterministic color via hash(gym_id). The same gym always
      gets the same color across refreshes (no flickering). The
      hash is taken modulo len(_PALETTE) so it lands in the palette
      range.
  D3  8-color palette. 6 colors from the Office theme (crimson,
      gold, steel, success, warning, danger) + 2 extra (blue +
      purple) for variety. Each color is dark enough that white
      initials read clearly on top. The palette is intentionally
      limited (8 colors) so the gym list looks cohesive — using
      the full RGB spectrum would look like a Jackson Pollock
      painting.
  D4  White initials. The first letters of each word in the gym
      name, up to 2 chars. "Alpha Combat Gym" → "AC". "Jackson's
      MMA" → "JM". "The Lab" → "TL". Falls back to "?" if the name
      is empty.
  D5  Module-level cache. _ICON_CACHE[(gym_id, size)] → CTkImage.
      The cache survives for the lifetime of the process. There's
      no eviction — 300 gyms × 1 size = 300 entries, which is
      trivial memory-wise (each CTkImage is ~1KB at 24×24).
  D6  PIL fallback. If PIL isn't installed, get_gym_icon returns
      None. Callers should fall back to a plain text label (the
      gym name without an icon).
  D7  Anti-aliased rendering. The octagon is drawn at 4x the
      target size + downsampled via LANCZOS so the edges are
      smooth (not pixelated). This is the same trick the portrait
      placeholder uses for the initials text.
"""

import hashlib

import customtkinter as ctk

# PIL is used for the procedural icon generation. Falls back
# gracefully if PIL isn't installed (callers get None + show a plain
# text label instead).
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from ui.theme import FONT_INTER_BOLD


# ============================================================
# COLOR PALETTE (D3)
# ============================================================
# 8 colors drawn from the Office theme + 2 extras for variety. Each
# color is dark enough that white initials read clearly on top. The
# hex strings are in PIL-friendly format (no alpha — the alpha comes
# from the octagonal mask).
_PALETTE = [
    "#c8323a",  # crimson
    "#d4a55a",  # gold
    "#6b7280",  # steel
    "#4ade80",  # success
    "#fbbf24",  # warning
    "#ef4444",  # danger
    "#3b82f6",  # blue
    "#a855f7",  # purple
]


# ============================================================
# CACHE (D5)
# ============================================================
# Maps (gym_id, size) → CTkImage. Survives for the process lifetime.
# 300 gyms × 1 size = 300 entries × ~1KB each = ~300KB total — trivial.
_ICON_CACHE = {}


# ============================================================
# PUBLIC API
# ============================================================

def get_gym_icon(gym_id, gym_name, size=24):
    """Return a CTkImage for the gym, generating it if needed (D5).

    Args:
        gym_id: int — the gym_id from the DB. Used for the
            deterministic color hash + the cache key.
        gym_name: str — the gym name. Used to compute the initials.
        size: int — target icon size in px (default 24). The icon
            is rendered at 4x + downsampled for anti-aliasing.

    Returns:
        ctk.CTkImage, or None if PIL isn't installed (D6). Callers
        should fall back to a plain text label in that case.
    """
    if not HAS_PIL:
        return None

    # Normalize gym_id to int (defensive — some callers may pass a
    # string from a row tuple).
    try:
        gym_id_int = int(gym_id) if gym_id is not None else 0
    except (TypeError, ValueError):
        gym_id_int = 0

    cache_key = (gym_id_int, size)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    # Generate the PIL image.
    pil_img = _generate_gym_image(gym_id_int, gym_name, size)
    if pil_img is None:
        return None

    # Wrap in CTkImage + cache.
    ctk_img = ctk.CTkImage(
        light_image=pil_img, dark_image=pil_img,
        size=(size, size),
    )
    _ICON_CACHE[cache_key] = ctk_img
    return ctk_img


# ============================================================
# PROCEDURAL GENERATION
# ============================================================

def _generate_gym_image(gym_id, gym_name, size):
    """Generate the octagonal gym icon as a PIL RGBA image (D1, D7).

    Renders at 4x the target size + downsamples via LANCZOS for
    anti-aliased edges. Returns the final size×size RGBA image.
    """
    if not HAS_PIL:
        return None

    # Render at 4x for anti-aliasing.
    render_size = max(size * 4, 64)
    img = Image.new("RGBA", (render_size, render_size),
                    (0, 0, 0, 0))  # transparent background
    draw = ImageDraw.Draw(img)

    # Pick the color (D2 + D3).
    color_hex = _pick_color(gym_id)
    fill_rgb = _hex_to_rgb(color_hex)

    # Draw the octagonal mask (D1). The octagon is inscribed in the
    # square — we cut the 4 corners by 25% of the side length.
    # Octagon points (clockwise from top-left of top edge):
    #   cut = side * 0.25
    #   (cut, 0) (side-cut, 0) (side, cut) (side, side-cut)
    #   (side-cut, side) (cut, side) (0, side-cut) (0, cut)
    cut = int(render_size * 0.25)
    side = render_size
    octagon_points = [
        (cut, 0),
        (side - cut, 0),
        (side, cut),
        (side, side - cut),
        (side - cut, side),
        (cut, side),
        (0, side - cut),
        (0, cut),
    ]
    draw.polygon(octagon_points, fill=fill_rgb + (255,))

    # Draw the initials (D4). White, centered, large.
    initials = _compute_initials(gym_name)
    font_size = int(render_size * 0.45)
    font = _load_font(font_size)
    if font is not None:
        try:
            # Center the text via textbbox.
            bbox = draw.textbbox((0, 0), initials, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (render_size - text_w) // 2 - bbox[0]
            y = (render_size - text_h) // 2 - bbox[1]
            draw.text((x, y), initials, fill="white", font=font)
        except Exception:
            # Fallback — draw the initials at a fixed position.
            try:
                draw.text((render_size // 4, render_size // 4),
                          initials, fill="white", font=font)
            except Exception:
                pass

    # Downsample to the target size (D7).
    img = img.resize((size, size), Image.LANCZOS)
    return img


def _pick_color(gym_id):
    """Pick a deterministic palette color for the gym_id (D2)."""
    # Use a stable hash (md5 of the string form) so the same gym_id
    # always maps to the same color. Python's built-in hash() is
    # randomized per-process (PYTHONHASHSEED) so it would produce
    # different colors across runs — md5 is deterministic.
    h = hashlib.md5(str(gym_id).encode("utf-8")).hexdigest()
    # Take the first 8 hex chars (32 bits) + modulo palette length.
    idx = int(h[:8], 16) % len(_PALETTE)
    return _PALETTE[idx]


def _hex_to_rgb(hex_str):
    """Convert a #RRGGBB hex string to an (R, G, B) tuple."""
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _compute_initials(gym_name):
    """Compute up to 2-letter initials from a gym name (D4).

    "Alpha Combat Gym" → "AC". "Jackson's MMA" → "JM". "The Lab" →
    "TL". Falls back to "?" if the name is empty.
    """
    if not gym_name:
        return "?"
    words = str(gym_name).strip().split()
    if not words:
        return "?"
    # Take the first letter of each of the first 2 words.
    initials = "".join(w[0].upper() for w in words[:2] if w)
    return initials or "?"


def _load_font(size):
    """Load the bundled Inter Bold font at the requested size.

    Falls back to PIL's default bitmap font if the bundled TTF isn't
    available (D6 — defensive against missing asset files).
    """
    try:
        if FONT_INTER_BOLD.exists():
            return ImageFont.truetype(str(FONT_INTER_BOLD), size)
    except Exception:
        pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


# ============================================================
# CACHE MANAGEMENT — for tests / theme changes
# ============================================================

def clear_gym_icon_cache():
    """Clear the module-level icon cache.

    Called by tests that need to verify the procedural generation
    (the cache would otherwise mask bugs). Not called by production
    code — the cache is meant to be process-lifetime.
    """
    global _ICON_CACHE
    _ICON_CACHE = {}
