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


def find_location_mentions(chapter, location, context_chars=60, limit=None):
    """Same shape as find_event_mentions but for Location."""
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
        mentions.append({
            'start': start,
            'before': before,
            'match': m.group(0),
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

def build_name_ref_html(character):
    html_output = f"<span class='character-ref badge rounded-pill' data-character-id='{ character.id }' "

    if character.primary_faction is not None:
        html_output += f"data-faction-id='{ character.primary_faction.id }'"

        html_output += f" style='"
        if character.primary_faction.bg_colour not in ["", character.primary_faction.default_colour]:
            html_output += f"background-color:{character.primary_faction.bg_colour};"
        else:
            html_output += f"background-color:#000;"

        if character.primary_faction.font_colour:
            html_output += f"color:{character.primary_faction.font_colour};"

        if character.primary_faction.border_colour not in ["", character.primary_faction.default_colour]:
            html_output += f"border:2px solid {character.primary_faction.border_colour};"

        html_output += "'"
    else:
        # No faction → Bootstrap's default badge styling makes the text
        # white, which disappears against the white page background.
        # Fall back to a plain outline pill: white fill, black text,
        # black border.
        html_output += "style='background-color:#fff; color:#000; border:2px solid #000;'"

    html_output += f">{ character.name }</span>"

    return html_output