"""`flask apply-fixes` — the generalized cross-resource bulk-fix command."""
import json

from app import db
from app.models import Relationship
from tests import factories


def write_ops(tmp_path, ops):
    p = tmp_path / 'fixes.json'
    p.write_text(json.dumps(ops))
    return str(p)


class TestUpdateOp:
    def test_dry_run_writes_nothing(self, cli_runner, db_session, tmp_path):
        loc = factories.make_location(name='Trailing Space ')
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'update', 'model': 'location', 'id': loc.id,
             'fields': {'name': 'Trailing Space'}}])
        result = cli_runner.invoke(args=['apply-fixes', path])
        assert result.exit_code == 0, result.output
        assert 'DRY RUN' in result.output
        assert "'Trailing Space '" in result.output
        db_session.expire_all()
        assert loc.name == 'Trailing Space '   # unchanged

    def test_apply_updates_field(self, cli_runner, db_session, tmp_path):
        loc = factories.make_location(name='Trailing Space ')
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'update', 'model': 'location', 'id': loc.id,
             'fields': {'name': 'Trailing Space'},
             '_note': 'strip whitespace'}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        assert '1 op(s) applied' in result.output
        db_session.expire_all()
        assert loc.name == 'Trailing Space'

    def test_rerun_is_noop(self, cli_runner, db_session, tmp_path):
        ev = factories.make_event(date='c. April 211')
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'update', 'model': 'event', 'id': ev.id,
             'fields': {'date': 'c. 211'}}])
        cli_runner.invoke(args=['apply-fixes', path, '--apply',
                                '--no-confirm'])
        result = cli_runner.invoke(args=['apply-fixes', path, '--apply',
                                         '--no-confirm'])
        assert 'no changes (already as requested)' in result.output
        assert 'Nothing to do' in result.output

    def test_denied_and_unknown_fields_rejected(self, cli_runner, db_session,
                                                tmp_path):
        c = factories.make_character()
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'update', 'model': 'character', 'id': c.id,
             'fields': {'created_by': 'me'}}])
        result = cli_runner.invoke(args=['apply-fixes', path])
        assert result.exit_code != 0
        assert 'not editable' in result.output
        path = write_ops(tmp_path, [
            {'op': 'update', 'model': 'character', 'id': c.id,
             'fields': {'nonsense_col': 1}}])
        result = cli_runner.invoke(args=['apply-fixes', path])
        assert result.exit_code != 0

    def test_unknown_model_and_op_rejected(self, cli_runner, db_session,
                                           tmp_path):
        path = write_ops(tmp_path, [
            {'op': 'update', 'model': 'user', 'id': 1, 'fields': {'x': 1}}])
        result = cli_runner.invoke(args=['apply-fixes', path])
        assert result.exit_code != 0
        assert 'unknown model' in result.output
        path = write_ops(tmp_path, [{'op': 'explode'}])
        result = cli_runner.invoke(args=['apply-fixes', path])
        assert result.exit_code != 0

    def test_chapter_content_warns(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter(content='<p>old</p>')
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'update', 'model': 'chapter', 'id': ch.id,
             'fields': {'content': '<p>new</p>'}}])
        result = cli_runner.invoke(args=['apply-fixes', path])
        assert 'can orphan' in result.output


class TestRelationshipOps:
    def test_add_by_type_name(self, cli_runner, db_session, tmp_path):
        t = factories.make_relationship_type(name='Fix Parent/Child')
        a = factories.make_character()
        b = factories.make_character()
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'add_relationship', 'character1_id': a.id,
             'character2_id': b.id, 'type': 'Fix Parent/Child'}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        r = Relationship.query.filter_by(character1_id=a.id).one()
        assert r.relationship_type_id == t.id

    def test_symmetric_reverse_dup_skipped(self, cli_runner, db_session,
                                           tmp_path):
        t = factories.make_relationship_type(name='Fix Siblings',
                                             side1_label='Brother',
                                             side2_label='')
        a = factories.make_character()
        b = factories.make_character()
        factories.make_relationship(a, b, t)
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'add_relationship', 'character1_id': b.id,
             'character2_id': a.id, 'type': t.id}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert 'already exists — skip' in result.output
        assert Relationship.query.count() == 1

    def test_remove_needs_confirm_and_removes(self, cli_runner, db_session,
                                              tmp_path):
        t = factories.make_relationship_type()
        a = factories.make_character()
        b = factories.make_character()
        factories.make_relationship(a, b, t)
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'remove_relationship', 'character1_id': a.id,
             'character2_id': b.id, 'type': t.id}])
        # Confirm prompt answered "n" → aborted, nothing removed.
        result = cli_runner.invoke(args=['apply-fixes', path, '--apply'],
                                   input='n\n')
        assert Relationship.query.count() == 1
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        assert Relationship.query.count() == 0


