"""Hand-rolled serializers for the public API.

Two tiers per resource:
  *_ref(obj)  — compact embed (id + name + display colours), used when a
                resource appears inside another resource's payload.
  *_full(obj) — the resource's own list/detail payload.

PRIVACY RULES (enforced here, asserted by tests/test_api.py):
  - Never emit `created_by`, `last_edited_by` or `notes`.
  - Never serialize soft-deleted (`is_deleted`) or hidden (`is_hidden`)
    rows — callers filter their queries, and embed helpers skip them
    defensively too.
  - Private annotations are never serialized (annotation endpoints
    filter `is_public == True`).
"""
from flask import url_for

from tools.book_parser import character_pill_colours
from tools.date_parser import parse_date_range


# --------------------------------------------------------------------------
# Shared building blocks
# --------------------------------------------------------------------------

def tag_shaped_ref(tag):
    """Common shape for any AbstractTag row (Faction, Role, Tag, UrlType,
    EventType, LocationType, RelationshipType) — what badge_widget needs."""
    if tag is None:
        return None
    return {
        'id': tag.id,
        'name': tag.name,
        'font_colour': tag.font_colour,
        'bg_colour': tag.bg_colour,
        'border_colour': tag.border_colour,
        'icon': tag.icon or '',
    }


def character_ref(c):
    """Compact character embed. Pill colours match the inline chapter
    pill (primary-faction driven)."""
    if c is None:
        return None
    bg, font, border = character_pill_colours(c)
    return {
        'id': c.id,
        'name': c.name,
        'chinese_name': c.chinese_name or '',
        'sex': c.sex,
        'is_fictional': bool(c.is_fictional),
        'pill_colours': {'bg': bg, 'font': font, 'border': border},
    }


def faction_ref(f):
    return tag_shaped_ref(f)


def url_entry(u):
    """One external link, mirroring what _url_list.html renders."""
    ut = u.url_type
    return {
        'name': u.name or '',
        'url': u.url or '',
        'favicon': (url_for('static', filename=u.favicon)
                    if u.favicon else ''),
        'url_type': tag_shaped_ref(ut),
    }


def urls_for(obj):
    """Active external links off a polymorphic `urls` relationship."""
    return [url_entry(u) for u in obj.urls if not u.is_deleted]


def date_span(date_str):
    """Free-form date string → {'raw', 'year_lo', 'year_hi',
    'uncertain'} (parsed via tools.date_parser; lo/hi None when
    unparseable). `uncertain` marks circa-family qualifiers — the span
    is the literal date either way."""
    from tools.date_parser import parse_date_range_detailed
    span = parse_date_range_detailed(date_str)
    return {
        'raw': date_str or '',
        'year_lo': span[0] if span else None,
        'year_hi': span[1] if span else None,
        'uncertain': bool(span[2]) if span else False,
    }


def portrait_entry(p):
    return {
        'id': p.id,
        'image': url_for('static', filename=p.static_path),
        'is_default': bool(p.is_default),
        'source_site': p.source_site or '',
        'source_url': p.source_url or '',
    }


def visible_portraits(c):
    """Public portraits, default-first — same ordering the sidebar uses."""
    rows = [p for p in c.portraits if not p.is_deleted and not p.is_hidden]
    rows.sort(key=lambda p: not p.is_default)
    return [portrait_entry(p) for p in rows]


def location_ref(loc):
    if loc is None:
        return None
    return {
        'id': loc.id,
        'name': loc.name,
        'chinese_name': loc.chinese_name or '',
        'location_type': tag_shaped_ref(loc.location_type),
    }


def event_type_ref(et):
    """EventType ref incl. its two faction-list labels."""
    if et is None:
        return None
    payload = tag_shaped_ref(et)
    payload['factions1_label'] = et.factions1_label or ''
    payload['factions2_label'] = et.factions2_label or ''
    return payload
