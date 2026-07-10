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


def strip_and_normalize_with_html_map(html):
    """Return (normalized_text, positions) where normalized_text is
    the whitespace-normalised strip of `html` (tags removed, all
    whitespace runs collapsed to a single space) and positions[i]
    is the html index of the character that produced
    normalized_text[i].

    Used by apply_hidden_snippets to find each hidden fingerprint's
    location in the stripped text and map back to the html index for
    removal / wrapping. Different from `strip_html_tags` which does
    not track positions.
    """
    if not html:
        return '', []
    out_chars = []
    positions = []
    last_was_ws = True  # collapse leading whitespace
    i = 0
    n = len(html)
    while i < n:
        c = html[i]
        if c == '<':
            # Skip the tag; treat as one whitespace boundary.
            if not last_was_ws:
                out_chars.append(' ')
                positions.append(i)
                last_was_ws = True
            j = html.find('>', i + 1)
            if j == -1:
                break
            i = j + 1
        elif c.isspace():
            if not last_was_ws:
                out_chars.append(' ')
                positions.append(i)
                last_was_ws = True
            i += 1
        else:
            out_chars.append(c)
            positions.append(i)
            last_was_ws = False
            i += 1
    # Trim trailing whitespace we accumulated.
    while out_chars and out_chars[-1] == ' ':
        out_chars.pop()
        positions.pop()
    return ''.join(out_chars), positions


def _hidden_snippet_context(normalized, idx, match_len, context_chars=60):
    """Same before/after trim algorithm as find_*_mentions, applied
    to `normalized` at position idx for a match of `match_len` chars.
    Returns the trimmed (before, after) pair with ellipses at truncation
    edges — the fingerprint the client sent at save time and the one
    the server recomputes at render time must both use this."""
    before = normalized[max(0, idx - context_chars):idx]
    end = idx + match_len
    after = normalized[end:end + context_chars]
    if idx - context_chars > 0:
        before = before.split(' ', 1)[1] if ' ' in before else before
        before = '…' + before.lstrip()
    if end + context_chars < len(normalized):
        after = after.rsplit(' ', 1)[0] if ' ' in after else after
        after = after.rstrip() + '…'
    return before, after


def apply_hidden_snippets(html, hidden_rows, admin=False):
    """Given raw chapter HTML and a list of ChapterHiddenSnippet rows,
    return HTML with each snippet either removed (public reader —
    admin=False) or wrapped in `<s class="hidden-snippet" data-hidden-id="…">`
    (admin editor — admin=True).

    Match location is found via the (before, match_text, after)
    fingerprint on the whitespace-normalised strip of the html; the
    position map from `strip_and_normalize_with_html_map` translates
    the found normalised index back to html positions for the actual
    removal/wrap.

    Rows whose fingerprint no longer matches anything in the current
    content (e.g. because the chapter's been rescraped and the ~60-char
    context shifted) are silently skipped — the row stays in the DB
    as an orphan, admin can clean up via the UI.
    """
    if not hidden_rows or not html:
        return html
    normalized, positions = strip_and_normalize_with_html_map(html)
    if not normalized:
        return html

    ranges = []  # (html_start, html_end, hidden_id)
    for row in hidden_rows:
        target = (row.match_text or '').strip()
        if not target:
            continue
        # Normalise the target too so a target with weird whitespace
        # compares apples-to-apples against normalized content.
        target = _WS_RE.sub(' ', target)
        stored_before = row.before_snippet or ''
        stored_after = row.after_snippet or ''
        start = 0
        while True:
            idx = normalized.find(target, start)
            if idx < 0:
                break
            before, after = _hidden_snippet_context(normalized, idx, len(target))
            if before == stored_before and after == stored_after:
                html_start = positions[idx]
                # +1 to include the last matched char in the range
                html_end = positions[idx + len(target) - 1] + 1
                ranges.append((html_start, html_end, row.id))
                break
            start = idx + 1

    if not ranges:
        return html

    # Sort ascending by start so we can walk html once, emitting
    # segments in order.
    ranges.sort(key=lambda r: r[0])
    out = []
    cursor = 0
    for start, end, hidden_id in ranges:
        # Guard against overlapping ranges (rare — same fingerprint
        # matched twice somehow). Skip anything that starts before
        # the previous range's end.
        if start < cursor:
            continue
        out.append(html[cursor:start])
        if admin:
            out.append(f'<s class="hidden-snippet" data-hidden-id="{hidden_id}">')
            out.append(html[start:end])
            out.append('</s>')
        # else: skip the range (public view — hidden means gone)
        cursor = end
    out.append(html[cursor:])
    return ''.join(out)