class TestAssociationOps:
    def test_add_event_association(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter()
        ev = factories.make_event()
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'add_association', 'target': 'event',
             'chapter_num': ch.chapter_num, 'target_id': ev.id,
             'keywords': ''}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        db_session.expire_all()
        assert ev in ch.events
        # Idempotent rerun.
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert 'already associated — skip' in result.output

    def test_add_character_association_recounts(self, cli_runner, db_session,
                                                 tmp_path):
        ch = factories.make_chapter(content='<p>Fixable Guy walks.</p>')
        c = factories.make_character(name='Fixable Guy')
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'add_association', 'target': 'character',
             'chapter_num': ch.chapter_num, 'target_id': c.id,
             'keywords': 'Fixable Guy'}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        db_session.expire_all()
        assert c.book_mention_count == 1   # recount fired

    def test_add_character_association_with_summary(self, cli_runner,
                                                    db_session, tmp_path):
        ch = factories.make_chapter(content='<p>Summary Guy bows.</p>')
        c = factories.make_character(name='Summary Guy')
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'add_association', 'target': 'character',
             'chapter_num': ch.chapter_num, 'target_id': c.id,
             'keywords': 'Summary Guy', 'summary': 'He bows once.'}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        row = db.session.execute(db.text(
            'SELECT keywords, summary FROM chapter_character '
            'WHERE chapter_id = :c AND character_id = :h'),
            {'c': ch.id, 'h': c.id}).first()
        assert row.keywords == 'Summary Guy'
        assert row.summary == 'He bows once.'

    def test_add_association_summary_rejected_for_non_character(
            self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter()
        ev = factories.make_event()
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'add_association', 'target': 'event',
             'chapter_num': ch.chapter_num, 'target_id': ev.id,
             'keywords': '', 'summary': 'not allowed'}])
        result = cli_runner.invoke(args=['apply-fixes', path])
        assert result.exit_code != 0
        assert 'summary only applies to character associations' in result.output

    def test_update_association_keywords_and_summary(self, cli_runner,
                                                     db_session, tmp_path):
        ch = factories.make_chapter(content='<p>Keyword Guy nods.</p>')
        c = factories.make_character(name='Keyword Guy')
        factories.associate_character(ch, c, keywords='Old')
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'update_association', 'target': 'character',
             'chapter_num': ch.chapter_num, 'target_id': c.id,
             'keywords': 'Keyword Guy', 'summary': 'He nods.'}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        row = db.session.execute(db.text(
            'SELECT keywords, summary FROM chapter_character '
            'WHERE chapter_id = :c AND character_id = :h'),
            {'c': ch.id, 'h': c.id}).first()
        assert row.keywords == 'Keyword Guy'
        assert row.summary == 'He nods.'

    def test_remove_association(self, cli_runner, db_session, tmp_path):
        ch = factories.make_chapter()
        loc = factories.make_location()
        factories.associate_location(ch, loc, keywords='x')
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'remove_association', 'target': 'location',
             'chapter_num': ch.chapter_num, 'target_id': loc.id}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        db_session.expire_all()
        assert loc not in ch.locations


class TestLeaderOps:
    def test_add_and_remove_leader(self, cli_runner, db_session, tmp_path):
        f = factories.make_faction()
        c = factories.make_character()
        db_session.commit()
        path = write_ops(tmp_path, [
            {'op': 'add_faction_leader', 'faction_id': f.id,
             'character_id': c.id}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        assert result.exit_code == 0, result.output
        db_session.expire_all()
        assert c in f.leaders
        path = write_ops(tmp_path, [
            {'op': 'remove_faction_leader', 'faction_id': f.id,
             'character_id': c.id}])
        result = cli_runner.invoke(
            args=['apply-fixes', path, '--apply', '--no-confirm'])
        db_session.expire_all()
        assert c not in f.leaders
