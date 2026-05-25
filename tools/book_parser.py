import re

from app.models import \
    Chapter, Character

_TAG_RE = re.compile(r'<[^>]+>')


def strip_html_tags(text):
    """Strip HTML tags out of scraped chapter content, replacing each with a
    space so adjacent words don't get glued together."""
    if not text:
        return ""
    return _TAG_RE.sub(' ', text)


_WS_RE = re.compile(r'\s+')


def normalize_snippet(s):
    """Collapse all whitespace runs to a single space and strip ends.

    The exclusion fingerprint stored in the DB came from a browser
    form submission, which normalises newlines (\\r\\n → \\n) and
    may collapse some whitespace; the render-time fingerprint comes
    straight out of the chapter content via strip_html_tags(), which
    preserves whatever was there. Without this normaliser the two
    sides can disagree on a single character and the exclusion lookup
    misses, leaving the "excluded" snippet still tagged in the prose
    and still counted in the admin live pool. Idempotent, so safe to
    call on both sides."""
    if not s:
        return ''
    return _WS_RE.sub(' ', s).strip()


def load_match_exclusions(chapter_id, target_type, target_id):
    """Return the set of (before, match, after) fingerprints excluded
    for this (chapter, target). Empty set when nothing's excluded —
    safe to call always. Fingerprints are whitespace-normalised so
    the lookup is robust against newline / multi-space drift between
    save and render (see normalize_snippet docstring).

    Imported lazily because tools.book_parser is reachable from CLI
    contexts where the Flask app isn't bound yet."""
    from app.models import MatchExclusion
    rows = MatchExclusion.query.filter_by(
        chapter_id=chapter_id,
        target_type=target_type,
        target_id=target_id,
    ).all()
    return {(
        normalize_snippet(r.before_snippet),
        normalize_snippet(r.match_text),
        normalize_snippet(r.after_snippet),
    ) for r in rows}


def find_location_mentions(chapter, location, context_chars=60, limit=None, exclusions=None):
    """Same shape as find_event_mentions but for Location.

    If `exclusions` (a set of (before, match, after) fingerprints) is
    passed, any match whose fingerprint is in the set is skipped. The
    admin location-associations page uses this to hide snippets the
    admin has marked as bad."""
    needles = [location.name]
    for alias in (location.aliases or '').split(','):
        alias = alias.strip()
        if alias and alias != location.name:
            needles.append(alias)
    needles = [n for n in needles if n]
    if not needles:
        return []

    content = strip_html_tags(chapter.content)
    pattern = build_needle_pattern(needles)

    mentions = []
    for m in pattern.finditer(content):
        start, end = m.start(), m.end()
        before = content[max(0, start - context_chars):start]
        after = content[end:end + context_chars]
        if start - context_chars > 0:
            before = before.split(' ', 1)[1] if ' ' in before else before
            before = '…' + before.lstrip()
        if end + context_chars < len(content):
            after = after.rsplit(' ', 1)[0] if ' ' in after else after
            after = after.rstrip() + '…'
        match_text = m.group(0)
        if exclusions:
            fp = (
                normalize_snippet(before),
                normalize_snippet(match_text),
                normalize_snippet(after),
            )
            if fp in exclusions:
                continue
        mentions.append({
            'start': start,
            'before': before,
            'match': match_text,
            'after': after,
        })
        if limit is not None and len(mentions) >= limit:
            break
    return mentions


def find_event_mentions(chapter, event, context_chars=60, limit=None):
    """Same shape as find_character_mentions but uses Event.name +
    Event.aliases (comma-delimited keywords) for the needle list.

    Events don't have a `courtesty_name` field, so we collect labels
    inline rather than going through get_all_name_labels()."""
    needles = [event.name]
    for alias in (event.aliases or '').split(','):
        alias = alias.strip()
        if alias and alias != event.name:
            needles.append(alias)
    needles = [n for n in needles if n]
    if not needles:
        return []

    content = strip_html_tags(chapter.content)
    pattern = build_needle_pattern(needles)

    mentions = []
    for m in pattern.finditer(content):
        start, end = m.start(), m.end()
        before = content[max(0, start - context_chars):start]
        after = content[end:end + context_chars]
        if start - context_chars > 0:
            before = before.split(' ', 1)[1] if ' ' in before else before
            before = '…' + before.lstrip()
        if end + context_chars < len(content):
            after = after.rsplit(' ', 1)[0] if ' ' in after else after
            after = after.rstrip() + '…'
        mentions.append({
            'start': start,
            'before': before,
            'match': m.group(0),
            'after': after,
        })
        if limit is not None and len(mentions) >= limit:
            break
    return mentions


def find_character_mentions(chapter, character, context_chars=60, limit=None):
    """Return a list of mention dicts for `character` in `chapter`.

    Each mention is {'before', 'match', 'after', 'start'} extracted from the
    chapter content with HTML tags stripped (so the admin sees prose, not
    markup). `limit` caps the number returned per character."""
    needles = [n for n in character.get_all_name_labels() if n]
    if not needles:
        return []

    content = strip_html_tags(chapter.content)
    pattern = build_needle_pattern(needles)

    mentions = []
    for m in pattern.finditer(content):
        start, end = m.start(), m.end()
        before = content[max(0, start - context_chars):start]
        after = content[end:end + context_chars]
        # Trim partial words at the edges of the context window for readability.
        if start - context_chars > 0:
            before = before.split(' ', 1)[1] if ' ' in before else before
            before = '…' + before.lstrip()
        if end + context_chars < len(content):
            after = after.rsplit(' ', 1)[0] if ' ' in after else after
            after = after.rstrip() + '…'
        mentions.append({
            'start': start,
            'before': before,
            'match': m.group(0),
            'after': after,
        })
        if limit is not None and len(mentions) >= limit:
            break
    return mentions


