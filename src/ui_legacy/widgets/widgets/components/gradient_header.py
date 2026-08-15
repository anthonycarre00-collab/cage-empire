"""CAGE EMPIRE — Phase 2 Component Library: GradientHeader (§5.24).

A PIL-gradient banner for screen H1 titles.

CRITICAL FIX (Claude's root-cause analysis, Task CTk-TRANSPARENCY-FIX):
CustomTkinter's fg_color="transparent" is NOT real transparency. CTkFrame._draw()
always paints an opaque rectangle, even when fg_color="transparent". The prior
version placed a "transparent" CTkFrame on top of the gradient image, which
painted a solid dark rectangle over the gold gradient, making it invisible.

This version bakes EVERYTHING (gradient + chain-link texture + logo + title
text + subtitle text) into ONE PIL bitmap, displayed by a single CTkLabel.
No overlay frame. No CTkFrame on top. Nothing to paint over the gradient.

The title/subtitle text is rendered directly into the PIL image using PIL's
ImageDraw.text() with the bundled Oswald font (or fallback). This means:
- The gradient IS visible (gold fading to dark)
- The chain-link cage motif IS visible (overlaid on the gradient)
- The title text IS visible (rendered on top of the gradient in the image)
- No CTkFrame can paint over it because there IS no CTkFrame overlay

Trade-off: the title/subtitle text is baked into the image, so it can't be
updated dynamically via configure(). To change the title, call set_title()
which regenerates the image. This is fine for screen headers (they change
rarely — only on navigation or Advance Day).
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_XL, SPACE_LG, SPACE_SM

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Import the gradient + chain-link helpers
from ._pil_utils import make_gradient
from ui.theme import FONT_OSWALD_BOLD, FONT_INTER_SEMIBOLD, FONTS_DIR

_HEADER_HEIGHT = 64
_GRADIENT_W = 1920  # wide enough for most screens; CTkImage scales it


def _resolve_variant(variant, theme, top_color=None, bottom_color=None):
    """Resolve variant name to (top_color, bottom_color, text_color, sub_color)."""
    if variant == "gold":
        return (
            top_color or theme.colors.gold,
            bottom_color or theme.colors.bg_base,
            theme.colors.text_on_gold if hasattr(theme.colors, 'text_on_gold') else "#1a1410",
            "#3a2810",
        )
    elif variant == "crimson":
        return (
            top_color or theme.colors.crimson,
            bottom_color or theme.colors.bg_base,
            "#ffffff",
            "#f5d0d0",
        )
    elif variant == "steel":
        return (
            top_color or theme.colors.bg_card_elevated,
            bottom_color or theme.colors.bg_base,
            theme.colors.text_primary,
            theme.colors.text_secondary,
        )
    else:  # custom
        return (
            top_color or theme.colors.gold,
            bottom_color or theme.colors.bg_base,
            "#1a1410",
            "#3a2810",
        )


def _hex_to_rgb(h):
    """Convert #rrggbb to (r, g, b) tuple."""
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _composite_chain_link(base_img, opacity=0.12):
    """Overlay a subtle chain-link pattern on the right half of the image."""
    try:
        from ui.theme import get_chain_link_dim_texture
        # Get the raw PIL image from the texture
        chain_ctk = get_chain_link_dim_texture()
        if chain_ctk is None:
            return base_img
        chain_pil = chain_ctk._light_image if hasattr(chain_ctk, '_light_image') else None
        if chain_pil is None:
            return base_img
        # Crop chain-link to right half of the base image
        w, h = base_img.size
        right_half = chain_pil.resize((w // 2, h), Image.LANCZOS)
        # Composite with opacity
        alpha = int(255 * opacity)
        overlay = Image.new("RGBA", (w // 2, h), (0, 0, 0, 0))
        # Blend the chain-link onto the overlay
        for x in range(0, w // 2, 2):
            for y in range(0, h, 2):
                px = right_half.getpixel((x, y))
                if len(px) == 4 and px[3] > 0:
                    overlay.putpixel((x, y), (px[0], px[1], px[2], min(alpha, px[3])))
        base_img.alpha_composite(overlay, (w // 2, 0))
        return base_img
    except Exception:
        return base_img


def _load_font(path, size):
    """Load a TTF font, falling back to default."""
    try:
        if path and path.exists():
            return ImageFont.truetype(str(path), size)
    except Exception:
        pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


class GradientHeader(ctk.CTkLabel):
    """A gradient banner with baked-in title text.

    Uses Claude's fix: everything is composited into one PIL image,
    displayed by a single CTkLabel. No CTkFrame overlay that could
    paint over the gradient.

    Args:
        parent: parent widget.
        title: the screen title text. Will be uppercased.
        subtitle: optional subtitle text.
        variant: "gold" | "crimson" | "steel" | "custom". Default "gold".
        height: banner height in px. Default 64.
        show_cage_motif: bool (default True) — overlay chain-link on right half.
        show_logo: bool (default False) — show compact logo on left.
    """

    def __init__(self, parent, title="", subtitle=None, variant="gold",
                 top_color=None, bottom_color=None, height=_HEADER_HEIGHT,
                 show_cage_motif=True, show_logo=False, **kwargs):
        self._title = title
        self._subtitle = subtitle
        self._variant = variant
        self._top_color = top_color
        self._bottom_color = bottom_color
        self._height = height
        self._show_cage_motif = show_cage_motif
        self._show_logo = show_logo

        theme = get_theme()
        self._theme = theme
        top, bot, text_color, sub_color = _resolve_variant(
            variant, theme, top_color, bottom_color)
        self._text_color = text_color
        self._sub_color = sub_color

        # Generate the baked image
        img = self._bake_image()

        # Display as a single CTkLabel — no CTkFrame overlay
        super().__init__(
            parent, image=img, text="",
            fg_color="transparent",
            anchor="w",
            **kwargs,
        )
        # Store for reference
        self._ctk_image = img

    def _bake_image(self):
        """Composite gradient + chain-link + logo + title + subtitle into one PIL image."""
        if not HAS_PIL:
            # No PIL — can't generate gradient. Return None (label shows nothing).
            return None

        try:
            theme = self._theme
            top, bot, text_color, sub_color = _resolve_variant(
                self._variant, theme, self._top_color, self._bottom_color)

            # 1. Create the gradient base
            pil_img = make_gradient(
                _GRADIENT_W, self._height,
                _hex_to_rgb(top) + (255,),
                _hex_to_rgb(bot) + (255,),
                direction="horizontal",
            )
            if pil_img is None:
                return None

            # Ensure RGBA mode
            if pil_img.mode != "RGBA":
                pil_img = pil_img.convert("RGBA")

            # 2. Composite chain-link cage motif on right half
            if self._show_cage_motif:
                pil_img = _composite_chain_link(pil_img, opacity=0.12)

            # 3. Draw the title text directly onto the image
            draw = ImageDraw.Draw(pil_img)

            # Load fonts
            title_font = _load_font(FONT_OSWALD_BOLD, 28)
            sub_font = _load_font(FONT_INTER_SEMIBOLD, 14)

            # Draw title (left-aligned, vertically centered)
            title_text = (self._title or "").upper()
            title_color_rgb = _hex_to_rgb(text_color) + (255,)

            # Calculate vertical centering
            if title_font:
                try:
                    bbox = draw.textbbox((0, 0), title_text, font=title_font)
                    text_h = bbox[3] - bbox[1]
                    text_y = (self._height - text_h) // 2 - bbox[1]
                except Exception:
                    text_y = self._height // 2 - 14
            else:
                text_y = self._height // 2 - 8

            # Left padding (more if logo is shown)
            x_pad = 60 if self._show_logo else 24
            draw.text((x_pad, text_y), title_text, fill=title_color_rgb,
                      font=title_font)

            # 4. Draw subtitle (right-aligned)
            if self._subtitle:
                sub_text = str(self._subtitle).upper()
                sub_color_rgb = _hex_to_rgb(sub_color) + (255,)

                if sub_font:
                    try:
                        bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
                        sub_w = bbox[2] - bbox[0]
                        sub_h = bbox[3] - bbox[1]
                        sub_y = (self._height - sub_h) // 2 - bbox[1]
                    except Exception:
                        sub_y = self._height // 2 - 7
                else:
                    sub_y = self._height // 2 - 7

                sub_x = _GRADIENT_W - sub_w - 24 if sub_font else _GRADIENT_W - 200
                draw.text((sub_x, sub_y), sub_text, fill=sub_color_rgb,
                          font=sub_font)

            # 5. Optional logo on the left
            if self._show_logo:
                try:
                    from ui.theme import LOGO_COMPACT
                    if LOGO_COMPACT.exists():
                        logo = Image.open(str(LOGO_COMPACT)).convert("RGBA")
                        logo = logo.resize((32, 32), Image.LANCZOS)
                        pil_img.alpha_composite(logo, (16, (self._height - 32) // 2))
                except Exception:
                    pass

            # Convert to CTkImage
            return ctk.CTkImage(
                light_image=pil_img, dark_image=pil_img,
                size=(_GRADIENT_W, self._height),
            )
        except Exception as e:
            print(f"[GradientHeader] _bake_image failed: {e}", flush=True)
            return None

    def set_title(self, title):
        """Regenerate the image with a new title."""
        self._title = title
        img = self._bake_image()
        if img is not None:
            self.configure(image=img)
            self._ctk_image = img

    def set_subtitle(self, subtitle):
        """Regenerate the image with a new subtitle."""
        self._subtitle = subtitle
        img = self._bake_image()
        if img is not None:
            self.configure(image=img)
            self._ctk_image = img
