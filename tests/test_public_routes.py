"""T10 — public pages, with the chapter renderer as the centrepiece."""
import sqlalchemy as sa

from tests import factories

PROSE = ('<p>Cao Cao rose in the east. Mengde smiled.</p>'
         '<p>They marched to Luoyang for the muster.</p>')


def _chapter_with_cast(db_session, content=PROSE):
    ch = factories.make_chapter(content=content)
    c = factories.make_character(name='Cao Cao', aliases='Mengde')
    factories.associate_character(ch, c, keywords='Cao Cao,Mengde')
    loc = factories.make_location(name='Luoyang')
    factories.associate_location(ch, loc, keywords='Luoyang')
    return ch, c, loc


class TestIndexAndBasics:
    def test_index_lists_chapters(self, client, db_session):
        ch = factories.make_chapter(name='The Peach Garden Oath')
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'Peach Garden Oath' in resp.data

    def test_chapter_404(self, client, db_session):
        assert client.get('/chapter/9999').status_code == 404

    def test_map_page_renders(self, client, db_session):
        assert client.get('/map').status_code == 200


class TestChapterRender:
    def test_character_pill_rendered(self, client, db_session):
        ch, c, _ = _chapter_with_cast(db_session)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert resp.status_code == 200
        assert f"data-character-id='{c.id}'".encode() in resp.data
        assert b'character-ref' in resp.data

    def test_alias_pill_shows_matched_word(self, client, db_session):
        ch, c, _ = _chapter_with_cast(db_session)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        # 'Mengde' occurrence keeps its prose form inside the pill.
        assert b'>Mengde</span>' in resp.data

    def test_location_ref_rendered(self, client, db_session):
        ch, _, loc = _chapter_with_cast(db_session)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert f"data-location-id='{loc.id}'".encode() in resp.data

    def test_event_ref_rendered(self, client, db_session):
        ch = factories.make_chapter(content='<p>The Great Muster began.</p>')
        ev = factories.make_event(name='Great Muster')
        factories.associate_event(ch, ev, keywords='Great Muster')
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert f"data-event-id='{ev.id}'".encode() in resp.data

    def test_character_wins_conflicting_needle(self, client, db_session):
        # A location whose keyword collides with a character keyword:
        # the character claims the pill.
        ch = factories.make_chapter(content='<p>Wu rode home.</p>')
        c = factories.make_character(name='Wu')
        factories.associate_character(ch, c, keywords='Wu')
        loc = factories.make_location(name='Wu')
        factories.associate_location(ch, loc, keywords='Wu')
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert f"data-character-id='{c.id}'".encode() in resp.data

    def test_chapter_date_shown_when_set(self, client, db_session):
        ch = factories.make_chapter(content='<p>x.</p>', date='192-200 AD')
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'192-200 AD' in resp.data

    def test_unassociated_character_not_tagged(self, client, db_session):
        # NB: a chapter with ZERO associations triggers the documented
        # fallback (regex-scan every character), which WOULD tag Liu
        # Bei. Associate someone else so the M2M cache is non-empty and
        # the fallback stays off — then the unassociated character must
        # not be tagged.
        ch = factories.make_chapter(
            content='<p>Liu Bei passed by Cao Cao.</p>')
        liu = factories.make_character(name='Liu Bei')   # NOT associated
        cao = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, cao, keywords='Cao Cao')
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert f"data-character-id='{cao.id}'".encode() in resp.data
        assert f"data-character-id='{liu.id}'".encode() not in resp.data

    def test_per_chapter_keywords_scope_render(self, client, db_session):
        # Keywords limited to 'Mengde': the 'Cao Cao' text stays plain.
        ch = factories.make_chapter(content='<p>Cao Cao met Mengde.</p>')
        c = factories.make_character(name='Cao Cao', aliases='Mengde')
        factories.associate_character(ch, c, keywords='Mengde')
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'>Mengde</span>' in resp.data
        assert b'>Cao Cao</span>' not in resp.data


class TestDuplicateNameWarning:
    def _dup_chapter(self, db_session):
        ch = factories.make_chapter(content='<p>Lady Cao entered.</p>')
        a = factories.make_character(name='Lady Cao', birth_date='150')
        b = factories.make_character(name='Lady Cao', birth_date='170')
        factories.associate_character(ch, a, keywords='Lady Cao')
        factories.associate_character(ch, b, keywords='Lady Cao')
        return ch

    def test_admin_sees_warning(self, admin_client, db_session):
        ch = self._dup_chapter(db_session)
        client, _ = admin_client
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'character-dup-warning' in resp.data

    def test_public_does_not_see_warning(self, client, db_session):
        ch = self._dup_chapter(db_session)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'character-dup-warning' not in resp.data


