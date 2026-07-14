"""Hand-rolled factory helpers for the test suite.

Each `make_*` function creates + flushes one row with sane unique
defaults, returning the ORM object. All writes happen through the
savepoint-joined session from conftest, so nothing persists past the
test. No factory_boy dependency — plain functions keep the behaviour
obvious.

Counters give unique names/emails per call within a test; they don't
need to survive rollbacks because uniqueness only matters inside one
test's transaction.
"""
import itertools

from app import db
from app.models import (
    Annotation, Chapter, ChapterHiddenSnippet, Character, Event, EventType,
    Faction, Location, LocationType, MatchExclusion, ProvinceMap,
    ProvinceMapPlacement, Role, Tag, Url, UrlType, User,
)
from app.models.character import Portrait

DEFAULT_PASSWORD = 'correct horse battery staple'

_seq = itertools.count(1)


def _n():
    return next(_seq)


def _flush(obj, session=None):
    (session or db.session).add(obj)
    (session or db.session).flush()
    return obj


# --- Auth ------------------------------------------------------------------

def make_user(session=None, **kw):
    n = _n()
    defaults = dict(
        email=f'user{n}@test.example',
        username=f'user{n}',
        confirmed=True,
        is_administrator=False,
    )
    defaults.update(kw)
    user = User(**defaults)
    user.password = DEFAULT_PASSWORD
    return _flush(user, session)


def make_admin(session=None, **kw):
    kw.setdefault('is_administrator', True)
    kw.setdefault('confirmed', True)
    return make_user(session, **kw)


# --- Content ----------------------------------------------------------------

def make_chapter(session=None, **kw):
    n = _n()
    defaults = dict(
        name=f'Chapter {n} Title',
        chapter_num=n,
        content=f'<p>Default content for chapter {n}.</p>',
    )
    defaults.update(kw)
    return _flush(Chapter(**defaults), session)


def make_faction(session=None, **kw):
    n = _n()
    defaults = dict(name=f'Faction{n}')
    defaults.update(kw)
    return _flush(Faction(**defaults), session)


def make_role(session=None, **kw):
    n = _n()
    defaults = dict(name=f'role{n}')
    defaults.update(kw)
    return _flush(Role(**defaults), session)


def make_character(session=None, **kw):
    n = _n()
    defaults = dict(name=f'Character{n}', aliases='')
    defaults.update(kw)
    return _flush(Character(**defaults), session)


def make_location_type(session=None, **kw):
    n = _n()
    defaults = dict(name=f'LocationType{n}')
    defaults.update(kw)
    return _flush(LocationType(**defaults), session)


def make_location(session=None, **kw):
    n = _n()
    defaults = dict(name=f'Location{n}', aliases='')
    defaults.update(kw)
    return _flush(Location(**defaults), session)


def make_province_map(session=None, *, location, **kw):
    n = _n()
    defaults = dict(location_id=location.id, filename=f'pm{n}.png', label='')
    defaults.update(kw)
    return _flush(ProvinceMap(**defaults), session)


def make_province_map_placement(session=None, *, province_map, location,
                                kind='point', geometry=None, **kw):
    defaults = dict(
        province_map_id=province_map.id,
        location_id=location.id,
        kind=kind,
        geometry=geometry if geometry is not None else [10, 20],
    )
    defaults.update(kw)
    return _flush(ProvinceMapPlacement(**defaults), session)


def make_event_type(session=None, **kw):
    n = _n()
    defaults = dict(name=f'EventType{n}')
    defaults.update(kw)
    return _flush(EventType(**defaults), session)


def make_event(session=None, **kw):
    n = _n()
    defaults = dict(name=f'Event{n}', aliases='')
    defaults.update(kw)
    return _flush(Event(**defaults), session)


def make_tag(session=None, **kw):
    n = _n()
    defaults = dict(name=f'Tag{n}')
    defaults.update(kw)
    return _flush(Tag(**defaults), session)


def make_url_type(session=None, **kw):
    n = _n()
    defaults = dict(name=f'UrlType{n}')
    defaults.update(kw)
    return _flush(UrlType(**defaults), session)


