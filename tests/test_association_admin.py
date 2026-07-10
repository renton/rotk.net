"""T11 — the three chapter-association admin editors."""
import sqlalchemy as sa

from app.models import Character, MatchExclusion
from tests import factories
from tools.book_parser import find_character_mentions


def _kw(db_session, table, id_col, chapter, entity):
    return db_session.execute(sa.text(
        f'SELECT keywords FROM {table} '
        f'WHERE chapter_id = :c AND {id_col} = :e'),
        {'c': chapter.id, 'e': entity.id}).scalar()


class TestCharacterAdd:
    def test_fresh_add_creates_m2m_with_matched_keywords(self, admin_client,
                                                         db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Mengde spoke twice.</p>')
        c = factories.make_character(name='Cao Cao')
        resp = client.post(f'/admin/chapter-associations/{ch.chapter_num}/add',
                           data={'search_terms': 'Mengde, NotInText',
                                 'character_id': str(c.id)},
                           follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        assert c in ch.characters
        # Only the matched keyword persists; 'NotInText' is skipped.
        assert _kw(db_session, 'chapter_character', 'character_id',
                   ch, c) == 'Mengde'

    def test_resync_replaces_keywords_this_chapter_only(self, admin_client,
                                                        db_session):
        client, _ = admin_client
        ch1 = factories.make_chapter(content='<p>Cao Cao and Mengde.</p>')
        ch2 = factories.make_chapter(content='<p>Cao Cao alone.</p>')
        c = factories.make_character(name='Cao Cao', aliases='Mengde')
        factories.associate_character(ch1, c, keywords='Cao Cao,Mengde')
        factories.associate_character(ch2, c, keywords='Cao Cao')
        # Resync ch1 down to just 'Mengde'.
        client.post(f'/admin/chapter-associations/{ch1.chapter_num}/add',
                    data={'search_terms': 'Mengde',
                          'character_id': str(c.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert _kw(db_session, 'chapter_character', 'character_id',
                   ch1, c) == 'Mengde'
        # ch2 untouched — per-chapter semantics.
        assert _kw(db_session, 'chapter_character', 'character_id',
                   ch2, c) == 'Cao Cao'

    def test_resync_does_not_duplicate_m2m_row(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        client.post(f'/admin/chapter-associations/{ch.chapter_num}/add',
                    data={'search_terms': 'Cao Cao',
                          'character_id': str(c.id)},
                    follow_redirects=True)
        n = db_session.execute(sa.text(
            'SELECT COUNT(*) FROM chapter_character '
            'WHERE chapter_id=:c AND character_id=:h'),
            {'c': ch.id, 'h': c.id}).scalar()
        assert n == 1

    def test_empty_keywords_rejected_for_characters(self, admin_client,
                                                    db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        c = factories.make_character()
        client.post(f'/admin/chapter-associations/{ch.chapter_num}/add',
                    data={'search_terms': '', 'character_id': str(c.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert c not in ch.characters

    def test_add_recounts_book_mentions(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao. Cao Cao again.</p>')
        c = factories.make_character(name='Cao Cao')
        assert c.book_mention_count == 0
        client.post(f'/admin/chapter-associations/{ch.chapter_num}/add',
                    data={'search_terms': 'Cao Cao',
                          'character_id': str(c.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert Character.query.get(c.id).book_mention_count == 2

    def test_name_hash_suffix_resolution(self, admin_client, db_session):
        # Picker fallback: 'Name #<id>' in character_name resolves
        # without character_id.
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Lady Cao entered.</p>')
        a = factories.make_character(name='Lady Cao', birth_date='150')
        factories.make_character(name='Lady Cao', birth_date='170')
        client.post(f'/admin/chapter-associations/{ch.chapter_num}/add',
                    data={'search_terms': 'Lady Cao',
                          'character_name': f'Lady Cao #{a.id}'},
                    follow_redirects=True)
        db_session.expire_all()
        assert a in ch.characters

    def test_bare_duplicate_name_rejected(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Lady Cao entered.</p>')
        factories.make_character(name='Lady Cao', birth_date='150')
        factories.make_character(name='Lady Cao', birth_date='170')
        client.post(f'/admin/chapter-associations/{ch.chapter_num}/add',
                    data={'search_terms': 'Lady Cao',
                          'character_name': 'Lady Cao'},
                    follow_redirects=True)
        assert len(ch.characters) == 0


class TestCharacterRemoveSwitch:
    def test_remove_drops_m2m_and_recounts(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao.</p>')
        c = factories.make_character(name='Cao Cao', book_mention_count=1)
        factories.associate_character(ch, c, keywords='Cao Cao')
        client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/remove/{c.id}',
            follow_redirects=True)
        db_session.expire_all()
        assert c not in ch.characters
        assert Character.query.get(c.id).book_mention_count == 0

    def test_switch_swaps_characters(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao.</p>')
        old = factories.make_character(name='Wrong Guy')
        new = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, old)
        client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/switch/{old.id}',
            data={'character_id': str(new.id)}, follow_redirects=True)
        db_session.expire_all()
        assert old not in ch.characters
        assert new in ch.characters


class TestCharacterExcludeRestore:
    def _setup(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao. Cao Cao again.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        mentions = find_character_mentions(ch, c, needles=['Cao Cao'])
        return ch, c, mentions

    def test_exclude_stores_row_and_suppresses_pill(self, admin_client,
                                                    db_session):
        client, _ = admin_client
        ch, c, mentions = self._setup(db_session)
        first = mentions[0]
        resp = client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/{c.id}/exclude',
            data={'match_text': first['match'],
                  'before_snippet': first['before'],
                  'after_snippet': first['after']},
            headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        assert resp.get_json()['id']
        row = MatchExclusion.query.filter_by(
            chapter_id=ch.id, target_type='character', target_id=c.id).first()
        assert row is not None
        # The chapter render now pills only the second occurrence.
        page = client.get(f'/chapter/{ch.chapter_num}')
        assert page.data.count(f"data-character-id='{c.id}'".encode()) == 1

    def test_exclude_idempotent_same_fingerprint(self, admin_client,
                                                 db_session):
        client, _ = admin_client
        ch, c, mentions = self._setup(db_session)
        first = mentions[0]
        payload = {'match_text': first['match'],
                   'before_snippet': first['before'],
                   'after_snippet': first['after']}
        r1 = client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/{c.id}/exclude',
            data=payload, headers={'Accept': 'application/json'})
        r2 = client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/{c.id}/exclude',
            data=payload, headers={'Accept': 'application/json'})
        assert r1.get_json()['id'] == r2.get_json()['id']
        assert MatchExclusion.query.filter_by(
            chapter_id=ch.id, target_id=c.id).count() == 1

    def test_restore_deletes_row(self, admin_client, db_session):
        client, _ = admin_client
        ch, c, mentions = self._setup(db_session)
        first = mentions[0]
        r = client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/{c.id}/exclude',
            data={'match_text': first['match'],
                  'before_snippet': first['before'],
                  'after_snippet': first['after']},
            headers={'Accept': 'application/json'})
        ex_id = r.get_json()['id']
        r2 = client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/{c.id}'
            f'/restore/{ex_id}',
            headers={'Accept': 'application/json'})
        assert r2.status_code == 200
        assert MatchExclusion.query.get(ex_id) is None

    def test_restore_wrong_pairing_404(self, admin_client, db_session):
        client, _ = admin_client
        ch, c, mentions = self._setup(db_session)
        other = factories.make_character(name='Other Guy')
        first = mentions[0]
        r = client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/{c.id}/exclude',
            data={'match_text': first['match'],
                  'before_snippet': first['before'],
                  'after_snippet': first['after']},
            headers={'Accept': 'application/json'})
        ex_id = r.get_json()['id']
        resp = client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/{other.id}'
            f'/restore/{ex_id}')
        assert resp.status_code == 404

    def test_empty_match_text_400(self, admin_client, db_session):
        client, _ = admin_client
        ch, c, _ = self._setup(db_session)
        resp = client.post(
            f'/admin/chapter-associations/{ch.chapter_num}/{c.id}/exclude',
            data={'match_text': ''},
            headers={'Accept': 'application/json'})
        assert resp.status_code == 400


class TestEventAssociations:
    def test_add_with_keywords_optional(self, admin_client, db_session):
        # dc92229: an event may associate with NO keywords.
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Something happened.</p>')
        ev = factories.make_event(name='Offstage Pact')
        client.post(f'/admin/event-associations/{ch.chapter_num}/add',
                    data={'search_terms': '', 'event_id': str(ev.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert ev in ch.events
        assert _kw(db_session, 'event_chapter', 'event_id', ch, ev) == ''

    def test_add_stores_matched_keywords(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>At Chibi the fires rose.</p>')
        ev = factories.make_event(name='Red Cliffs')
        client.post(f'/admin/event-associations/{ch.chapter_num}/add',
                    data={'search_terms': 'Chibi, Missing',
                          'event_id': str(ev.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert _kw(db_session, 'event_chapter', 'event_id', ch, ev) == 'Chibi'

    def test_resync_replaces_event_keywords(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>At Chibi near Red Cliffs.</p>')
        ev = factories.make_event(name='The Battle')
        factories.associate_event(ch, ev, keywords='Chibi')
        client.post(f'/admin/event-associations/{ch.chapter_num}/add',
                    data={'search_terms': 'Red Cliffs',
                          'event_id': str(ev.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert _kw(db_session, 'event_chapter', 'event_id',
                   ch, ev) == 'Red Cliffs'

    def test_remove_event(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        ev = factories.make_event()
        factories.associate_event(ch, ev)
        client.post(
            f'/admin/event-associations/{ch.chapter_num}/remove/{ev.id}',
            follow_redirects=True)
        db_session.expire_all()
        assert ev not in ch.events


class TestLocationAssociations:
    def test_add_and_keywords(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>They reached Loyang.</p>')
        loc = factories.make_location(name='Luoyang')
        client.post(f'/admin/location-associations/{ch.chapter_num}/add',
                    data={'search_terms': 'Loyang',
                          'location_id': str(loc.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert loc in ch.locations
        assert _kw(db_session, 'chapter_location', 'location_id',
                   ch, loc) == 'Loyang'

    def test_location_exclude_restore_round_trip(self, admin_client,
                                                 db_session):
        client, _ = admin_client
        ch = factories.make_chapter(
            content='<p>Luoyang stood. Luoyang fell.</p>')
        loc = factories.make_location(name='Luoyang')
        factories.associate_location(ch, loc, keywords='Luoyang')
        from tools.book_parser import find_location_mentions
        mentions = find_location_mentions(ch, loc, needles=['Luoyang'])
        first = mentions[0]
        r = client.post(
            f'/admin/location-associations/{ch.chapter_num}/{loc.id}/exclude',
            data={'match_text': first['match'],
                  'before_snippet': first['before'],
                  'after_snippet': first['after']},
            headers={'Accept': 'application/json'})
        assert r.status_code == 200
        ex_id = r.get_json()['id']
        page = client.get(f'/chapter/{ch.chapter_num}')
        assert page.data.count(f"data-location-id='{loc.id}'".encode()) >= 1
        r2 = client.post(
            f'/admin/location-associations/{ch.chapter_num}/{loc.id}'
            f'/restore/{ex_id}',
            headers={'Accept': 'application/json'})
        assert r2.status_code == 200
        assert MatchExclusion.query.get(ex_id) is None

    def test_remove_location(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        loc = factories.make_location()
        factories.associate_location(ch, loc)
        client.post(
            f'/admin/location-associations/{ch.chapter_num}/remove/{loc.id}',
            follow_redirects=True)
        db_session.expire_all()
        assert loc not in ch.locations


class TestListPagesRender:
    def test_association_pages_render_with_selection(self, admin_client,
                                                     db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao at Luoyang.</p>')
        c = factories.make_character(name='Cao Cao')
        loc = factories.make_location(name='Luoyang')
        ev = factories.make_event(name='Muster')
        factories.associate_character(ch, c, keywords='Cao Cao')
        factories.associate_location(ch, loc, keywords='Luoyang')
        factories.associate_event(ch, ev)
        for page in ('chapter-associations', 'event-associations',
                     'location-associations'):
            resp = client.get(f'/admin/{page}/{ch.chapter_num}')
            assert resp.status_code == 200, page

    def test_keywords_column_visible(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao spoke.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao,Mengde')
        resp = client.get(f'/admin/chapter-associations/{ch.chapter_num}')
        assert b'Cao Cao,Mengde' in resp.data
