"""B3 — the rescrape safety guarantee + colour/portrait CLIs.

rescrape-chapter must only touch chapter.name/content: associations,
per-chapter keywords, MatchExclusion rows, hidden snippets, and
annotations all survive. That's the property that makes rescraping
safe after scraper fixes — pinned here with a mocked scraper.
"""
import sqlalchemy as sa

from app.models import (
    Annotation, Chapter, ChapterHiddenSnippet, Character, Faction,
    MatchExclusion, Role,
)
from app.models.character import Portrait
from tests import factories
from tools.colours import _relative_luminance


class TestRescrapeChapterSafety:
    def _seeded_chapter(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao rode east.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        ex = factories.make_match_exclusion(
            chapter=ch, target_type='character', target_id=c.id,
            match_text='Cao Cao', before='b', after='a')
        hs = factories.make_hidden_snippet(chapter=ch, match_text='east')
        ann = factories.make_annotation(chapter=ch,
                                        section_text='Cao Cao rode east.')
        db_session.flush()
        return ch, c, ex, hs, ann

    def _mock_scraper(self, monkeypatch, new_content):
        import tools.scraper
        monkeypatch.setattr(
            tools.scraper, 'scrape_chapter',
            lambda n: ('Updated Title', new_content))

    def test_content_updated_in_place(self, cli_runner, db_session,
                                      monkeypatch):
        ch, *_ = self._seeded_chapter(db_session)
        self._mock_scraper(monkeypatch,
                           '<p>Cao Cao rode east. NEW PARAGRAPH.</p>')
        result = cli_runner.invoke(
            args=['rescrape-chapter', str(ch.chapter_num)])
        assert result.exit_code == 0
        db_session.expire_all()
        refreshed = Chapter.query.get(ch.id)
        assert 'NEW PARAGRAPH' in refreshed.content
        assert refreshed.name == 'Updated Title'

    def test_associations_keywords_survive(self, cli_runner, db_session,
                                           monkeypatch):
        ch, c, *_ = self._seeded_chapter(db_session)
        self._mock_scraper(monkeypatch, '<p>Totally new content.</p>')
        cli_runner.invoke(args=['rescrape-chapter', str(ch.chapter_num)])
        db_session.expire_all()
        assert c in Chapter.query.get(ch.id).characters
        kw = db_session.execute(sa.text(
            'SELECT keywords FROM chapter_character '
            'WHERE chapter_id=:c AND character_id=:h'),
            {'c': ch.id, 'h': c.id}).scalar()
        assert kw == 'Cao Cao'

    def test_exclusions_hidden_annotations_survive(self, cli_runner,
                                                   db_session, monkeypatch):
        ch, c, ex, hs, ann = self._seeded_chapter(db_session)
        self._mock_scraper(monkeypatch, '<p>Totally new content.</p>')
        cli_runner.invoke(args=['rescrape-chapter', str(ch.chapter_num)])
        db_session.expire_all()
        assert MatchExclusion.query.get(ex.id) is not None
        assert ChapterHiddenSnippet.query.get(hs.id) is not None
        assert Annotation.query.get(ann.id) is not None

    def test_chapter_id_stable(self, cli_runner, db_session, monkeypatch):
        ch, *_ = self._seeded_chapter(db_session)
        old_id = ch.id
        self._mock_scraper(monkeypatch, '<p>Replacement.</p>')
        cli_runner.invoke(args=['rescrape-chapter', str(ch.chapter_num)])
        db_session.expire_all()
        assert Chapter.query.get(old_id) is not None

    def test_mention_counts_recounted(self, cli_runner, db_session,
                                      monkeypatch):
        ch, c, *_ = self._seeded_chapter(db_session)
        self._mock_scraper(
            monkeypatch, '<p>Cao Cao here. Cao Cao there. Cao Cao gone.</p>')
        cli_runner.invoke(args=['rescrape-chapter', str(ch.chapter_num)])
        db_session.expire_all()
        assert Character.query.get(c.id).book_mention_count == 3

    def test_unknown_chapter_fails(self, cli_runner, db_session, monkeypatch):
        self._mock_scraper(monkeypatch, '<p>x</p>')
        result = cli_runner.invoke(args=['rescrape-chapter', '4242'])
        assert result.exit_code != 0


class TestRescrapeAllChapters:
    def test_unchanged_chapters_skipped(self, cli_runner, db_session,
                                        monkeypatch):
        ch = factories.make_chapter(content='<p>Same as ever.</p>',
                                    name='Same Title')
        import tools.scraper
        monkeypatch.setattr(tools.scraper, 'scrape_chapter',
                            lambda n: ('Same Title', '<p>Same as ever.</p>'))
        result = cli_runner.invoke(args=['rescrape-all-chapters'])
        assert result.exit_code == 0
        assert 'unchanged' in result.output


class TestRandomizeColourCLIs:
    def test_faction_colours_randomized_and_readable(self, cli_runner,
                                                     db_session):
        f = factories.make_faction(name='PlainFaction')
        result = cli_runner.invoke(args=['randomize-faction-colours'])
        assert result.exit_code == 0
        db_session.expire_all()
        refreshed = Faction.query.get(f.id)
        assert refreshed.bg_colour != '#ffffff'
        # Font colour must be readable on the background (the command's
        # core promise): black on light, white on dark.
        bg_lum = _relative_luminance(refreshed.bg_colour)
        expected_font = '#000000' if bg_lum > 0.5 else '#ffffff'
        assert refreshed.font_colour.lower() == expected_font

    def test_role_colours_randomized(self, cli_runner, db_session):
        r = factories.make_role(name='plainrole')
        result = cli_runner.invoke(args=['randomize-role-colours'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Role.query.get(r.id).bg_colour != '#ffffff'


class TestAssignDefaultPortraits:
    def test_promotes_when_none_visible(self, cli_runner, db_session):
        c = factories.make_character()
        factories.make_portrait(character=c)   # hidden, not default
        result = cli_runner.invoke(args=['assign-default-portraits'])
        assert result.exit_code == 0
        db_session.expire_all()
        p = Portrait.query.filter_by(character_id=c.id).first()
        assert p.is_default is True
        assert p.is_hidden is False

    def test_leaves_characters_with_visible_portraits_alone(self, cli_runner,
                                                            db_session):
        c = factories.make_character()
        visible = factories.make_portrait(character=c, is_hidden=False)
        result = cli_runner.invoke(args=['assign-default-portraits'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Portrait.query.get(visible.id).is_default is False

    def test_dry_run_writes_nothing(self, cli_runner, db_session):
        c = factories.make_character()
        p = factories.make_portrait(character=c)
        result = cli_runner.invoke(
            args=['assign-default-portraits', '--dry-run'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Portrait.query.get(p.id).is_default is False
