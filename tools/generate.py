#!/usr/bin/env python3
"""
Regenerate every colour / background asset for the Lumen rEFInd theme.

A "look" here is a **colour** x a **background**:

  * colour     — white (default) + green red pink blue
                 + premium iridescent obsidian-purple / champagne-gold
                 + premium gradient aurora / cyberpunk / platinum
                 — dark-background pieces
  * background — dark (black, default) or light (near-white)

Icons render white on the dark background (dark ink on the light one),
tinted toward the variant's own colour (ICON_TINT_MIX_SIMPLE / _PREMIUM) so
they read as the same palette as the selection graphic without becoming a
fully coloured icon. PREMIUM/GRADIENT get a much stronger tint than SIMPLE —
the selection ring already sells "premium" through full-saturation stroke +
hot core + halo + bloom, and a SIMPLE-strength wash on the icon next to that
just read as a plain pale colour, not the same finish. Every icon also bakes in a faint glass card: a barely-visible outline
plus an even fainter interior wash (see CARD_BORDER_ALPHA / CARD_FILL_ALPHA),
since rEFInd has no notion of an "unselected" graphic to draw it separately.
The OS row's card is a rounded square, the func_/tool_ row's a circle (see
SPECS) — otherwise identical treatment. The one focused entry also gets a
*partial light* traced on that exact same card perimeter (ring_geometry).
Only two opposite points ever light up — fixed at the upper-left and
lower-right, each a smoothstep bump in true distance along the card's own
edge (corner_bump) that fades to fully transparent well before the far
side, never a continuous ring. render_card_border already bakes a complete
faint neutral border into every icon (composited on top of this at the same
geometry), so this image adds only the coloured light — nothing in the dead
zones. Each lit point
layers a crisp hued core (blended toward white at its peak, for a "hot"
look), a softer wider halo, and a very restrained outer bloom — the halo/
bloom are just a Gaussian blur of the core's alpha, scaled down and capped
to the card's own margin so neither ever clips against the PNG edge. SIMPLE
colours show the same flat hue at both corners; PREMIUM and GRADIENT sample
their hue loop at the two anchor angles (phase-shifted per variant per
CYCLE_PHASE), so each corner picks up a different, related hue. On the light
background flat/iridescent/gradient hues are all darkened for contrast.

The five PREMIUM/GRADIENT variants additionally get an "elite material" pass
(see the MATERIAL_* constants and material_field/tone/lut_sample below) so the
FRAME's two lit corners and the OS/tool icons' own tint read as dimensional
material instead of one flat sampled hue: obsidian-purple and aurora sweep a
small arc of their own hue loop across each lit surface (a "different facet
at a different angle"), champagne-gold and platinum keep one hue per surface
but light/shadow it like brushed vs. polished metal, and cyberpunk stays
cyan-dominant with magenta demoted to a restrained secondary reflection. Every
one of these draws its highlight/shadow tones from that SAME variant's own
existing hex stops (tone() only pushes toward white/black, never a new hue),
and the icon's own light/shadow gradient is anchored to the same upper-left/
lower-right axis as the frame's two lit corners, so all three pieces read as
one lighting scheme. Kept deliberately low-frequency (broad gradients, no fine
texture) since tool icons in particular get flattened hard by rEFInd's own
naive-bilinear egScaleImage (see FEATHER_SMALL below).

Every icon is also re-padded to a fixed content size so the row has consistent,
generous spacing regardless of how tightly each source icon was cropped.

There is no permanent, pre-generated `colors/` directory in this repository —
colour variants are build products, generated on demand (by install.sh, or by
hand) into a throwaway output directory.

Output:

    backgrounds/<bg>.png                           solid colour, 64x64
                                                     (only rewritten on a full,
                                                     no-args / no --out-dir run)
    <out>/<colour>/selection_big.png               1024x1024 (dark bg)
    <out>/<colour>/selection_small.png             256x256
    <out>/<colour>/icons/*.png
    <out>/<colour>/light/selection_big.png                   (light bg)
    <out>/<colour>/light/selection_small.png
    <out>/<colour>/light/icons/*.png

`<out>` is `--out-dir=PATH` if given, else `build/colors/` in this repo
checkout (gitignored — a local scratch dir, never committed).

Usage:
    python3 tools/generate.py                 # regenerate everything into build/colors/
    python3 tools/generate.py green blue      # just these colours
    python3 tools/generate.py --out-dir=/tmp/look white  # build one colour elsewhere
    python3 tools/generate.py --list          # print available colour names, one per line
    python3 tools/generate.py --preview       # also write preview*.png
    python3 tools/generate.py --icons-dir=PATH   # read source icons from PATH
                                                 # instead of icons/

Dependencies: Pillow, numpy   (never shipped to the ESP — install.sh checks
for these before it runs this script).
"""

from __future__ import annotations

import hashlib
import hashlib as _hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parent.parent
COLORS_DIR = REPO / "build" / "colors"   # default; override with --out-dir=PATH
ICONS_DIR = REPO / "icons"
BG_DIR = REPO / "backgrounds"

# Fingerprint of this script's own source, written into every generated
# colour dir (see build()) and checked by install.sh's is_cached() before
# reusing a cached build/colors/<colour> — otherwise a `build/colors` left
# over from before some rendering fix (e.g. a card/frame geometry change)
# reads as "already generated" forever by file-existence alone, so an
# install would keep shipping the stale, pre-fix render until someone
# thinks to `rm -rf build/colors` by hand. Any edit to this file changes the
# hash and invalidates every colour's cache on the next generate/install.
GENERATOR_FINGERPRINT = _hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# ---------------------------------------------------------------- palette --

SIMPLE: dict[str, str] = {
    "white":  "#FFFFFF",
    "green":  "#40DC77",
    "red":    "#FF4D4D",
    "pink":   "#FF74C4",
    "blue":   "#4D9DFF",
}

# Premium variants: an ordered loop of hue stops the colour cycles through
# (the list wraps). Weighted toward the name hue so it still reads as
# purple / gold, with off-hues for the oil-slick shimmer.
PREMIUM: dict[str, list[str]] = {
    # Deep, dark jewel purple/indigo/magenta only (hue ~253-296°, L 22-46%)
    # -- pulled well below the old loop's own lighter, blue-leaning stop
    # (#4E78F0, hue ~221°, nearly flat blue), so it doesn't read as "a
    # lighter/darker version of an existing flat colour."
    "obsidian-purple": ["#4C0F8C", "#7A1FA8", "#9D2BB8", "#5E1499",
                        "#2D1466", "#8B2FA0", "#3D1470"],
    # Pure gold/bronze only (hue ~40-45°) -- the old loop's pink and green
    # stops (which pulled it toward other territory) are gone.
    "champagne-gold":  ["#8B6508", "#B8860B", "#D4A82E", "#E8C468",
                        "#C9962E", "#F0DCA0", "#A67C1E"],
}

PREMIUM_PHASE: dict[str, float] = {
    "obsidian-purple": 0.00,
    "champagne-gold":  0.68,
}

# Premium gradients: a simple two-stop hue loop (start -> end -> back to
# start). Painted onto the selection graphic by render_outline(); icon_tint()
# also draws on these same stops for the icon set's own light colour cast.
GRADIENT: dict[str, list[str]] = {
    "aurora":     ["#00E676", "#00D4FF"],
    "cyberpunk":  ["#FF0080", "#00E5FF"],
    # Blue-violet steel (hue ~232°, the gap between flat blue at 213° and
    # obsidian-purple's own range starting ~253°), more saturated than a
    # real "grey" ever would be (S 42-48%) so it still reads as coloured
    # after ICON_TINT_MIX_PREMIUM's dilution toward white.
    "platinum":   ["#3C4AAA", "#A1A8D9"],
}

GRADIENT_PHASE: dict[str, float] = {
    "aurora":    0.00,
    "cyberpunk": 0.60,
    "platinum":  0.80,
}