_P_RE = re.compile(r'(<p\b[^>]*>)(.*?)(</p>)', re.DOTALL | re.IGNORECASE)


def normalize_paragraph_text(text):
    """Whitespace-normalised paragraph text used as an Annotation's
    `section_text` fingerprint. Same normalization on save + render
    so equality-lookup works reliably."""
    if not text:
        return ''
    return _WS_RE.sub(' ', text).strip()


def annotation_section_hash(text):
    """Short SHA-256 hash of the normalised text — used as a DOM-safe
    key on annotation icons and in the client-side lookup dict."""
    import hashlib
    return hashlib.sha256(normalize_paragraph_text(text).encode('utf-8')).hexdigest()[:16]


def inject_annotation_icons(html, annotations_by_section, is_admin):
    """Walk each <p> in `html` and inject one annotation icon at the
    very start of the paragraph.

    Icon rules:
      - Public reader: black icon iff the section has ≥1 public
        annotation. Nothing otherwise.
      - Admin: red icon (+ exclamation) iff the section has ≥1
        private annotation; else black iff public ones exist; else
        BLUE "add" icon (hidden by default, CSS reveals it on
        <p>:hover so admin can start a new thread).
    """
    if not html:
        return html

    def process(match):
        open_tag, inner, close_tag = match.group(1), match.group(2), match.group(3)
        section = normalize_paragraph_text(strip_html_tags(inner))
        anns = annotations_by_section.get(section) if annotations_by_section else None
        has_public = any(a.is_public for a in anns) if anns else False
        has_private = any(not a.is_public for a in anns) if anns else False

        # Public reader with no public annotations → no icon at all.
        if not is_admin and not has_public:
            return match.group(0)

        if is_admin and has_private:
            icon_class = 'annotation-icon annotation-icon-red'
            extra = '<i class="fa-solid fa-circle-exclamation text-danger ms-1" aria-hidden="true"></i>'
        elif has_public:
            icon_class = 'annotation-icon annotation-icon-black'
            extra = ''
        else:
            # Admin, no annotations yet → blue "add" affordance,
            # revealed on <p>:hover by CSS.
            icon_class = 'annotation-icon annotation-icon-blue annotation-icon-add'
            extra = ''

        section_hash = annotation_section_hash(inner) if anns else ''
        icon = (
            f'<a href="#" class="{icon_class}" '
            f'data-section-key="{section_hash}" '
            f'aria-label="Annotations">'
            f'<i class="fa-solid fa-note-sticky" aria-hidden="true"></i>{extra}</a> '
        )
        return f'{open_tag}{icon}{inner}{close_tag}'

    return _P_RE.sub(process, html)


def load_chapter_keywords(chapter_id, table_name, target_id_column):
    """Return {target_id: keyword_csv} for every association row in the
    given M2M table (chapter_character / event_chapter / chapter_location)
    that belongs to `chapter_id`. Result is the per-(chapter, target)
    keyword override list — the chapter renderer uses it instead of the
    global character.aliases / event.aliases / location.aliases.

    Imported lazily because tools.book_parser is reachable from CLI
    contexts where the Flask app isn't bound yet."""
    from app import db
    from sqlalchemy import text
    rows = db.session.execute(
        text(
            f"SELECT {target_id_column}, keywords FROM {table_name} "
            f"WHERE chapter_id = :cid"
        ),
        {'cid': chapter_id},
    ).all()
    return {row[0]: (row[1] or '') for row in rows}


def load_chapter_character_summaries(chapter_id):
    """Return {character_id: summary_text} for every chapter_character
    row belonging to `chapter_id`. Mirrors load_chapter_keywords but
    pulls the `summary` column added by migration 0017."""
    from app import db
    from sqlalchemy import text
    rows = db.session.execute(
        text(
            "SELECT character_id, summary FROM chapter_character "
            "WHERE chapter_id = :cid"
        ),
        {'cid': chapter_id},
    ).all()
    return {row[0]: (row[1] or '') for row in rows}