def make_url(session=None, *, target_type, target_id, **kw):
    n = _n()
    defaults = dict(
        name=f'Link {n}',
        url=f'https://example.test/{n}',
        target_type=target_type,
        target_id=target_id,
    )
    defaults.update(kw)
    return _flush(Url(**defaults), session)


def make_portrait(session=None, *, character, **kw):
    n = _n()
    defaults = dict(
        name=character.name,
        character_id=character.id,
        image_url=f'https://img.test/{n}.png',
        filename=f'{character.id}_test_{n}.png',
    )
    defaults.update(kw)
    return _flush(Portrait(**defaults), session)


# --- Annotation / exclusion / hidden-snippet -------------------------------

def make_annotation(session=None, *, chapter, section_text, body='note body', **kw):
    defaults = dict(
        chapter_id=chapter.id,
        section_text=section_text,
        body=body,
        is_public=False,
    )
    defaults.update(kw)
    return _flush(Annotation(**defaults), session)


def make_match_exclusion(session=None, *, chapter, target_type, target_id,
                         match_text, before='', after='', **kw):
    defaults = dict(
        chapter_id=chapter.id,
        target_type=target_type,
        target_id=target_id,
        match_text=match_text,
        before_snippet=before,
        after_snippet=after,
    )
    defaults.update(kw)
    return _flush(MatchExclusion(**defaults), session)


def make_hidden_snippet(session=None, *, chapter, match_text,
                        before='', after='', **kw):
    defaults = dict(
        chapter_id=chapter.id,
        match_text=match_text,
        before_snippet=before,
        after_snippet=after,
    )
    defaults.update(kw)
    return _flush(ChapterHiddenSnippet(**defaults), session)


# --- Association helpers -----------------------------------------------------

def associate_character(chapter, character, keywords='', summary='', session=None):
    """Link a character to a chapter and set the per-association
    keywords/summary columns (mirrors what the admin add endpoint does)."""
    s = session or db.session
    if character not in chapter.characters:
        chapter.characters.append(character)
        s.flush()
    s.execute(
        db.text(
            'UPDATE chapter_character SET keywords = :kw, summary = :sm '
            'WHERE chapter_id = :cid AND character_id = :chid'
        ),
        {'kw': keywords, 'sm': summary, 'cid': chapter.id, 'chid': character.id},
    )
    s.flush()


def associate_event(chapter, event, keywords='', session=None):
    s = session or db.session
    if event not in chapter.events:
        chapter.events.append(event)
        s.flush()
    s.execute(
        db.text(
            'UPDATE event_chapter SET keywords = :kw '
            'WHERE chapter_id = :cid AND event_id = :eid'
        ),
        {'kw': keywords, 'cid': chapter.id, 'eid': event.id},
    )
    s.flush()


def associate_location(chapter, location, keywords='', session=None):
    s = session or db.session
    if location not in chapter.locations:
        chapter.locations.append(location)
        s.flush()
    s.execute(
        db.text(
            'UPDATE chapter_location SET keywords = :kw '
            'WHERE chapter_id = :cid AND location_id = :lid'
        ),
        {'kw': keywords, 'cid': chapter.id, 'lid': location.id},
    )
    s.flush()


# --- Relationships ----------------------------------------------------------

def make_relationship_type(session=None, **kw):
    """Two-ended tie label. Defaults to an asymmetric Father/Son shape;
    pass side2_label='' for a symmetric type (Brothers, Cousins)."""
    from app.models import RelationshipType
    n = _n()
    defaults = dict(
        name=f'RelType{n}',
        side1_label='Father',
        side2_label='Son',
    )
    defaults.update(kw)
    return _flush(RelationshipType(**defaults), session)


def make_relationship(character1, character2, relationship_type,
                      session=None):
    """One tie row: character1 IS the side-1 role (the Father)."""
    from app.models import Relationship
    return _flush(Relationship(
        character1_id=character1.id,
        character2_id=character2.id,
        relationship_type_id=relationship_type.id,
    ), session)