# One combined lookup for the angular hue-cycle offset — used by every
# gradient-painted variant, iridescent PREMIUM or two-stop GRADIENT alike.
CYCLE_PHASE: dict[str, float] = {**PREMIUM_PHASE, **GRADIENT_PHASE}

ALL_VARIANTS = list(SIMPLE) + list(PREMIUM) + list(GRADIENT)
MATERIAL_VARIANTS = set(PREMIUM) | set(GRADIENT)  # the 5 that get elite material shading

# Backgrounds and how the hue shifts for each.
BACKGROUNDS: dict[str, str] = {"dark": "#000000", "light": "#F4F4F5"}
LIGHT_DARKEN_SIMPLE = 0.52   # flat hue x this on the light background
LIGHT_DARKEN_PREMIUM = 0.58  # also used for GRADIENT — same treatment
WHITE_ON_LIGHT = "#2B2B2D"   # the "white" variant's ink on the light background

# --------------------------------------------------------------- geometry --

# Every icon is re-padded so its content fills this fraction of its canvas —
# evens out the ~0.5-0.62 the source icons vary between and, with a large
# big_icon_size in theme.conf, gives big icons AND wide, even gaps. Sized well
# below the card's own footprint (see CARD_SPECS) so the logo reads as
# sitting inside the card with visible breathing room, not crowding its
# border — shrinking this does NOT change the card's own size at all, only
# how much of it the logo fills.
ICON_CONTENT = 0.48

# Master resolution multiplier. The OS icons in icons/ are 4x hi-res masters
# (Real-ESRGAN x4plus upscales of the originals), so every big asset is
# emitted at 4x the historical size — OS icons 1024, selection outlines to
# match. theme.conf still asks for big_icon_size 200 / small_icon_size 50, so
# rEFInd only ever *downscales* these at boot → crisp.
SCALE = 4

# OS icons emit at 256*SCALE (1024), downscaled to big_icon_size at boot.
# Function/tool icons emit at 64, not 128: a controlled study against rEFInd's
# actual egScaleImage() (libeg/image.c) -- a naive 2-tap bilinear with no
# area/box filter, so it only ever blends the 4 source pixels straddling each
# output sample -- found the max single-pixel alpha jump in the final 50px
# render fell from ~250/255 at 128px down to ~165/255 at 64px. The smaller
# master keeps the downscale ratio (64/50 = 1.28x) close to identity, so
# egScaleImage's taps land inside the master's own AA ramp instead of
# skipping across most of it. See FEATHER_SMALL below for the rest of the fix.
OUT_BIG, OUT_SMALL = 256 * SCALE, 64

# Small (func_/tool_) icons get a touch of alpha-only Gaussian feather after
# padding, widening their AA ramp before egScaleImage sees it -- this narrows
# the max single-step alpha jump in the final 50px render further without
# softening the icon's white interior (only edge pixels have any alpha
# gradient to blur). Tuned against a reference theme's shipped 64px icon run
# through the same egScaleImage math: 0.5px lands at reference-level edge
# smoothness (comparable max-jump and transition-pixel counts) while keeping
# the silhouette crisp, not blurry.
FEATHER_SMALL = 0.5

# The big outline canvas is 256*SCALE, the small one 64*SCALE; rEFInd scales
# them down to big_icon_size / small_icon_size (200 / 50 in theme.conf) — so
# `border` is a bit more than the thin on-screen stroke. `margin` keeps the
# outline just outside the re-padded icon. `radius` is ~19% of each card's own
# outer half-width (size/2 - margin) — a soft, generous "app icon" rounding,
# not the tight corner a smaller radius reads as (unused for "small", a
# circle — see shape_sdf). All four measures scale with SCALE.
#
# rEFInd does NOT draw the selection backdrop at the icon's own size: it's
# scaled to (icon_size * 9/8) for the big row and (icon_size * 4/3) for the
# small one — refind/menu.c: `TileSizes[0] = IconSizes[BIG]*9/8;
# TileSizes[1] = IconSizes[SMALL]*4/3;`, `SelectionImages[i] =
# egScaleImage(..., TileSizes[i], TileSizes[i])` — both the icon and the
# backdrop then centred on the same point (libeg's BltImageCompositeBadge:
# `OffsetX = (TotalWidth - CompWidth) >> 1`). The margin/radius/border below
# were tuned by eye as if backdrop and icon rendered at the same size — which
# is what this file's own preview wrongly assumed too (see TILE_RATIO's use
# in make_menu_preview), so it looked right there. On real hardware the
# backdrop is 12.5%/33% bigger than the icon it sits behind, so the card
# visibly floats outside the icon instead of hugging it. shrink_spec()
# pre-shrinks the card shape toward the canvas centre by 1/ratio so rEFInd's
# own re-inflation lands it back where it was actually designed.
TILE_RATIO = {"big": 9 / 8, "small": 4 / 3}


def shrink_spec(px: float, margin: float, radius: float, border: float, ratio: float) -> dict:
    """Scale a card shape toward the canvas centre by 1/ratio. `margin` is
    size/2 minus the shape's own outer half-width, not a length measured from
    the centre, so it has to be solved back out from the shrunk outer rather
    than scaled directly; `radius` and `border` are plain lengths and scale
    straight through."""
    outer = px / 2.0 - margin
    return dict(margin=px / 2.0 - outer / ratio, radius=radius / ratio, border=border / ratio)


SPECS = {
    "big":   dict(px=256 * SCALE, shape="square",
                  **shrink_spec(256 * SCALE, 34.0 * SCALE, 18.0 * SCALE, 3.4 * SCALE,
                                 TILE_RATIO["big"])),
    "small": dict(px=64 * SCALE, shape="circle",
                  **shrink_spec(64 * SCALE, 9.0 * SCALE, 4.5 * SCALE, 2.3 * SCALE,
                                 TILE_RATIO["small"])),
}

# The faint card border baked directly into every icon (render_card_border)
# must NOT use SPECS' shrunk geometry: that shrink exists only to pre-cancel
# rEFInd's own TILE_RATIO re-inflation of the SEPARATELY-scaled selection
# backdrop (render_outline / selection_big.png), so the backdrop's glow lands
# back on the as-designed perimeter after boot scales it up by 9/8 or 4/3.
# The icon itself never gets that extra re-inflation — it's blitted straight
# at big_icon_size/small_icon_size — so baking the SHRUNK ring onto it left
# the card's own border sitting visibly inside where the (correctly
# re-inflated) backdrop's lit corners land: a gap between the two on real
# hardware. CARD_SPECS keeps the original, as-designed margin/radius/border
# (pre shrink_spec) so the card renders at the same perimeter the backdrop
# re-inflates back to — the two now trace the same on-screen ring with no
# padding between them.
CARD_SPECS = {
    "big":   dict(px=SPECS["big"]["px"], shape=SPECS["big"]["shape"],
                  margin=34.0 * SCALE, radius=18.0 * SCALE, border=3.4 * SCALE),
    "small": dict(px=SPECS["small"]["px"], shape=SPECS["small"]["shape"],
                  margin=9.0 * SCALE, radius=4.5 * SCALE, border=2.3 * SCALE),
}
SS = 4  # supersample factor
# Cap the outline supersample buffer: at SCALE 4 the square outline is 1024 px
# and 1024*SS would be a 4096² float grid (OOM-prone on low-RAM boxes). A
# rounded-rect stroke needs no more than ~2x SSAA at that size.
MAX_OUTLINE_RES = 2048
# The focused item's light is NOT a continuous ring: it traces the SAME
# perimeter as the card itself (ring_geometry — rounded square for "big",
# circle for "small") and only two opposite points of it ever light up,
# fixed at the upper-left / lower-right. Each fades smoothly to a hard,
# genuine 0 well before reaching the far side (corner_bump) — unlike a raised
# cosine, which is never actually zero over a stretch. There is no separate
# neutral base layer here: render_card_border already bakes the complete faint card
# border into every icon (composited on top of this, same geometry), so the
# dead zones are simply fully transparent.
ORBIT_WIDTH_MULT = 1.5       # lit-corner stroke width, x the card border's own width
                              # — a bit more prominent than the card's own hairline,
                              # but still the same perimeter, not a new ribbon
