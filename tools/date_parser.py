"""Free-form date string → year-range parser.

Used by the timeline view to place chapters, events, and character
lifelines on a numeric axis. Every datestring resolves to a
`(year_min, year_max)` pair of *floats* (year number + fractional
position within the year) or `None` if it can't be parsed.

Pair semantics:
- `year_min == year_max` is impossible by construction — every parse
  returns a non-empty span, even if it's just a single day or a single
  month, so downstream renderers can always treat the result as a range.
- For a single instant ("February 3, 168"), the span covers that day.
- For a range ("168-172"), the span covers the full range inclusively.
- For a fuzzy qualifier ("circa 168"), the span is widened beyond the
  literal year to express the uncertainty.

BC dates use astronomical year numbering — BC 1 → 0, BC 2 → -1, etc.
The RotK era is comfortably AD so the BC branch is small but kept for
ancestral-home / pre-Han characters.
"""
import re


_MONTHS = {
    'january': 1, 'jan': 1,
    'february': 2, 'feb': 2,
    'march': 3, 'mar': 3,
    'april': 4, 'apr': 4,
    'may': 5,
    'june': 6, 'jun': 6,
    'july': 7, 'jul': 7,
    'august': 8, 'aug': 8,
    'september': 9, 'sep': 9, 'sept': 9,
    'october': 10, 'oct': 10,
    'november': 11, 'nov': 11,
    'december': 12, 'dec': 12,
}

_SEASONS = {
    # Northern-hemisphere seasons. Approximations — the goal is to anchor
    # "Winter 208" to roughly Dec-Feb so the timeline marker lands in the
    # right neighbourhood, not to be astronomically precise.
    'spring': (3, 5),
    'summer': (6, 8),
    'autumn': (9, 11),
    'fall':   (9, 11),
    'winter': (12, 12),
}

# Cumulative day-of-year for the start of each month (non-leap).
_MONTH_START_DOY = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def _era_to_sign(token):
    if token is None:
        return 1
    t = token.lower().strip().rstrip('.').replace(' ', '')
    if t in ('bc', 'bce'):
        return -1
    return 1


def _to_astro_year(year, sign):
    """Convert (positive year, sign) → astronomical year number.

    AD 168 → 168. BC 168 → -167 (since BC 1 == year 0)."""
    if sign < 0:
        return -(year - 1)
    return year


def _year_span(astro_year):
    """Span covering a whole year, [Y, Y+1)."""
    return (float(astro_year), float(astro_year + 1))


def _month_span(astro_year, month):
    """Span covering a whole month."""
    start = astro_year + _MONTH_START_DOY[month] / 365.0
    end_doy = 365 if month == 12 else _MONTH_START_DOY[month + 1]
    end = astro_year + end_doy / 365.0
    return (start, end)


def _day_span(astro_year, month, day):
    """Span covering a single day. ~1/365th wide so it has positive
    extent for downstream renderers but doesn't visually dominate."""
    doy = _MONTH_START_DOY[month] + max(1, day) - 1
    start = astro_year + doy / 365.0
    end = astro_year + (doy + 1) / 365.0
    return (start, end)


def _apply_qualifier(span, qualifier):
    """Tighten or widen a span based on a leading qualifier word.

    early/mid/late shrink to the first/middle/last third of the span.
    circa / approx / ~ pad outward by ~3 years on each side."""
    if not qualifier:
        return span
    q = qualifier.lower().strip().rstrip('.')
    lo, hi = span
    width = hi - lo
    if q in ('early',):
        return (lo, lo + width / 3.0)
    if q in ('mid', 'middle'):
        return (lo + width / 3.0, lo + 2.0 * width / 3.0)
    if q in ('late',):
        return (lo + 2.0 * width / 3.0, hi)
    if q in ('circa', 'c', 'ca', 'approx', 'approximately', 'around', '~', '?'):
        pad = 3.0
        return (lo - pad, hi + pad)
    return span


# Word-tokens we strip from the input to make pattern matching simpler.
_NOISE = re.compile(r'\b(?:the\s+year\s+of|year\s+of|in|of|on|year)\b', re.IGNORECASE)
_WS = re.compile(r'\s+')

_QUALIFIERS = r'(?:circa|approximately|approx\.?|around|early|mid|middle|late|c\.?|ca\.?|~|\?)'
# `\s*` (not `\s+`) so "c.208" without a space still parses. The
# trailing `\.?\s*` swallows any punctuation between qualifier and year.
_QUALIFIER_RE = re.compile(rf'^\s*({_QUALIFIERS})\s*', re.IGNORECASE)

_ERA = r'(?:AD|A\.?D\.?|CE|BC|B\.?C\.?|BCE)'
_YEAR = r'\d{1,4}'
_MONTH_NAMES = '|'.join(sorted(_MONTHS.keys(), key=len, reverse=True))
_SEASON_NAMES = '|'.join(_SEASONS.keys())

