"""T7 — M2M association rows, polymorphic targets, cascade semantics."""
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    Annotation, Chapter, ChapterHiddenSnippet, Character, Event, Location,
    MatchExclusion, Tag, TagAssociation, Url,
)
from app.models.character import Portrait
from tests import factories


def _scalar(db_session, sql, **params):
    return db_session.execute(sa.text(sql), params).scalar()


class TestAssociationRowColumns:
    def test_chapter_character_keywords_and_summary(self, db_session):
        ch = factories.make_chapter()
        c = factories.make_character()
        factories.associate_character(ch, c, keywords='a,b', summary='did things')
        row = db_session.execute(sa.text(
            'SELECT keywords, summary FROM chapter_character '
            'WHERE chapter_id=:c AND character_id=:h'), {'c': ch.id, 'h': c.id}
        ).first()
        assert row.keywords == 'a,b'
        assert row.summary == 'did things'

    def test_event_chapter_keywords(self, db_session):
        ch = factories.make_chapter()
        ev = factories.make_event()
        factories.associate_event(ch, ev, keywords='Chibi')
        kw = _scalar(db_session,
                     'SELECT keywords FROM event_chapter '
                     'WHERE chapter_id=:c AND event_id=:e', c=ch.id, e=ev.id)
        assert kw == 'Chibi'

    def test_chapter_location_keywords(self, db_session):
        ch = factories.make_chapter()
        loc = factories.make_location()
        factories.associate_location(ch, loc, keywords='Loyang')
        kw = _scalar(db_session,
                     'SELECT keywords FROM chapter_location '
                     'WHERE chapter_id=:c AND location_id=:l', c=ch.id, l=loc.id)
        assert kw == 'Loyang'

    def test_m2m_duplicate_pair_rejected(self, db_session):
        ch = factories.make_chapter()
        c = factories.make_character()
        factories.associate_character(ch, c)
        with pytest.raises(IntegrityError):
            db_session.execute(sa.text(
                'INSERT INTO chapter_character (chapter_id, character_id) '
                'VALUES (:c, :h)'), {'c': ch.id, 'h': c.id})
        db_session.rollback()


class TestPolymorphicUrls:
    def test_character_urls_scoped_to_character(self, db_session):
        c = factories.make_character()
        ev = factories.make_event()
        u_char = factories.make_url(target_type='character', target_id=c.id)
        factories.make_url(target_type='event', target_id=ev.id)
        db_session.flush()
        db_session.expire_all()
        char_urls = list(c.urls)
        assert [u.id for u in char_urls] == [u_char.id]

    def test_same_target_id_different_type_isolated(self, db_session):
        # Polymorphic target_id has no FK — a character and an event
        # can share the same numeric id without cross-talk.
        c = factories.make_character()
        ev = factories.make_event()
        factories.make_url(target_type='event', target_id=c.id)
        db_session.expire_all()
        assert all(u.target_type == 'character' for u in c.urls)

    def test_url_type_set_null_on_type_delete(self, db_session):
        ut = factories.make_url_type()
        c = factories.make_character()
        u = factories.make_url(target_type='character', target_id=c.id,
                               url_type_id=ut.id)
        db_session.flush()
        db_session.delete(ut)
        db_session.flush()
        db_session.expire_all()
        assert u.url_type_id is None


class TestTagAssociations:
    def test_unique_triple_enforced(self, db_session):
        t = factories.make_tag()
        c = factories.make_character()
        db_session.add(TagAssociation(tag_id=t.id, target_type='portrait',
                                      target_id=c.id))
        db_session.flush()
        with pytest.raises(IntegrityError):
            db_session.add(TagAssociation(tag_id=t.id, target_type='portrait',
                                          target_id=c.id))
            db_session.flush()
        db_session.rollback()

    def test_tag_delete_cascades_associations(self, db_session):
        t = factories.make_tag()
        db_session.add(TagAssociation(tag_id=t.id, target_type='portrait',
                                      target_id=1))
        db_session.flush()
        db_session.delete(t)
        db_session.flush()
        assert TagAssociation.query.filter_by(tag_id=t.id).count() == 0


