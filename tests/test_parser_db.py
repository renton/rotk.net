"""T8 — book_parser functions that read the database."""
from app.models import Chapter
from tests import factories
from tools.book_parser import (
    count_mentions_per_character,
    detect_annotation_refs,
    find_character_mentions,
    find_event_mentions,
    find_location_mentions,
    get_characters_for_chapter,
    load_chapter_keywords,
    load_match_exclusions,
    recount_character_book_mentions,
    scan_chapter_for_characters,
)

PROSE = ('<p>Cao Cao rose. Later Cao Cao marched. Mengde smiled at '
         'Luoyang before Cao Cao slept.</p>')


class TestFindCharacterMentions:
    def test_mention_shape(self, db_session):
        ch = factories.make_chapter(content=PROSE)
        c = factories.make_character(name='Cao Cao')
        mentions = find_character_mentions(ch, c)
        assert len(mentions) == 3
        m = mentions[0]
        assert set(m) >= {'start', 'before', 'match', 'after'}
        assert m['match'] == 'Cao Cao'

    def test_limit(self, db_session):
        ch = factories.make_chapter(content=PROSE)
        c = factories.make_character(name='Cao Cao')
        assert len(find_character_mentions(ch, c, limit=2)) == 2

    def test_needles_override(self, db_session):
        ch = factories.make_chapter(content=PROSE)
        c = factories.make_character(name='Cao Cao')
        mentions = find_character_mentions(ch, c, needles=['Mengde'])
        assert [m['match'] for m in mentions] == ['Mengde']

    def test_exclusions_filter(self, db_session):
        ch = factories.make_chapter(content=PROSE)
        c = factories.make_character(name='Cao Cao')
        all_mentions = find_character_mentions(ch, c)
        target = all_mentions[1]
        factories.make_match_exclusion(
            chapter=ch, target_type='character', target_id=c.id,
            match_text=target['match'], before=target['before'],
            after=target['after'])
        exclusions = load_match_exclusions(ch.id, 'character', c.id)
        remaining = find_character_mentions(ch, c, exclusions=exclusions)
        assert len(remaining) == len(all_mentions) - 1

    def test_no_needles_no_mentions(self, db_session):
        ch = factories.make_chapter(content=PROSE)
        c = factories.make_character(name='Nobody Mentioned')
        assert find_character_mentions(ch, c) == []


class TestFindEventLocationMentions:
    def test_event_mentions_via_aliases(self, db_session):
        ch = factories.make_chapter(
            content='<p>The Battle of Red Cliffs, called Chibi, raged.</p>')
        ev = factories.make_event(name='Battle of Red Cliffs', aliases='Chibi')
        matches = [m['match'] for m in find_event_mentions(ch, ev)]
        assert 'Battle of Red Cliffs' in matches
        assert 'Chibi' in matches

    def test_location_mentions_with_needles_override(self, db_session):
        ch = factories.make_chapter(content='<p>They rode to Loyang.</p>')
        loc = factories.make_location(name='Luoyang', aliases='Loyang')
        matches = find_location_mentions(ch, loc, needles=['Loyang'])
        assert [m['match'] for m in matches] == ['Loyang']

    def test_location_exclusions(self, db_session):
        ch = factories.make_chapter(content='<p>Luoyang stood. Luoyang fell.</p>')
        loc = factories.make_location(name='Luoyang')
        all_m = find_location_mentions(ch, loc)
        assert len(all_m) == 2
        t = all_m[0]
        factories.make_match_exclusion(
            chapter=ch, target_type='location', target_id=loc.id,
            match_text=t['match'], before=t['before'], after=t['after'])
        exclusions = load_match_exclusions(ch.id, 'location', loc.id)
        assert len(find_location_mentions(ch, loc, exclusions=exclusions)) == 1


class TestLoadHelpers:
    def test_load_chapter_keywords(self, db_session):
        ch = factories.make_chapter()
        c = factories.make_character()
        factories.associate_character(ch, c, keywords='x,y')
        kw = load_chapter_keywords(ch.id, 'chapter_character', 'character_id')
        assert kw[c.id] == 'x,y'

    def test_load_chapter_keywords_scoped_to_chapter(self, db_session):
        ch1 = factories.make_chapter()
        ch2 = factories.make_chapter()
        c = factories.make_character()
        factories.associate_character(ch1, c, keywords='only-ch1')
        factories.associate_character(ch2, c, keywords='only-ch2')
        assert load_chapter_keywords(ch1.id, 'chapter_character',
                                     'character_id')[c.id] == 'only-ch1'

    def test_load_match_exclusions_normalises_whitespace(self, db_session):
        ch = factories.make_chapter()
        c = factories.make_character()
        factories.make_match_exclusion(
            chapter=ch, target_type='character', target_id=c.id,
            match_text='Cao  Cao', before='was\r\nthere', after='and  left')
        fps = load_match_exclusions(ch.id, 'character', c.id)
        assert ('was there', 'Cao Cao', 'and left') in fps

    def test_load_match_exclusions_scoped(self, db_session):
        ch = factories.make_chapter()
        c1 = factories.make_character()
        c2 = factories.make_character()
        factories.make_match_exclusion(chapter=ch, target_type='character',
                                       target_id=c1.id, match_text='x')
        assert load_match_exclusions(ch.id, 'character', c2.id) == set()


