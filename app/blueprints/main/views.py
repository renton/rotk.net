import math
import os
import re
import string
from flask import render_template, abort, request, current_app, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from app import db
from app.models import Chapter, Character, Faction, Role, Tag, TagAssociation, Url, UrlType, Location, LocationType, Event
from app.models.character import Portrait, PORTRAIT_DIR
from . import main
from .forms import EditCharacterForm, EditFactionForm, EditRoleForm, \
    CharacterFilterForm, UploadPortraitForm, MergeFactionForm, AddUrlForm, \
    EditLocationForm, EditEventForm, MergeLocationForm

from tools.decorators import admin_required
from tools.book_parser import get_characters_for_chapter, build_needle_pattern, build_name_ref_html, count_mentions_per_character, build_event_ref_html, build_location_ref_html, get_event_labels, get_location_labels, strip_html_tags, load_match_exclusions, normalize_snippet, load_chapter_keywords, load_chapter_character_summaries, split_keywords_csv, find_location_character_overlap, find_shared_needle_ids, location_needles, character_pill_colours
from tools.date_parser import parse_date_range


def _chapter_years(date_str):
    """Inclusive list of calendar years a chapter's free-form date string
    spans, or [] when the string is empty / unparseable.

    parse_date_range returns a positive-width (lo, hi) float span where an
    integer `hi` is an exclusive edge ("208" → (208.0, 209.0) is just the
    year 208), so the last covered year is ceil(hi) - 1."""
    span = parse_date_range(date_str)
    if span is None:
        return []
    lo, hi = span
    first = math.floor(lo)
    last = max(first, math.ceil(hi) - 1)
    return list(range(first, last + 1))


def _normalize_csv(s):
    """Normalise a comma-delimited keyword list: strip whitespace around
    each entry, drop empties, rejoin with bare commas (no spaces). Keeps
    the stored format stable so "A, B" and "A,B" never live side-by-side
    in the same `aliases` column."""
    if not s:
        return ''
    return ','.join(part.strip() for part in s.split(',') if part.strip())


def _back_arg():
    """Return a safe `?back=` URL from the current request, or None.

    Listing pages tag every edit link with `?back=<filtered-listing>`
    so the edit page can render a 1-click "Back to listing" button
    that returns the admin to the exact page + filters they came
    from. The back value rides along through form save → redirect so
    the link still works after multiple edits.

    Only relative paths (start with '/' but NOT '//') are accepted —
    blocks open-redirect attempts via crafted external URLs."""
    back = request.args.get('back') or ''
    if back.startswith('/') and not back.startswith('//'):
        return back
    return None


# Per-portrait upload cap. The WSGI-level MAX_CONTENT_LENGTH is slightly
# higher to leave room for multipart overhead; this is the post-parse limit
# we apply to the file itself.
_MAX_PORTRAIT_BYTES = 10 * 1024 * 1024  # 10 MB