def split_keywords_csv(s):
    """Split a comma-delimited keyword string into a deduped, stripped
    list. Used by both the chapter render path and the admin association
    views to turn the stored `keywords` column into a needle list."""
    seen = set()
    out = []
    for part in (s or '').split(','):
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return out


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


def find_location_mentions(chapter, location, context_chars=60, limit=None, exclusions=None, needles=None):
    """Same shape as find_event_mentions but for Location.

    If `exclusions` (a set of (before, match, after) fingerprints) is
    passed, any match whose fingerprint is in the set is skipped. The
    admin location-associations page uses this to hide snippets the
    admin has marked as bad.

    `needles` overrides the default needle list (location.name +
    aliases) — used to pass per-(chapter, location) keywords."""
    if needles is None:
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


def find_event_mentions(chapter, event, context_chars=60, limit=None, exclusions=None, needles=None):
    """Same shape as find_character_mentions but for Event."""
    if needles is None:
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


def find_character_mentions(chapter, character, context_chars=60, limit=None, exclusions=None, needles=None):
    """Return a list of mention dicts for `character` in `chapter`.

    Each mention is {'before', 'match', 'after', 'start'} extracted from the
    chapter content with HTML tags stripped (so the admin sees prose, not
    markup). `limit` caps the number returned per character. `exclusions`
    is the same shape as in find_location_mentions / find_event_mentions:
    a set of whitespace-normalised (before, match, after) fingerprints that
    should be skipped (matches the per-snippet MatchExclusion table).

    `needles` overrides the default needle list (character.name +
    courtesy + aliases). The chapter-association admin and the chapter
    renderer pass per-(chapter, character) keywords here so each chapter
    can have its own keyword set independent of the character's global
    aliases."""
    if needles is None:
        needles = character.get_all_name_labels()
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
        # Trim partial words at the edges of the context window for readability.
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


def count_mentions_per_character(chapters, characters):
    """Return {character_id: total_mentions_across_book}, association-
    aware. For each character we walk only the chapters they're linked
    to via chapter_character, and use that pair's per-chapter `keywords`
    column as the needle set (falling back to the character's global
    name labels when the keywords column is still empty — pre-backfill
    data).

    This fixes the historic over-count where two characters with the
    same name (e.g. two "Lady Cao"s) were each credited with every
    "Lady Cao" mention anywhere in the book. Now each character only
    counts mentions in chapters they actually belong to.

    The `chapters` arg is the universe of Chapter rows to scan against;
    pre-loading all of them once is the efficient way to call this for
    bulk recounts. Single-character recounts pass the same full list —
    the inner loop only visits chapters the character is associated
    with, so unrelated chapters cost nothing per character."""
    from app import db
    from sqlalchemy import text

    if not characters:
        return {}

    chapters_by_id = {c.id: c for c in chapters}
    stripped_by_id = {cid: strip_html_tags(c.content) for cid, c in chapters_by_id.items()}

    # One query pulls every (character_id, chapter_id, keywords) row
    # we care about, grouped by character below.
    rows = db.session.execute(
        text(
            "SELECT character_id, chapter_id, keywords FROM chapter_character "
            "WHERE character_id = ANY(:cids)"
        ),
        {'cids': [c.id for c in characters]},
    ).all()
    assocs_by_char = {}
    for character_id, chapter_id, keywords in rows:
        assocs_by_char.setdefault(character_id, []).append((chapter_id, keywords or ''))

    counts = {}
    for character in characters:
        total = 0
        for chapter_id, kw_csv in assocs_by_char.get(character.id, []):
            stripped = stripped_by_id.get(chapter_id)
            if stripped is None:
                continue
            needles = split_keywords_csv(kw_csv)
            if not needles:
                # Backward-compat fallback: per-chapter keywords haven't
                # been seeded yet for this association. Use the
                # character's global labels so the count isn't zero.
                needles = [n for n in character.get_all_name_labels() if n]
            if not needles:
                continue
            pattern = build_needle_pattern(needles)
            total += len(pattern.findall(stripped))
        counts[character.id] = total
    return counts