# Patterns, tried in order. Each must consume the entire (cleaned) input
# via fullmatch.
_PATTERNS = [
    # "February 3, 168 AD" / "February 3 168" / "Feb 3 168 BC"
    re.compile(
        rf'(?:({_ERA})\s+)?({_MONTH_NAMES})\s+(\d{{1,2}})[,]?\s+({_YEAR})\s*({_ERA})?',
        re.IGNORECASE,
    ),
    # "3 February 168 AD"
    re.compile(
        rf'(?:({_ERA})\s+)?(\d{{1,2}})\s+({_MONTH_NAMES})\s+({_YEAR})\s*({_ERA})?',
        re.IGNORECASE,
    ),
    # "February 168 AD"
    re.compile(
        rf'(?:({_ERA})\s+)?({_MONTH_NAMES})\s+({_YEAR})\s*({_ERA})?',
        re.IGNORECASE,
    ),
    # "Winter 208 AD"
    re.compile(
        rf'(?:({_ERA})\s+)?({_SEASON_NAMES})\s+({_YEAR})\s*({_ERA})?',
        re.IGNORECASE,
    ),
    # "168-172 AD" / "168 AD - 172 AD" / "168 BC - 167 BC" / "168–172"
    # / "168/172"  -- includes en/em dash, slash, and the word "to".
    re.compile(
        rf'(?:({_ERA})\s+)?({_YEAR})\s*({_ERA})?\s*(?:-|–|—|to|/)\s*({_YEAR})\s*({_ERA})?',
        re.IGNORECASE,
    ),
    # "168 AD" / "AD 168" / "168 BC" / "168"
    re.compile(
        rf'(?:({_ERA})\s+)?({_YEAR})\s*({_ERA})?',
        re.IGNORECASE,
    ),
]


def parse_date_range(s):
    """Parse a free-form date string into a `(year_min, year_max)` float
    pair, or return None if the string doesn't match any known shape.

    The returned span is *always* positive-width — even a single-day
    parse produces a ~1/365 year span — so renderers can treat the
    output uniformly without special-casing point dates.

    Empty / whitespace / None all return None."""
    if not s:
        return None
    text = str(s).strip()
    if not text:
        return None

    text = _NOISE.sub(' ', text)
    text = _WS.sub(' ', text).strip()

    qualifier = None
    m = _QUALIFIER_RE.match(text)
    if m:
        qualifier = m.group(1)
        text = text[m.end():].strip()

    for pat in _PATTERNS:
        m = pat.fullmatch(text)
        if not m:
            continue
        groups = list(m.groups())
        span = _extract_span(pat, groups)
        if span is None:
            continue
        return _apply_qualifier(span, qualifier)

    return None


def _extract_span(pat, groups):
    """Per-pattern dispatch — figure out which pattern matched by group
    arity and shape, then build the appropriate span."""
    g = groups

    # 5 groups + month name → month-day-year shape
    # (era1, month, day, year, era2)
    if len(g) == 5 and g[1] and g[1].lower() in _MONTHS and g[2] and g[2].isdigit() and len(g[2]) <= 2:
        era = g[0] or g[4]
        month = _MONTHS[g[1].lower()]
        try:
            day = int(g[2])
            year = int(g[3])
        except (TypeError, ValueError):
            return None
        astro = _to_astro_year(year, _era_to_sign(era))
        return _day_span(astro, month, day)

    # 5 groups + day-month-year shape
    # (era1, day, month, year, era2)
    if len(g) == 5 and g[2] and g[2].lower() in _MONTHS and g[1] and g[1].isdigit():
        era = g[0] or g[4]
        try:
            day = int(g[1])
            month = _MONTHS[g[2].lower()]
            year = int(g[3])
        except (TypeError, ValueError, KeyError):
            return None
        astro = _to_astro_year(year, _era_to_sign(era))
        return _day_span(astro, month, day)

    # 4 groups + month name → month-year shape (no day)
    # (era1, month, year, era2)
    if len(g) == 4 and g[1] and g[1].lower() in _MONTHS:
        era = g[0] or g[3]
        month = _MONTHS[g[1].lower()]
        try:
            year = int(g[2])
        except (TypeError, ValueError):
            return None
        astro = _to_astro_year(year, _era_to_sign(era))
        return _month_span(astro, month)

    # 4 groups + season name → season-year shape
    if len(g) == 4 and g[1] and g[1].lower() in _SEASONS:
        era = g[0] or g[3]
        m_lo, m_hi = _SEASONS[g[1].lower()]
        try:
            year = int(g[2])
        except (TypeError, ValueError):
            return None
        astro = _to_astro_year(year, _era_to_sign(era))
        lo, _ = _month_span(astro, m_lo)
        _, hi = _month_span(astro, m_hi)
        return (lo, hi)

    # 5 groups + two years → range shape
    # (era1, year_lo, era2, year_hi, era3)
    if len(g) == 5 and g[1] and g[1].isdigit() and g[3] and g[3].isdigit():
        era_lo = g[0] or g[2]
        era_hi = g[4] or era_lo
        try:
            y_lo = int(g[1])
            y_hi = int(g[3])
        except (TypeError, ValueError):
            return None
        astro_lo = _to_astro_year(y_lo, _era_to_sign(era_lo))
        astro_hi = _to_astro_year(y_hi, _era_to_sign(era_hi))
        if astro_hi < astro_lo:
            astro_lo, astro_hi = astro_hi, astro_lo
        lo, _ = _year_span(astro_lo)
        _, hi = _year_span(astro_hi)
        return (lo, hi)

    # 3 groups → bare year shape
    # (era1, year, era2)
    if len(g) == 3 and g[1] and g[1].isdigit():
        era = g[0] or g[2]
        try:
            year = int(g[1])
        except (TypeError, ValueError):
            return None
        astro = _to_astro_year(year, _era_to_sign(era))
        return _year_span(astro)

    return None
