"""T14 — composite cross-feature scenarios.

"What happens when features collide" — annotations vs hidden snippets,
exclusions vs content changes, duplicate-name splits through the full
HTTP render, per-chapter keyword isolation. Several of these are
executable documentation of ACCEPTED behaviours (orphaning caveats),
so if a future change 'fixes' them, the test failing is a prompt to
update docs + decide intentionally.
"""
import sqlalchemy as sa

from app.models import Annotation, Character, MatchExclusion
from tests import factories
from tools.book_parser import (
    _hidden_snippet_context,
    find_character_mentions,
    strip_and_normalize_with_html_map,
)


def hide_via_http(client, ch, target, before='', after=''):
    resp = client.post(f'/admin/chapter-edit/{ch.chapter_num}/hide',
                       data={'match_text': target, 'before': before,
                             'after': after},
                       headers={'Accept': 'application/json'})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['id']


class TestAnnotationVsHiddenSnippet:
    P1 = 'First paragraph stays put entirely.'
    P2 = 'Second paragraph has a REMOVABLE PIECE inside it.'
    CONTENT = f'<p>{P1}</p><p>{P2}</p>'

    def test_hide_inside_annotated_paragraph_orphans_icon(self, admin_client,
                                                          db_session):
        """Documents the accepted caveat: hiding text inside an
        annotated paragraph shifts its canonical form, so the
        annotation icon stops appearing. The row survives."""
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        ann = factories.make_annotation(chapter=ch, section_text=self.P2,
                                        is_public=True)
        page = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon-black' in page.data   # visible before

        hide_via_http(client, ch, 'REMOVABLE PIECE',
                      before='Second paragraph has a', after='inside it.')
        page = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon-black' not in page.data  # orphaned
        # Row still exists and shows on the admin list.
        assert Annotation.query.get(ann.id) is not None
        lst = client.get('/admin/annotations/public')
        assert b'note body' in lst.data

    def test_hide_in_other_paragraph_leaves_annotation_alone(self,
                                                             admin_client,
                                                             db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        factories.make_annotation(chapter=ch, section_text=self.P1,
                                  is_public=True)
        hide_via_http(client, ch, 'REMOVABLE PIECE',
                      before='Second paragraph has a', after='inside it.')
        page = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon-black' in page.data   # P1 icon survives

    def test_restore_unorphans_annotation(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content=self.CONTENT)
        factories.make_annotation(chapter=ch, section_text=self.P2,
                                  is_public=True)
        sid = hide_via_http(client, ch, 'REMOVABLE PIECE',
                            before='Second paragraph has a',
                            after='inside it.')
        client.post(f'/admin/chapter-edit/{ch.chapter_num}/restore/{sid}',
                    headers={'Accept': 'application/json'})
        page = client.get(f'/chapter/{ch.chapter_num}')
        assert b'annotation-icon-black' in page.data   # back again


class TestHiddenSnippetVsPills:
    def test_hidden_text_never_pill_tagged(self, admin_client, client,
                                           db_session):
        """Hidden snippets are stripped BEFORE pill tagging — a hidden
        occurrence of a keyword neither renders nor counts."""
        aclient, _ = admin_client
        ch = factories.make_chapter(
            content='<p>Cao Cao opened. Cao Cao closed the day.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        # Hide the SECOND occurrence with its context.
        hide_via_http(aclient, ch, 'Cao Cao closed',
                      before='Cao Cao opened.', after='the day.')
        page = client.get(f'/chapter/{ch.chapter_num}')
        assert page.data.count(f"data-character-id='{c.id}'".encode()) == 1


class TestExclusionVsContentChange:
    def test_exclusion_orphans_when_context_window_changes(self, db_session):
        """Documents the f7a1ab5 caveat: content inserted inside the
        60-char window breaks the fingerprint (row remains, filter
        stops applying)."""
        ch = factories.make_chapter(
            content='<p>Alpha Cao Cao omega.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        m = find_character_mentions(ch, c, needles=['Cao Cao'])[0]
        factories.make_match_exclusion(
            chapter=ch, target_type='character', target_id=c.id,
            match_text=m['match'], before=m['before'], after=m['after'])
        # Rescrape-style content change right next to the match.
        ch.content = '<p>Alpha NEWLY INSERTED TEXT Cao Cao omega.</p>'
        db_session.flush()
        from tools.book_parser import load_match_exclusions
        exclusions = load_match_exclusions(ch.id, 'character', c.id)
        remaining = find_character_mentions(ch, c, needles=['Cao Cao'],
                                            exclusions=exclusions)
        assert len(remaining) == 1   # exclusion no longer bites

    def test_exclusion_survives_distant_change(self, db_session):
        filler = 'x' * 200
        ch = factories.make_chapter(
            content=f'<p>{filler}</p><p>Alpha Cao Cao omega.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        m = find_character_mentions(ch, c, needles=['Cao Cao'])[0]
        factories.make_match_exclusion(
            chapter=ch, target_type='character', target_id=c.id,
            match_text=m['match'], before=m['before'], after=m['after'])
        # Change far upstream (>60 chars away from the match).
        ch.content = ch.content.replace(filler, filler + ' plus more')
        db_session.flush()
        from tools.book_parser import load_match_exclusions
        exclusions = load_match_exclusions(ch.id, 'character', c.id)
        remaining = find_character_mentions(ch, c, needles=['Cao Cao'],
                                            exclusions=exclusions)
        assert remaining == []   # still excluded


class TestDuplicateNameSplit:
    """The full Lady Cao scenario (5f6d08a): two same-named characters
    share a keyword; mirror-exclusions split the occurrences."""

    CONTENT = ('<p>Lady Cao entered. Lady Cao spoke.</p>'
               '<p>Then Lady Cao wept while Lady Cao watched.</p>')

    def _setup(self, db_session):
        ch = factories.make_chapter(content=self.CONTENT)
        a = factories.make_character(name='Lady Cao', birth_date='150')
        b = factories.make_character(name='Lady Cao', birth_date='170')
        factories.associate_character(ch, a, keywords='Lady Cao')
        factories.associate_character(ch, b, keywords='Lady Cao')
        mentions = find_character_mentions(ch, a, needles=['Lady Cao'])
        assert len(mentions) == 4
        return ch, a, b, mentions

    def _exclude(self, db_session, ch, char, mention):
        factories.make_match_exclusion(
            chapter=ch, target_type='character', target_id=char.id,
            match_text=mention['match'], before=mention['before'],
            after=mention['after'])

    def test_mirror_exclusions_split_pills(self, client, db_session):
        ch, a, b, m = self._setup(db_session)
        # A excludes occurrences 1 and 3; B excludes 0 and 2.
        self._exclude(db_session, ch, a, m[1])
        self._exclude(db_session, ch, a, m[3])
        self._exclude(db_session, ch, b, m[0])
        self._exclude(db_session, ch, b, m[2])
        page = client.get(f'/chapter/{ch.chapter_num}').data
        assert page.count(f"data-character-id='{a.id}'".encode()) == 2
        assert page.count(f"data-character-id='{b.id}'".encode()) == 2

    def test_both_excluded_occurrence_renders_plain(self, client, db_session):
        ch, a, b, m = self._setup(db_session)
        # Both exclude occurrence 0 → plain text there; A wins the rest.
        self._exclude(db_session, ch, a, m[0])
        self._exclude(db_session, ch, b, m[0])
        page = client.get(f'/chapter/{ch.chapter_num}').data
        total_pills = (page.count(f"data-character-id='{a.id}'".encode()) +
                       page.count(f"data-character-id='{b.id}'".encode()))
        assert total_pills == 3

    def test_no_exclusions_first_candidate_wins_all(self, client, db_session):
        ch, a, b, _ = self._setup(db_session)
        page = client.get(f'/chapter/{ch.chapter_num}').data
        pills_a = page.count(f"data-character-id='{a.id}'".encode())
        pills_b = page.count(f"data-character-id='{b.id}'".encode())
        assert pills_a + pills_b == 4
        assert (pills_a == 4) or (pills_b == 4)   # one candidate sweeps


class TestPerChapterKeywordIsolation:
    def test_resync_one_chapter_leaves_other_render_unchanged(
            self, admin_client, client, db_session):
        aclient, _ = admin_client
        ch5 = factories.make_chapter(content='<p>Cao Cao and Mengde met.</p>')
        ch6 = factories.make_chapter(content='<p>Cao Cao and Mengde parted.</p>')
        c = factories.make_character(name='Cao Cao', aliases='Mengde')
        factories.associate_character(ch5, c, keywords='Cao Cao,Mengde')
        factories.associate_character(ch6, c, keywords='Cao Cao,Mengde')
        # Resync ch5 down to only Mengde via the admin endpoint.
        aclient.post(f'/admin/chapter-associations/{ch5.chapter_num}/add',
                     data={'search_terms': 'Mengde',
                           'character_id': str(c.id)},
                     follow_redirects=True)
        page5 = client.get(f'/chapter/{ch5.chapter_num}').data
        page6 = client.get(f'/chapter/{ch6.chapter_num}').data
        assert page5.count(f"data-character-id='{c.id}'".encode()) == 1
        assert page6.count(f"data-character-id='{c.id}'".encode()) == 2

    def test_empty_keywords_fall_back_to_global_labels(self, client,
                                                       db_session):
        ch = factories.make_chapter(content='<p>Cao Cao waved.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='')
        page = client.get(f'/chapter/{ch.chapter_num}').data
        assert page.count(f"data-character-id='{c.id}'".encode()) == 1


class TestAnnotationRefSnapshot:
    """Accepted behaviour: refs are computed at CREATE time and never
    refreshed automatically."""

    def test_association_added_after_annotation_does_not_backfill(
            self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Cao Cao pondered.</p>')
        resp = client.post('/admin/annotations/create', data={
            'chapter_id': str(ch.id),
            'section_text': 'Cao Cao pondered.',
            'body': 'early note', 'is_public': '1',
        }, headers={'Accept': 'application/json'})
        ann = Annotation.query.get(resp.get_json()['id'])
        assert ann.characters == []   # nothing associated yet
        # NOW associate the character whose keyword matches.
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        db_session.expire_all()
        assert Annotation.query.get(ann.id).characters == []  # unchanged

    def test_backfill_cli_fills_refless_and_skips_reffed(self, cli_runner,
                                                         db_session):
        ch = factories.make_chapter(content='<p>Cao Cao pondered.</p>')
        c = factories.make_character(name='Cao Cao')
        other = factories.make_character(name='Liu Bei')
        factories.associate_character(ch, c, keywords='Cao Cao')
        factories.associate_character(ch, other, keywords='Liu Bei')
        refless = factories.make_annotation(chapter=ch,
                                            section_text='Cao Cao pondered.')
        reffed = factories.make_annotation(chapter=ch,
                                           section_text='Cao Cao pondered.')
        reffed.characters = [other]   # deliberately 'wrong' but present
        db_session.flush()
        result = cli_runner.invoke(args=['backfill-annotation-refs'])
        assert result.exit_code == 0
        db_session.expire_all()
        assert [x.id for x in Annotation.query.get(refless.id).characters] == [c.id]
        # Existing refs untouched — never refreshed.
        assert [x.id for x in Annotation.query.get(reffed.id).characters] == [other.id]


class TestCloseThreadVsPublicIcon:
    def test_close_leaves_black_icon_from_public_annotation(self,
                                                            admin_client,
                                                            db_session):
        client, _ = admin_client
        section = 'The paragraph in question here.'
        ch = factories.make_chapter(content=f'<p>{section}</p>')
        factories.make_annotation(chapter=ch, section_text=section,
                                  is_public=True)
        factories.make_annotation(chapter=ch, section_text=section,
                                  is_public=False)
        page = client.get(f'/chapter/{ch.chapter_num}').data
        assert b'annotation-icon-red' in page   # private dominates for admin
        client.post('/admin/annotations/close-thread', data={
            'chapter_id': str(ch.id), 'section_text': section,
        }, follow_redirects=True)
        page = client.get(f'/chapter/{ch.chapter_num}').data
        assert b'annotation-icon-red' not in page
        assert b'annotation-icon-black' in page   # public thread persists


class TestRecountChain:
    def test_add_resync_remove_chain_keeps_count_fresh(self, admin_client,
                                                       db_session):
        client, _ = admin_client
        ch = factories.make_chapter(
            content='<p>Cao Cao rode. Mengde walked. Cao Cao slept.</p>')
        c = factories.make_character(name='Cao Cao', aliases='Mengde')
        base = f'/admin/chapter-associations/{ch.chapter_num}'
        # add: both keywords → 3 mentions
        client.post(f'{base}/add', data={'search_terms': 'Cao Cao,Mengde',
                                         'character_id': str(c.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert Character.query.get(c.id).book_mention_count == 3
        # resync: only Mengde → 1
        client.post(f'{base}/add', data={'search_terms': 'Mengde',
                                         'character_id': str(c.id)},
                    follow_redirects=True)
        db_session.expire_all()
        assert Character.query.get(c.id).book_mention_count == 1
        # remove → 0
        client.post(f'{base}/remove/{c.id}', follow_redirects=True)
        db_session.expire_all()
        assert Character.query.get(c.id).book_mention_count == 0


class TestAllThreeFeaturesStacked:
    def test_annotated_excluded_and_hidden_renders_without_error(
            self, admin_client, client, db_session):
        """Annotation + MatchExclusion + ChapterHiddenSnippet all on one
        paragraph must not 500 anywhere."""
        aclient, _ = admin_client
        ch = factories.make_chapter(
            content='<p>Cao Cao spoke. Cao Cao left. EXTRA BIT ends.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        # Exclude second pill occurrence.
        m = find_character_mentions(ch, c, needles=['Cao Cao'])
        factories.make_match_exclusion(
            chapter=ch, target_type='character', target_id=c.id,
            match_text=m[1]['match'], before=m[1]['before'],
            after=m[1]['after'])
        # Annotate the paragraph.
        factories.make_annotation(
            chapter=ch,
            section_text='Cao Cao spoke. Cao Cao left. EXTRA BIT ends.',
            is_public=True)
        # Hide a chunk.
        hide_via_http(aclient, ch, 'EXTRA BIT',
                      before='Cao Cao left.', after='ends.')
        for cl in (client, aclient):
            resp = cl.get(f'/chapter/{ch.chapter_num}')
            assert resp.status_code == 200
            assert b'EXTRA BIT' not in resp.data
