"""T6 — model basics, constraints, audit stamping, edit log, tokens."""
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    Chapter, Character, Edit, Faction, Tag, User,
)
from app.models.character import Portrait
from tests import factories


class TestDefaultsAndSoftDelete:
    def test_abstract_object_defaults(self, db_session):
        c = factories.make_character(name='Defaults Guy')
        db_session.flush()
        assert c.is_deleted is False
        assert c.created_by == 'rotk.net_system'
        assert c.last_edited_by == 'rotk.net_system'
        assert c.created_at is not None

    def test_soft_delete_via_get_all_active(self, db_session):
        alive = factories.make_character(name='Alive')
        dead = factories.make_character(name='Dead', is_deleted=True)
        active_ids = {c.id for c in Character.get_all_active()}
        assert alive.id in active_ids
        assert dead.id not in active_ids

    def test_book_mention_count_defaults_zero(self, db_session):
        c = factories.make_character()
        assert c.book_mention_count == 0

    def test_chapter_title_hybrid(self, db_session):
        ch = factories.make_chapter(name='The Oath')
        assert ch.title == 'The Oath'

    def test_annotation_defaults(self, db_session):
        ch = factories.make_chapter()
        a = factories.make_annotation(chapter=ch, section_text='sec')
        db_session.flush()
        assert a.is_public is False
        assert a.is_deleted is False
        assert a.created_by == 'rotk.net_system'

    def test_portrait_defaults_hidden_not_default(self, db_session):
        c = factories.make_character()
        p = factories.make_portrait(character=c)
        assert p.is_hidden is True
        assert p.is_default is False

    def test_portrait_static_path(self, db_session):
        c = factories.make_character()
        p = factories.make_portrait(character=c, filename='42_test.png')
        assert p.static_path.endswith('42_test.png')
        assert 'portraits' in p.static_path


class TestUniqueConstraints:
    def test_chapter_num_unique(self, db_session):
        factories.make_chapter(chapter_num=900)
        with pytest.raises(IntegrityError):
            factories.make_chapter(chapter_num=900)
        db_session.rollback()

    def test_tag_name_unique(self, db_session):
        factories.make_tag(name='SameTag')
        with pytest.raises(IntegrityError):
            factories.make_tag(name='SameTag')
        db_session.rollback()

    def test_faction_name_unique(self, db_session):
        factories.make_faction(name='Wei')
        with pytest.raises(IntegrityError):
            factories.make_faction(name='Wei')
        db_session.rollback()

    def test_character_composite_unique(self, db_session):
        kw = dict(name='Zhang Liang', birth_date='?', death_date='?',
                  ancestral_home='Ye')
        factories.make_character(**kw)
        with pytest.raises(IntegrityError):
            factories.make_character(**kw)
        db_session.rollback()

    def test_character_same_name_different_dates_allowed(self, db_session):
        factories.make_character(name='Zhang Liang', birth_date='100')
        factories.make_character(name='Zhang Liang', birth_date='150')
        assert Character.query.filter_by(name='Zhang Liang').count() == 2


class TestCaseSensitivity:
    """The C collation makes name comparisons byte-wise."""

    def test_names_differing_only_in_case_coexist(self, db_session):
        factories.make_character(name='Cao')
        factories.make_character(name='cao')
        assert Character.query.filter_by(name='Cao').count() == 1
        assert Character.query.filter_by(name='cao').count() == 1

    def test_equality_filter_is_case_sensitive(self, db_session):
        factories.make_character(name='Cao')
        assert Character.query.filter_by(name='CAO').count() == 0


class TestAuditStamping:
    def test_system_label_outside_request(self, db_session):
        c = factories.make_character()
        assert c.created_by == 'rotk.net_system'

    def test_request_user_stamped_on_admin_write(self, admin_client, db_session):
        client, admin = admin_client
        resp = client.post('/factions/new', data={
            'name': 'StampedFaction',
            'font_colour': '#ffffff', 'bg_colour': '#ffffff',
            'border_colour': '#ffffff',
        }, follow_redirects=True)
        assert resp.status_code == 200
        f = Faction.query.filter_by(name='StampedFaction').first()
        assert f is not None
        assert f.created_by == admin.username

    def test_update_does_not_clobber_created_by(self, db_session):
        c = factories.make_character(name='Original')
        c.notes = 'edited'
        db_session.flush()
        assert c.created_by == 'rotk.net_system'


class TestEditLog:
    def test_insert_writes_create_edit(self, db_session):
        c = factories.make_character(name='Logged Insert')
        db_session.flush()
        row = Edit.query.filter_by(
            target_type='character', target_id=c.id, action='create'
        ).first()
        assert row is not None
        assert row.changes.get('name') == 'Logged Insert'

    def test_update_writes_diff(self, db_session):
        c = factories.make_character(name='Before Edit')
        db_session.flush()
        c.notes = 'now with notes'
        db_session.flush()
        row = Edit.query.filter_by(
            target_type='character', target_id=c.id, action='update'
        ).first()
        assert row is not None
        assert 'notes' in row.changes

    def test_delete_writes_snapshot(self, db_session):
        c = factories.make_character(name='Doomed')
        db_session.flush()
        cid = c.id
        db_session.delete(c)
        db_session.flush()
        row = Edit.query.filter_by(
            target_type='character', target_id=cid, action='delete'
        ).first()
        assert row is not None

    def test_edit_rows_never_log_themselves(self, db_session):
        factories.make_character()
        db_session.flush()
        assert Edit.query.filter_by(target_type='edit').count() == 0


class TestUserAuthModel:
    def test_password_hashed_and_verifiable(self, db_session):
        u = factories.make_user()
        assert u.password_hash != factories.DEFAULT_PASSWORD
        assert u.verify_password(factories.DEFAULT_PASSWORD)
        assert not u.verify_password('wrong')

    def test_password_not_readable(self, db_session):
        u = factories.make_user()
        with pytest.raises(AttributeError):
            _ = u.password

    def test_confirmation_token_round_trip(self, app, db_session):
        u = factories.make_user(confirmed=False)
        token = u.generate_confirmation_token()
        assert u.confirm(token) is True
        assert u.confirmed is True

    def test_confirmation_token_wrong_user_rejected(self, app, db_session):
        u1 = factories.make_user(confirmed=False)
        u2 = factories.make_user(confirmed=False)
        token = u1.generate_confirmation_token()
        assert u2.confirm(token) is False

    def test_garbage_token_rejected(self, app, db_session):
        u = factories.make_user(confirmed=False)
        assert u.confirm('not-a-token') is False

    def test_reset_token_round_trip(self, app, db_session):
        u = factories.make_user()
        token = u.generate_reset_token()
        assert User.reset_password(token, 'new password 123') is True
        db_session.flush()
        assert u.verify_password('new password 123')


class TestTagGetOrCreate:
    def test_creates_then_reuses(self, db_session):
        t1, created1 = Tag.get_or_create('DW9')
        db_session.flush()
        t2, created2 = Tag.get_or_create('DW9')
        assert created1 is True
        assert created2 is False
        assert t1.id == t2.id

    def test_new_tag_gets_colours(self, db_session):
        t, _ = Tag.get_or_create('Fresh')
        assert t.bg_colour and t.bg_colour.startswith('#')