class TestAnnotationIconVisibility:
    SECTION = 'Cao Cao rose in the east. Mengde smiled.'

    def test_public_sees_black_for_public_annotation(self, client, db_session):
        ch, _, _ = _chapter_with_cast(db_session)
        factories.make_annotation(chapter=ch, section_text=self.SECTION,
                                  is_public=True)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon-black' in resp.data

    def test_public_sees_nothing_for_private_only(self, client, db_session):
        ch, _, _ = _chapter_with_cast(db_session)
        factories.make_annotation(chapter=ch, section_text=self.SECTION,
                                  is_public=False)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon' not in resp.data

    def test_admin_sees_red_for_private(self, admin_client, db_session):
        ch, _, _ = _chapter_with_cast(db_session)
        factories.make_annotation(chapter=ch, section_text=self.SECTION,
                                  is_public=False)
        client, _ = admin_client
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon-red' in resp.data

    def test_admin_sees_blue_add_on_clean_paragraphs(self, admin_client,
                                                     db_session):
        ch, _, _ = _chapter_with_cast(db_session)
        client, _ = admin_client
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon-blue' in resp.data

    def test_deleted_annotation_invisible(self, client, db_session):
        ch, _, _ = _chapter_with_cast(db_session)
        factories.make_annotation(chapter=ch, section_text=self.SECTION,
                                  is_public=True, is_deleted=True)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon-black' not in resp.data


class TestHiddenSnippetOnPublicPage:
    def test_hidden_text_absent_public(self, client, db_session):
        ch = factories.make_chapter(
            content='<p>Keep this. REMOVE THIS PART. Keep that.</p>')
        from tools.book_parser import (
            _hidden_snippet_context, strip_and_normalize_with_html_map)
        normalized, _ = strip_and_normalize_with_html_map(ch.content)
        idx = normalized.find('REMOVE THIS PART')
        before, after = _hidden_snippet_context(normalized, idx,
                                                len('REMOVE THIS PART'))
        factories.make_hidden_snippet(chapter=ch,
                                      match_text='REMOVE THIS PART',
                                      before=before, after=after)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert b'REMOVE THIS PART' not in resp.data
        assert b'Keep this' in resp.data and b'Keep that' in resp.data

    def test_admin_chapter_edit_shows_strikethrough(self, admin_client,
                                                    db_session):
        ch = factories.make_chapter(
            content='<p>Keep this. REMOVE THIS PART. Keep that.</p>')
        from tools.book_parser import (
            _hidden_snippet_context, strip_and_normalize_with_html_map)
        normalized, _ = strip_and_normalize_with_html_map(ch.content)
        idx = normalized.find('REMOVE THIS PART')
        before, after = _hidden_snippet_context(normalized, idx,
                                                len('REMOVE THIS PART'))
        factories.make_hidden_snippet(chapter=ch,
                                      match_text='REMOVE THIS PART',
                                      before=before, after=after)
        client, _ = admin_client
        resp = client.get(f'/admin/chapter-edit/{ch.chapter_num}')
        assert b'hidden-snippet' in resp.data
        assert b'REMOVE THIS PART' in resp.data


class TestListPages:
    def test_characters_page(self, client, db_session):
        factories.make_character(name='ListMe')
        resp = client.get('/characters')
        assert resp.status_code == 200

    def test_fictional_icon_on_characters_page(self, client, db_session):
        factories.make_character(name='Made Up', is_fictional=True)
        resp = client.get('/characters')
        assert b'fa-book' in resp.data

    def test_factions_page(self, client, db_session):
        factories.make_faction(name='Shu')
        resp = client.get('/factions')
        assert resp.status_code == 200
        assert b'Shu' in resp.data

    def test_roles_page(self, client, db_session):
        factories.make_role(name='strategist')
        assert client.get('/roles').status_code == 200

    def test_events_page(self, client, db_session):
        factories.make_event(name='Great Muster')
        resp = client.get('/events')
        assert resp.status_code == 200
        assert b'Great Muster' in resp.data

    def test_locations_page(self, client, db_session):
        factories.make_location(name='Chengdu')
        resp = client.get('/locations')
        assert resp.status_code == 200
        assert b'Chengdu' in resp.data


class TestMapGeojsonFiltering:
    """Bug 11f25f9: a JSON scalar "" in the JSONB column must not count
    as geo data."""

    def test_empty_string_geojson_excluded(self, client, db_session):
        loc = factories.make_location(name='BadGeoTown')
        db_session.execute(sa.text(
            "UPDATE location SET geojson = '\"\"'::jsonb WHERE id = :i"),
            {'i': loc.id})
        db_session.flush()
        resp = client.get('/map')
        assert b'BadGeoTown' not in resp.data

    def test_real_point_included(self, client, db_session):
        factories.make_location(name='GoodGeoTown', latitude=34.6,
                                longitude=112.4)
        resp = client.get('/map')
        assert b'GoodGeoTown' in resp.data

    def test_no_geo_excluded(self, client, db_session):
        factories.make_location(name='NowhereTown')
        resp = client.get('/map')
        assert b'NowhereTown' not in resp.data