def _detect_image_type(header):
    """Inspect the first ~12 bytes of an upload and return one of
    'jpg' | 'png' | 'gif' | 'webp', or None if no known image signature
    matches. Used to confirm the file's actual content matches its
    declared extension before we trust either."""
    if header.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if header[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'webp'
    return None

@main.route('/', methods=['GET'])
def index():
    chapters = Chapter.query.order_by(Chapter.chapter_num).all()

    return render_template(
        'book/table_of_contents.html',
        chapters=chapters
    )


@main.route('/map', methods=['GET'])
def map_view():
    """Public map view.

    Plots every Location that has either lat/lng or a stored GeoJSON
    polygon. Precedence on the rendering side:

      1. lat + lng present  → single pin
      2. geojson present    → polygon overlay
      3. neither            → omitted

    A Location is the same object that powers the chapter sidebar, so
    every pin / polygon is clickable through to its location page."""
    rows = (
        Location.query
        .filter(Location.is_deleted.is_(False))
        .options(selectinload(Location.location_type))
        .order_by(Location.name)
        .all()
    )

    map_items = []
    for loc in rows:
        has_point = loc.latitude is not None and loc.longitude is not None
        # Truthy (not "is not None") check: an empty string accidentally
        # stored in this JSONB column would pass `is not None` but isn't
        # renderable geo. Same below in the chapter sidebar.
        has_geojson = bool(loc.geojson)
        if not has_point and not has_geojson:
            continue
        lt = loc.location_type
        map_items.append({
            'id':            loc.id,
            'name':          loc.name or '',
            'chinese_name':  loc.chinese_name or '',
            'type_name':     (lt.name if lt else '') or '',
            'icon':          (lt.icon if lt else '') or '',
            'bg_colour':     (lt.bg_colour if lt else '') or '#6c757d',
            'font_colour':   (lt.font_colour if lt else '') or '#ffffff',
            'border_colour': (lt.border_colour if lt else '') or '#6c757d',
            'latitude':      loc.latitude if has_point else None,
            'longitude':     loc.longitude if has_point else None,
            'geojson':       loc.geojson if (has_geojson and not has_point) else None,
        })

    return render_template('map.html', map_items_json=map_items)


@main.route('/timeline', methods=['GET'])
def timeline():
    """Public timeline view.

    Pulls every chapter, event, and character whose free-form date
    field(s) parse cleanly into a year range, then ships them as JSON
    to the client. vis-timeline (CDN) handles pan/zoom; the page
    renders chapter + event points on top groups and one character
    lifeline range per dated character below."""

    # --- Chapters ---
    # Chapter names carry an embedded <br> to break the two-clause
    # title across two lines on the chapter page; for the timeline
    # detail tooltip we want a single flowing line, so collapse it
    # (and any HTML-escaped variant) into a space.
    _br_re = re.compile(r'<\s*br\s*/?\s*>', re.IGNORECASE)
    def _timeline_title(s):
        return _br_re.sub(' ', s or '').strip()

    chapter_items = []
    for c in Chapter.query.order_by(Chapter.chapter_num).all():
        span = parse_date_range(c.date)
        if span is None:
            continue
        lo, hi = span
        chapter_items.append({
            'id': c.id,
            'num': c.chapter_num,
            'name': _timeline_title(c.name),
            'date_str': c.date,
            'year_lo': lo,
            'year_hi': hi,
        })

    # --- Events ---
    # AbstractTag defaults bg/font/border colour to '#ffffff' (white).
    # On the timeline an event renders as JUST its FA icon painted in
    # the event-type's bg colour, so a default-white event-type means
    # white-on-white-row → invisible icons. Treat white (or empty) as
    # "no colour configured" and substitute a visible default.
    _DEFAULT_EVENT_COLOUR = '#6c757d'

    def _visible_colour(raw, fallback=_DEFAULT_EVENT_COLOUR):
        if not raw:
            return fallback
        # Normalise (#FFF / #ffffff variants).
        n = raw.strip().lower()
        if n in ('#fff', '#ffffff', 'white'):
            return fallback
        return raw

    event_items = []
    events = (
        Event.query
        .filter(Event.is_deleted.is_(False))
        .options(selectinload(Event.event_type))
        .order_by(Event.name)
        .all()
    )

    # Bulk-load every event's external URLs in one query (and their
    # UrlTypes for the badge colours / icon). Mirrors the data shape
    # _url_list.html renders on chapter pages, so the timeline detail
    # panel can show the same favicon -> type-icon -> link rows.
    event_ids = [e.id for e in events]
    urls_by_event_id = {}
    if event_ids:
        url_rows = (
            Url.query
            .filter(Url.is_deleted.is_(False))
            .filter(Url.target_type == 'event')
            .filter(Url.target_id.in_(event_ids))
            .options(selectinload(Url.url_type))
            .order_by(Url.name)
            .all()
        )
        for u in url_rows:
            ut = u.url_type
            urls_by_event_id.setdefault(u.target_id, []).append({
                'name':    u.name or u.url or '',
                'url':     u.url or '',
                'favicon': (
                    url_for('static', filename=u.favicon)
                    if u.favicon else ''
                ),
                'type_name':     (ut.name if ut else '') or '',
                'type_icon':     (ut.icon if ut else '') or '',
                'type_bg':       (ut.bg_colour     if ut else '') or '',
                'type_font':     (ut.font_colour   if ut else '') or '',
                'type_border':   (ut.border_colour if ut else '') or '',
            })

    for e in events:
        span = parse_date_range(e.date)
        if span is None:
            continue
        lo, hi = span
        # Optional event-type colour + icon for the marker.
        et = getattr(e, 'event_type', None)
        event_items.append({
            'id': e.id,
            'name': e.name or '',
            'date_str': e.date,
            'year_lo': lo,
            'year_hi': hi,
            'type_name': (et.name if et else '') or '',
            'icon': (et.icon if et else '') or '',
            'bg_colour':     _visible_colour(et.bg_colour     if et else None),
            'font_colour':   et.font_colour                   if et else '#ffffff',
            'border_colour': _visible_colour(et.border_colour if et else None),
            'urls':          urls_by_event_id.get(e.id, []),
        })

    # --- Characters ---
    # Eager-load primary_faction so the per-character colour lookup
    # doesn't fire one query per row.
    character_items = []
    factions_seen = {}
    chars = (
        Character.query
        .filter(Character.is_deleted.is_(False))
        .filter((Character.birth_date != '') | (Character.death_date != ''))
        .options(selectinload(Character.primary_faction))
        .order_by(Character.name)
        .all()
    )
    for ch in chars:
        b = parse_date_range(ch.birth_date)
        d = parse_date_range(ch.death_date)
        if b is None and d is None:
            continue
        # Single-ended lifelines aren't supported in v1 — without one
        # end the bar would either extend off-screen or guess a
        # lifespan, both confusing. Skip until we have a UI for it.
        if b is None or d is None:
            continue
        f = ch.primary_faction
        faction_id = f.id if f else 0
        faction_name = f.name if f else 'Unaffiliated'
        if f and not f.is_hidden:
            factions_seen[faction_id] = faction_name
        elif not f:
            factions_seen[0] = 'Unaffiliated'

        character_items.append({
            'id': ch.id,
            'name': ch.name or '',
            'chinese_name': ch.chinese_name or '',
            'birth_str': ch.birth_date,
            'death_str': ch.death_date,
            'birth_lo': b[0],
            'birth_hi': b[1],
            'death_lo': d[0],
            'death_hi': d[1],
            'faction_id': faction_id,
            'faction_name': faction_name,
            'bg_colour': (f.bg_colour if f else '') or '#6c757d',
            'font_colour': (f.font_colour if f else '') or '#ffffff',
            'border_colour': (f.border_colour if f else '') or '#6c757d',
        })

    factions = [
        {'id': fid, 'name': fname}
        for fid, fname in sorted(factions_seen.items(), key=lambda kv: kv[1].lower())
    ]

    return render_template(
        'timeline.html',
        chapters_json=chapter_items,
        events_json=event_items,
        characters_json=character_items,
        factions_json=factions,
    )

@main.route('/chapter/<int:chapter_num>', methods=['GET'])
def chapter(chapter_num):
    from collections import defaultdict
    from flask_wtf import FlaskForm
    from app.models import ChapterHiddenSnippet
    from tools.book_parser import apply_hidden_snippets

    chapter = Chapter.query.filter(Chapter.chapter_num == chapter_num).first()

    if not chapter:
        abort(404)

    # Strip admin-hidden prose BEFORE any character/event/location
    # pill-tagging. The renderer that follows only ever sees the
    # visible-to-public version of the content, so exclusions can't
    # accidentally leak into fingerprint calculations, mention
    # counts, or the inline pill output.
    # Assign to a local — don't touch chapter.content on the ORM
    # instance or the mutated value could get written back on the
    # next session commit.
    hidden_rows = ChapterHiddenSnippet.query.filter_by(chapter_id=chapter.id).all()
    chapter_content = chapter.content
    if hidden_rows:
        chapter_content = apply_hidden_snippets(chapter_content, hidden_rows, admin=False)

    # Yearly territory maps: one tab per year in the chapter's date span
    # that has an uploaded YearMap image (years without an image get no
    # tab at all).
    chapter_year_maps = []
    span_years = _chapter_years(chapter.date)
    if span_years:
        from app.models import YearMap
        chapter_year_maps = (
            YearMap.query
            .filter(YearMap.year.in_(span_years))
            # The tab panes render each map's factions and, per faction,
            # a leader panel (portrait, roles, factions) — eager-load the
            # non-dynamic hops. Character.roles / .factions are
            # lazy='dynamic' and load per leader; leader counts are tiny.
            .options(
                selectinload(YearMap.factions)
                .selectinload(Faction.leaders)
                .selectinload(Character.portraits)
            )
            .order_by(YearMap.year)
            .all()
        )

    characters = get_characters_for_chapter(chapter.id)
    characters.sort(key=lambda x: x.name)

    replacements = {}
    # `needle_to_character_ids` is a LIST of character ids per needle so
    # the duplicate-name case (two characters both called "Cao Cao", both
    # tagged in the same chapter) works: each character contributes its
    # own exclusion set, and replace_match picks the first one that
    # hasn't excluded the current occurrence. `character_html` stores
    # one rendered pill per (char_id, needle) so we can swap to the
    # right character's badge at substitution time.
    needle_to_character_ids = defaultdict(list)
    character_html = {}
    needle_to_location_id = {}

    # Per-(chapter, target) keyword overrides. The chapter renderer
    # reads from these instead of each character's / event's / location's
    # global aliases. Empty rows (e.g. pre-backfill scrape data) fall
    # back to the entity's global labels via the helpers below.
    chapter_char_kw = load_chapter_keywords(chapter.id, 'chapter_character', 'character_id')
    chapter_event_kw = load_chapter_keywords(chapter.id, 'event_chapter', 'event_id')
    chapter_loc_kw = load_chapter_keywords(chapter.id, 'chapter_location', 'location_id')

    def _character_needles(character):
        kws = split_keywords_csv(chapter_char_kw.get(character.id, ''))
        return kws if kws else character.get_all_name_labels()

    def _event_needles(event):
        kws = split_keywords_csv(chapter_event_kw.get(event.id, ''))
        return kws if kws else get_event_labels(event)

    def _location_needles(loc):
        kws = split_keywords_csv(chapter_loc_kw.get(loc.id, ''))
        return kws if kws else get_location_labels(loc)

    # Admin-only: flag characters that share at least one needle (name /
    # courtesy / alias) with another character in this same chapter so
    # the inline pill gets a red circle-exclamation linking to the
    # Character/Chapter Association editor. Lets the admin spot
    # ambiguous matches without having to cross-check every name by hand.
    is_admin = current_user.is_authenticated and current_user.is_administrator

    # Pre-collect the locations for THIS chapter so we can compute the
    # location ↔ character cross-overlap once and feed both pill loops
    # below. (The actual location pill loop still runs AFTER the
    # character loop so characters keep first claim on a shared needle.)
    seen_loc_ids = set()
    locations_for_render = []
    for loc in [*(e.location for e in chapter.events if e.location), *chapter.locations]:
        # `chapter.locations` and `event.location` are M2M / FK
        # relationships that don't filter `is_deleted`, so we drop
        # soft-deleted locations here to keep them out of the prose
        # tagging AND the sidebar card list.
        if loc is None or loc.id in seen_loc_ids or loc.is_deleted:
            continue
        seen_loc_ids.add(loc.id)
        locations_for_render.append(loc)

    # Admin warning signals, all computed once up front:
    #   char_dup_ids      — character ids that share at least one needle
    #                       (name / courtesy / alias) with ANOTHER
    #                       character tagged in this chapter.
    #   loc_dup_ids       — location ids that share at least one needle
    #                       (name or alias) with another location in
    #                       this chapter. Catches the canonical-import
    #                       case where "Yu Province" + "Yu County" both
    #                       carry the bare alias "Yu" — a name-only
    #                       check would miss it.
    #   {loc,char}_loc_overlap_ids — cross-type needle overlap.
    # Public readers skip the cross-product (find_location_character_overlap
    # is the expensive bit) since they don't see any of these icons.
    # Duplicate + cross-overlap checks key off the same chapter-scoped
    # needles the inline tagger uses (_character_needles / _location_needles
    # above) — chapter_character.keywords / chapter_location.keywords
    # when set, else the entity's global labels. Without that, the
    # global aliases drive a green-icon match that doesn't reflect
    # what's actually tagged in this chapter's prose.
    char_dup_ids = find_shared_needle_ids(characters, _character_needles)
    loc_dup_ids = find_shared_needle_ids(locations_for_render, _location_needles)
    char_admin_url = (
        url_for('admin.chapter_associations', chapter_num=chapter.chapter_num)
        if is_admin else None
    )
    loc_admin_url = (
        url_for('admin.location_associations', chapter_num=chapter.chapter_num)
        if is_admin else None
    )
    dup_url     = char_admin_url if char_dup_ids else None
    loc_dup_url = loc_admin_url  if loc_dup_ids  else None
    # loc_char_overlaps : dict[location.id  -> list[Character]]
    # char_loc_overlaps : dict[character.id -> list[Location]]
    # Pill renderers feed the matched names into the green icon's
    # title= attribute so admins can see WHICH cross-type entities
    # overlap without clicking through.
    loc_char_overlaps = {}
    char_loc_overlaps = {}
    if is_admin:
        loc_char_overlaps, char_loc_overlaps = find_location_character_overlap(
            locations_for_render, characters,
            location_needles_for=_location_needles,
            character_needles_for=_character_needles,
        )

    # Characters get first claim on a needle so character mentions never
    # get accidentally re-coloured as an event/location with the same word.
    # display_text=name_needle keeps the prose word visible in the pill
    # (e.g. "Mengde" stays "Mengde") while data-character-id still points
    # at the canonical character — so the sidebar panel + chapter-style
    # switcher / link-style behaviour resolve to the right person.
    for character in characters:
        warn_url = dup_url if (dup_url and character.id in char_dup_ids) else None
        overlap_locs = char_loc_overlaps.get(character.id, [])
        overlap_url = loc_admin_url if overlap_locs else None
        overlap_names = [l.name for l in overlap_locs]
        for name_needle in _character_needles(character):
            html = build_name_ref_html(
                character,
                duplicate_warning_url=warn_url,
                location_overlap_url=overlap_url,
                location_overlap_with=overlap_names,
                display_text=name_needle,
            )
            character_html[(character.id, name_needle)] = html
            needle_to_character_ids[name_needle].append(character.id)
            # The combined-pattern build only cares about the key; the
            # value here is a fallback (first character wins). The real
            # per-character HTML is picked in replace_match.
            if name_needle not in replacements:
                replacements[name_needle] = html

    # Events + locations get black-underlined spans linking to the
    # respective sidebar accordion item.
    for event in sorted(chapter.events, key=lambda e: e.name):
        for needle in _event_needles(event):
            if needle in replacements or needle_to_character_ids.get(needle):
                continue   # character already claimed it
            replacements[needle] = build_event_ref_html(event, match_text=needle)

    # Locations were pre-collected above (so the cross-overlap with
    # characters can be computed once and shared between both pill
    # loops). Now we just claim needles in priority order: events
    # already ran above, so locations get whatever the character /
    # event loops didn't claim.
    for loc in locations_for_render:
        loc_warn_url = loc_dup_url if (loc_dup_url and loc.id in loc_dup_ids) else None
        # Both green icons (on character pills AND location pills) link
        # to the LOCATION admin: that's where the bare-name aliases from
        # the CSV import live, and that's where most noisy-overlap
        # cleanup happens regardless of which side took priority.
        overlap_chars = loc_char_overlaps.get(loc.id, [])
        loc_overlap_url = loc_admin_url if overlap_chars else None
        loc_overlap_names = [c.name for c in overlap_chars]
        for needle in _location_needles(loc):
            if needle in replacements or needle_to_character_ids.get(needle):
                continue
            replacements[needle] = build_location_ref_html(
                loc, match_text=needle,
                duplicate_warning_url=loc_warn_url,
                character_overlap_url=loc_overlap_url,
                character_overlap_with=loc_overlap_names,
            )
            needle_to_location_id[needle] = loc.id

    pattern = build_needle_pattern(list(replacements.keys()))

    # ----- Per-snippet exclusions (characters + locations) ----------------
    # Admins can mark individual character / location matches as "wrong"
    # on their respective association admin pages. The exclusion
    # fingerprints below match what find_*_mentions() produces against
    # stripped chapter content. Pre-compute which (id, needle, occurrence)
    # tuples should NOT get re-wrapped as inline refs; the replace_match
    # closure consults this skip-set per match.
    needs_stripped = bool(needle_to_character_ids or needle_to_location_id)
    stripped_content = strip_html_tags(chapter_content) if needs_stripped else ''

    def _skip_indices_for(needle, fingerprints):
        """Return the set of 0-indexed occurrences of `needle` (in
        left-to-right, target-needle-filtered order) whose
        (before, match, after) fingerprint is in the exclusion set.

        We deliberately iterate the *combined* pattern (the one
        replace_match uses below) rather than a per-needle pattern.
        Two reasons:
          1) build_needle_pattern sorts alternatives by length
             descending, so when one needle is a prefix of another
             ("Cao" + "Cao Cao"), the combined pattern always picks
             the longer alternative. A per-needle scan for "Cao"
             would also count the "Cao" sitting inside "Cao Cao",
             which the combined pattern's longest-first rule swallows.
          2) The counter character_seen / location_seen in
             replace_match increments per (id, matched) tuple — i.e.
             per matched alternative under the combined pattern. The
             skip indices have to align with that same counter.
        We filter inside the loop so the occurrence counter (`occ`)
        only advances on matches whose alternative is `needle`."""
        skips = set()
        occ = 0
        for m in pattern.finditer(stripped_content):
            if m.group(0) != needle:
                continue
            start, end = m.start(), m.end()
            before = stripped_content[max(0, start - 60):start]
            after = stripped_content[end:end + 60]
            if start - 60 > 0:
                before = before.split(' ', 1)[1] if ' ' in before else before
                before = '…' + before.lstrip()
            if end + 60 < len(stripped_content):
                after = after.rsplit(' ', 1)[0] if ' ' in after else after
                after = after.rstrip() + '…'
            fp = (
                normalize_snippet(before),
                normalize_snippet(needle),
                normalize_snippet(after),
            )
            if fp in fingerprints:
                skips.add(occ)
            occ += 1
        return skips

    character_skip_indices = {}   # (char_id, needle) -> set of indices
    for character in characters:
        fingerprints = load_match_exclusions(chapter.id, 'character', character.id)
        if not fingerprints:
            continue
        for needle in _character_needles(character):
            # Note: multiple characters can claim the same needle now
            # (duplicate-name case). Each character's skip set is built
            # against the SAME global occurrence sequence — what differs
            # is which fingerprints belong to which character's
            # exclusion table.
            if character.id not in needle_to_character_ids.get(needle, ()):
                continue
            skips = _skip_indices_for(needle, fingerprints)
            if skips:
                character_skip_indices[(character.id, needle)] = skips

    location_skip_indices = {}   # (loc_id, needle) -> set of indices
    for loc in locations_for_render:
        fingerprints = load_match_exclusions(chapter.id, 'location', loc.id)
        if not fingerprints:
            continue
        for needle in _location_needles(loc):
            if needle_to_location_id.get(needle) != loc.id:
                continue
            skips = _skip_indices_for(needle, fingerprints)
            if skips:
                location_skip_indices[(loc.id, needle)] = skips

    # Count mentions per character as a side-effect of the rendering pass —
    # avoids a second scan of the chapter content for the sidebar's
    # "N mentions" badges.
    mention_counts = defaultdict(int)
    # Per-needle GLOBAL counter (one bump per match of the needle in
    # the combined pattern). Skip indices are keyed against this same
    # global sequence; in the duplicate-name case each character's
    # skip set covers different subset of occurrences but all indices
    # reference the same numbering.
    needle_seen = defaultdict(int)
    location_seen = defaultdict(int)

    def replace_match(match):
        matched = match.group(0)
        # Needles compile with \s+ between words so a name split across
        # a line break ("Wang\nYun") still matches. The character /
        # location dicts are keyed by the canonical single-space form,
        # so collapse whatever whitespace the prose had before lookup.
        key_str = re.sub(r'\s+', ' ', matched)
        cids = needle_to_character_ids.get(key_str)
        if cids:
            idx = needle_seen[key_str]
            needle_seen[key_str] += 1
            # Walk candidate characters in registration order, give the
            # pill to the first one who hasn't excluded this occurrence.
            # Duplicate-name resolution: A excludes occurrences they
            # don't want, B excludes the ones THEY don't want; what
            # remains for each character is rendered with that
            # character's pill. If both excluded → plain text.
            for cid in cids:
                skips = character_skip_indices.get((cid, key_str))
                if skips is not None and idx in skips:
                    continue
                mention_counts[cid] += 1
                return character_html[(cid, key_str)]
            return matched   # every candidate excluded this occurrence
        loc_id = needle_to_location_id.get(key_str)
        if loc_id is not None:
            inner_key = (loc_id, key_str)
            l_idx = location_seen[inner_key]
            location_seen[inner_key] += 1
            skips = location_skip_indices.get(inner_key)
            if skips is not None and l_idx in skips:
                return matched
        return replacements[key_str]

    rendered_content = pattern.sub(replace_match, chapter_content) if replacements else chapter_content

    # Events associated with this chapter, plus the unique set of
    # Locations — both event-pinned (from each event.location) AND
    # directly-associated (chapter ↔ location M2M via the
    # /admin/location-associations tool). Deduped by id, name-sorted.
    chapter_events = sorted(chapter.events, key=lambda e: e.name)
    locations_by_id = {
        e.location.id: e.location for e in chapter_events
        if e.location and not e.location.is_deleted
    }
    for loc in chapter.locations:
        if loc.is_deleted:
            continue
        locations_by_id.setdefault(loc.id, loc)
    chapter_locations = sorted(locations_by_id.values(), key=lambda loc: loc.name)

    # Pre-walk each chapter location's parent chain so the sidebar can
    # render the "Province › Commandery › County" breadcrumb without
    # any tricky chain-walking in Jinja. Closest-parent first; the
    # template reverses for display. `seen` and max_depth defend
    # against cycle data even though the merge + cycle-guard logic
    # forbid them — better to truncate than render forever.
    ancestry_by_loc_id = {}
    for loc in chapter_locations:
        chain = []
        seen = {loc.id}
        cur = loc.parent
        depth = 0
        while cur is not None and cur.id not in seen and depth < 10:
            chain.append(cur)
            seen.add(cur.id)
            cur = cur.parent
            depth += 1
        ancestry_by_loc_id[loc.id] = chain

    # Adjacent chapters for the prev/next nav buttons at the bottom of
    # the page. `chapter_num` is 1..120 and gapless in this dataset, so
    # +/-1 lookups are fine — the .first() falls back to None at the
    # extremes (chapter 1 has no prev; the final chapter has no next).
    prev_chapter = (
        Chapter.query.filter(Chapter.chapter_num == chapter.chapter_num - 1).first()
    )
    next_chapter = (
        Chapter.query.filter(Chapter.chapter_num == chapter.chapter_num + 1).first()
    )

    # Map payload for the chapter sidebar's mini-map — same item
    # shape as the /map view (so map_base.js renders both identically).
    # Locations without lat/lng AND without geojson are omitted; they
    # still appear in the Locations accordion but can't be placed.
    chapter_map_items = []
    for loc in chapter_locations:
        has_point = loc.latitude is not None and loc.longitude is not None
        has_geo = bool(loc.geojson)   # see /map view comment
        if not has_point and not has_geo:
            continue
        lt = loc.location_type
        chapter_map_items.append({
            'id':            loc.id,
            'name':          loc.name or '',
            'chinese_name':  loc.chinese_name or '',
            'type_name':     (lt.name if lt else '') or '',
            'icon':          (lt.icon if lt else '') or '',
            'bg_colour':     (lt.bg_colour if lt else '') or '#6c757d',
            'font_colour':   (lt.font_colour if lt else '') or '#ffffff',
            'border_colour': (lt.border_colour if lt else '') or '#6c757d',
            'latitude':      loc.latitude if has_point else None,
            'longitude':     loc.longitude if has_point else None,
            'geojson':       loc.geojson if (has_geo and not has_point) else None,
        })

    # Per-(chapter, character) editorial summaries — shown in the
    # Characters accordion when set.
    char_summary_by_id = load_chapter_character_summaries(chapter.id)

    # ---- Annotations --------------------------------------------------
    # Public readers see only public annotations; admins see everything.
    # We inject an icon before each <p> that has matching annotations,
    # and ship a JSON payload keyed by SHA-256 hash so the client JS
    # can populate the thread modal on click.
    from app.models import Annotation
    from tools.book_parser import (
        inject_annotation_icons,
        annotation_section_hash,
        annotation_section_canonical,
    )
    ann_query = Annotation.query.filter_by(chapter_id=chapter.id, is_deleted=False)
    if not is_admin:
        ann_query = ann_query.filter_by(is_public=True)
    annotations_all = ann_query.order_by(Annotation.created_at).all()
    # Keyed by the CANONICAL form (whitespace-free) so save-time
    # textContent and render-time tag-strip land on the same key.
    annotations_by_section = {}
    for a in annotations_all:
        annotations_by_section.setdefault(
            annotation_section_canonical(a.section_text), []
        ).append(a)

    rendered_content = inject_annotation_icons(
        rendered_content, annotations_by_section, is_admin=is_admin,
    )

    # Client payload — hash keys so the DOM data-attribute is short.
    # section_text in the payload is the READABLE form (first stored
    # row's text, spaces intact) — the dict key is canonical/whitespace-
    # free which would be unreadable in the modal preview.
    from tools.book_parser import character_pill_colours
    annotations_payload = {}
    for canonical_key, ann_list in annotations_by_section.items():
        key = annotation_section_hash(canonical_key)
        # Union of character/location refs across the thread — shown
        # under the section preview in the modal.
        ref_chars = {}
        ref_locs = {}
        for a in ann_list:
            for c in a.characters:
                ref_chars[c.id] = c
            for l in a.locations:
                ref_locs[l.id] = l
        char_payload = []
        for c in sorted(ref_chars.values(), key=lambda x: x.name):
            bg, font, border = character_pill_colours(c)
            char_payload.append({'id': c.id, 'name': c.name, 'bg': bg, 'font': font, 'border': border})
        annotations_payload[key] = {
            'section_text': ann_list[0].section_text,
            'characters': char_payload,
            'locations': [
                {'id': l.id, 'name': l.name}
                for l in sorted(ref_locs.values(), key=lambda x: x.name)
            ],
            'thread': [
                {
                    'id': a.id,
                    'body': a.body,
                    'created_at': a.created_at.strftime('%Y-%m-%d %H:%M'),
                    'created_by': a.created_by,
                    'is_public': a.is_public,
                }
                for a in ann_list
            ],
        }

    return render_template(
        'book/chapter.html',
        chapter=chapter,
        chapter_content=rendered_content,
        characters=characters,
        mention_counts=mention_counts,
        chapter_events=chapter_events,
        chapter_locations=chapter_locations,
        ancestry_by_loc_id=ancestry_by_loc_id,
        prev_chapter=prev_chapter,
        next_chapter=next_chapter,
        chapter_map_items=chapter_map_items,
        chapter_year_maps=chapter_year_maps,
        char_summary_by_id=char_summary_by_id,
        annotations_payload=annotations_payload,
        annotation_csrf_form=FlaskForm(),
    )

@main.route('/characters', methods=['GET', 'POST'])
def characters():

    letter = request.args.get("letter", "").upper()
    alphabet = alphabet = list(string.ascii_uppercase)
    page = request.args.get('page', 1, type=int)

    form = CharacterFilterForm(request.args)

    # Start with the base query
    query = Character.query

    # Apply filtering if a letter is selected
    if letter:
        query = query.filter(Character.name.startswith(letter))

    # Apply role filter
    if form.role.data:
        query = query.filter(Character.roles.any(Role.id == form.role.data.id))

    # Two independent faction filters. `any_faction` matches characters
    # whose M2M factions list contains the chosen faction (past or
    # present); `primary_faction` matches strictly on primary. Both can
    # be combined.
    if form.any_faction.data:
        query = query.filter(Character.factions.any(Faction.id == form.any_faction.data.id))
    if form.primary_faction.data:
        query = query.filter(Character.primary_faction == form.primary_faction.data)

    if form.search_query.data:
        search_term = f"%{form.search_query.data}%"
        query = query.filter(Character.name.ilike(search_term))

    # Batch-load portraits and chapters so the per-row image + chapter list
    # in the template doesn't N+1 the DB.
    query = query.options(
        selectinload(Character.portraits),
        selectinload(Character.chapters),
    )

    # Sortable mentions column: ?sort=mentions&dir=asc|desc. Anything
    # else falls back to the default name ordering. Name is always the
    # tiebreaker so equal counts stay stable across pages.
    sort = request.args.get('sort', '')
    direction = request.args.get('dir', 'desc')
    if sort == 'mentions':
        count_col = Character.book_mention_count
        order = (count_col.asc() if direction == 'asc' else count_col.desc())
        query = query.order_by(order, Character.name)
    else:
        sort = ''
        query = query.order_by(Character.name)

    # Apply pagination after filtering
    pagination = query.paginate(
        page=page,
        per_page=current_app.config['CHARACTERS_PER_PAGE'],
        error_out=False
    )

    characters = pagination.items  # Get current page items

    # Pick one image per character to show next to the row: the default if
    # set, else the first non-hidden portrait, else None. Matches the
    # ordering the chapter sidebar uses for its first tab.
    default_portraits = {}
    chapter_lists = {}
    for ch in characters:
        visible = sorted(
            (p for p in ch.portraits if not p.is_deleted and not p.is_hidden),
            key=lambda p: not p.is_default,
        )
        default_portraits[ch.id] = visible[0] if visible else None
        chapter_lists[ch.id] = sorted(
            ch.chapters, key=lambda c: c.chapter_num
        )

    return render_template(
        'characters/characters.html',
        characters=characters,
        pagination=pagination,
        page=page,
        alphabet=alphabet,
        form=form,
        letter=letter,
        sort=sort,
        direction=direction,
        default_portraits=default_portraits,
        chapter_lists=chapter_lists,
    )

@main.route('/characters/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_character():
    """Admin form to create a brand-new Character. Reuses the same template
    as the edit page, but doesn't pass `portraits` / `upload_form` so the
    images section is skipped (the character has no id yet to attach
    portraits to)."""
    from sqlalchemy.exc import IntegrityError

    form = EditCharacterForm()
    if form.validate_on_submit():
        character = Character()
        form.populate_obj(character)
        character.aliases = _normalize_csv(character.aliases)

        # Same primary_faction consistency rule as edit_character.
        if (
            character.primary_faction is not None
            and character.primary_faction not in character.factions.all()
        ):
            character.factions.append(character.primary_faction)

        db.session.add(character)
        try:
            db.session.flush()   # populate character.id for the recount step
        except IntegrityError:
            db.session.rollback()
            flash(
                f"Couldn't create {form.name.data!r}: a character with the "
                f"same name + birth/death + ancestral home already exists."
            )
            return render_template('characters/character_edit.html', form=form)

        # Fresh row → its book mention count is unknown; compute it now so
        # the chapter sidebar shows real numbers right away.
        counts = count_mentions_per_character(Chapter.query.all(), [character])
        character.book_mention_count = counts.get(character.id, 0)

        db.session.commit()
        flash(f"Created character {character.name!r}.")
        return redirect(url_for('main.edit_character', id=character.id))

    return render_template('characters/character_edit.html', form=form)


@main.route('/characters/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_character(id):
    character = Character.query.get_or_404(id)
    form = EditCharacterForm(obj=character)

    if form.validate_on_submit():
        # Capture the pre-edit labels so we can tell whether the regex-needles
        # for this character changed. If they did, the cached
        # book_mention_count is stale and we should recount before commit.
        old_labels = (character.name, character.courtesty_name, character.aliases)
        form.populate_obj(character)
        character.aliases = _normalize_csv(character.aliases)
        new_labels = (character.name, character.courtesty_name, character.aliases)

        # If a main faction is picked but isn't in the M2M factions list,
        # auto-add it so the data stays consistent (otherwise the chapter
        # sidebar would highlight a faction the character supposedly
        # isn't a member of).
        if (
            character.primary_faction is not None
            and character.primary_faction not in character.factions.all()
        ):
            character.factions.append(character.primary_faction)

        if old_labels != new_labels:
            counts = count_mentions_per_character(
                Chapter.query.all(), [character]
            )
            character.book_mention_count = counts.get(character.id, 0)

        db.session.add(character)
        db.session.commit()
        flash('The character has been updated.')
        return redirect(url_for("main.edit_character", id=character.id, back=_back_arg()))

    # Admin view of the edit page surfaces hidden portraits too (with a
    # visual marker), so the admin can promote / unhide them from here
    # without bouncing to the Image Manager.
    portraits = [p for p in character.portraits if not p.is_deleted]
    portraits.sort(key=lambda p: (not p.is_default, p.is_hidden))

    upload_form = UploadPortraitForm()
    all_tags = Tag.query.order_by(Tag.name).all()
    add_url_form = AddUrlForm()
    urls = [u for u in character.urls if not u.is_deleted]

    # Bare FlaskForm gives us CSRF tokens for the per-portrait toggle forms
    # below. They POST to admin.toggle_portrait_hidden / set_default_portrait
    # which both verify the token via their own _CsrfOnlyForm instance.
    from flask_wtf import FlaskForm
    csrf_form = FlaskForm()

    return render_template(
        'characters/character_edit.html',
        form=form,
        character=character,
        portraits=portraits,
        upload_form=upload_form,
        all_tags=all_tags,
        add_url_form=add_url_form,
        urls=urls,
        csrf_form=csrf_form,
        back=_back_arg(),
    )


@main.route('/characters/<int:id>/upload-portrait', methods=['POST'])
@login_required
@admin_required
def upload_portrait(id):
    """Manually upload an image for a character.

    Defense in depth:
      1. Admin-only (decorators).
      2. CSRF (FlaskForm).
      3. Werkzeug-level request size cap (Config.MAX_CONTENT_LENGTH).
      4. Per-file size cap re-checked here against _MAX_PORTRAIT_BYTES.
      5. Extension allow-list at the form level (FileAllowed).
      6. Magic-byte sniffing — we never trust the declared extension alone.
      7. Filename is server-constructed; user input never reaches the path.
      8. Saved path is verified to live inside PORTRAIT_DIR before write.
    """
    character = Character.query.get_or_404(id)
    form = UploadPortraitForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}")
        return redirect(url_for('main.edit_character', id=character.id))

    file = form.image_file.data
    if not file or not file.filename:
        flash("No file selected.")
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Size check ------------------------------------------------------
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size <= 0:
        flash("Uploaded file is empty.")
        return redirect(url_for('main.edit_character', id=character.id))
    if size > _MAX_PORTRAIT_BYTES:
        flash(
            f"File too large ({size:,} bytes). Max {_MAX_PORTRAIT_BYTES:,} bytes."
        )
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Magic-byte check ------------------------------------------------
    header = file.stream.read(32)
    file.stream.seek(0)
    detected = _detect_image_type(header)
    if detected is None:
        flash(
            "Uploaded file doesn't look like a real image "
            "(JPEG/PNG/GIF/WEBP signatures didn't match)."
        )
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Extension consistency ------------------------------------------
    # FileAllowed already rejected anything outside the allow-list, but we
    # also want the declared extension to match the file's actual content.
    safe_original = secure_filename(file.filename) or 'upload'
    declared_ext = os.path.splitext(safe_original)[1].lower()
    declared = 'jpg' if declared_ext == '.jpeg' else declared_ext.lstrip('.')
    if declared != detected:
        flash(
            f"File extension {declared_ext!r} doesn't match the actual "
            f"content ({detected!r}). Refusing to save."
        )
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Tag validation --------------------------------------------------
    tag_name = (form.tag_name.data or '').strip()
    if tag_name and len(tag_name) > 255:
        flash("Tag name too long (max 255 characters).")
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Build the destination path (server-constructed, never user input) ----
    portraits_dir = os.path.join(current_app.static_folder, PORTRAIT_DIR)
    os.makedirs(portraits_dir, exist_ok=True)
    final_ext = f'.{detected}'  # always sanitised; never echoes user value
    n = 0
    while True:
        suffix = f'_{n}' if n else ''
        filename = f'{character.id}_manual{suffix}{final_ext}'
        path = os.path.join(portraits_dir, filename)
        if not os.path.exists(path):
            break
        n += 1

    # Belt-and-braces: confirm the resolved path stays inside PORTRAIT_DIR
    # even if filename construction ever regresses.
    abs_path = os.path.abspath(path)
    abs_dir = os.path.abspath(portraits_dir)
    if not abs_path.startswith(abs_dir + os.sep):
        abort(400)

    file.save(path)

    # ---- DB rows ---------------------------------------------------------
    tag = None
    if tag_name:
        tag, _ = Tag.get_or_create(tag_name)

    is_default = bool(form.is_default.data)
    is_visible = bool(form.is_visible.data)

    # Credit fields — admin can supply both, either, or neither. Default
    # the site label to "Manual upload" so the UI always has a string
    # to display in the source line.
    site_label = (form.source_site.data or '').strip() or 'Manual upload'
    src_url = (form.source_url.data or '').strip()

    portrait = Portrait(
        name=character.name,
        character_id=character.id,
        image_url=src_url,      # used as the "originating URL"; safe to be empty
        filename=filename,
        description='',
        source_url=src_url,
        source_site=site_label,
        is_default=False,       # set below if requested
        is_hidden=not is_visible,
    )

    if is_default:
        # Clear is_default on any other portraits for this character; the
        # partial unique index would otherwise reject our insert.
        Portrait.query.filter(
            Portrait.character_id == character.id,
        ).update({'is_default': False})
        portrait.is_default = True
        portrait.is_hidden = False   # defaults are always public

    db.session.add(portrait)
    db.session.flush()   # populate portrait.id (and tag.id if newly added)

    if tag is not None:
        db.session.add(TagAssociation(
            tag_id=tag.id,
            target_type='portrait',
            target_id=portrait.id,
        ))

    db.session.commit()
    flash(f"Uploaded {filename} ({size:,} bytes) for {character.name}.")
    return redirect(url_for('main.edit_character', id=character.id))


# Owner-type → (model class, edit view endpoint name) for the generic
# URL add route below. Restricting the param via this map prevents an
# attacker from inserting a Url against an arbitrary target_type value.
_URL_OWNER_TYPES = {
    'character': (Character, 'main.edit_character'),
    'event':     (Event,     'main.edit_event'),
    'location':  (Location,  'main.edit_location'),
    'faction':   (Faction,   'main.edit_faction'),
    'role':      (Role,      'main.edit_role'),
}


@main.route('/<owner_type>/<int:id>/urls/add', methods=['POST'])
@login_required
@admin_required
def add_owner_url(owner_type, id):
    """Attach a new external link (Url) to a first-class object.
    `owner_type` is one of the allow-listed keys in _URL_OWNER_TYPES;
    `id` resolves to a row in the corresponding model. After insert we
    best-effort auto-fetch a favicon from the URL's host and stash it
    under app/static/favicons/<host>_favicon.ico (deduped per host)."""
    from tools.favicon_fetcher import fetch_favicon

    if owner_type not in _URL_OWNER_TYPES:
        abort(404)
    model_cls, edit_endpoint = _URL_OWNER_TYPES[owner_type]
    owner = model_cls.query.get_or_404(id)

    form = AddUrlForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}")
        return redirect(url_for(edit_endpoint, id=owner.id))

    favicon_path = (form.favicon.data or '').strip()
    if not favicon_path:
        # Admin didn't supply one — try to fetch & cache.
        favicon_path = fetch_favicon(
            form.url.data.strip(),
            current_app.static_folder,
        ) or ''

    url = Url(
        name=form.name.data.strip(),
        url=form.url.data.strip(),
        favicon=favicon_path,
        url_type=form.url_type.data or None,
        target_type=owner_type,
        target_id=owner.id,
    )
    db.session.add(url)
    db.session.commit()
    flash(f"Added link {url.name!r} to {owner.name}.")
    return redirect(url_for(edit_endpoint, id=owner.id))


@main.route('/urls/<int:url_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_url(url_id):
    """Hard-delete a Url row. Redirects back to wherever the click came
    from (request.referrer) so the admin stays on the page they were on."""
    from flask_wtf import FlaskForm
    form = FlaskForm()
    if not form.validate_on_submit():
        abort(400)

    url = Url.query.get_or_404(url_id)
    label = url.name
    db.session.delete(url)
    db.session.commit()
    flash(f"Deleted link {label!r}.")
    return redirect(request.referrer or url_for('main.index'))


@main.route('/factions', methods=['GET'])
def factions():
    # Skip hidden factions (merged-away). To unhide, flip is_hidden=false in
    # the DB directly — no UI for it per the design.
    factions = (
        Faction.query
        .filter(Faction.is_hidden.is_(False))
        .options(selectinload(Faction.leaders))
        .order_by(Faction.name)
        .all()
    )

    # Leader pills, coloured like the character's inline chapter pill
    # (i.e. by their primary faction) — same precomputed-dict pattern
    # the admin annotation lists use.
    leaders_by_faction = {}
    for f in factions:
        pills = []
        for ch in f.leaders:
            if ch.is_deleted:
                continue
            bg, font, border = character_pill_colours(ch)
            pills.append({'id': ch.id, 'name': ch.name,
                          'bg': bg, 'font': font, 'border': border})
        leaders_by_faction[f.id] = pills

    return render_template(
        'factions/factions.html',
        factions=factions,
        leaders_by_faction=leaders_by_faction,
    )

@main.route('/factions/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_faction():
    """Admin form to create a Faction. Mirrors new_character / new_event /
    new_location — same template as edit_faction with `faction=None`."""
    from sqlalchemy.exc import IntegrityError
    form = EditFactionForm()
    if form.validate_on_submit():
        faction = Faction()
        form.populate_obj(faction)
        db.session.add(faction)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A faction named {form.name.data!r} already exists.")
            return render_template('factions/faction_edit.html', form=form, faction=None)
        flash(f"Created faction {faction.name!r}.")
        return redirect(url_for('main.edit_faction', id=faction.id))
    return render_template('factions/faction_edit.html', form=form, faction=None)


@main.route('/factions/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_faction(id):
    from flask_wtf import FlaskForm
    faction = Faction.query.get_or_404(id)
    form = EditFactionForm(obj=faction)

    if form.validate_on_submit():
        form.populate_obj(faction)

        db.session.add(faction)
        db.session.commit()
        flash('The faction has been updated.')
        # If the admin came from a filtered listing, send them back to
        # the exact filter/page they were on; otherwise the bare list.
        return redirect(_back_arg() or url_for("main.factions"))

    # Merge form + its target picker datalist. Excludes the source itself
    # and anything already hidden.
    merge_form = MergeFactionForm()
    mergeable_factions = (
        Faction.query
        .filter(Faction.is_hidden.is_(False), Faction.id != faction.id)
        .order_by(Faction.name)
        .all()
    )

    # Leaders section: current leaders (with remove buttons) + a picker
    # datalist over every active character for adding new ones.
    leader_picker_characters = (
        Character.query
        .filter(Character.is_deleted.is_(False))
        .order_by(Character.name)
        .all()
    )
    # Faction names per character, one query (Character.factions is
    # lazy='dynamic' — touching it per row would N+1 across ~1000
    # characters). Shown in the picker options so duplicate names
    # ("Zhang Wen" the Wu minister vs the Han official) disambiguate.
    leader_picker_faction_names = {}
    for cid, fname in (
        db.session.query(Character.faction_table.c.character_id, Faction.name)
        .join(Faction, Faction.id == Character.faction_table.c.faction_id)
        .filter(Faction.is_hidden.is_(False))
        .order_by(Faction.name)
        .all()
    ):
        leader_picker_faction_names.setdefault(cid, []).append(fname)

    return render_template(
        'factions/faction_edit.html',
        form=form,
        faction=faction,
        merge_form=merge_form,
        mergeable_factions=mergeable_factions,
        leaders=[c for c in faction.leaders if not c.is_deleted],
        leader_picker_characters=leader_picker_characters,
        leader_picker_faction_names=leader_picker_faction_names,
        urls=[u for u in faction.urls if not u.is_deleted],
        add_url_form=AddUrlForm(),
        csrf_form=FlaskForm(),
        back=_back_arg(),
    )


@main.route('/factions/<int:id>/leaders/add', methods=['POST'])
@login_required
@admin_required
def add_faction_leader(id):
    """Attach a character as a leader of this faction.

    The form ships the picker pair: a hidden `character_id` (filled by
    admin_picker.js) with a `Name #<id>` suffix fallback in
    `character_search` when JS hasn't resolved it."""
    from flask_wtf import FlaskForm
    if not FlaskForm().validate_on_submit():
        abort(400)
    faction = Faction.query.get_or_404(id)

    raw_id = (request.form.get('character_id') or '').strip()
    if not raw_id.isdigit():
        m = re.search(r'#(\d+)\s*$', request.form.get('character_search') or '')
        raw_id = m.group(1) if m else ''
    character = Character.query.get(int(raw_id)) if raw_id.isdigit() else None
    if character is None or character.is_deleted:
        flash("Couldn't resolve that character — pick one from the list.")
        return redirect(url_for('main.edit_faction', id=faction.id))

    if character in faction.leaders:
        flash(f"{character.name} is already a leader of {faction.name}.")
    else:
        faction.leaders.append(character)
        db.session.commit()
        flash(f"Added {character.name} as a leader of {faction.name}.")
    return redirect(url_for('main.edit_faction', id=faction.id))


@main.route('/factions/<int:id>/leaders/remove/<int:character_id>', methods=['POST'])
@login_required
@admin_required
def remove_faction_leader(id, character_id):
    from flask_wtf import FlaskForm
    if not FlaskForm().validate_on_submit():
        abort(400)
    faction = Faction.query.get_or_404(id)
    character = Character.query.get_or_404(character_id)
    if character in faction.leaders:
        faction.leaders.remove(character)
        db.session.commit()
        flash(f"Removed {character.name} from {faction.name}'s leaders.")
    else:
        flash(f"{character.name} isn't a leader of {faction.name}.")
    return redirect(url_for('main.edit_faction', id=faction.id))


@main.route('/factions/<int:id>/merge', methods=['POST'])
@login_required
@admin_required
def merge_faction(id):
    """Merge faction `id` (source) into the target picked in the form.

    1. Every character with `source` in their M2M factions list ALSO gets
       `target` added (M2M is non-destructive — source link stays, but
       source is about to be hidden anyway so it falls out of all
       listings).
    2. Every character whose primary_faction is `source` gets switched
       to `target`. Other characters' primaries are not touched.
    3. `source.is_hidden` flips to True so it disappears from listings.

    The action isn't undoable from the UI — flip is_hidden back in the DB
    if you need to recover (the M2M membership added to characters stays
    either way)."""
    merge_form = MergeFactionForm()
    if not merge_form.validate_on_submit():
        abort(400)

    source = Faction.query.get_or_404(id)

    raw = (request.form.get('target_faction_id') or '').strip()
    if not raw.isdigit():
        flash("Pick a faction from the dropdown to merge into.")
        return redirect(url_for('main.edit_faction', id=id))
    target = Faction.query.get(int(raw))
    if target is None or target.is_hidden:
        flash("Target faction is missing or already hidden.")
        return redirect(url_for('main.edit_faction', id=id))
    if target.id == source.id:
        flash("Can't merge a faction into itself.")
        return redirect(url_for('main.edit_faction', id=id))

    members_carried = 0
    for character in list(source.characters):
        if target not in character.factions.all():
            character.factions.append(target)
        members_carried += 1

    primary_switched = (
        Character.query
        .filter(Character.primary_faction_id == source.id)
        .update(
            {'primary_faction_id': target.id},
            synchronize_session='fetch',
        )
    )

    source.is_hidden = True
    db.session.commit()

    flash(
        f"Merged {source.name!r} into {target.name!r}. "
        f"{members_carried} member(s) inherited the target, "
        f"{primary_switched} primary(s) switched. "
        f"{source.name!r} is now hidden."
    )
    return redirect(url_for('main.factions'))

@main.route('/roles', methods=['GET'])
def roles():

    roles = Role.query.order_by(Role.name).all()

    return render_template(
        'roles/roles.html',
        roles=roles
    )

@main.route('/roles/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_role():
    """Admin form to create a Role. Mirrors new_faction — same template
    as edit_role with `role=None`."""
    from sqlalchemy.exc import IntegrityError
    form = EditRoleForm()
    if form.validate_on_submit():
        role = Role()
        form.populate_obj(role)
        db.session.add(role)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A role named {form.name.data!r} already exists.")
            return render_template('roles/role_edit.html', form=form, role=None)
        flash(f"Created role {role.name!r}.")
        return redirect(url_for('main.edit_role', id=role.id))
    return render_template('roles/role_edit.html', form=form, role=None)


@main.route('/roles/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_role(id):
    from flask_wtf import FlaskForm
    role = Role.query.get_or_404(id)
    form = EditRoleForm(obj=role)

    if form.validate_on_submit():
        form.populate_obj(role)

        db.session.add(role)
        db.session.commit()
        flash('The role has been updated.')
        return redirect(url_for("main.roles"))

    return render_template(
        'roles/role_edit.html',
        form=form,
        role=role,
        urls=[u for u in role.urls if not u.is_deleted],
        add_url_form=AddUrlForm(),
        csrf_form=FlaskForm(),
    )


# ----- Locations ----------------------------------------------------------

@main.route('/locations', methods=['GET'])
def locations():
    from collections import defaultdict
    from sqlalchemy.orm import aliased

    page = request.args.get('page', 1, type=int)
    q = (request.args.get('q') or '').strip()
    type_id = request.args.get('type_id', type=int)
    province_id = request.args.get('province_id', type=int)
    commandery_id = request.args.get('commandery_id', type=int)
    county_id = request.args.get('county_id', type=int)

    # Type lookup by name powers the cascade — we filter the
    # Province / Commandery / County dropdowns by the matching type id.
    type_by_name = {
        t.name: t for t in
        LocationType.query
        .filter(LocationType.is_deleted.is_(False))
        .filter(LocationType.is_hidden.is_(False))
        .order_by(LocationType.name).all()
    }
    province_type_id   = type_by_name.get('Province').id   if 'Province'   in type_by_name else None
    commandery_type_id = type_by_name.get('Commandery').id if 'Commandery' in type_by_name else None
    county_type_id     = type_by_name.get('County').id     if 'County'     in type_by_name else None

    # ----- Cascade dropdown contents -------------------------------------
    # Each level is filtered by the level above (if selected) so picking a
    # province narrows the commandery dropdown to that province's
    # commanderies, etc.
    def _by_type(tid):
        return (Location.query
                .filter(Location.is_deleted.is_(False))
                .filter(Location.location_type_id == tid)
                .order_by(Location.name).all())

    provinces = _by_type(province_type_id) if province_type_id else []

    commanderies = []
    if commandery_type_id:
        cq = (Location.query
              .filter(Location.is_deleted.is_(False))
              .filter(Location.location_type_id == commandery_type_id))
        if province_id:
            cq = cq.filter(Location.parent_id == province_id)
        commanderies = cq.order_by(Location.name).all()

    counties = []
    if county_type_id:
        cq = (Location.query
              .filter(Location.is_deleted.is_(False))
              .filter(Location.location_type_id == county_type_id))
        if commandery_id:
            cq = cq.filter(Location.parent_id == commandery_id)
        elif province_id:
            # Counties whose commandery sits under the chosen province.
            com_alias = aliased(Location)
            cq = (cq.join(com_alias, Location.parent_id == com_alias.id)
                    .filter(com_alias.parent_id == province_id))
        counties = cq.order_by(Location.name).all()

    # ----- Build the main listing query ---------------------------------
    query = Location.query.filter(Location.is_deleted.is_(False))
    if q:
        query = query.filter(Location.name.ilike(f"%{q}%"))
    if type_id:
        query = query.filter(Location.location_type_id == type_id)

    # Scope filter: limit results to the descendants of the most-specific
    # ancestor the user has selected. Falls through county → commandery
    # → province so partial selections still narrow the listing.
    scope_ancestor_id = county_id or commandery_id or province_id
    if scope_ancestor_id:
        # Fetch every (id, parent_id) pair once and BFS in Python — at
        # ~800 rows this is cheaper and clearer than a recursive CTE.
        pairs = db.session.execute(
            db.select(Location.id, Location.parent_id)
            .where(Location.is_deleted.is_(False))
        ).all()
        kids_of = defaultdict(list)
        for cid, pid in pairs:
            if pid is not None:
                kids_of[pid].append(cid)
        descendants = {scope_ancestor_id}
        stack = [scope_ancestor_id]
        while stack:
            node = stack.pop()
            for child in kids_of.get(node, ()):
                if child not in descendants:
                    descendants.add(child)
                    stack.append(child)
        query = query.filter(Location.id.in_(descendants))

    # Avoid N+1 on the row render — every row reads its type, parent,
    # and chapter list.
    query = query.options(
        selectinload(Location.location_type),
        selectinload(Location.parent).selectinload(Location.location_type),
        selectinload(Location.chapters),
    )

    pagination = query.order_by(Location.name).paginate(
        page=page,
        per_page=current_app.config['CHARACTERS_PER_PAGE'],
        error_out=False,
    )

    # Pre-sort chapters per location so the "Chapter References" cell
    # renders them in book order. Done in Python because the M2M was
    # selectin-loaded — no extra query.
    chapter_lists = {
        loc.id: sorted(loc.chapters, key=lambda c: c.chapter_num)
        for loc in pagination.items
    }

    # Walk each row's parent chain so the Parent column can render the
    # full breadcrumb (closest parent first; template reverses for
    # root → leaf order). Depth cap + seen-set guard against accidental
    # parent loops in dirty data. Mirrors the chapter view's
    # ancestry_by_loc_id helper.
    ancestry_by_loc_id = {}
    for loc in pagination.items:
        chain = []
        seen = set()
        cur = loc.parent
        depth = 0
        while cur is not None and cur.id not in seen and depth < 10:
            chain.append(cur)
            seen.add(cur.id)
            cur = cur.parent
            depth += 1
        ancestry_by_loc_id[loc.id] = chain

    return render_template(
        'locations/locations.html',
        pagination=pagination,
        q=q,
        page=page,
        types=list(type_by_name.values()),
        provinces=provinces,
        commanderies=commanderies,
        counties=counties,
        selected_type_id=type_id,
        selected_province_id=province_id,
        selected_commandery_id=commandery_id,
        selected_county_id=county_id,
        chapter_lists=chapter_lists,
        ancestry_by_loc_id=ancestry_by_loc_id,
    )


@main.route('/locations/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_location():
    form = EditLocationForm()
    if form.validate_on_submit():
        location = Location()
        form.populate_obj(location)
        location.aliases = _normalize_csv(location.aliases)
        # populate_obj set location.geojson to the raw form string,
        # which is "" when the admin left the field blank — that
        # would land in JSONB as the JSON string "" and make
        # `loc.geojson is not None` true downstream, fooling the
        # chapter sidebar into treating the location as clickable.
        # validate_geojson exposes the parsed dict (or None) as
        # form.geojson.parsed — use that instead. Mirrors edit_location.
        location.geojson = getattr(form.geojson, 'parsed', None)
        db.session.add(location)
        db.session.commit()
        flash(f"Created location {location.name!r}.")
        return redirect(url_for('main.edit_location', id=location.id))
    return render_template('locations/location_edit.html', form=form, location=None)


@main.route('/locations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_location(id):
    from flask_wtf import FlaskForm
    import json as _json
    location = Location.query.get_or_404(id)
    form = EditLocationForm(obj=location)
    # The model stores geojson as a JSONB dict; the form field is a
    # TextAreaField holding the pretty-printed JSON string. Translate
    # both ways here so the user sees JSON text and we still write
    # the dict on save.
    if request.method == 'GET' and location.geojson is not None:
        form.geojson.data = _json.dumps(location.geojson, ensure_ascii=False, indent=2)
    if form.validate_on_submit():
        # Cycle guard: parent must not be self, and must not be any
        # descendant of self (which would close a loop). Walk the
        # proposed parent's own ancestor chain looking for `location`.
        proposed_parent = form.parent.data
        if proposed_parent is not None:
            if proposed_parent.id == location.id:
                flash("A location can't be its own parent.")
                return render_template(
                    'locations/location_edit.html',
                    form=form, location=location,
                    urls=[u for u in location.urls if not u.is_deleted],
                    add_url_form=AddUrlForm(), csrf_form=FlaskForm(),
                )
            cur, seen = proposed_parent, set()
            while cur is not None and cur.id not in seen:
                if cur.id == location.id:
                    flash(
                        f"That would create a cycle: {proposed_parent.name!r} "
                        f"already has {location.name!r} as an ancestor."
                    )
                    return render_template(
                        'locations/location_edit.html',
                        form=form, location=location,
                        urls=[u for u in location.urls if not u.is_deleted],
                        add_url_form=AddUrlForm(), csrf_form=FlaskForm(),
                    )
                seen.add(cur.id)
                cur = cur.parent

        form.populate_obj(location)
        location.aliases = _normalize_csv(location.aliases)
        # `form.geojson.parsed` is set by the form's validate_geojson
        # — either the parsed dict or None. populate_obj wrote the
        # raw string; overwrite with the dict (or null).
        location.geojson = getattr(form.geojson, 'parsed', None)
        db.session.add(location)
        db.session.commit()
        flash("Location updated.")
        return redirect(url_for('main.edit_location', id=location.id, back=_back_arg()))
    # Merge picker — same shape as edit_faction. Show every active
    # location other than this one as a candidate target.
    merge_form = MergeLocationForm()
    mergeable_locations = (
        Location.query
        .filter(Location.is_deleted.is_(False), Location.id != location.id)
        .order_by(Location.name)
        .all()
    )
    return render_template(
        'locations/location_edit.html',
        form=form,
        location=location,
        urls=[u for u in location.urls if not u.is_deleted],
        add_url_form=AddUrlForm(),
        csrf_form=FlaskForm(),
        merge_form=merge_form,
        mergeable_locations=mergeable_locations,
        back=_back_arg(),
    )


@main.route('/locations/<int:id>/merge', methods=['POST'])
@login_required
@admin_required
def merge_location(id):
    """Merge location `id` (source) into the target chosen in the form.

    Moves every reference to source onto target before soft-deleting
    source. References handled:

      - chapter_location M2M (with per-link `keywords` merged)
      - event.location_id
      - location.parent_id (children re-parented)
      - polymorphic Url rows         (target_type='location')
      - polymorphic MatchExclusion   (target_type='location')

    Target also inherits source's name + chinese_name + every alias on
    source (added to target.aliases CSV, deduped). location_type, lat,
    lng, and chinese_name on target are filled in from source ONLY when
    target currently has them blank/null — pre-set values are never
    overwritten, same rule the CSV import uses.

    Refuses if target is in source's descendant chain — that would
    require breaking the hierarchy first to avoid a self-loop. The
    admin can re-parent and retry.

    Source ends with is_deleted=True; UI listings filter it out.
    Recovery is a DB-level flip of is_deleted back to false — there's
    no un-merge UI."""
    from collections import defaultdict
    from sqlalchemy import text

    merge_form = MergeLocationForm()
    if not merge_form.validate_on_submit():
        abort(400)

    source = Location.query.get_or_404(id)

    raw = (request.form.get('target_location_id') or '').strip()
    if not raw.isdigit():
        flash("Pick a location from the dropdown to merge into.")
        return redirect(url_for('main.edit_location', id=id))
    target = Location.query.get(int(raw))
    if target is None or target.is_deleted:
        flash("Target location is missing or already deleted.")
        return redirect(url_for('main.edit_location', id=id))
    if target.id == source.id:
        flash("Can't merge a location into itself.")
        return redirect(url_for('main.edit_location', id=id))

    # Cycle guard: refuse if target is a descendant of source. Otherwise
    # re-parenting source's children to target would loop target back
    # onto itself via its own ancestry. Same BFS the /locations filter
    # uses, scoped to active rows.
    pairs = db.session.execute(
        db.select(Location.id, Location.parent_id)
        .where(Location.is_deleted.is_(False))
    ).all()
    kids_of = defaultdict(list)
    for cid, pid in pairs:
        if pid is not None:
            kids_of[pid].append(cid)
    descendants = {source.id}
    stack = [source.id]
    while stack:
        node = stack.pop()
        for child in kids_of.get(node, ()):
            if child not in descendants:
                descendants.add(child)
                stack.append(child)
    if target.id in descendants:
        flash(
            f"Can't merge: {target.name!r} is a descendant of "
            f"{source.name!r}. Re-parent it first, then retry."
        )
        return redirect(url_for('main.edit_location', id=id))

    # ----- chapter_location M2M ------------------------------------
    # The M2M carries a per-link `keywords` column. For chapters where
    # source AND target are both linked, merge the keyword CSVs into
    # target's row; for chapters where only source is linked, re-point
    # the row at target.
    params = {'source_id': source.id, 'target_id': target.id}

    # 1. Merge keywords on chapters where both rows exist (CSVs joined
    #    with a comma — admin can de-dup later if they care). NULLIF
    #    keeps a trailing comma from showing up when one side is empty.
    db.session.execute(text("""
        UPDATE chapter_location AS tgt
        SET keywords = TRIM(BOTH ',' FROM
            COALESCE(NULLIF(tgt.keywords, ''), '')
            || CASE
                WHEN tgt.keywords <> '' AND src.keywords <> '' THEN ','
                ELSE ''
            END
            || COALESCE(NULLIF(src.keywords, ''), '')
        )
        FROM chapter_location AS src
        WHERE tgt.chapter_id  = src.chapter_id
          AND tgt.location_id = :target_id
          AND src.location_id = :source_id
    """), params)

    # 2. Re-point chapters that only had source linked.
    db.session.execute(text("""
        UPDATE chapter_location
        SET location_id = :target_id
        WHERE location_id = :source_id
          AND chapter_id NOT IN (
              SELECT chapter_id FROM chapter_location
              WHERE location_id = :target_id
          )
    """), params)

    # 3. Drop any source row that's left (only the dup-chapter ones,
    #    since step 2 took the rest).
    db.session.execute(text(
        "DELETE FROM chapter_location WHERE location_id = :source_id"
    ), params)

    # ----- Event.location_id ---------------------------------------
    db.session.execute(text(
        "UPDATE event SET location_id = :target_id WHERE location_id = :source_id"
    ), params)

    # ----- Location.parent_id (re-parent source's children) --------
    db.session.execute(text(
        "UPDATE location SET parent_id = :target_id WHERE parent_id = :source_id"
    ), params)

    # ----- Polymorphic relationships -------------------------------
    db.session.execute(text("""
        UPDATE url SET target_id = :target_id
        WHERE target_type = 'location' AND target_id = :source_id
    """), params)
    db.session.execute(text("""
        UPDATE match_exclusion SET target_id = :target_id
        WHERE target_type = 'location' AND target_id = :source_id
    """), params)

    # ----- Aliases (target absorbs source's name + chinese + aliases) ---
    aliases_existing = [a.strip() for a in (target.aliases or '').split(',') if a.strip()]
    candidates = [source.name, source.chinese_name]
    candidates += [a.strip() for a in (source.aliases or '').split(',') if a.strip()]
    for alias in candidates:
        if alias and alias not in aliases_existing:
            aliases_existing.append(alias)
    target.aliases = ','.join(aliases_existing)

    # ----- Fill blank-only fields on target ------------------------
    if not target.chinese_name and source.chinese_name:
        target.chinese_name = source.chinese_name
    if target.location_type_id is None and source.location_type_id is not None:
        target.location_type_id = source.location_type_id
    if target.latitude is None and source.latitude is not None:
        target.latitude = source.latitude
    if target.longitude is None and source.longitude is not None:
        target.longitude = source.longitude

    # ----- Soft-delete source --------------------------------------
    source.is_deleted = True

    db.session.commit()

    flash(
        f"Merged {source.name!r} into {target.name!r}. "
        f"Source is now hidden from listings; aliases + references "
        f"moved to target."
    )
    return redirect(url_for('main.edit_location', id=target.id))


# ----- Events -------------------------------------------------------------

@main.route('/events', methods=['GET'])
def events():
    page = request.args.get('page', 1, type=int)
    q = (request.args.get('q') or '').strip()
    location_id = request.args.get('location_id', type=int)

    query = (
        Event.query
        .options(selectinload(Event.chapters))
        .filter(Event.is_deleted.is_(False))
    )
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Event.name.ilike(like)) | (Event.aliases.ilike(like))
        )
    if location_id:
        query = query.filter(Event.location_id == location_id)

    pagination = query.order_by(Event.name).paginate(
        page=page,
        per_page=current_app.config['CHARACTERS_PER_PAGE'],
        error_out=False,
    )

    locations_for_filter = Location.query.filter(Location.is_deleted.is_(False))\
                                         .order_by(Location.name).all()

    # Sorted-by-chapter-num chapter list per event, for the table column.
    chapter_lists = {
        e.id: sorted(e.chapters, key=lambda c: c.chapter_num)
        for e in pagination.items
    }

    return render_template(
        'events/events.html',
        pagination=pagination,
        q=q,
        location_id=location_id,
        locations=locations_for_filter,
        chapter_lists=chapter_lists,
        page=page,
    )


@main.route('/events/<int:id>/factions/<int:side>/add', methods=['POST'])
@login_required
@admin_required
def add_event_faction(id, side):
    """Attach a faction to one side of an event's participation lists.

    Same picker pair as the faction-leaders form: hidden `faction_id`
    (filled by admin_picker.js) with a `Name #<id>` suffix fallback in
    `faction_search`. Writes the event_faction row directly so `side`
    is explicit (the model relationships are viewonly)."""
    from flask_wtf import FlaskForm
    from app.models.event import event_faction
    if not FlaskForm().validate_on_submit():
        abort(400)
    if side not in (1, 2):
        abort(404)
    event = Event.query.get_or_404(id)

    raw_id = (request.form.get('faction_id') or '').strip()
    if not raw_id.isdigit():
        m = re.search(r'#(\d+)\s*$', request.form.get('faction_search') or '')
        raw_id = m.group(1) if m else ''
    faction = Faction.query.get(int(raw_id)) if raw_id.isdigit() else None
    if faction is None or faction.is_hidden:
        flash("Couldn't resolve that faction — pick one from the list.")
        return redirect(url_for('main.edit_event', id=event.id))

    if faction in event.factions_for_side(side):
        flash(f"{faction.name} is already in that list.")
    else:
        db.session.execute(event_faction.insert().values(
            event_id=event.id, faction_id=faction.id, side=side))
        db.session.commit()
        flash(f"Added {faction.name}.")
    return redirect(url_for('main.edit_event', id=event.id))


@main.route('/events/<int:id>/factions/<int:side>/remove/<int:faction_id>', methods=['POST'])
@login_required
@admin_required
def remove_event_faction(id, side, faction_id):
    from flask_wtf import FlaskForm
    from app.models.event import event_faction
    if not FlaskForm().validate_on_submit():
        abort(400)
    if side not in (1, 2):
        abort(404)
    event = Event.query.get_or_404(id)
    faction = Faction.query.get_or_404(faction_id)

    result = db.session.execute(
        event_faction.delete().where(
            (event_faction.c.event_id == event.id)
            & (event_faction.c.faction_id == faction.id)
            & (event_faction.c.side == side)
        )
    )
    db.session.commit()
    if result.rowcount:
        flash(f"Removed {faction.name}.")
    else:
        flash(f"{faction.name} wasn't in that list.")
    return redirect(url_for('main.edit_event', id=event.id))


@main.route('/events/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_event():
    form = EditEventForm()
    if form.validate_on_submit():
        event = Event()
        form.populate_obj(event)
        event.aliases = _normalize_csv(event.aliases)
        db.session.add(event)
        db.session.commit()
        flash(f"Created event {event.name!r}.")
        return redirect(url_for('main.edit_event', id=event.id))
    return render_template('events/event_edit.html', form=form, event=None)


@main.route('/events/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_event(id):
    from flask_wtf import FlaskForm
    event = Event.query.get_or_404(id)
    form = EditEventForm(obj=event)
    if form.validate_on_submit():
        form.populate_obj(event)
        event.aliases = _normalize_csv(event.aliases)
        db.session.add(event)
        db.session.commit()
        flash("Event updated.")
        return redirect(url_for('main.edit_event', id=event.id))
    # Sided faction lists. Side 2 only applies when the event's type
    # carries a factions2_label (or legacy data already exists there).
    faction_picker_factions = (
        Faction.query
        .filter(Faction.is_hidden.is_(False))
        .order_by(Faction.name)
        .all()
    )
    return render_template(
        'events/event_edit.html',
        form=form,
        event=event,
        faction_picker_factions=faction_picker_factions,
        urls=[u for u in event.urls if not u.is_deleted],
        add_url_form=AddUrlForm(),
        csrf_form=FlaskForm(),
    )