# Both fractions are of `outer`, the card's own half-width at its flat edges
# (see ring_geometry). bump = max(bump_tl, bump_br) stays fully dark at a
# boundary point only while BOTH dist_tl and dist_br there are >= half_width
# -- i.e. the true ceiling is set by min(dist_tl, dist_br)'s own maximum over
# the whole boundary (reached at the two OTHER, unlit corners, where both
# distances are roughly a full edge-length), NOT by "half an edge away" --
# an earlier version of this comment got that wrong by ~2x and capped both
# shapes far more conservatively than the geometry actually allows. Measured
# numerically straight off ring_geometry's own boundary (see scratch check,
# 2026-09-13): ceiling frac is ~1.568 x outer for the rounded-square "big"
# card and ~1.414 x outer (== sqrt(2), the chord length between the two
# antipodal lit points at 90°) for the circular "small" one -- "small" isn't
# actually the one with more headroom, they're close; "big" has slightly
# more. Both get 80% of their own ceiling here, which leaves ~20% of the
# full perimeter genuinely dark (never a continuous ring) while making the
# lit majority the dominant read -- clearly past the midpoint of each edge,
# per the reference image the user pointed at ("currently reaches half a
# side; each one should be MORE than half"). Plateau is always HALF of its
# own half-width (not a sliver at the tip), so the lit stretch reads as a
# real block of solid colour that then fades, rather than a fade with a
# bright pinpoint.
#
# IMPORTANT: `outer` itself is already the POST-shrink_spec value (see
# SPECS/TILE_RATIO above) — these fractions apply to the smaller, hardware-
# correct card, not the original design size, so a frac increase here does
# NOT translate 1:1 into a longer arc measured against how an *old* build
# looked (outer itself moves too whenever SPECS changes) -- always recompute
# `half_width_frac * outer` in canvas px and compare that number, not the
# frac alone. Judge the actual result from make_menu_preview's output (it
# simulates rEFInd's real TILE_RATIO re-inflation) or an actual installed
# icon, never from make_preview's swatch grid or the raw selection_*.png
# files directly — neither undoes the shrink, so both always show the
# card+glow smaller/tighter than they'll actually render.
ORBIT_PLATEAU_FRAC = {"big": 0.627, "small": 0.566}      # 50% of the half-width below
ORBIT_HALF_WIDTH_FRAC = {"big": 1.255, "small": 1.131}   # 80% of each shape's own ceiling
ORBIT_CORE_ALPHA = 0.95      # crisp core, peak strength at each corner's centre
ORBIT_CORE_WHITE_MIX = 0.50  # blend toward white at the peak, for a hot core
ORBIT_HALO_BLUR = 1.6        # x card border width, capped by the card's own margin
ORBIT_HALO_ALPHA = 0.70
ORBIT_BLOOM_BLUR = 4.0       # x card border width, capped by the card's own margin
ORBIT_BLOOM_ALPHA = 0.42

# SIMPLE colours are the plain, no-frills tier — their focused light should
# read as a clean, minimal accent, not compete with PREMIUM/GRADIENT's
# iridescent glow (see render_outline). Same corner geometry, same width —
# only the "hot" white blend and the halo/bloom glow are dropped, so the two
# tiers are told apart by finish (flat colour vs glowing shimmer), not by a
# different shape.
SIMPLE_CORE_ALPHA = 0.85     # a touch calmer than ORBIT_CORE_ALPHA
SIMPLE_CORE_WHITE_MIX = 0.0  # pure flat hue at the corner, no hot highlight
SIMPLE_HALO_ALPHA = 0.0      # no soft glow
SIMPLE_BLOOM_ALPHA = 0.0     # no outer bloom

# Every icon — focused or not — bakes in this faint glass-card look (rEFInd
# only ever draws the vivid ring above behind the one focused entry, so this
# is the only way every other icon still reads as a card): a barely-there
# border plus an even fainter interior wash, both a neutral white on the dark
# background / dark ink on the light one, same geometry as the vivid ring so
# a focused icon's outline and glow trace exactly over it.
CARD_BORDER_ALPHA = 0.12
CARD_FILL_ALPHA = 0.05

# Every icon in a variant also picks up a tint of that variant's own colour
# (see icon_tint / recolor_icon) — a mix, not a full recolour, so it still
# plainly reads as a white icon with a colour cast rather than a coloured
# icon. rEFInd keeps one fixed icon file per OS regardless of which entry is
# currently focused (there is no separate "unfocused" icon asset to swap to),
# so this applies to every icon in the variant alike, not only whichever one
# happens to be selected at any moment.
#
# SIMPLE gets a modest mix — just enough to read as "a bit of colour," since
# a flat hue has no extra finish to sell. PREMIUM/GRADIENT get a much
# stronger one: their selection ring already reads as unmistakably premium
# (full-saturation stroke, hot white core, halo, bloom, a different hue per
# icon via icon_tint's `name` phase), and at SIMPLE-strength dilution that
# same colour collapsed to a near-white smudge on the icon itself — no
# iridescence left to see. The higher mix keeps that per-icon hue clearly
# legible while `base` still carries most of the icon's own value, so it
# still reads as a white/dark-ink glyph, just an obviously tinted one.
ICON_TINT_MIX_SIMPLE = 0.34
ICON_TINT_MIX_PREMIUM = 0.60   # also used for GRADIENT


# ------------------------------------------------------------------ maths --

def hex_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float) / 255.0


def smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def shape_sdf(shape: str, px: np.ndarray, py: np.ndarray,
              half: float, r: float) -> np.ndarray:
    """Signed distance (<0 inside) to a circle or rounded square at the origin."""
    if shape == "circle":
        return np.hypot(px, py) - half
    qx = np.abs(px) - (half - r)
    qy = np.abs(py) - (half - r)
    return (np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
            + np.minimum(np.maximum(qx, qy), 0.0) - r)


def gradient_lut(stops: list[str], n: int = 1024) -> np.ndarray:
    """A looped LUT (n,3): linear ramp through the stops, last wrapping to first."""
    cols = [hex_rgb(s) for s in stops]
    cols.append(cols[0])
    segs = len(cols) - 1
    lut = np.empty((n, 3), dtype=float)
    for i in range(n):
        f = (i / n) * segs
        k = int(f)
        frac = f - k
        lut[i] = cols[k] * (1.0 - frac) + cols[k + 1] * frac
    return lut


def clear_transparent_rgb(rgba_u8: np.ndarray) -> np.ndarray:
    """Zero the RGB of fully-transparent pixels (alpha == 0) in place, so
    transparent regions carry no colour — smaller PNGs and no matte / fringe
    risk for any downstream compositor."""
    rgba_u8[rgba_u8[..., 3] == 0, 0:3] = 0
    return rgba_u8


def downscale(arr: np.ndarray, size: int) -> np.ndarray:
    """LANCZOS downscale of a float array in [0,1]; keeps last axis for RGB."""
    mode = "L" if arr.ndim == 2 else "RGB"
    img = Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8), mode)
    img = img.resize((size, size), Image.LANCZOS)
    return np.asarray(img, dtype=float) / 255.0


def paint(variant: str, bg: str):
    """The colour for a (variant, background): ('flat', rgb) or ('grad', lut)."""
    if variant in PREMIUM or variant in GRADIENT:
        stops = PREMIUM[variant] if variant in PREMIUM else GRADIENT[variant]
        lut = gradient_lut(stops)
        return "grad", lut * (LIGHT_DARKEN_PREMIUM if bg == "light" else 1.0)
    if variant == "white":
        return "flat", hex_rgb("#FFFFFF" if bg == "dark" else WHITE_ON_LIGHT)
    rgb = hex_rgb(SIMPLE[variant])
    return "flat", rgb * (LIGHT_DARKEN_SIMPLE if bg == "light" else 1.0)