class TestCountMentionsAssociationAware:
    """Bug cdb3180: the count must only cover chapters the character is
    associated with, using per-chapter keywords."""

    def test_lady_cao_duplicates_do_not_cross_count(self, db_session):
        ch16 = factories.make_chapter(content='<p>Lady Cao wept once.</p>')
        ch20 = factories.make_chapter(
            content='<p>Lady Cao smiled. Lady Cao ruled.</p>')
        a = factories.make_character(name='Lady Cao', birth_date='150')
        b = factories.make_character(name='Lady Cao', birth_date='170')
        factories.associate_character(ch16, a, keywords='Lady Cao')
        factories.associate_character(ch20, b, keywords='Lady Cao')
        chapters = Chapter.query.all()
        counts = count_mentions_per_character(chapters, [a, b])
        assert counts[a.id] == 1   # only ch16
        assert counts[b.id] == 2   # only ch20

    def test_unassociated_character_counts_zero(self, db_session):
        factories.make_chapter(content='<p>Cao Cao everywhere.</p>')
        c = factories.make_character(name='Cao Cao')  # no association
        counts = count_mentions_per_character(Chapter.query.all(), [c])
        assert counts[c.id] == 0

    def test_per_chapter_keywords_honored(self, db_session):
        ch = factories.make_chapter(
            content='<p>Mengde spoke. Cao Cao slept.</p>')
        c = factories.make_character(name='Cao Cao', aliases='Mengde')
        # Keywords limited to 'Mengde' only — the 'Cao Cao' occurrence
        # must NOT count.
        factories.associate_character(ch, c, keywords='Mengde')
        counts = count_mentions_per_character(Chapter.query.all(), [c])
        assert counts[c.id] == 1

    def test_global_labels_fallback_when_keywords_empty(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao slept.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='')
        counts = count_mentions_per_character(Chapter.query.all(), [c])
        assert counts[c.id] == 1

    def test_recount_overwrites_from_scratch(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao slept.</p>')
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao')
        c.book_mention_count = 999   # stale garbage
        result = recount_character_book_mentions(c)
        assert result == 1
        assert c.book_mention_count == 1


class TestDetectAnnotationRefs:
    def test_detects_characters_and_locations(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao at Luoyang.</p>')
        c = factories.make_character(name='Cao Cao')
        loc = factories.make_location(name='Luoyang')
        factories.associate_character(ch, c, keywords='Cao Cao')
        factories.associate_location(ch, loc, keywords='Luoyang')
        chars, locs = detect_annotation_refs(ch, 'Cao Cao at Luoyang.')
        assert [x.id for x in chars] == [c.id]
        assert [x.id for x in locs] == [loc.id]

    def test_only_entities_in_section_detected(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao. Liu Bei.</p>')
        c1 = factories.make_character(name='Cao Cao')
        c2 = factories.make_character(name='Liu Bei')
        factories.associate_character(ch, c1, keywords='Cao Cao')
        factories.associate_character(ch, c2, keywords='Liu Bei')
        chars, _ = detect_annotation_refs(ch, 'Only Cao Cao appears here.')
        assert [x.id for x in chars] == [c1.id]

    def test_event_pinned_location_detected(self, db_session):
        ch = factories.make_chapter(content='<p>At Red Cliffs.</p>')
        loc = factories.make_location(name='Red Cliffs')
        ev = factories.make_event(name='The Battle', location_id=loc.id)
        factories.associate_event(ch, ev)
        db_session.flush()
        db_session.expire_all()
        _, locs = detect_annotation_refs(ch, 'The fires at Red Cliffs rose.')
        assert [x.id for x in locs] == [loc.id]

    def test_unassociated_entity_never_detected(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao spoke.</p>')
        factories.make_character(name='Cao Cao')  # NOT associated
        chars, locs = detect_annotation_refs(ch, 'Cao Cao spoke.')
        assert chars == [] and locs == []


class TestChapterCharacterFallback:
    def test_scan_finds_by_global_labels(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao and Liu Bei met.</p>')
        c1 = factories.make_character(name='Cao Cao')
        c2 = factories.make_character(name='Liu Bei')
        factories.make_character(name='Sun Quan')
        found = {c.id for c in scan_chapter_for_characters(ch)}
        assert found == {c1.id, c2.id}

    def test_get_characters_prefers_m2m_cache(self, db_session):
        ch = factories.make_chapter(content='<p>Cao Cao and Liu Bei met.</p>')
        c1 = factories.make_character(name='Cao Cao')
        factories.make_character(name='Liu Bei')  # in text but NOT associated
        factories.associate_character(ch, c1)
        got = get_characters_for_chapter(ch.id)
        assert [c.id for c in got] == [c1.id]