def count_mentions_per_character(chapters, characters):
    """Return {character_id: total_mentions_across_chapters}.

    HTML is stripped from each chapter content once up front so we don't
    pay that cost per character. Each character's `get_all_name_labels()`
    becomes one regex; we scan every chapter and sum findall() counts."""
    stripped = [strip_html_tags(c.content) for c in chapters]
    counts = {}
    for character in characters:
        needles = [n for n in character.get_all_name_labels() if n]
        if not needles:
            counts[character.id] = 0
            continue
        pattern = build_needle_pattern(needles)
        counts[character.id] = sum(
            len(pattern.findall(text)) for text in stripped
        )
    return counts


def get_characters_for_chapter(chapter_id):
    chapter = Chapter.query.get_or_404(chapter_id)

    # Prefer the precomputed M2M (populated by `flask build-chapter-character-association`).
    cached = list(chapter.characters)
    if cached:
        return cached

    return scan_chapter_for_characters(chapter)


def scan_chapter_for_characters(chapter):
    """Regex-scan the chapter text against every character's names/aliases.

    Slow — O(N_characters) regex compilations + scans per chapter. Used as
    a fallback when the chapter_character association table is empty.
    """
    all_characters = Character.query.all()
    chapter_characters = set()

    for character in all_characters:
        name_needles = character.get_all_name_labels()
        pattern = build_needle_pattern(name_needles)
        if pattern.search(chapter.content):
            chapter_characters.add(character)

    return list(chapter_characters)

def build_needle_pattern(name_needles):
    return re.compile(r'\b(' + '|'.join(map(re.escape, name_needles)) + r')(?=\s|,|\.|\!|\?|\'|;|"|-)')

def build_name_ref_html(character, duplicate_warning_url=None, display_text=None):
    """Emit the inline character-ref span. Includes:

      * The default pill styling inline so no-JS renders / first paint
        still look right.
      * data-bg / data-font / data-border attributes carrying the same
        three colours regardless of whether the character has a primary
        faction. The chapter-page style switcher (chapter_style.js)
        uses these to re-style the span on the fly without round-
        tripping to the server.
      * A shared `text-ref` class so future inline-tagged data types
        (events, locations) can opt into the same style switcher by
        adding the class.
      * When `duplicate_warning_url` is provided, a small red
        circle-exclamation anchor follows the pill — for admins, this
        signals that more than one character in the chapter shares this
        name, and links to the Character/Chapter Association editor so
        the admin can pick the right one.
      * `display_text` overrides the pill text; default is
        `character.name`. The chapter renderer passes the matched
        alias (courtesy name, nickname, …) so the inline pill reads
        the same word the prose uses, while still linking to the
        canonical character via data-character-id.
    """
    if character.primary_faction is not None:
        f = character.primary_faction
        bg = f.bg_colour if f.bg_colour not in ["", f.default_colour] else "#000000"
        font = f.font_colour or "#ffffff"
        border = f.border_colour if f.border_colour not in ["", f.default_colour] else bg
        faction_attr = f"data-faction-id='{f.id}' "
    else:
        # No faction → plain outline pill (white fill, black text + border).
        # Same three colours go into the data attributes so the style
        # switcher's "readable text colour" picker has something to work
        # with.
        bg, font, border = "#ffffff", "#000000", "#000000"
        faction_attr = ""

    style = (
        f"background-color:{bg};"
        f"color:{font};"
        f"border:2px solid {border};"
    )
    label = display_text if display_text is not None else character.name
    pill = (
        f"<span class='text-ref character-ref badge rounded-pill' "
        f"data-character-id='{character.id}' "
        f"{faction_attr}"
        f"data-bg='{bg}' data-font='{font}' data-border='{border}' "
        f"style='{style}'>{label}</span>"
    )
    if duplicate_warning_url:
        # No-underline link so the icon doesn't grow a baseline rule.
        # title= drives the browser tooltip; aria-label echoes it for
        # screen readers.
        msg = f'Multiple characters named &quot;{character.name}&quot; in this chapter — click to resolve'
        pill += (
            f"<a href='{duplicate_warning_url}' "
            f"class='character-dup-warning text-danger ms-1 text-decoration-none' "
            f"title='{msg}' aria-label='{msg}'>"
            f"<i class='fa-solid fa-circle-exclamation' aria-hidden='true'></i>"
            f"</a>"
        )
    return pill


def build_event_ref_html(event, match_text=None):
    """Inline span for an event mention in chapter prose. Plain black
    underlined text, clickable — chapter.js wires it to open the
    Events accordion in the sidebar and scroll to the matching item.

    `match_text` lets the caller render the exact substring that matched
    (an alias) instead of the event's canonical name."""
    label = match_text if match_text is not None else event.name
    return (
        f"<span class='event-ref' data-event-id='{event.id}'>"
        f"{label}</span>"
    )


def build_location_ref_html(location, match_text=None):
    """Same as build_event_ref_html but for Location."""
    label = match_text if match_text is not None else location.name
    return (
        f"<span class='location-ref' data-location-id='{location.id}'>"
        f"{label}</span>"
    )


def get_event_labels(event):
    """Name + aliases for an event (used as needles when tagging the
    event's mentions in chapter prose)."""
    labels = [event.name]
    for alias in (event.aliases or '').split(','):
        alias = alias.strip()
        if alias and alias != event.name:
            labels.append(alias)
    return [l for l in labels if l]


def get_location_labels(location):
    """Name + aliases for a location, mirroring get_event_labels."""
    labels = [location.name]
    for alias in (location.aliases or '').split(','):
        alias = alias.strip()
        if alias and alias != location.name:
            labels.append(alias)
    return [l for l in labels if l]