# --------------------------------------------------------------- material --

# Elite treatment for the five PREMIUM/GRADIENT palettes: FRAME (the corner
# glow, render_outline) and the OS/tool icon tint (material_field) both pull
# from the same per-variant recipe below, so the three read as one deliberate
# material rather than three independently flat tints. Every recipe stays
# inside its own variant's existing hex stops (paint() / gradient_lut) — only
# lightness and hue-POSITION within that fixed loop ever move, tone() only
# ever pushes toward white or black, so "obsidian purple" etc. stay exactly
# the palette they already are, just rendered with depth. SIMPLE colours and
# "white" are untouched (flat is correct for that tier — see SIMPLE_* /
# ICON_TINT_MIX_SIMPLE); MATERIAL_VARIANTS above is the 5 that opt in.

# Iridescent variants (obsidian-purple, aurora) sweep this fraction of their
# own hue loop across one lit surface instead of showing one fixed hue — a
# "different facet at a different angle". Metals (champagne-gold, platinum)
# and cyberpunk are deliberately absent here: real metal doesn't shift hue
# with the light, and cyberpunk's two hues are handled explicitly instead
# (see render_outline / material_field) so cyan always stays dominant rather
# than sweeping through a muddy midpoint between cyan and magenta.
MATERIAL_HUE_SPAN = {"obsidian-purple": 0.11, "aurora": 0.16}

# A genuine specular glint (Gaussian, in units of `outer`) at each lit
# corner's own tip, layered ON TOP of the existing flat hot-mix plateau —
# narrow + strong for platinum ("sharp but elegant"), broad + gentler for
# champagne-gold ("soft directional reflections"). This has to be a separate
# term rather than reshaping corner_bump's own falloff: bump_ds sits at a
# flat plateau (== 1.0) across most of the near-corner arc (see
# ORBIT_PLATEAU_FRAC), so any exponent on it (power ** 1) leaves every
# material's peak identical — there's no "shape" there left to sharpen.
FRAME_GLINT_SIGMA = {"champagne-gold": 0.85, "platinum": 0.32}  # x outer; smaller = tighter
FRAME_GLINT_BOOST = {"champagne-gold": 0.28, "platinum": 0.48}  # extra white-mix at the peak


