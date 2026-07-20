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
- For a fuzzy qualifier ("circa 168", "220?"), the span is widened
  beyond the literal year to express the uncertainty.

Grammar (informal): the input is at most `SIDE sep SIDE`, where `sep`
is a dash / "to" / slash, and each SIDE is `POINT` or `POINT or POINT`
(the "or" unions the two points). A POINT is any of the single-date
shapes (year, month year, day month year, month day year, season year,
each with optional era tokens) — and inside a range a POINT may omit
its year and/or era, which are borrowed from the other side:

    "December 215 - April 216"     both sides full
    "February 190 - 191"           month-year -> bare year
    "3 February - 2 March 200"     left borrows the year 200
    "c. August - December 219"     left borrows 219; circa pads
    "500-401 BCE"                  left borrows the BCE era
    "January or February 213 - July 214"

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
    circa / approx / ~ / ? pad outward by ~3 years on each side."""
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

# "190s" / "90s" / "190s BC" — a decade.
_DECADE_RE = re.compile(
    rf'^(?:({_ERA})\s+)?(\d{{1,3}}0)s\s*({_ERA})?$', re.IGNORECASE)

# Range separator between the two SIDEs: any dash (ASCII or unicode,
# normalised below), "to", or a slash. Spaces optional so "168-172"
# and "December 215 - April 216" both split.
_RANGE_SEP = re.compile(r'\s*(?:-|\bto\b|/)\s*', re.IGNORECASE)
_OR_SEP = re.compile(r'\s+or\s+', re.IGNORECASE)

# ---- endpoint (POINT) grammar ------------------------------------------
# Each pattern must fullmatch one endpoint. The year is OPTIONAL in the
# month/day/season shapes — a missing year is borrowed from the other
# side of a range. Era tokens may sit before the whole thing, directly
# before the year ("6 October AD 23"), or after the year.
_P_MONTH_DAY = re.compile(     # "February 3 168" / "February 3" (+eras)
    rf'(?:({_ERA})\s+)?({_MONTH_NAMES})\s+(\d{{1,2}})'
    rf'(?:\s+(?:({_ERA})\s+)?({_YEAR})\s*({_ERA})?)?',
    re.IGNORECASE)
_P_DAY_MONTH = re.compile(     # "3 February 168" / "3 February" (+eras)
    rf'(?:({_ERA})\s+)?(\d{{1,2}})\s+({_MONTH_NAMES})'
    rf'(?:\s+(?:({_ERA})\s+)?({_YEAR})\s*({_ERA})?)?',
    re.IGNORECASE)
_P_MONTH_YEAR = re.compile(    # "February 168" / "February" (+eras)
    rf'(?:({_ERA})\s+)?({_MONTH_NAMES})'
    rf'(?:\s+(?:({_ERA})\s+)?({_YEAR})\s*({_ERA})?)?',
    re.IGNORECASE)
_P_SEASON = re.compile(        # "Winter 208" / "Winter" (+eras)
    rf'(?:({_ERA})\s+)?({_SEASON_NAMES})'
    rf'(?:\s+(?:({_ERA})\s+)?({_YEAR})\s*({_ERA})?)?',
    re.IGNORECASE)
_P_YEAR = re.compile(          # "168" / "AD 168" / "168 BC"
    rf'(?:({_ERA})\s+)?({_YEAR})\s*({_ERA})?',
    re.IGNORECASE)


class _Point:
    """One parsed endpoint: some of (era, year, month, day, season)."""
    __slots__ = ('era', 'year', 'month', 'day', 'season')

    def __init__(self, era=None, year=None, month=None, day=None,
                 season=None):
        self.era = era
        self.year = year
        self.month = month
        self.day = day
        self.season = season

    def span(self):
        """(lo, hi) span — requires `year` to be resolved."""
        if self.year is None:
            return None
        astro = _to_astro_year(self.year, _era_to_sign(self.era))
        if self.season is not None:
            m_lo, m_hi = _SEASONS[self.season]
            lo, _ = _month_span(astro, m_lo)
            _, hi = _month_span(astro, m_hi)
            return (lo, hi)
        if self.month is not None and self.day is not None:
            return _day_span(astro, self.month, self.day)
        if self.month is not None:
            return _month_span(astro, self.month)
        return _year_span(astro)


def _parse_point(text):
    """Parse one endpoint into a _Point (year may be None), or None."""
    text = text.strip()
    if not text:
        return None

    m = _P_MONTH_DAY.fullmatch(text)
    if m:
        era = m.group(1) or m.group(4) or m.group(6)
        day = int(m.group(3))
        if 1 <= day <= 31:
            year = int(m.group(5)) if m.group(5) else None
            return _Point(era=era, year=year,
                          month=_MONTHS[m.group(2).lower()], day=day)

    m = _P_DAY_MONTH.fullmatch(text)
    if m:
        era = m.group(1) or m.group(4) or m.group(6)
        day = int(m.group(2))
        if 1 <= day <= 31:
            year = int(m.group(5)) if m.group(5) else None
            return _Point(era=era, year=year,
                          month=_MONTHS[m.group(3).lower()], day=day)

    m = _P_MONTH_YEAR.fullmatch(text)
    if m:
        era = m.group(1) or m.group(3) or m.group(5)
        year = int(m.group(4)) if m.group(4) else None
        return _Point(era=era, year=year,
                      month=_MONTHS[m.group(2).lower()])

    m = _P_SEASON.fullmatch(text)
    if m:
        era = m.group(1) or m.group(3) or m.group(5)
        year = int(m.group(4)) if m.group(4) else None
        return _Point(era=era, year=year, season=m.group(2).lower())

    m = _P_YEAR.fullmatch(text)
    if m:
        era = m.group(1) or m.group(3)
        return _Point(era=era, year=int(m.group(2)))

    return None


def _parse_side(text):
    """Parse one SIDE of a range: a POINT, or "POINT or POINT" (the
    alternatives merge into the (points list); each keeps its own
    month/day, missing years borrow later)."""
    parts = _OR_SEP.split(text)
    points = []
    for part in parts:
        p = _parse_point(part)
        if p is None:
            return None
        points.append(p)
    # Alternatives borrow year/era from each other ("January or
    # February 213" — January picks up 213).
    year = next((p.year for p in points if p.year is not None), None)
    era = next((p.era for p in points if p.era is not None), None)
    for p in points:
        if p.year is None:
            p.year = year
        if p.era is None:
            p.era = era
    return points


def _side_span(points):
    """Union span across a SIDE's alternative points."""
    spans = [p.span() for p in points]
    if any(s is None for s in spans):
        return None
    return (min(s[0] for s in spans), max(s[1] for s in spans))


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

    # Normalise: unicode dashes → '-', commas → space (they only ever
    # separate a day/month from the year), unicode thin spaces → space.
    text = re.sub(r'[–—−]', '-', text)
    text = text.replace(',', ' ')
    text = _NOISE.sub(' ', text)
    text = _WS.sub(' ', text).strip()

    qualifier = None
    m = _QUALIFIER_RE.match(text)
    if m:
        qualifier = m.group(1)
        text = text[m.end():].strip()
    # Trailing "?" ("220?") marks uncertainty — same padding as circa.
    # Only when something else remains: a bare "?" stays unparseable.
    if text.endswith('?'):
        stripped = text.rstrip('?').strip()
        if stripped:
            text = stripped
            qualifier = qualifier or '?'

    if not text:
        return None

    # Decade — "90s" / "190s BC".
    m = _DECADE_RE.fullmatch(text)
    if m:
        era = m.group(1) or m.group(3)
        astro = _to_astro_year(int(m.group(2)), _era_to_sign(era))
        span = (float(astro), float(astro + 10))
        return _apply_qualifier(span, qualifier)

    # Try RANGE: exactly two SIDEs around one separator. A dash may also
    # be the year-range inside a single side ("168-172" splits fine too:
    # both sides are bare-year points).
    span = None
    parts = _RANGE_SEP.split(text)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        left = _parse_side(parts[0])
        right = _parse_side(parts[1])
        if left is not None and right is not None:
            # Borrow year / era across the range for sides missing them
            # ("3 February - 2 March 200", "500-401 BCE").
            year = next((p.year for side in (right, left) for p in side
                         if p.year is not None), None)
            era = next((p.era for side in (right, left) for p in side
                        if p.era is not None), None)
            for side in (left, right):
                for p in side:
                    if p.year is None:
                        p.year = year
                    if p.era is None:
                        p.era = era
            lo_span = _side_span(left)
            hi_span = _side_span(right)
            if lo_span is not None and hi_span is not None:
                lo, hi = lo_span[0], hi_span[1]
                if hi < lo:
                    lo, hi = hi_span[0], lo_span[1]
                span = (lo, hi)

    # Fall back to a single POINT (which must carry its own year).
    if span is None:
        points = _parse_side(text)
        if points is not None:
            span = _side_span(points)

    if span is None:
        return None
    return _apply_qualifier(span, qualifier)
