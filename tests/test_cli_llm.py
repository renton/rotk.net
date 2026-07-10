"""B2-4 — the LLM-assisted dump/apply CLI workflow commands."""
import json

import sqlalchemy as sa

from app.models import Chapter, Location, MatchExclusion
from tests import factories
from tools.book_parser import find_character_mentions


class TestDumpChapterTriage:
    def test_outputs_json_with_matches(self, cli_runner, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao rode east.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        result = cli_runner.invoke(
            args=['dump-chapter-triage', str(ch.chapter_num)])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload['chapter']['num'] == ch.chapter_num
        matches = payload['matches']
        # Dump entries use entity_type/entity_id (the apply-side input
        # uses target_type/target_id — different vocabulary by design).
        assert any(m['entity_type'] == 'character' and
                   m['entity_id'] == c.id for m in matches)


class TestDumpLocations:
    def test_outputs_locations(self, cli_runner, db_session):
        factories.make_location(name='DumpTown', latitude=1.0, longitude=2.0)
        result = cli_runner.invoke(args=['dump-locations'])
        assert result.exit_code == 0
        rows = json.loads(result.output)
        assert any(r['name'] == 'DumpTown' for r in rows)

    def test_soft_deleted_excluded(self, cli_runner, db_session):
        factories.make_location(name='GhostTown', is_deleted=True)
        result = cli_runner.invoke(args=['dump-locations'])
        rows = json.loads(result.output)
        assert not any(r['name'] == 'GhostTown' for r in rows)


class TestDumpChaptersForDating:
    def test_outputs_range(self, cli_runner, db_session):
        ch = factories.make_chapter(content='<p>Prose here.</p>')
        result = cli_runner.invoke(
            args=['dump-chapters-for-dating', str(ch.chapter_num)])
        assert result.exit_code == 0
        rows = json.loads(result.output)
        assert any(r['chapter_num'] == ch.chapter_num for r in rows)


class TestApplyTriageDecisions:
    def _decisions_file(self, tmp_path, chapter, actions):
        f = tmp_path / 'triage.json'
        f.write_text(json.dumps({
            'chapter_num': chapter.chapter_num,
            'decisions': actions,
        }))
        return str(f)

    def test_exclude_dry_run_writes_nothing(self, cli_runner, db_session,
                                            tmp_path):
        ch = factories.make_chapter(content='<p>Cao Cao rode.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        m = find_character_mentions(ch, c, needles=['Cao Cao'])[0]
        path = self._decisions_file(tmp_path, ch, [{
            'target_type': 'character', 'target_id': c.id,
            'action': 'exclude', 'match_text': m['match'],
            'before_snippet': m['before'], 'after_snippet': m['after'],
        }])
        result = cli_runner.invoke(args=['apply-triage-decisions', path])
        assert result.exit_code == 0
        assert MatchExclusion.query.count() == 0

    def test_exclude_apply_writes(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter(content='<p>Cao Cao rode.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        m = find_character_mentions(ch, c, needles=['Cao Cao'])[0]
        path = self._decisions_file(tmp_path, ch, [{
            'target_type': 'character', 'target_id': c.id,
            'action': 'exclude', 'match_text': m['match'],
            'before_snippet': m['before'], 'after_snippet': m['after'],
        }])
        result = cli_runner.invoke(
            args=['apply-triage-decisions', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0
        assert MatchExclusion.query.filter_by(
            chapter_id=ch.id, target_type='character',
            target_id=c.id).count() == 1

    def test_remove_m2m_apply(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter(content='<p>Cao Cao rode.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        path = self._decisions_file(tmp_path, ch, [{
            'target_type': 'character', 'target_id': c.id,
            'action': 'remove_m2m',
        }])
        result = cli_runner.invoke(
            args=['apply-triage-decisions', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert c not in Chapter.query.get(ch.id).characters

    def test_restore_apply_deletes_exclusion(self, cli_runner, db_session,
                                             tmp_path):
        ch = factories.make_chapter(content='<p>Cao Cao rode.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        m = find_character_mentions(ch, c, needles=['Cao Cao'])[0]
        factories.make_match_exclusion(
            chapter=ch, target_type='character', target_id=c.id,
            match_text=m['match'], before=m['before'], after=m['after'])
        path = self._decisions_file(tmp_path, ch, [{
            'target_type': 'character', 'target_id': c.id,
            'action': 'restore', 'match_text': m['match'],
            'before_snippet': m['before'], 'after_snippet': m['after'],
        }])
        result = cli_runner.invoke(
            args=['apply-triage-decisions', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0
        assert MatchExclusion.query.count() == 0


class TestApplyChapterCharacterSummaries:
    def _file(self, tmp_path, rows):
        f = tmp_path / 'summaries.json'
        f.write_text(json.dumps(rows))
        return str(f)

    def test_apply_sets_summary(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter()
        c = factories.make_character()
        factories.associate_character(ch, c)
        path = self._file(tmp_path, [{
            'chapter_num': ch.chapter_num, 'character_id': c.id,
            'summary': 'Did many things.',
        }])
        result = cli_runner.invoke(
            args=['apply-chapter-character-summaries', path, '--apply'])
        assert result.exit_code == 0
        s = db_session.execute(sa.text(
            'SELECT summary FROM chapter_character '
            'WHERE chapter_id=:c AND character_id=:h'),
            {'c': ch.id, 'h': c.id}).scalar()
        assert s == 'Did many things.'

    def test_dry_run_default(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter()
        c = factories.make_character()
        factories.associate_character(ch, c)
        path = self._file(tmp_path, [{
            'chapter_num': ch.chapter_num, 'character_id': c.id,
            'summary': 'Should not persist.',
        }])
        cli_runner.invoke(args=['apply-chapter-character-summaries', path])
        s = db_session.execute(sa.text(
            'SELECT summary FROM chapter_character WHERE character_id=:h'),
            {'h': c.id}).scalar()
        assert s == ''

    def test_unassociated_character_skipped(self, cli_runner, db_session,
                                            tmp_path):
        ch = factories.make_chapter()
        c = factories.make_character()   # not associated
        path = self._file(tmp_path, [{
            'chapter_num': ch.chapter_num, 'character_id': c.id,
            'summary': 'Nope.',
        }])
        result = cli_runner.invoke(
            args=['apply-chapter-character-summaries', path, '--apply'])
        assert result.exit_code == 0
        n = db_session.execute(sa.text(
            'SELECT COUNT(*) FROM chapter_character WHERE character_id=:h'),
            {'h': c.id}).scalar()
        assert n == 0   # no association auto-created


class TestApplyLocationGeo:
    def _file(self, tmp_path, rows):
        f = tmp_path / 'geo.json'
        f.write_text(json.dumps(rows))
        return str(f)

    def test_apply_point(self, cli_runner, db_session, tmp_path):
        loc = factories.make_location(name='PointMe')
        path = self._file(tmp_path, [{
            'id': loc.id, 'latitude': 34.5, 'longitude': 112.3,
        }])
        result = cli_runner.invoke(
            args=['apply-location-geo', path, '--apply'])
        assert result.exit_code == 0
        db_session.expire_all()
        refreshed = Location.query.get(loc.id)
        assert refreshed.latitude == 34.5
        assert refreshed.longitude == 112.3

    def test_apply_polygon(self, cli_runner, db_session, tmp_path):
        loc = factories.make_location(name='PolyMe')
        poly = {'type': 'Polygon',
                'coordinates': [[[1, 2], [3, 4], [5, 6], [1, 2]]]}
        path = self._file(tmp_path, [{'id': loc.id, 'geojson': poly}])
        result = cli_runner.invoke(
            args=['apply-location-geo', path, '--apply'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert Location.query.get(loc.id).geojson['type'] == 'Polygon'

    def test_dry_run_default(self, cli_runner, db_session, tmp_path):
        loc = factories.make_location(name='DryPoint')
        path = self._file(tmp_path, [{
            'id': loc.id, 'latitude': 1.0, 'longitude': 2.0,
        }])
        cli_runner.invoke(args=['apply-location-geo', path])
        db_session.expire_all()
        assert Location.query.get(loc.id).latitude is None


class TestImportAdminDivisions:
    def test_dry_run_against_bundled_csv(self, cli_runner, db_session):
        # Read-only smoke: the bundled CSV parses without writing
        # Location rows. Location types seeded first since the import
        # wires location_type_id.
        cli_runner.invoke(args=['seed-location-types'])
        before = Location.query.count()
        result = cli_runner.invoke(
            args=['import-admin-divisions', '--dry-run'])
        assert result.exit_code == 0
        assert Location.query.count() == before
