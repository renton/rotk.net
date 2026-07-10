"""T15 — Flask CLI commands (no scrapers — those hit the network)."""
import json

import sqlalchemy as sa

from app.models import Character, Chapter, Location, LocationType, User
from tests import factories


class TestRecountBookMentions:
    def test_bulk_recount(self, cli_runner, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao twice? Cao Cao.</p>')
        c = factories.make_character(name='Cao Cao', book_mention_count=99)
        factories.associate_character(ch, c, keywords='Cao Cao')
        result = cli_runner.invoke(args=['recount-book-mentions'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Character.query.get(c.id).book_mention_count == 2


class TestBackfillAssociationKeywords:
    def test_seeds_empty_rows_and_skips_populated(self, cli_runner,
                                                  db_session):
        ch = factories.make_chapter()
        empty_kw = factories.make_character(name='Xun Yu', aliases='Wenruo',
                                            courtesty_name='')
        has_kw = factories.make_character(name='Guo Jia')
        factories.associate_character(ch, empty_kw, keywords='')
        factories.associate_character(ch, has_kw, keywords='custom')
        result = cli_runner.invoke(args=['backfill-association-keywords'])
        assert result.exit_code == 0

        def kw(char):
            return db_session.execute(sa.text(
                'SELECT keywords FROM chapter_character '
                'WHERE chapter_id=:c AND character_id=:h'),
                {'c': ch.id, 'h': char.id}).scalar()

        assert kw(empty_kw) == 'Xun Yu,Wenruo'
        assert kw(has_kw) == 'custom'   # untouched

    def test_dry_run_writes_nothing(self, cli_runner, db_session):
        ch = factories.make_chapter()
        c = factories.make_character(name='Dry Run Guy')
        factories.associate_character(ch, c, keywords='')
        result = cli_runner.invoke(
            args=['backfill-association-keywords', '--dry-run'])
        assert result.exit_code == 0
        kw = db_session.execute(sa.text(
            'SELECT keywords FROM chapter_character WHERE character_id=:h'),
            {'h': c.id}).scalar()
        assert kw == ''


class TestCleanEmptyLocationGeojson:
    def _bad_location(self, db_session, name):
        loc = factories.make_location(name=name)
        db_session.execute(sa.text(
            "UPDATE location SET geojson = '\"\"'::jsonb WHERE id=:i"),
            {'i': loc.id})
        db_session.flush()
        return loc

    def test_clears_scalar_junk(self, cli_runner, db_session):
        loc = self._bad_location(db_session, 'JunkTown')
        result = cli_runner.invoke(args=['clean-empty-location-geojson'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Location.query.get(loc.id).geojson is None

    def test_preserves_real_polygon(self, cli_runner, db_session):
        loc = factories.make_location(name='RealPolyTown', geojson={
            'type': 'Polygon', 'coordinates': [[[1, 2], [3, 4], [5, 6], [1, 2]]],
        })
        result = cli_runner.invoke(args=['clean-empty-location-geojson'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Location.query.get(loc.id).geojson['type'] == 'Polygon'

    def test_dry_run_reports_but_keeps(self, cli_runner, db_session):
        loc = self._bad_location(db_session, 'DryJunkTown')
        result = cli_runner.invoke(
            args=['clean-empty-location-geojson', '--dry-run'])
        assert result.exit_code == 0
        assert 'DryJunkTown' in result.output
        db_session.expire_all()
        assert Location.query.get(loc.id).geojson is not None


class TestSeedLocationTypes:
    def test_seeds_standard_types(self, cli_runner, db_session):
        result = cli_runner.invoke(args=['seed-location-types'])
        assert result.exit_code == 0
        names = {t.name for t in LocationType.query.all()}
        assert 'Province' in names
        assert 'County' in names

    def test_idempotent(self, cli_runner, db_session):
        cli_runner.invoke(args=['seed-location-types'])
        first_count = LocationType.query.count()
        result = cli_runner.invoke(args=['seed-location-types'])
        assert result.exit_code == 0
        assert LocationType.query.count() == first_count


class TestApplyChapterDates:
    def test_dry_run_default(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter(date='')
        f = tmp_path / 'dates.json'
        f.write_text(json.dumps([
            {'chapter_num': ch.chapter_num, 'date': '208 AD'},
        ]))
        result = cli_runner.invoke(args=['apply-chapter-dates', str(f)])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Chapter.query.get(ch.id).date == ''   # not applied

    def test_apply_writes(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter(date='')
        f = tmp_path / 'dates.json'
        f.write_text(json.dumps([
            {'chapter_num': ch.chapter_num, 'date': '208 AD'},
        ]))
        result = cli_runner.invoke(
            args=['apply-chapter-dates', str(f), '--apply'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Chapter.query.get(ch.id).date == '208 AD'


class TestUserCommands:
    def test_make_admin(self, cli_runner, db_session):
        u = factories.make_user(is_administrator=False, confirmed=False)
        result = cli_runner.invoke(args=['make-admin', u.email])
        assert result.exit_code == 0
        db_session.expire_all()
        refreshed = User.query.get(u.id)
        assert refreshed.is_administrator is True
        assert refreshed.confirmed is True

    def test_make_admin_unknown_email_fails(self, cli_runner, db_session):
        result = cli_runner.invoke(args=['make-admin', 'ghost@x.example'])
        assert result.exit_code != 0

    def test_create_user(self, cli_runner, db_session):
        result = cli_runner.invoke(args=[
            'create-user', 'cli-new@test.example', 'cliuser',
            '--password', 'some pass 1',
        ])
        assert result.exit_code == 0
        u = User.query.filter_by(email='cli-new@test.example').first()
        assert u is not None
        assert u.verify_password('some pass 1')
        assert u.is_administrator is False

    def test_create_user_admin_flag(self, cli_runner, db_session):
        result = cli_runner.invoke(args=[
            'create-user', 'cli-adm@test.example', 'cliadmin',
            '--password', 'some pass 2', '--admin',
        ])
        assert result.exit_code == 0
        u = User.query.filter_by(email='cli-adm@test.example').first()
        assert u.is_administrator is True

    def test_create_user_duplicate_email_fails(self, cli_runner, db_session):
        existing = factories.make_user()
        result = cli_runner.invoke(args=[
            'create-user', existing.email, 'freshname',
            '--password', 'irrelevant 3',
        ])
        assert result.exit_code != 0


class TestBuildChapterCharacterAssociation:
    def test_populates_m2m_from_scan(self, cli_runner, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao and Liu Bei met.</p>')
        c1 = factories.make_character(name='Cao Cao')
        c2 = factories.make_character(name='Liu Bei')
        factories.make_character(name='Sun Quan')   # not in text
        result = cli_runner.invoke(
            args=['build-chapter-character-association'])
        assert result.exit_code == 0
        db_session.expire_all()
        ids = {c.id for c in Chapter.query.get(ch.id).characters}
        assert ids == {c1.id, c2.id}


class TestBackfillAnnotationRefsCliDryRun:
    def test_dry_run_reports_without_writing(self, cli_runner, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao pondered.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        ann = factories.make_annotation(chapter=ch,
                                        section_text='Cao Cao pondered.')
        result = cli_runner.invoke(
            args=['backfill-annotation-refs', '--dry-run'])
        assert result.exit_code == 0
        db_session.expire_all()
        from app.models import Annotation
        assert Annotation.query.get(ann.id).characters == []
