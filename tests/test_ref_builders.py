"""T5 — inline ref-HTML builders, pill colours, needle-label helpers.

These run without app context — the builders only read attributes off
the objects they're handed, so plain fakes suffice.
"""
from types import SimpleNamespace

from app.models import Character
from tools.book_parser import (
    _word_boundary_overlap,
    build_event_ref_html,
    build_location_ref_html,
    build_name_ref_html,
    character_pill_colours,
    find_location_character_overlap,
    find_shared_needle_ids,
    get_event_labels,
    get_location_labels,
    location_needles,
)


def fake_faction(bg='#112233', font='#ffffff', border='#445566'):
    return SimpleNamespace(
        id=7, bg_colour=bg, font_colour=font, border_colour=border,
        default_colour='#ffffff',
    )


def fake_character(name='Cao Cao', faction=None, id=42):
    return SimpleNamespace(id=id, name=name, primary_faction=faction)


class TestBuildNameRefHtml:
    def test_faction_colours_used(self):
        c = fake_character(faction=fake_faction())
        html = build_name_ref_html(c)
        assert 'background-color:#112233' in html
        assert 'color:#ffffff' in html
        assert 'border:2px solid #445566' in html
        assert "data-faction-id='7'" in html

    def test_no_faction_outline_defaults(self):
        c = fake_character(faction=None)
        html = build_name_ref_html(c)
        assert 'background-color:#ffffff' in html
        assert 'color:#000000' in html
        assert 'data-faction-id' not in html

    def test_default_coloured_faction_falls_back_to_black_bg(self):
        f = fake_faction(bg='#ffffff', border='#ffffff')  # == default_colour
        html = build_name_ref_html(fake_character(faction=f))
        assert 'background-color:#000000' in html

    def test_data_attributes_for_style_switcher(self):
        html = build_name_ref_html(fake_character(faction=fake_faction()))
        assert "data-bg='#112233'" in html
        assert "data-font='#ffffff'" in html
        assert "data-border='#445566'" in html

    def test_text_ref_and_character_ref_classes(self):
        html = build_name_ref_html(fake_character())
        assert 'text-ref' in html and 'character-ref' in html

    def test_display_text_override_shows_alias(self):
        # Bug 2e0d5c8: pill shows the matched prose word, not the
        # canonical name.
        c = fake_character(name='Cao Cao')
        html = build_name_ref_html(c, display_text='Mengde')
        assert '>Mengde</span>' in html
        assert '>Cao Cao</span>' not in html

    def test_display_text_default_is_name(self):
        html = build_name_ref_html(fake_character(name='Cao Cao'))
        assert '>Cao Cao</span>' in html

    def test_duplicate_warning_anchor(self):
        html = build_name_ref_html(
            fake_character(), duplicate_warning_url='/admin/x')
        assert "href='/admin/x'" in html
        assert 'character-dup-warning' in html
        assert 'fa-circle-exclamation' in html

    def test_no_duplicate_warning_by_default(self):
        html = build_name_ref_html(fake_character())
        assert 'character-dup-warning' not in html

    def test_location_overlap_warning_anchor(self):
        html = build_name_ref_html(
            fake_character(),
            location_overlap_url='/admin/loc',
            location_overlap_with=['Luoyang'],
        )
        assert 'character-loc-overlap-warning' in html
        assert 'Luoyang' in html

    def test_both_warnings_can_coexist(self):
        html = build_name_ref_html(
            fake_character(),
            duplicate_warning_url='/a',
            location_overlap_url='/b',
        )
        assert 'character-dup-warning' in html
        assert 'character-loc-overlap-warning' in html


class TestCharacterPillColours:
    def test_parity_with_pill_faction(self):
        c = fake_character(faction=fake_faction())
        bg, font, border = character_pill_colours(c)
        html = build_name_ref_html(c)
        assert f'background-color:{bg}' in html
        assert f'color:{font}' in html
        assert f'border:2px solid {border}' in html

    def test_no_faction_defaults(self):
        assert character_pill_colours(fake_character(faction=None)) == \
            ('#ffffff', '#000000', '#000000')


class TestEventLocationRefs:
    def test_event_ref_shape(self):
        ev = SimpleNamespace(id=5, name='Battle of Red Cliffs')
        html = build_event_ref_html(ev)
        assert "class='event-ref'" in html
        assert "data-event-id='5'" in html
        assert '>Battle of Red Cliffs</span>' in html

    def test_event_ref_match_text(self):
        ev = SimpleNamespace(id=5, name='Battle of Red Cliffs')
        html = build_event_ref_html(ev, match_text='Chibi')
        assert '>Chibi</span>' in html

    def test_location_ref_shape(self):
        loc = SimpleNamespace(id=9, name='Luoyang')
        html = build_location_ref_html(loc)
        assert "class='location-ref'" in html or 'location-ref' in html
        assert "data-location-id='9'" in html

    def test_location_ref_match_text(self):
        loc = SimpleNamespace(id=9, name='Luoyang')
        html = build_location_ref_html(loc, match_text='Loyang')
        assert '>Loyang<' in html


