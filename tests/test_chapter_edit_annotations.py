"""T12 — Chapter Edit (hide-snippet) + annotation endpoints."""
from app.models import Annotation, ChapterHiddenSnippet
from tests import factories


class TestChapterEditHide:
    CONTENT = ('<p>Keep the opening. HIDE ME NOW. Keep the closing.</p>'
               '<p>Repeated phrase here. Repeated phrase there.</p>')

    def _hide(self, client, ch, match_text, before='', after=''):
        return client.post(f'/admin/chapter-edit/{ch.chapter_num}/hide',
                           data={'match_text': match_text,
                                 'before': before, 'after': after},
                           headers={'Accept': 'application/json'})

    def test_hide_stores_row(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        resp = self._hide(client, ch, 'HIDE ME NOW',
                          before='Keep the opening.',
                          after='Keep the closing.')
        assert resp.status_code == 200
        assert resp.get_json()['id']
        row = ChapterHiddenSnippet.query.filter_by(chapter_id=ch.id).first()
        assert row.match_text == 'HIDE ME NOW'

    def test_hidden_text_gone_from_public_render(self, admin_client, client,
                                                 db_session):
        aclient, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        self._hide(aclient, ch, 'HIDE ME NOW',
                   before='Keep the opening.', after='Keep the closing.')
        page = client.get(f'/chapter/{ch.chapter_num}')
        assert b'HIDE ME NOW' not in page.data
        assert b'Keep the opening' in page.data

    def test_hide_idempotent(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        r1 = self._hide(client, ch, 'HIDE ME NOW',
                        before='Keep the opening.',
                        after='Keep the closing.')
        r2 = self._hide(client, ch, 'HIDE ME NOW',
                        before='Keep the opening.',
                        after='Keep the closing.')
        assert r1.get_json()['id'] == r2.get_json()['id']
        assert ChapterHiddenSnippet.query.filter_by(
            chapter_id=ch.id).count() == 1

    def test_context_disambiguates_repeats(self, admin_client, client,
                                           db_session):
        aclient, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        # Hide the SECOND 'Repeated phrase' using its right context.
        resp = self._hide(aclient, ch, 'Repeated phrase',
                          before='Repeated phrase here.', after='there.')
        assert resp.status_code == 200
        page = aclient.get(f'/chapter/{ch.chapter_num}')
        # One occurrence survives.
        assert page.data.count(b'Repeated phrase') == 1

    def test_empty_selection_400(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        resp = self._hide(client, ch, '')
        assert resp.status_code == 400

    def test_text_not_in_chapter_400(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        resp = self._hide(client, ch, 'THIS TEXT DOES NOT EXIST ANYWHERE')
        assert resp.status_code == 400

    def test_restore_deletes_row(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        r = self._hide(client, ch, 'HIDE ME NOW',
                       before='Keep the opening.', after='Keep the closing.')
        sid = r.get_json()['id']
        r2 = client.post(
            f'/admin/chapter-edit/{ch.chapter_num}/restore/{sid}',
            headers={'Accept': 'application/json'})
        assert r2.status_code == 200
        assert ChapterHiddenSnippet.query.get(sid) is None

    def test_restore_wrong_chapter_404(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        other = factories.make_chapter(content='<p>Other.</p>')
        r = self._hide(client, ch, 'HIDE ME NOW',
                       before='Keep the opening.', after='Keep the closing.')
        sid = r.get_json()['id']
        resp = client.post(
            f'/admin/chapter-edit/{other.chapter_num}/restore/{sid}')
        assert resp.status_code == 404

    def test_editor_page_renders(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        resp = client.get(f'/admin/chapter-edit/{ch.chapter_num}')
        assert resp.status_code == 200
        assert b'Hide selected' in resp.data


class TestAnnotationCreate:
    SECTION = 'The one paragraph of this chapter.'
    CONTENT = f'<p>{SECTION}</p>'

    def _create(self, client, ch, body='a note', is_public='0',
                section_text=None):
        return client.post('/admin/annotations/create', data={
            'chapter_id': str(ch.id),
            'section_text': section_text or self.SECTION,
            'body': body,
            'is_public': is_public,
        }, headers={'Accept': 'application/json'})

    def test_create_returns_row(self, admin_client, db_session):
        client, admin = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        resp = self._create(client, ch, body='first note')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['body'] == 'first note'
        assert data['is_public'] is False
        assert data['created_by'] == admin.username

    def test_private_by_default_flag_handling(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        pub = self._create(client, ch, is_public='1').get_json()
        priv = self._create(client, ch, is_public='0').get_json()
        assert pub['is_public'] is True
        assert priv['is_public'] is False

    def test_auto_detected_refs_attached(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao at Luoyang.</p>')
        c = factories.make_character(name='Cao Cao')
        loc = factories.make_location(name='Luoyang')
        factories.associate_character(ch, c, keywords='Cao Cao')
        factories.associate_location(ch, loc, keywords='Luoyang')
        resp = self._create(client, ch, section_text='Cao Cao at Luoyang.')
        ann = Annotation.query.get(resp.get_json()['id'])
        assert [x.id for x in ann.characters] == [c.id]
        assert [x.id for x in ann.locations] == [loc.id]

    def test_unknown_chapter_404(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/admin/annotations/create', data={
            'chapter_id': '999999', 'section_text': 'x', 'body': 'y',
        }, headers={'Accept': 'application/json'})
        assert resp.status_code == 404

    def test_missing_body_400(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        resp = self._create(client, ch, body='')
        assert resp.status_code == 400

    def test_section_text_normalised(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        resp = self._create(client, ch,
                            section_text='The  one\nparagraph of this chapter.')
        ann = Annotation.query.get(resp.get_json()['id'])
        assert '\n' not in ann.section_text
        assert '  ' not in ann.section_text


class TestAnnotationDeleteRestore:
    def test_delete_is_soft(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        ann = factories.make_annotation(chapter=ch, section_text='s')
        resp = client.post(f'/admin/annotations/{ann.id}/delete',
                           headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        db_session.expire_all()
        survivor = Annotation.query.get(ann.id)
        assert survivor is not None
        assert survivor.is_deleted is True

    def test_restore_flips_back(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        ann = factories.make_annotation(chapter=ch, section_text='s',
                                        is_deleted=True)
        resp = client.post(f'/admin/annotations/{ann.id}/restore',
                           headers={'Accept': 'application/json'})
        assert resp.status_code == 200
        db_session.expire_all()
        assert Annotation.query.get(ann.id).is_deleted is False


class TestCloseThread:
    def test_close_soft_deletes_private_only_that_section(self, admin_client,
                                                          db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        p1 = factories.make_annotation(chapter=ch, section_text='sec A',
                                       is_public=False)
        p2 = factories.make_annotation(chapter=ch, section_text='sec A',
                                       is_public=False)
        pub = factories.make_annotation(chapter=ch, section_text='sec A',
                                        is_public=True)
        other = factories.make_annotation(chapter=ch, section_text='sec B',
                                          is_public=False)
        resp = client.post('/admin/annotations/close-thread', data={
            'chapter_id': str(ch.id), 'section_text': 'sec A',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        assert Annotation.query.get(p1.id).is_deleted is True
        assert Annotation.query.get(p2.id).is_deleted is True
        assert Annotation.query.get(pub.id).is_deleted is False   # public safe
        assert Annotation.query.get(other.id).is_deleted is False  # other section safe

    def test_close_missing_params_400(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/admin/annotations/close-thread', data={})
        assert resp.status_code == 400


class TestAnnotationListPages:
    def _seed(self, db_session):
        ch = factories.make_chapter()
        factories.make_annotation(chapter=ch, section_text='thread one',
                                  body='opener one', is_public=True)
        factories.make_annotation(chapter=ch, section_text='thread one',
                                  body='reply one', is_public=True)
        factories.make_annotation(chapter=ch, section_text='thread two',
                                  body='private opener', is_public=False)
        return ch

    def test_public_page_stacks_by_thread(self, admin_client, db_session):
        client, _ = admin_client
        ch = self._seed(db_session)
        resp = client.get('/admin/annotations/public')
        assert resp.status_code == 200
        # Public page shows the public thread's opener but not the
        # private thread.
        assert b'opener one' in resp.data
        assert b'private opener' not in resp.data

    def test_first_annotation_previewed_not_latest(self, admin_client,
                                                   db_session):
        # The page ALSO embeds the full thread as a JSON payload for the
        # modal (so 'reply one' appears in the raw HTML) — the preview
        # column is distinguished by its title attribute.
        client, _ = admin_client
        self._seed(db_session)
        resp = client.get('/admin/annotations/public')
        assert b'title="opener one"' in resp.data
        assert b'title="reply one"' not in resp.data

    def test_private_page_shows_private_and_close_button(self, admin_client,
                                                         db_session):
        client, _ = admin_client
        self._seed(db_session)
        resp = client.get('/admin/annotations/private')
        assert b'private opener' in resp.data
        assert b'Close' in resp.data

    def test_chapter_filter(self, admin_client, db_session):
        client, _ = admin_client
        ch1 = factories.make_chapter()
        ch2 = factories.make_chapter()
        factories.make_annotation(chapter=ch1, section_text='in one',
                                  body='chapter-one-note', is_public=True)
        factories.make_annotation(chapter=ch2, section_text='in two',
                                  body='chapter-two-note', is_public=True)
        resp = client.get(
            f'/admin/annotations/public?chapter_num={ch1.chapter_num}')
        assert b'chapter-one-note' in resp.data
        assert b'chapter-two-note' not in resp.data

    def test_show_deleted_shows_only_deleted(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        factories.make_annotation(chapter=ch, section_text='alive',
                                  body='living-note', is_public=True)
        factories.make_annotation(chapter=ch, section_text='dead',
                                  body='deleted-note', is_public=True,
                                  is_deleted=True)
        normal = client.get('/admin/annotations/public')
        assert b'living-note' in normal.data
        assert b'deleted-note' not in normal.data
        deleted = client.get('/admin/annotations/public?show_deleted=1')
        assert b'deleted-note' in deleted.data
        assert b'living-note' not in deleted.data

    def test_character_filter(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao spoke.</p>')
        c = factories.make_character(name='Cao Cao')
        ann = factories.make_annotation(chapter=ch, section_text='Cao Cao spoke.',
                                        body='cao-note', is_public=True)
        ann.characters = [c]
        other = factories.make_annotation(chapter=ch, section_text='elsewhere',
                                          body='other-note', is_public=True)
        db_session.flush()
        resp = client.get(f'/admin/annotations/public?character_id={c.id}')
        assert b'cao-note' in resp.data
        assert b'other-note' not in resp.data

    def test_location_filter(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        loc = factories.make_location(name='Luoyang')
        ann = factories.make_annotation(chapter=ch, section_text='at Luoyang',
                                        body='loc-note', is_public=True)
        ann.locations = [loc]
        factories.make_annotation(chapter=ch, section_text='elsewhere',
                                  body='nowhere-note', is_public=True)
        db_session.flush()
        resp = client.get(f'/admin/annotations/public?location_id={loc.id}')
        assert b'loc-note' in resp.data
        assert b'nowhere-note' not in resp.data