def recount_character_book_mentions(character):
    """Recount one character's `book_mention_count` from scratch by
    re-querying their current chapter_character associations + per-
    chapter keywords. Sets the new value on the character row but
    leaves the commit to the caller — usually the same transaction
    that mutated the association in the first place.

    Returns the freshly-computed integer."""
    chapters = Chapter.query.all()
    counts = count_mentions_per_character(chapters, [character])
    character.book_mention_count = counts.get(character.id, 0)
    return character.book_mention_count


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


def scan_chapter_for_locations(chapter):
    """Regex-scan the chapter text against every location's name/aliases.

    Mirrors scan_chapter_for_characters for the Location model. Used by
    `flask build-location-chapter-association` to bulk-populate the
    chapter_location M2M. Soft-deleted Locations (merge sources, etc.)
    are skipped so they don't leak back into chapter sidebars.
    """
    # Local import keeps the top-of-module import cheap.
    from app.models import Location

    all_locations = (
        Location.query
        .filter(Location.is_deleted.is_(False))
        .all()
    )
    chapter_locations = set()

    for location in all_locations:
        needles = [location.name]
        for alias in (location.aliases or '').split(','):
            alias = alias.strip()
            if alias and alias != location.name:
                needles.append(alias)
        needles = [n for n in needles if n]
        if not needles:
            continue
        pattern = build_needle_pattern(needles)
        if pattern.search(chapter.content):
            chapter_locations.add(location)

    return list(chapter_locations)


def build_needle_pattern(name_needles):
    """Combined regex over all keyword needles for the chapter renderer.

    Python's alternation is leftmost-first (NOT longest-match), so we
    sort the needles by descending length before joining. That way when
    one needle is a prefix of another (e.g. "Cao" + "Cao Cao", or "Liu"
    + "Liu Bei"), the longer one wins.

    Multi-word needles compile with `\\s+` between tokens — not a
    literal space — so a name split across two lines of prose
    ("Wang\\nYun") or padded with multiple spaces still matches.
    Callers must normalise the matched text via re.sub(r'\\s+', ' ', m)
    when looking it up against keyed dicts that were built from the
    canonical single-space needle (see replace_match in the chapter
    view).

    Trailing context is `(?=\\W|$)` — any non-word character or
    end-of-string — instead of an explicit punctuation allowlist, so
    `"Wang Yun:"` (colon), `"Wang Yun)"` (close-paren), em-dashes,
    etc. all match correctly. Leading `\\b` keeps the original word-
    boundary semantics on the front; together they're equivalent to
    a `\\b ... \\b` wrap without depending on a hand-rolled punctuation
    list."""
    ordered = sorted(name_needles, key=len, reverse=True)
    alternatives = []
    for n in ordered:
        tokens = [t for t in re.split(r'\s+', n) if t]
        if not tokens:
            continue
        alternatives.append(r'\s+'.join(re.escape(t) for t in tokens))
    if not alternatives:
        # Fallback: a pattern that never matches anything. Caller code
        # treats an empty result list as "no inline tags" anyway.
        return re.compile(r'(?!)')
    return re.compile(r'\b(' + '|'.join(alternatives) + r')(?=\W|$)')

def _overlap_tooltip_phrase(other_kind_plural, other_names, max_show=3):
    """Render the names of overlapping cross-type entities into a short
    HTML-attribute-safe phrase for use in a hover tooltip. Caps at
    `max_show` names + "(+N more)" so the tooltip doesn't grow into a
    wall of text. `other_kind_plural` is the noun for the listed
    entities (e.g. "locations", "characters")."""
    if not other_names:
        return f'a {other_kind_plural[:-1]} name'  # "a location name" / "a character name"
    import html as _html
    shown = other_names[:max_show]
    extra = len(other_names) - len(shown)
    joined = ', '.join(_html.escape(n, quote=True) for n in shown)
    if extra:
        joined += f' (+{extra} more)'
    return f'{other_kind_plural}: {joined}'


