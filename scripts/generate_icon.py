"""Generate the CARE app icon and README banner.

Produces a multi-resolution .ico, a 256×256 PNG, a 512×512 @2x PNG,
a macOS .icns, and a 1280×320 README banner from a single
procedurally-drawn master at 1024×1024. Re-runnable; output paths
are fixed so re-runs overwrite cleanly.

Concept
-------
Rounded-square (macOS-convention) app mark in deep navy. Bold
geometric **C** on the left, **amber redaction bar** extending to
its right. Reads as "C[REDACTED]" — the brand letter + the function
the engine performs, in one mark.

Why no shield / document / road glyph? Those skew toward "generic
gov-tech" and don't survive at 16×16. The C+bar combination is
sharply distinct at every size and ties the icon to both the brand
acronym and the redaction guarantee.

Palette
-------
- Background: ``#0F172A`` (Tailwind slate-900) — serious, sober.
- C mark:     ``#FFFFFF``                       — high contrast.
- Bar:        ``#F59E0B`` (Tailwind amber-500)  — caution / safety,
              fits the transportation domain without being literal.

Run
---
    uv run python scripts/generate_icon.py

The script is idempotent and has no network calls.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "assets"

MASTER_SIZE = 1024

NAVY = (15, 23, 42, 255)
NAVY_TOP = (23, 33, 56, 255)        # very subtle gradient top stop
SLATE_300 = (203, 213, 225, 255)    # banner subtitle
SLATE_400 = (148, 163, 184, 255)    # banner tertiary
WHITE = (255, 255, 255, 255)
AMBER = (245, 158, 11, 255)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Sizes packed into the multi-resolution .ico. Windows asks for the
# size that best matches the dpi-scaled UI element it's rendering in
# (16 in the taskbar small icons, 256 on the desktop, etc.). Shipping
# all of them avoids any blur.
ICO_SIZES = [16, 32, 48, 64, 128, 256]


def _rounded_square(canvas_size: int, radius_frac: float, fill) -> Image.Image:
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    radius = int(canvas_size * radius_frac)
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, canvas_size, canvas_size), radius=radius, fill=fill
    )
    return img


def _draw_c(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Bold geometric C, left-of-centre to leave room for the bar.

    PIL angles: 0° points east; increasing clockwise. We draw an arc
    from 38° (~5 o'clock) clockwise to 322° (~7 o'clock the long way
    round), leaving a 76° gap on the right — the C's mouth.
    """
    cx = int(size * 0.38)
    cy = size // 2
    outer = int(size * 0.31)
    stroke = int(size * 0.135)
    bbox = [
        (cx - outer + stroke // 2, cy - outer + stroke // 2),
        (cx + outer - stroke // 2, cy + outer - stroke // 2),
    ]
    draw.arc(bbox, start=38, end=322, fill=WHITE, width=stroke)


def _draw_redaction_bar(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Amber redaction bar — reads as [REDACTED] continuing the C.

    The bar's left edge sits *inside* the C's mouth so the two glyphs
    visually couple instead of drifting apart at small sizes. Height
    matches the C's stroke (≈13.5% of canvas) so the two read as one
    typographic line at any zoom.
    """
    bar_h = int(size * 0.135)
    bar_w = int(size * 0.42)
    left = int(size * 0.44)
    top = (size - bar_h) // 2
    radius = bar_h // 2  # pill, not a bare rectangle
    draw.rounded_rectangle(
        (left, top, left + bar_w, top + bar_h),
        radius=radius,
        fill=AMBER,
    )


def _add_top_sheen(base: Image.Image) -> Image.Image:
    """Faint white gradient across the top third — premium-app feel.

    Done as a separate alpha-composited layer so the highlight stays
    clipped to the rounded-square footprint via the base alpha.
    """
    size = base.size[0]
    sheen = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sheen_draw = ImageDraw.Draw(sheen)
    band_h = size // 3
    for y in range(band_h):
        alpha = int(36 * (1 - y / band_h))  # peak ~36/255 at top
        sheen_draw.line(((0, y), (size, y)), fill=(255, 255, 255, alpha))
    # Clip the sheen to the rounded square: where the base is opaque,
    # the sheen contributes; elsewhere it's invisible.
    base_alpha = base.getchannel("A")
    sheen_alpha = sheen.getchannel("A")
    clipped_alpha = Image.eval(
        Image.merge("LA", (sheen_alpha, base_alpha)).getchannel("A"),
        lambda v: v,
    )
    # Multiply: sheen's own alpha × base's alpha.
    new_alpha = Image.new("L", base.size, 0)
    new_alpha.paste(
        Image.eval(sheen_alpha, lambda v: v),
        mask=base_alpha,
    )
    sheen.putalpha(new_alpha)
    out = base.copy()
    out.alpha_composite(sheen)
    return out


def build_master() -> Image.Image:
    base = _rounded_square(MASTER_SIZE, 0.22, NAVY)
    base = _add_top_sheen(base)
    draw = ImageDraw.Draw(base)
    _draw_c(draw, MASTER_SIZE)
    _draw_redaction_bar(draw, MASTER_SIZE)
    return base


def _vertical_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    """Top-to-bottom linear gradient as an RGBA image."""
    w, h = size
    img = Image.new("RGBA", size, top)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(4))
        draw.line(((0, y), (w, y)), fill=c)
    return img


def build_banner(icon_master: Image.Image) -> Image.Image:
    """1280×320 README hero banner.

    Layout:
        [icon 220px]   CARE                         (96pt bold white)
                       ──── (amber underline)
                       Crash Analysis & Redaction Engine   (32pt slate)
                       Offline-first · Fail-closed · Plugin-based  (20pt slate-400)

    The amber underline echoes the redaction bar from the icon,
    keeping the icon and wordmark visually unified.
    """
    W, H = 1280, 320
    bg = _vertical_gradient((W, H), NAVY_TOP, NAVY)

    # Icon on the left, vertically centred.
    icon_size = 220
    icon = icon_master.resize((icon_size, icon_size), Image.LANCZOS)
    icon_x = 64
    icon_y = (H - icon_size) // 2
    bg.alpha_composite(icon, (icon_x, icon_y))

    draw = ImageDraw.Draw(bg)

    # Wordmark
    text_x = icon_x + icon_size + 56
    title_font = ImageFont.truetype(FONT_BOLD, 96)
    sub_font = ImageFont.truetype(FONT_REG, 32)
    foot_font = ImageFont.truetype(FONT_REG, 20)

    # CARE — bold, tight tracking
    title_y = 70
    draw.text((text_x, title_y), "CARE", font=title_font, fill=WHITE)

    # Amber underline — matches the icon's redaction bar in spirit.
    # Width: span of "CARE" only; height: 8px; sits 12px below the title.
    title_bbox = draw.textbbox((text_x, title_y), "CARE", font=title_font)
    bar_top = title_bbox[3] + 14
    bar_bottom = bar_top + 8
    bar_left = title_bbox[0]
    bar_right = title_bbox[2]
    draw.rounded_rectangle(
        (bar_left, bar_top, bar_right, bar_bottom),
        radius=4,
        fill=AMBER,
    )

    # Subtitle — the full expansion of the acronym
    sub_y = bar_bottom + 22
    draw.text(
        (text_x, sub_y),
        "Crash Analysis & Redaction Engine",
        font=sub_font,
        fill=SLATE_300,
    )

    # Tertiary line — three load-bearing project values
    foot_y = sub_y + 52
    draw.text(
        (text_x, foot_y),
        "Offline-first  ·  Fail-closed  ·  Plugin-based",
        font=foot_font,
        fill=SLATE_400,
    )

    return bg


def build_social_card(icon_master: Image.Image) -> Image.Image:
    """1280×640 GitHub social-preview card.

    Sized for the og:image consumed by Twitter / LinkedIn / Slack
    link previews. Layout: icon left, wordmark + amber underline +
    subtitle + footer line stacked vertically and centred as a single
    block. Font sizes are tuned so the longest line (the subtitle)
    fits inside the right gutter without clipping.
    """
    W, H = 1280, 640
    bg = _vertical_gradient((W, H), NAVY_TOP, NAVY)

    icon_size = 300
    icon = icon_master.resize((icon_size, icon_size), Image.LANCZOS)
    icon_x = 96
    icon_y = (H - icon_size) // 2
    bg.alpha_composite(icon, (icon_x, icon_y))

    draw = ImageDraw.Draw(bg)
    text_x = icon_x + icon_size + 64
    right_margin = 64
    available_w = W - text_x - right_margin

    title_font = ImageFont.truetype(FONT_BOLD, 132)
    foot_font = ImageFont.truetype(FONT_REG, 26)

    # Pick the largest subtitle size that still fits in `available_w`.
    # 33-char string is right at the edge of the gutter at 44pt; step
    # down until textbbox reports a width that fits.
    subtitle = "Crash Analysis & Redaction Engine"
    sub_font: ImageFont.FreeTypeFont = ImageFont.truetype(FONT_REG, 38)
    for size in (42, 40, 38, 36, 34):
        candidate = ImageFont.truetype(FONT_REG, size)
        bbox = draw.textbbox((0, 0), subtitle, font=candidate)
        if bbox[2] - bbox[0] <= available_w:
            sub_font = candidate
            break

    # Measure the full text block first, then position it so the block
    # is vertically centred within the canvas — keeps the icon and the
    # wordmark visually balanced.
    title_bbox = draw.textbbox((0, 0), "CARE", font=title_font)
    title_h = title_bbox[3] - title_bbox[1]
    underline_gap = 16
    underline_h = 12
    sub_gap = 30
    sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
    sub_h = sub_bbox[3] - sub_bbox[1]
    foot_gap = 28
    foot_bbox = draw.textbbox(
        (0, 0),
        "Offline-first  ·  Fail-closed  ·  Plugin-based",
        font=foot_font,
    )
    foot_h = foot_bbox[3] - foot_bbox[1]

    block_h = title_h + underline_gap + underline_h + sub_gap + sub_h + foot_gap + foot_h
    title_y = (H - block_h) // 2 - title_bbox[1]

    draw.text((text_x, title_y), "CARE", font=title_font, fill=WHITE)
    rendered_title_bbox = draw.textbbox((text_x, title_y), "CARE", font=title_font)
    bar_top = rendered_title_bbox[3] + underline_gap
    bar_bottom = bar_top + underline_h
    draw.rounded_rectangle(
        (rendered_title_bbox[0], bar_top, rendered_title_bbox[2], bar_bottom),
        radius=6,
        fill=AMBER,
    )

    sub_y = bar_bottom + sub_gap
    draw.text((text_x, sub_y), subtitle, font=sub_font, fill=SLATE_300)
    rendered_sub_bbox = draw.textbbox((text_x, sub_y), subtitle, font=sub_font)

    foot_y = rendered_sub_bbox[3] + foot_gap
    draw.text(
        (text_x, foot_y),
        "Offline-first  ·  Fail-closed  ·  Plugin-based",
        font=foot_font,
        fill=SLATE_400,
    )

    return bg


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = build_master()

    icon_png = ASSETS / "icon.png"
    icon_2x = ASSETS / "icon@2x.png"
    icon_ico = ASSETS / "icon.ico"
    icon_icns = ASSETS / "icon.icns"
    banner_png = ASSETS / "banner.png"
    social_png = ASSETS / "social-card.png"

    master.resize((256, 256), Image.LANCZOS).save(icon_png, "PNG", optimize=True)
    master.resize((512, 512), Image.LANCZOS).save(icon_2x, "PNG", optimize=True)

    # Multi-resolution Windows .ico
    master.save(icon_ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES])

    # macOS .icns — Pillow ships an ICNS encoder; 512 is plenty.
    master.resize((512, 512), Image.LANCZOS).save(icon_icns, format="ICNS")

    # README hero banner (1280×320 → renders well at GitHub's standard
    # ~1012px content width).
    build_banner(master).save(banner_png, "PNG", optimize=True)

    # GitHub social-preview card (1280×640 — what's pulled into Twitter
    # / LinkedIn / Slack link previews via the og:image meta tag).
    build_social_card(master).save(social_png, "PNG", optimize=True)

    print("wrote:")
    for p in (icon_png, icon_2x, icon_ico, icon_icns, banner_png, social_png):
        print(f"  {p.relative_to(REPO_ROOT)}  ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