class TestPortraitPartialUnique:
    def test_second_default_rejected(self, db_session):
        c = factories.make_character()
        factories.make_portrait(character=c, is_default=True, is_hidden=False)
        with pytest.raises(IntegrityError):
            factories.make_portrait(character=c, is_default=True,
                                    is_hidden=False)
        db_session.rollback()

    def test_multiple_non_defaults_fine(self, db_session):
        c = factories.make_character()
        factories.make_portrait(character=c)
        factories.make_portrait(character=c)
        assert Portrait.query.filter_by(character_id=c.id).count() == 2

    def test_defaults_on_different_characters_fine(self, db_session):
        c1 = factories.make_character()
        c2 = factories.make_character()
        factories.make_portrait(character=c1, is_default=True)
        factories.make_portrait(character=c2, is_default=True)
        assert Portrait.query.filter_by(is_default=True).count() == 2


class TestChapterDeleteCascades:
    def _full_chapter(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao at Luoyang.</p>')
        c = factories.make_character(name='Cao Cao')
        loc = factories.make_location(name='Luoyang')
        ev = factories.make_event(name='The Council')
        factories.associate_character(ch, c, keywords='Cao Cao')
        factories.associate_location(ch, loc, keywords='Luoyang')
        factories.associate_event(ch, ev)
        factories.make_match_exclusion(chapter=ch, target_type='character',
                                       target_id=c.id, match_text='Cao Cao')
        factories.make_hidden_snippet(chapter=ch, match_text='at')
        ann = factories.make_annotation(chapter=ch, section_text='Cao Cao at Luoyang.')
        ann.characters = [c]
        ann.locations = [loc]
        db_session.flush()
        return ch, c, loc, ev

    def test_everything_chapter_scoped_cascades(self, db_session):
        ch, c, loc, ev = self._full_chapter(db_session)
        cid = ch.id
        db_session.delete(ch)
        db_session.flush()
        assert MatchExclusion.query.filter_by(chapter_id=cid).count() == 0
        assert ChapterHiddenSnippet.query.filter_by(chapter_id=cid).count() == 0
        assert Annotation.query.filter_by(chapter_id=cid).count() == 0
        for table in ('chapter_character', 'event_chapter', 'chapter_location'):
            n = _scalar(db_session,
                        f'SELECT COUNT(*) FROM {table} WHERE chapter_id=:c',
                        c=cid)
            assert n == 0, table

    def test_entities_survive_chapter_delete(self, db_session):
        ch, c, loc, ev = self._full_chapter(db_session)
        db_session.delete(ch)
        db_session.flush()
        assert Character.query.get(c.id) is not None
        assert Location.query.get(loc.id) is not None
        assert Event.query.get(ev.id) is not None

    def test_character_delete_removes_annotation_refs_only(self, db_session):
        ch = factories.make_chapter()
        c = factories.make_character()
        ann = factories.make_annotation(chapter=ch, section_text='sec')
        ann.characters = [c]
        db_session.flush()
        aid = ann.id
        # Detach from any chapters first (mirrors real admin flow).
        db_session.delete(c)
        db_session.flush()
        db_session.expire_all()
        survivor = Annotation.query.get(aid)
        assert survivor is not None
        assert survivor.characters == []

    def test_event_location_set_null(self, db_session):
        loc = factories.make_location()
        ev = factories.make_event(location_id=loc.id)
        db_session.flush()
        db_session.delete(loc)
        db_session.flush()
        db_session.expire_all()
        assert Event.query.get(ev.id).location_id is None

    def test_location_parent_set_null(self, db_session):
        parent = factories.make_location(name='Province X')
        child = factories.make_location(name='County Y', parent_id=parent.id)
        db_session.flush()
        db_session.delete(parent)
        db_session.flush()
        db_session.expire_all()
        assert Location.query.get(child.id).parent_id is None