def tone(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Blend a colour toward white (amount > 0) or black (amount < 0) —
    never toward a different hue. `amount` is a plain float, clipped to
    [-1, 1]; `rgb` broadcasts as any (..., 3) array, so this works equally
    on a single sampled colour or a full (size, size, 3) field."""
    amount = max(-1.0, min(1.0, amount))
    target = 1.0 if amount >= 0.0 else 0.0
    return rgb + (target - rgb) * abs(amount)


def lut_sample(lut: np.ndarray, phase: np.ndarray) -> np.ndarray:
    """Vectorised looped LUT lookup (see gradient_lut/paint's "grad" mode):
    `phase` is an array of any shape (or a 0-d np.array for a single sample),
    wrapped mod 1; returns an array of shape (*phase.shape, 3)."""
    n = len(lut)
    idx = (np.mod(phase, 1.0) * n).astype(np.int64) % n
    return lut[idx]


# ---------------------------------------------------------------- outline --

def ring_geometry(kind: str, specs: dict = SPECS):
    """The card's own ring band (and its filled interior) for a SPECS kind
    (rounded square for "big", circle for "small" — see shape_sdf), at its
    own supersampled resolution — shared by the vivid focused ring
    (render_outline, always SPECS) and the faint default card
    (render_card_border, CARD_SPECS — see its own comment above) baked into
    every icon. Both trace the exact same shape family at the same canvas
    size, just at each geometry's own (possibly TILE_RATIO-shrunk) margin."""
    spec = specs[kind]
    size = spec["px"]
    ss = SS if size * SS <= MAX_OUTLINE_RES else MAX_OUTLINE_RES / size
    hi = int(round(size * ss))
    ys, xs = np.mgrid[0:hi, 0:hi].astype(float)
    c = (hi - 1) / 2.0
    px, py = xs - c, ys - c
    outer = (size / 2.0 - spec["margin"]) * ss
    bw = spec["border"] * ss
    r = spec["radius"] * ss
    aa = 1.1 * ss
    d_out = shape_sdf(spec["shape"], px, py, outer, r)
    d_in = shape_sdf(spec["shape"], px, py, outer - bw, max(r - bw, 0.4 * ss))
    fill = smoothstep(aa, -aa, d_out)  # 1 across the whole card footprint, 0 outside
    ring = np.clip(fill - smoothstep(aa, -aa, d_in), 0.0, 1.0)
    return spec, ring, fill, d_out, px, py, xs, ys, hi, size, ss


def corner_bump(dist_from_corner: np.ndarray, outer: float, kind: str) -> np.ndarray:
    """1.0 right at the lit point, then smoothstepping down to a hard 0 by
    ORBIT_HALF_WIDTH_FRAC[kind] x outer moving away from it — a real dead zone,
    unlike a raised cosine which never actually reaches zero over a stretch.
    For the rounded-square "big" card, `dist_from_corner` is Euclidean
    distance to the corner arc's own centre, minus its radius, so it already
    reads ~0 along the whole rounding arc and grows ~linearly (true
    arc-length, not angle) out along the two straight edges past it. For the
    circular "small" card there's no arc to speak of, just a fixed point on
    the ring, so it's plain chord distance from that point — a reasonable
    stand-in for arc-length at these proportions (only two opposite points
    are ever lit, so there is no adjoining neighbour to bunch against).
    Deliberately NOT angle-based: a raw atan2 angle bunches badly approaching
    a rounded rect's flat edges, and the old always-on ring's
    position-dependent "nudge" (matching neither angle nor arc-length) only
    ever had to look fine averaged over a fully lit loop -- it badly
    distorts where a real dead zone falls."""
    plateau = ORBIT_PLATEAU_FRAC[kind] * outer
    half_width = ORBIT_HALF_WIDTH_FRAC[kind] * outer
    return 1.0 - smoothstep(plateau, half_width, dist_from_corner)


def blur_alpha(alpha: np.ndarray, radius_px: float) -> np.ndarray:
    """Gaussian-blur a 0..1 alpha plane alone (no colour) — the same trick
    pad_icon uses for FEATHER_SMALL — so the halo/bloom layers fall straight
    out of the core's crisp shape instead of needing their own hand-tuned
    geometry."""
    if radius_px <= 0.05:
        return alpha
    im = Image.fromarray(np.clip(alpha * 255.0, 0, 255).astype(np.uint8), "L")
    im = im.filter(ImageFilter.GaussianBlur(radius_px))
    return np.asarray(im, dtype=float) / 255.0


def render_outline(kind: str, variant: str, bg: str) -> Image.Image:
    spec, _ring, _fill, d_out, px, py, _xs, _ys, _hi, size, ss = ring_geometry(kind)

    # The two lit points, upper-left / lower-right, in the same supersampled
    # (px, py) frame as d_out. For a rounded square this is distance to the
    # corner's own rounding-arc centre (see shape_sdf: exactly where those
    # arcs are centred), minus its radius, so it reads ~0 along the whole
    # arc. A circle has no corners, so the direct analogue is just distance
    # to a single fixed point on the ring at the same two diagonal
    # directions — everything downstream (corner_bump, band, colour) is
    # unchanged, so it's the exact same effect, only traced on a round card.
    outer = (size / 2.0 - spec["margin"]) * ss
    if spec["shape"] == "circle":
        diag = outer / np.sqrt(2.0)
        dist_tl = np.hypot(px + diag, py + diag)
        dist_br = np.hypot(px - diag, py - diag)
    else:
        r = spec["radius"] * ss
        c = outer - r
        dist_tl = np.maximum(np.hypot(px + c, py + c) - r, 0.0)
        dist_br = np.maximum(np.hypot(px - c, py - c) - r, 0.0)
    bump_tl, bump_br = corner_bump(dist_tl, outer, kind), corner_bump(dist_br, outer, kind)
    bump = np.maximum(bump_tl, bump_br)

    # A thin, anti-aliased band straddling the card's own perimeter contour
    # (d_out == 0 exactly on it) — deliberately re-derived here rather than
    # reusing ring_geometry's `_ring`, so ORBIT_WIDTH_MULT can widen it a
    # little beyond the card's own hairline border.
    bw = spec["border"] * ss * ORBIT_WIDTH_MULT
    aa = 1.1 * ss
    band = smoothstep(bw / 2.0 + aa, bw / 2.0 - aa, np.abs(d_out))

    core_mask = downscale(band * bump, size)
    bump_ds = downscale(bump, size)

    # Each corner gets its own fixed colour (phase apart on the loop/gradient)
    # rather than a continuously-swept hue — the two lit patches don't touch,
    # so there is no arc for a sweep to travel across; blending is only ever
    # needed for the sliver of "big" small-spec canvases where both corners'
    # falloff might faintly overlap near the image centre, which never
    # actually happens at these proportions but costs nothing to handle.
    phase = CYCLE_PHASE.get(variant, 0.0)
    mode, col = paint(variant, bg)
    hue_span = MATERIAL_HUE_SPAN.get(variant, 0.0)
    if mode == "grad" and variant == "cyberpunk":
        # Cyan stays the dominant, primary illumination at BOTH corners;
        # magenta only ever shows as a restrained secondary reflection on
        # the opposing corner, never a full corner of its own hue (a flat
        # phase/phase+0.5 split of this 2-stop loop would otherwise hand an
        # entire corner to magenta — see PREMIUM COLOR TREATMENT brief).
        col_tl = lut_sample(col, np.array(0.5))
        col_br = lut_sample(col, np.array(0.5 + 0.14))
    elif mode == "grad" and hue_span > 0.0:
        # Iridescent variants: sweep a small arc of the hue loop across each
        # lit surface (see MATERIAL_HUE_SPAN) instead of one fixed hue —
        # dist_tl/dist_br (already computed above, supersampled) give a 0..1
        # position along each corner's own falloff to sweep across.
        half_w = ORBIT_HALF_WIDTH_FRAC[kind] * outer
        t_tl = np.clip(dist_tl / half_w, 0.0, 1.0)
        t_br = np.clip(dist_br / half_w, 0.0, 1.0)
        col_tl = downscale(lut_sample(col, phase + (t_tl - 0.5) * hue_span), size)
        col_br = downscale(lut_sample(col, phase + 0.5 + (t_br - 0.5) * hue_span), size)
    elif mode == "grad":
        col_tl = col[int(np.mod(phase, 1.0) * len(col)) % len(col)]
        col_br = col[int(np.mod(phase + 0.5, 1.0) * len(col)) % len(col)]
    else:
        col_tl = col_br = col
    w = downscale(bump_tl, size)
    w = w / np.maximum(w + downscale(bump_br, size), 1e-6)
    stroke_rgb = col_tl * w[..., None] + col_br * (1.0 - w)[..., None]

    # SIMPLE colours are the plain tier: a clean, flat accent (no hot white
    # blend, no halo/bloom glow). PREMIUM/GRADIENT keep the full iridescent
    # treatment — that visible gap is the whole point (see SIMPLE_* above).
    is_simple = variant in SIMPLE
    core_white_mix = SIMPLE_CORE_WHITE_MIX if is_simple else ORBIT_CORE_WHITE_MIX
    core_alpha_k = SIMPLE_CORE_ALPHA if is_simple else ORBIT_CORE_ALPHA
    halo_alpha_k = SIMPLE_HALO_ALPHA if is_simple else ORBIT_HALO_ALPHA
    bloom_alpha_k = SIMPLE_BLOOM_ALPHA if is_simple else ORBIT_BLOOM_ALPHA

    # The core blends toward white at each corner's peak — a "hot" highlight —
    # the halo/bloom stay pure hue, which is what actually carries the colour.
    # FRAME_GLINT_SIGMA/_BOOST add a genuine specular glint on top for the two
    # metals (see the constant's own comment above for why this can't just
    # reshape bump_ds).
    white = np.array([1.0, 1.0, 1.0])
    mix = (core_white_mix * bump_ds)[..., None]
    if variant in FRAME_GLINT_SIGMA:
        sig = FRAME_GLINT_SIGMA[variant] * outer
        d_tl_n, d_br_n = dist_tl / sig, dist_br / sig
        glint = np.maximum(np.exp(-d_tl_n ** 2), np.exp(-d_br_n ** 2))
        mix = np.clip(mix + (FRAME_GLINT_BOOST[variant] * downscale(glint, size))[..., None], 0.0, 1.0)
    core_rgb = stroke_rgb * (1.0 - mix) + white * mix

    if variant == "platinum":
        # Liquid-metal double-tone: a thin darker ring just outside the
        # glint's own radius (d_tl_n/d_br_n, set above), before the stroke
        # returns to its base hue — what actually reads as "polished chrome"
        # rather than a flat glow.
        ring = np.maximum(smoothstep(1.0, 1.6, d_tl_n) * (1.0 - smoothstep(1.6, 2.4, d_tl_n)),
                           smoothstep(1.0, 1.6, d_br_n) * (1.0 - smoothstep(1.6, 2.4, d_br_n)))
        ring_ds = downscale(ring, size)
        core_rgb = core_rgb * (1.0 - ring_ds)[..., None] + tone(stroke_rgb, -0.35) * ring_ds[..., None]

    core_alpha = np.clip(core_mask * core_alpha_k, 0.0, 1.0)

    # Blur radii are capped to a fraction of the card's own margin (the clear
    # canvas headroom already reserved outside its edge) so the halo/bloom
    # always fade out before the PNG edge, never clip against it.
    margin = spec["margin"]
    halo_alpha = np.clip(blur_alpha(core_mask, min(spec["border"] * ORBIT_HALO_BLUR, margin * 0.5))
                          * halo_alpha_k, 0.0, 1.0)
    bloom_alpha = np.clip(blur_alpha(core_mask, min(spec["border"] * ORBIT_BLOOM_BLUR, margin * 0.8))
                           * bloom_alpha_k, 0.0, 1.0)

    # Cyberpunk only: a thin magenta chromatic-aberration fringe just outside
    # the main cyan stroke — "subtle chromatic aberration ... ONLY at edges",
    # not a second full-strength corner (see col_tl/col_br above, which keeps
    # magenta a restrained accent rather than an equal corner).
    fringe_rgb, fringe_alpha = stroke_rgb, np.zeros((size, size))
    if variant == "cyberpunk":
        offset = 1.4 * spec["border"] * ss
        fringe_band = smoothstep(bw / 2.0 + aa, bw / 2.0 - aa, np.abs(d_out - offset))
        fringe_mask = downscale(fringe_band * bump, size)
        fringe_rgb = np.broadcast_to(lut_sample(col, np.array(0.0)), (size, size, 3))
        fringe_alpha = np.clip(fringe_mask * 0.32, 0.0, 1.0)

    def over(base_rgb, base_a, layer_rgb, layer_a):
        out_a = layer_a + base_a * (1.0 - layer_a)
        safe = np.maximum(out_a, 1e-6)
        out_rgb = (layer_rgb * layer_a[..., None]
                   + base_rgb * base_a[..., None] * (1.0 - layer_a[..., None])) / safe[..., None]
        return out_rgb, out_a

    # Back-to-front: bloom, then halo, then the crisp core on top. No neutral
    # base layer — render_card_border already bakes the complete faint card
    # border into the icon drawn on top of this at the same geometry, so this
    # image only ever needs to add the coloured light, transparent elsewhere.
    rgb = np.zeros((size, size, 3))
    a = np.zeros((size, size))
    rgb, a = over(rgb, a, stroke_rgb, bloom_alpha)
    rgb, a = over(rgb, a, stroke_rgb, halo_alpha)
    rgb, a = over(rgb, a, fringe_rgb, fringe_alpha)
    rgb, a = over(rgb, a, core_rgb, core_alpha)

    rgba = np.clip(np.dstack([rgb, a]), 0.0, 1.0)
    return Image.fromarray(
        clear_transparent_rgb((rgba * 255.0 + 0.5).astype(np.uint8)), "RGBA")


def render_card_border(kind: str, bg: str) -> Image.Image:
    """The faint glass card baked into every icon (see CARD_BORDER_ALPHA /
    CARD_FILL_ALPHA) — same shape as render_outline's vivid ring, just a
    flat, low-alpha wash of the same white/dark-ink tone the icon glyphs
    themselves use, with no colour cycling and no glow. `np.maximum` rather
    than adding the two keeps the border the brighter rim it should be
    instead of double-counting where it overlaps the fill."""
    _spec, ring, fill, _d_out, _px, _py, _xs, _ys, _hi, size, _ss = ring_geometry(kind, CARD_SPECS)
    alpha = np.maximum(downscale(fill, size) * CARD_FILL_ALPHA,
                        downscale(ring, size) * CARD_BORDER_ALPHA)
    _, col = paint("white", bg)
    rgb = np.broadcast_to(col, (size, size, 3)).astype(float)
    rgba = np.clip(np.dstack([rgb, alpha]), 0.0, 1.0)
    return Image.fromarray(
        clear_transparent_rgb((rgba * 255.0 + 0.5).astype(np.uint8)), "RGBA")


# ------------------------------------------------------------------ icons --

def pad_icon(img: Image.Image, out: int, sharpen: bool = True, feather: float = 0.0) -> Image.Image:
    """Re-centre an icon's content to ICON_CONTENT of an `out`-px canvas. When
    `sharpen`, also crisp the edges: a light unsharp mask undoes interpolation
    softness and a steep contrast curve on the alpha pulls the anti-aliased
    border back to a tight ~1 px — so it still reads clean after rEFInd's own
    downscale. Function/tool icons render at a flat 64px with `sharpen` off:
    that post-processing was tuned for the big OS icons' 1024->200 downscale
    and just adds ringing ahead of the small icons' 64->50 one. `feather`
    (small icons only) is a Gaussian blur applied to the alpha channel alone
    after compositing — it widens the AA ramp for egScaleImage's naive 2-tap
    bilinear without touching the interior's flat 255 alpha."""
    im = img.convert("RGBA")
    a = np.asarray(im)
    ys, xs = np.where(a[..., 3] > 8)
    if len(xs) == 0:
        return im.resize((out, out), Image.LANCZOS)
    content = im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    s = (out * ICON_CONTENT) / max(content.size)
    nw, nh = max(1, round(content.size[0] * s)), max(1, round(content.size[1] * s))
    content = content.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (out, out), (0, 0, 0, 0))
    canvas.alpha_composite(content, ((out - nw) // 2, (out - nh) // 2))
    if not sharpen:
        if feather > 0:
            r, g, b, alpha_ch = canvas.split()
            alpha_ch = alpha_ch.filter(ImageFilter.GaussianBlur(feather))
            canvas = Image.merge("RGBA", (r, g, b, alpha_ch))
        return canvas

    canvas = canvas.filter(ImageFilter.UnsharpMask(radius=1.4, percent=90, threshold=0))
    arr = np.asarray(canvas, dtype=float) / 255.0
    edge = arr[..., 3]
    arr[..., 3] = np.clip((edge - 0.5) * 1.5 + 0.5, 0.0, 1.0)
    return Image.fromarray((arr * 255.0 + 0.5).astype(np.uint8), "RGBA")


def icon_hue_phase(name: str) -> float:
    """A stable pseudo-random phase in [0, 1) derived from an icon's own
    filename — deterministic across runs (unlike Python's salted hash()) and
    independent of directory-listing order or icon count, so adding or
    removing an icon never reshuffles anyone else's hue."""
    digest = hashlib.sha256(name.encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2 ** 32


def icon_tint(variant: str, bg: str, name: str | None = None) -> np.ndarray:
    """A representative colour for a variant's icon tint. SIMPLE variants
    are one fixed hue, same for every icon — as they should be. GRADIENT/
    PREMIUM variants sweep a whole hue loop on the selection graphic, but
    giving every icon the same single averaged blend of that loop made the
    whole set read exactly as flat as a SIMPLE colour, with none of the
    iridescent variety the ring shows. So when `name` is given (big OS icons
    only, see build()), each icon instead samples its OWN point on the loop
    (icon_hue_phase) — the set as a whole then shows the same multi-hue
    spread as the ring, just spread across icons instead of across one
    icon's corners. `name=None` (small func_/tool_ icons) keeps the old
    single averaged hue: at 64px a per-icon hue split doesn't read cleanly,
    and a toolbar reads better as one cohesive tint than as a shimmer."""
    mode, col = paint(variant, bg)
    if mode != "grad":
        return col
    if name is None:
        return col.mean(axis=0)
    phase = CYCLE_PHASE.get(variant, 0.0) + icon_hue_phase(name)
    return col[int(np.mod(phase, 1.0) * len(col)) % len(col)]


def material_field(variant: str, bg: str, name: str | None, size: int, big: bool
                    ) -> tuple[np.ndarray, np.ndarray | None]:
    """A dimensional (size, size, 3) tint field for one of the five
    MATERIAL_VARIANTS — a synthetic upper-left-lit / lower-right-shadowed
    gradient (the SAME implied light direction as the frame's own two lit
    corners, see render_outline) reshaping icon_tint's flat colour into a
    highlight or shadow tone drawn from that variant's own existing hue loop
    (tone() / lut_sample, never a new hue — see the "material" section
    above). `big` is whether this is an OS icon (the visual centrepiece) or
    a func_/tool_ icon, which gets a restrained fraction (k) of the same
    swing instead of its own weaker recipe, so the hierarchy stays clean.
    Deliberately a single broad, low-frequency gradient — nothing finer
    survives rEFInd's own naive-bilinear downscale of the shipped icon (see
    FEATHER_SMALL). Returns (rgb_field, mix_field): mix_field is normally
    None (the caller's existing flat ICON_TINT_MIX_PREMIUM stands), except
    for obsidian-purple, where staying "dark, mysterious" needs MORE tint
    and LESS of the white/ink base showing through on the shadow side than
    a flat mix could ever reach — every other material stays legible and
    bright per its own brief, so only its hue/value (the RGB field) moves."""
    ys, xs = np.mgrid[0:size, 0:size].astype(float)
    d = (xs + ys) / (2.0 * max(size - 1, 1)) * 2.0 - 1.0  # -1 upper-left .. +1 lower-right
    light = 1.0 - smoothstep(-0.6, 0.6, d)                  # ~1 upper-left, ~0 lower-right
    k = 1.0 if big else 0.55

    base = icon_tint(variant, bg, name)
    _, col = paint(variant, bg)
    mix_field = None

    if variant == "champagne-gold":
        hi, lo = tone(base, 0.55 * k), tone(base, -0.30 * k)
        field = lo + (hi - lo) * smoothstep(0.15, 0.85, light)[..., None]
        if bg == "light":
            # The neutral dark-ink base (paint("white", "light")) desaturates
            # a warm hue toward mud far more than it dilutes a cool one —
            # gold specifically reads as brown/khaki, not "gold", once ~40%
            # of it is mixed in at the flat ICON_TINT_MIX_PREMIUM ratio (see
            # PREMIUM COLOR TREATMENT brief: "luxury watch/jewelry-grade...
            # never cheap-looking"). Needs far less ink to stay gold.
            mix_field = np.full((size, size), 0.80)
    elif variant == "platinum":
        hi, lo = tone(base, 0.70 * k), tone(base, -0.35 * k)
        field = lo + (hi - lo) * smoothstep(0.30, 0.70, light)[..., None]  # sharper than gold
    elif variant in MATERIAL_HUE_SPAN:
        base_phase = CYCLE_PHASE.get(variant, 0.0) + (icon_hue_phase(name) if name else 0.0)
        swept = lut_sample(col, base_phase + (light - 0.5) * MATERIAL_HUE_SPAN[variant] * k)
        if variant == "obsidian-purple":
            # Stays dark and mysterious: a violet rim lift on the lit side
            # (unchanged from the flat tint's own mix), a hard drop toward
            # near-black on the shadow side — helped along by mix_field
            # below, since ICON_TINT_MIX_PREMIUM alone can't reach past its
            # own fixed ratio of white/ink base no matter how dark the tint
            # colour itself goes.
            hi, lo = tone(swept, 0.28 * k), tone(swept, -0.55 * k)
            field = lo + (hi - lo) * smoothstep(0.10, 0.85, light)[..., None]
            shadow = 1.0 - smoothstep(0.15, 0.85, light)
            mix_field = ICON_TINT_MIX_PREMIUM + (0.92 - ICON_TINT_MIX_PREMIUM) * shadow * k
        else:  # aurora — airy/luminous, never heavy
            hi, lo = tone(swept, 0.42 * k), tone(swept, -0.12 * k)
            field = lo + (hi - lo) * smoothstep(0.15, 0.90, light)[..., None]
    elif variant == "cyberpunk":
        cyan = lut_sample(col, np.array(0.5))
        magenta = lut_sample(col, np.array(0.0))
        accent = (smoothstep(0.55, 0.0, light) * 0.30 * k)[..., None]
        based = cyan * (1.0 - accent) + magenta * accent
        field = based + (tone(based, 0.38 * k) - based) * smoothstep(0.35, 0.88, light)[..., None]
    else:
        return np.broadcast_to(base, (size, size, 3)).copy(), None

    return np.clip(field, 0.0, 1.0), mix_field


def recolor_icon(padded: Image.Image, variant: str, bg: str, name: str | None = None) -> Image.Image:
    """White on the dark background, dark ink on the light one, same as
    every variant — but blended toward that variant's own colour
    (ICON_TINT_MIX_SIMPLE / _PREMIUM) rather than staying neutral, so the
    icon and the selection graphic read as the same palette, and PREMIUM/
    GRADIENT icons carry the same obviously-not-flat finish their ring does.
    `name` (see icon_tint) is what lets each PREMIUM/GRADIENT big icon pick
    its own facet of the variant's hue loop instead of sharing one flat
    average."""
    a = np.asarray(padded.convert("RGBA"), dtype=float) / 255.0
    alpha = a[..., 3]
    _, base = paint("white", bg)
    mix_field = None
    if variant in MATERIAL_VARIANTS:
        tint, mix_field = material_field(variant, bg, name, alpha.shape[0], big=name is not None)
    else:
        tint = icon_tint(variant, bg, name)
    mix = ICON_TINT_MIX_SIMPLE if variant in SIMPLE else ICON_TINT_MIX_PREMIUM
    if mix_field is not None:
        mix = mix_field[..., None]
    rgb = np.broadcast_to(base * (1.0 - mix) + tint * mix, alpha.shape + (3,))
    out = np.clip(np.dstack([rgb, alpha]), 0.0, 1.0)
    return Image.fromarray(
        clear_transparent_rgb((out * 255.0 + 0.5).astype(np.uint8)), "RGBA")


def look_dir(variant: str, bg: str) -> Path:
    return COLORS_DIR / variant if bg == "dark" else COLORS_DIR / variant / "light"


def look_icon(variant: str, bg: str, name: str) -> Image.Image:
    return Image.open(look_dir(variant, bg) / "icons" / name).convert("RGBA")


# ----------------------------------------------------------------- driver --

def build_backgrounds() -> None:
    BG_DIR.mkdir(exist_ok=True)
    for name, hx in BACKGROUNDS.items():
        rgb = tuple(int(round(v * 255)) for v in hex_rgb(hx))
        Image.new("RGB", (64, 64), rgb).save(BG_DIR / f"{name}.png", optimize=True)


def is_big_icon(name: str) -> bool:
    return name.startswith(("os_", "boot_"))


def build(variant: str) -> None:
    sources = sorted(ICONS_DIR.glob("*.png"))
    padded = {f.name: pad_icon(Image.open(f), OUT_BIG if is_big_icon(f.name) else OUT_SMALL,
                                sharpen=is_big_icon(f.name),
                                feather=0.0 if is_big_icon(f.name) else FEATHER_SMALL)
              for f in sources}
    for bg in ("dark", "light"):
        d = look_dir(variant, bg)
        (d / "icons").mkdir(parents=True, exist_ok=True)
        render_outline("big", variant, bg).save(d / "selection_big.png", optimize=True)
        render_outline("small", variant, bg).save(d / "selection_small.png", optimize=True)
        # render_card_border emits at SPECS[kind]["px"], same as the OS icon
        # canvas (OUT_BIG) for "big" but not the tool icon canvas (OUT_SMALL
        # is deliberately smaller, see FEATHER_SMALL above) — downscale to
        # match before compositing onto the icon.
        card = {"big": render_card_border("big", bg),
                "small": render_card_border("small", bg).resize((OUT_SMALL, OUT_SMALL), Image.LANCZOS)}
        for name, pic in padded.items():
            # Per-icon hue variation (icon_tint's `name` arg) only for the
            # big OS icons — plenty of resolution there for the premium
            # loop's own facets to read cleanly per icon. func_/tool_ icons
            # pass name=None and keep the old single averaged tint.
            big = is_big_icon(name)
            icon = recolor_icon(pic, variant, bg, name=name if big else None)
            icon = Image.alpha_composite(icon, card["big" if big else "small"])
            icon.save(d / "icons" / name, optimize=True)
    (look_dir(variant, "dark") / ".fingerprint").write_text(GENERATOR_FINGERPRINT)
    print(f"  {variant:16s} -> {COLORS_DIR}/{variant}/  (+ light/)  {len(sources)} icons x2")


# ----------------------------------------------------------------- preview --

def _cell(bg_hex: str, size: int, *layers: Image.Image) -> Image.Image:
    tile = Image.new("RGBA", (size, size), tuple(int(round(v * 255)) for v in hex_rgb(bg_hex)) + (255,))
    for l in layers:
        tile.alpha_composite(l)
    return tile


def as_refind(img: Image.Image, refind_px: int, draw_px: int) -> Image.Image:
    """rEFInd downscales the shipped icon/backdrop to *_icon_size (or the
    TILE_RATIO-bigger backdrop size) with a plain filter; mimic that so a
    preview shows the real on-screen sharpness rather than a clean LANCZOS
    downscale straight from the 4x master."""
    return img.resize((refind_px, refind_px), Image.BILINEAR).resize((draw_px, draw_px), Image.LANCZOS)


def centered(x: int, y: int, ref_size: int, draw_size: int) -> tuple[int, int]:
    """Top-left for a draw_size box sharing a centre with a ref_size box
    whose own top-left is (x, y) — how rEFInd centres the (smaller) icon
    inside the (bigger) selection backdrop's tile box."""
    off = (draw_size - ref_size) // 2
    return x - off, y - off


def make_preview(variants: list[str]) -> None:
    """A quick hue/palette comparison sheet. Uses the same TILE_RATIO-aware
    compositing as make_menu_preview (as_refind/centered) so the selection
    backdrop lands in the same relative position here as it does on real
    hardware — drawing backdrop and icon at the same size (the old
    behaviour) nested the (still-shrunk) backdrop visibly INSIDE the icon's
    own card border instead of tracing it, since only the backdrop gets
    TILE_RATIO's extra re-inflation at boot."""
    if not (ICONS_DIR / "os_arch.png").exists():
        print("  (skipping preview: no icons)")
        return
    cell, pad, cols = 240, 22, 5
    chip = 84
    label_h = 26
    font = ImageFont.load_default(size=17)
    sel_cell = round(cell * TILE_RATIO["big"])
    sel_chip = round(chip * TILE_RATIO["small"])
    tile_dim = sel_cell             # canvas big enough to hold the larger backdrop without clipping
    off = (tile_dim - cell) // 2    # the icon's own inset within that canvas, sharing a centre with the backdrop
    row_h = cell + off + label_h    # extra `off` headroom so the backdrop's own lower-right glow can't bleed onto the label below it
    rows_per_bg = (len(variants) + cols - 1) // cols
    W = cols * cell + (cols + 1) * pad
    H = 2 * rows_per_bg * row_h + (2 * rows_per_bg + 2) * pad + 40
    sheet = Image.new("RGB", (W, H), (17, 17, 19))
    draw = ImageDraw.Draw(sheet)

    for bi, bg in enumerate(("dark", "light")):
        y_off = bi * (rows_per_bg * row_h + (rows_per_bg + 1) * pad + 20)
        for i, v in enumerate(variants):
            cx = pad + (i % cols) * (cell + pad)
            cy = y_off + 24 + pad + (i // cols) * (row_h + pad)
            tile = _cell(BACKGROUNDS[bg], tile_dim)
            # refind_px for the backdrops is the *inflated* TILE_RATIO size
            # rEFInd actually renders them at ((200*9)//8, (50*4)//3 — same
            # numbers as make_menu_preview), not the plain icon size: only
            # the backdrop gets that extra re-inflation, so simulating its
            # bilinear downscale at the icon's own resolution would slightly
            # under-blur it relative to real hardware.
            sel_b = as_refind(Image.open(look_dir(v, bg) / "selection_big.png").convert("RGBA"),
                               (200 * 9) // 8, sel_cell)
            icon_b = as_refind(look_icon(v, bg, "os_arch.png"), 200, cell)
            tile.alpha_composite(sel_b, centered(off, off, cell, sel_cell))
            tile.alpha_composite(icon_b, (off, off))
            # Tool-icon chip in the top-right corner (was bottom-right).
            ox, oy = off + cell - chip - 6, off + 6
            sel_s = as_refind(Image.open(look_dir(v, bg) / "selection_small.png").convert("RGBA"),
                               (50 * 4) // 3, sel_chip)
            icon_s = as_refind(look_icon(v, bg, "func_shutdown.png"), 50, chip)
            tile.alpha_composite(sel_s, centered(ox, oy, chip, sel_chip))
            tile.alpha_composite(icon_s, (ox, oy))
            sheet.paste(tile.convert("RGB"), (cx - off, cy - off))
            bbox = draw.textbbox((0, 0), v, font=font)
            tw = bbox[2] - bbox[0]
            draw.text((cx + (cell - tw) // 2, cy + cell + off + (label_h - (bbox[3] - bbox[1])) // 2),
                       v, font=font, fill=(200, 200, 206))

    dest = REPO / "preview.png"
    sheet.save(dest, optimize=True)
    print(f"  preview -> preview.png ({W}x{H}; rows: {', '.join(variants)}; dark then light)")


def make_menu_preview(variants: list[str]) -> None:
    os_names = [n for n in ("os_omarchy", "os_arch", "os_linux", "os_win11", "os_mac")
                if (ICONS_DIR / f"{n}.png").exists()]
    tool_names = [n for n in ("func_shutdown", "func_reset", "func_firmware", "func_about")
                  if (ICONS_DIR / f"{n}.png").exists()]
    if len(os_names) < 3:
        print("  (skipping menu preview: not enough icons)")
        return

    W, strip_h = 1280, 250
    big, small = 100, 25         # ~theme.conf 200/50 at 0.5 px per rEFInd px
    # rEFInd draws the selection backdrop BIGGER than the icon it sits behind
    # (TILE_RATIO — see SPECS above) and centres both on the same point.
    # Mirror that here instead of drawing both at the same size: that's the
    # earlier bug that made this preview look right while the real boot menu
    # showed the border floating outside the card.
    sel_big = round(big * TILE_RATIO["big"])
    sel_small = round(small * TILE_RATIO["small"])
    gap_big, gap_small = 16, 12  # rEFInd's own cell gap is small; the spacing
    sel_os, sel_tool = 1, 0      # you see comes from the icons' transparent pad
    combos = [(v, bg) for bg in ("dark", "light") for v in variants]
    panel = Image.new("RGB", (W, strip_h * len(combos)), (17, 17, 19))

    for row, (v, bg) in enumerate(combos):
        rgb = tuple(int(round(c * 255)) for c in hex_rgb(BACKGROUNDS[bg]))
        strip = Image.new("RGBA", (W, strip_h), rgb + (255,))
        sel_b = as_refind(Image.open(look_dir(v, bg) / "selection_big.png").convert("RGBA"),
                           (200 * 9) // 8, sel_big)
        sel_s = as_refind(Image.open(look_dir(v, bg) / "selection_small.png").convert("RGBA"),
                           (50 * 4) // 3, sel_small)

        x0 = (W - (len(os_names) * big + (len(os_names) - 1) * gap_big)) // 2
        y_os = 64
        for i, n in enumerate(os_names):
            x = x0 + i * (big + gap_big)
            if i == sel_os:
                strip.alpha_composite(sel_b, centered(x, y_os, big, sel_big))
            strip.alpha_composite(as_refind(look_icon(v, bg, f"{n}.png"), 200, big), (x, y_os))

        tx0 = (W - (len(tool_names) * small + (len(tool_names) - 1) * gap_small)) // 2
        y_tool = y_os + big + 56
        for i, n in enumerate(tool_names):
            x = tx0 + i * (small + gap_small)
            if i == sel_tool:
                strip.alpha_composite(sel_s, centered(x, y_tool, small, sel_small))
            strip.alpha_composite(as_refind(look_icon(v, bg, f"{n}.png"), 50, small), (x, y_tool))

        panel.paste(strip.convert("RGB"), (0, row * strip_h))

    dest = REPO / "preview-menu.png"
    panel.save(dest, optimize=True)
    print(f"  menu preview -> preview-menu.png ({panel.width}x{panel.height}; {', '.join(v for v, _ in combos)})")


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for v in ALL_VARIANTS:
            print(v)
        return 0

    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}

    global ICONS_DIR, COLORS_DIR
    out_dir_explicit = False
    for a in flags:
        if a.startswith("--icons-dir="):
            ICONS_DIR = Path(a.split("=", 1)[1]).expanduser().resolve()
        elif a.startswith("--out-dir="):
            COLORS_DIR = Path(a.split("=", 1)[1]).expanduser().resolve()
            out_dir_explicit = True
    if not ICONS_DIR.is_dir():
        print(f"icons dir not found: {ICONS_DIR}", file=sys.stderr)
        return 2

    variants = args or ALL_VARIANTS
    unknown = [v for v in variants if v not in ALL_VARIANTS]
    if unknown:
        print(f"unknown variant(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"available: {', '.join(ALL_VARIANTS)}", file=sys.stderr)
        return 2

    print(f"source icons: {ICONS_DIR}")
    print(f"output: {COLORS_DIR}")
    # Backgrounds are committed source (backgrounds/dark.png, light.png), not a
    # per-colour build product — only touch them on a full, in-repo rebuild
    # (no --out-dir), never when install.sh drives a narrow, throwaway build.
    if not out_dir_explicit:
        build_backgrounds()
    COLORS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"generating {len(variants)} colour(s) x 2 backgrounds")
    for v in variants:
        build(v)

    if "--preview" in flags:
        shown = [v for v in ALL_VARIANTS if v in variants] or ALL_VARIANTS
        make_preview(shown)
        make_menu_preview([v for v in ("white", "blue", "obsidian-purple") if v in shown] or shown[:3])

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