class TestLabelHelpers:
    def test_event_labels_name_plus_aliases(self):
        ev = SimpleNamespace(name='Red Cliffs', aliases='Chibi, 赤壁')
        labels = get_event_labels(ev)
        assert labels == ['Red Cliffs', 'Chibi', '赤壁']

    def test_event_labels_skip_alias_equal_to_name(self):
        ev = SimpleNamespace(name='Red Cliffs', aliases='Red Cliffs,Chibi')
        assert get_event_labels(ev) == ['Red Cliffs', 'Chibi']

    def test_location_labels(self):
        loc = SimpleNamespace(name='Luoyang', aliases=' Loyang , capital ')
        assert get_location_labels(loc) == ['Luoyang', 'Loyang', 'capital']

    def test_location_needles(self):
        loc = SimpleNamespace(name='Luoyang', aliases='Loyang,')
        assert location_needles(loc) == ['Luoyang', 'Loyang']

    def test_get_all_name_labels_strips_whitespace(self):
        # Bug afabbbf: legacy aliases like "Mengde, Lord Cao" produced
        # a needle " Lord Cao" with a leading space.
        c = Character(name=' Cao Cao ', courtesty_name='Mengde',
                      aliases='Lord Cao, The Chancellor ')
        labels = c.get_all_name_labels()
        assert labels == ['Cao Cao', 'Mengde', 'Lord Cao', 'The Chancellor']

    def test_get_all_name_labels_handles_none_fields(self):
        c = Character(name='Solo')
        assert c.get_all_name_labels() == ['Solo']


class TestSharedNeedleIds:
    def test_exact_shared_needle_flagged(self):
        a = SimpleNamespace(id=1)
        b = SimpleNamespace(id=2)
        needles = {1: ['Lady Cao'], 2: ['Lady Cao', 'Empress']}
        dup = find_shared_needle_ids([a, b], lambda e: needles[e.id])
        assert dup == {1, 2}

    def test_distinct_needles_not_flagged(self):
        a = SimpleNamespace(id=1)
        b = SimpleNamespace(id=2)
        needles = {1: ['Cao Cao'], 2: ['Liu Bei']}
        assert find_shared_needle_ids([a, b], lambda e: needles[e.id]) == set()

    def test_alias_collision_across_different_names(self):
        a = SimpleNamespace(id=1)
        b = SimpleNamespace(id=2)
        needles = {1: ['Yu Province', 'Yu'], 2: ['Yu County', 'Yu']}
        dup = find_shared_needle_ids([a, b], lambda e: needles[e.id])
        assert dup == {1, 2}

    def test_blank_needles_ignored(self):
        a = SimpleNamespace(id=1)
        b = SimpleNamespace(id=2)
        needles = {1: ['', '  '], 2: ['', '  ']}
        assert find_shared_needle_ids([a, b], lambda e: needles[e.id]) == set()


class TestWordBoundaryOverlap:
    def test_equal_strings_overlap(self):
        assert _word_boundary_overlap('Yu', 'Yu')

    def test_word_boundary_substring_overlaps(self):
        assert _word_boundary_overlap('Yu', 'Yu Province')

    def test_mid_word_substring_does_not(self):
        # 'Yu' inside 'Yun' is NOT a word-boundary hit — the false
        # positive this helper exists to prevent.
        assert not _word_boundary_overlap('Yu', 'Xia Yun')

    def test_empty_never_overlaps(self):
        assert not _word_boundary_overlap('', 'anything')
        assert not _word_boundary_overlap('x', '')


class TestLocationCharacterOverlap:
    def test_cross_overlap_detected_both_directions(self):
        loc = SimpleNamespace(id=1, name='Wu', aliases='')
        ch = SimpleNamespace(id=2)
        loc_over, char_over = find_location_character_overlap(
            [loc], [ch],
            location_needles_for=lambda l: ['Wu'],
            character_needles_for=lambda c: ['Wu Guotai'],
        )
        assert 1 in loc_over
        assert 2 in char_over

    def test_no_overlap_when_disjoint(self):
        loc = SimpleNamespace(id=1)
        ch = SimpleNamespace(id=2)
        loc_over, char_over = find_location_character_overlap(
            [loc], [ch],
            location_needles_for=lambda l: ['Luoyang'],
            character_needles_for=lambda c: ['Cao Cao'],
        )
        assert loc_over == {} and char_over == {}

    def test_mid_word_not_overlap(self):
        loc = SimpleNamespace(id=1)
        ch = SimpleNamespace(id=2)
        loc_over, char_over = find_location_character_overlap(
            [loc], [ch],
            location_needles_for=lambda l: ['Yu'],
            character_needles_for=lambda c: ['Xia Yun'],
        )
        assert loc_over == {} and char_over == {}