def build_name_ref_html(
    character,
    duplicate_warning_url=None,
    location_overlap_url=None,
    location_overlap_with=None,
    display_text=None,
):
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
      * Up to two optional admin warning anchors after the pill (each
        a no-underline link with its own tooltip + screen-reader
        label):
          - `duplicate_warning_url`: red circle-exclamation — more
            than one character in the chapter shares this `name`.
          - `location_overlap_url`: green circle-exclamation — this
            character's needles (name + courtesy name + aliases)
            overlap (substring either way) a location's needles in
            the same chapter. Character mentions take priority over
            location mentions in the scanner, so the character is
            correctly tagged here — but a location with the same
            text exists too, which the admin may want to refine.
        Both icons can appear together; they're independent signals.
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
        # screen readers. "Shared needle" not "shared name" because we
        # flag overlap on any of name + courtesy + aliases.
        msg = (
            f'&quot;{character.name}&quot; shares a name or alias with '
            f'another character in this chapter — click to resolve'
        )
        pill += (
            f"<a href='{duplicate_warning_url}' "
            f"class='character-dup-warning text-danger ms-1 text-decoration-none' "
            f"title='{msg}' aria-label='{msg}'>"
            f"<i class='fa-solid fa-circle-exclamation' aria-hidden='true'></i>"
            f"</a>"
        )
    if location_overlap_url:
        phrase = _overlap_tooltip_phrase('locations', location_overlap_with or [])
        msg = (
            f'&quot;{character.name}&quot; overlaps {phrase} in this chapter '
            f'— click to review'
        )
        pill += (
            f"<a href='{location_overlap_url}' "
            f"class='character-loc-overlap-warning text-success ms-1 text-decoration-none' "
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


def find_shared_needle_ids(entities, get_needles):
    """Return the set of entity ids that share at least one needle
    (name or alias, exact-match) with another entity in the same
    iterable.

    Used to drive the red admin warning icon on inline pills and
    association rows. Catches the common case where two Locations
    have different `name`s but the import has given them the same
    bare-English alias (e.g. "Yu Province" and "Yu County" both
    carry the alias "Yu"); a `name`-only Counter would miss it.

    `get_needles(entity)` returns an iterable of strings for the
    entity. Empty / whitespace-only needles are skipped before
    comparing. The match is exact equality between needle strings —
    cross-substring overlap is a separate signal handled by
    find_location_character_overlap.
    """
    from collections import defaultdict
    needle_to_ids = defaultdict(set)
    for e in entities:
        for n in get_needles(e):
            n = (n or '').strip()
            if n:
                needle_to_ids[n].add(e.id)
    dup_ids = set()
    for ids in needle_to_ids.values():
        if len(ids) > 1:
            dup_ids.update(ids)
    return dup_ids


def location_needles(loc):
    """Standard needle list for a Location: name + comma-split aliases.
    Shared by the chapter view + admin listings so the duplicate-name
    detection and the cross-overlap detection agree on what counts
    as a 'needle'."""
    out = []
    if loc.name:
        out.append(loc.name)
    for alias in (loc.aliases or '').split(','):
        alias = alias.strip()
        if alias:
            out.append(alias)
    return out


def _word_boundary_overlap(a, b):
    """True iff `a` is a word-boundary substring of `b`, or vice versa.
    Empty strings never overlap. Falls back to plain equality when both
    sides are the same length and equal.

    Using `\\b ... \\b` mirrors the regex semantics `build_needle_pattern`
    uses against chapter prose. Without it, the alias 'Yu' would
    "overlap" the character name 'Xia Yun' purely because 'Yu' is a
    raw substring of 'Yun' — a false-positive the admin can never
    resolve because Yu isn't actually competing with Xia Yun in the
    text.
    """
    a = (a or '').strip()
    b = (b or '').strip()
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return re.search(r'\b' + re.escape(shorter) + r'\b', longer) is not None


def find_location_character_overlap(locations, characters,
                                    location_needles_for=None,
                                    character_needles_for=None):
    """Cross-product the needles of every Location against every
    Character in the given lists.  Return `(loc_overlaps, char_overlaps)`
    — two dicts mapping an entity id to the list of *other-side*
    entities whose needles overlap it.

    "Overlap" means *word-boundary* substring containment in either
    direction: a needle from one side word-boundary-matches inside a
    needle from the other.  Plain `in` matching produced false
    positives like 'Yu' (alias of Yu Province) flagging the character
    'Xia Yun' just because 'Yu' is a substring of 'Yun'.

    Pass `location_needles_for(loc)` / `character_needles_for(char)`
    to supply chapter-scoped needles (e.g. `chapter_location.keywords`
    when set, falling back to `location.aliases`).  Defaults to the
    entity's global labels, which is fine when no chapter context
    exists.

        loc_overlaps  : dict[location.id  -> list[Character]]
        char_overlaps : dict[character.id -> list[Location]]

    Used by the chapter view + the admin association listings to
    surface a green warning icon (with a tooltip naming the matched
    cross-type entities) next to entries whose needles share text
    with a cross-type entity in the same chapter. Pure-Python and
    quadratic in (sum of needles per side) — chapter-scoped lists
    are small enough that this stays fast.  Only call when an admin
    is being rendered to; the work is wasted otherwise.

    Membership checks (`id in loc_overlaps`) still work the way the
    older set-returning version did, so callers that only care about
    "is this thing overlapping?" don't need to change.
    """
    if character_needles_for is None:
        character_needles_for = lambda c: c.get_all_name_labels()
    if location_needles_for is None:
        location_needles_for = location_needles

    char_needles_by_id = {}
    char_obj_by_id = {}
    for c in characters:
        ns = {n for n in character_needles_for(c) if n and n.strip()}
        if ns:
            char_needles_by_id[c.id] = ns
            char_obj_by_id[c.id] = c

    loc_needles_by_id = {}
    loc_obj_by_id = {}
    for loc in locations:
        ns = {n for n in location_needles_for(loc) if n and n.strip()}
        if ns:
            loc_needles_by_id[loc.id] = ns
            loc_obj_by_id[loc.id] = loc

    loc_overlaps = {}
    char_overlaps = {}
    for loc_id, ln_set in loc_needles_by_id.items():
        for char_id, cn_set in char_needles_by_id.items():
            hit = False
            for ln in ln_set:
                for cn in cn_set:
                    if _word_boundary_overlap(ln, cn):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                loc_overlaps.setdefault(loc_id, []).append(char_obj_by_id[char_id])
                char_overlaps.setdefault(char_id, []).append(loc_obj_by_id[loc_id])

    return loc_overlaps, char_overlaps


def build_location_ref_html(
    location,
    match_text=None,
    duplicate_warning_url=None,
    character_overlap_url=None,
    character_overlap_with=None,
):
    """Inline span for a location mention in chapter prose.

    Same as build_event_ref_html — plain underlined text, clickable
    (chapter.js opens the Locations accordion in the sidebar) — plus
    up to two optional admin warning anchors:

      * `duplicate_warning_url`: red circle-exclamation when multiple
        Locations in this chapter share the same `name`. Click to
        jump to /admin/location-associations and disambiguate.
      * `character_overlap_url`: green circle-exclamation when any of
        the location's needles (name + aliases) overlaps — by exact
        match OR substring containment in either direction — with any
        character's needles (name + courtesy name + aliases) tagged
        on this chapter. Surfaces ambiguity between location and
        character mentions so admins can refine the per-(chapter,
        location) keywords without staring at every page.

    Both warnings can show on the same pill — they're independent
    signals."""
    label = match_text if match_text is not None else location.name
    pill = (
        f"<span class='location-ref' data-location-id='{location.id}'>"
        f"{label}</span>"
    )
    if duplicate_warning_url:
        msg = (
            f'&quot;{location.name}&quot; shares a name or alias with '
            f'another location in this chapter — click to resolve'
        )
        pill += (
            f"<a href='{duplicate_warning_url}' "
            f"class='location-dup-warning text-danger ms-1 text-decoration-none' "
            f"title='{msg}' aria-label='{msg}'>"
            f"<i class='fa-solid fa-circle-exclamation' aria-hidden='true'></i>"
            f"</a>"
        )
    if character_overlap_url:
        phrase = _overlap_tooltip_phrase('characters', character_overlap_with or [])
        msg = (
            f'&quot;{location.name}&quot; overlaps {phrase} in this chapter '
            f'— click to review'
        )
        pill += (
            f"<a href='{character_overlap_url}' "
            f"class='location-char-overlap-warning text-success ms-1 text-decoration-none' "
            f"title='{msg}' aria-label='{msg}'>"
            f"<i class='fa-solid fa-circle-exclamation' aria-hidden='true'></i>"
            f"</a>"
        )
    return pill


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