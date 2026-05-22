"""Colour helpers — random palette generation with readable contrast.

All inputs/outputs are 7-char `#RRGGBB` strings to match the storage
format used on AbstractTag (font_colour / bg_colour / border_colour).
"""
import colorsys
import random


def _hex_to_rgb(hex_colour):
    h = hex_colour.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(r)))),
        max(0, min(255, int(round(g)))),
        max(0, min(255, int(round(b)))),
    )


def _relative_luminance(hex_colour):
    """WCAG 2.x relative luminance. Returns a float in [0, 1].
    See https://www.w3.org/TR/WCAG20/#relativeluminancedef."""
    def _channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hex_colour)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def random_bg_colour(rng=None):
    """Random `#RRGGBB` biased toward saturated mid-lightness so neither
    black nor white text is forced into a bad contrast corner."""
    rng = rng or random
    h = rng.random()
    s = rng.uniform(0.45, 0.85)
    l = rng.uniform(0.30, 0.70)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return _rgb_to_hex(r * 255, g * 255, b * 255)


def readable_font_colour(bg_hex):
    """Pick #000000 or #ffffff based on which has higher contrast vs bg.
    Threshold 0.5 on relative luminance is a good rough cut for badges."""
    return "#000000" if _relative_luminance(bg_hex) > 0.5 else "#ffffff"


def derive_border_colour(bg_hex, shift=0.18, rng=None):
    """Border = bg shifted in HLS lightness by `shift`. Direction is chosen
    so the border stays inside [0, 1] — i.e. dark bgs get a lighter
    border, light bgs get a darker one. Visible without screaming."""
    r, g, b = _hex_to_rgb(bg_hex)
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    new_l = l - shift if l > 0.5 else l + shift
    new_l = max(0.05, min(0.95, new_l))
    nr, ng, nb = colorsys.hls_to_rgb(h, new_l, s)
    return _rgb_to_hex(nr * 255, ng * 255, nb * 255)


def randomize_palette(rng=None):
    """Return (bg, font, border) hex strings as a coherent set."""
    bg = random_bg_colour(rng=rng)
    return bg, readable_font_colour(bg), derive_border_colour(bg, rng=rng)
