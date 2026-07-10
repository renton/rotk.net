"""T2 — build_needle_pattern + text utilities.

Every rule in build_needle_pattern exists because its absence was a
shipped bug (see CLAUDE.md "build_needle_pattern rules"). These tests
pin each rule so nobody "simplifies" it back into a bug.
"""
import re

import pytest

from tools.book_parser import (
    build_needle_pattern,
    normalize_snippet,
    split_keywords_csv,
    strip_html_tags,
)


class TestLongestFirstAlternation:
    """Bug e7dbfc2: Python | alternation is leftmost-first, so shorter
    prefixes must be sorted after their superstrings."""

    def test_longer_needle_wins_when_prefix_collides(self):
        pat = build_needle_pattern(['Cao', 'Cao Cao'])
        m = pat.search('Cao Cao rose in the east.')
        assert m.group(0) == 'Cao Cao'

    def test_order_of_input_does_not_matter(self):
        for needles in (['Cao', 'Cao Cao'], ['Cao Cao', 'Cao']):
            pat = build_needle_pattern(needles)
            assert pat.search('Cao Cao spoke.').group(0) == 'Cao Cao'

    def test_shorter_needle_still_matches_alone(self):
        pat = build_needle_pattern(['Cao', 'Cao Cao'])
        assert pat.search('Cao spoke.').group(0) == 'Cao'

    def test_findall_mixed_occurrences(self):
        pat = build_needle_pattern(['Cao', 'Cao Cao'])
        found = [m.group(0) for m in pat.finditer('Cao spoke, then Cao Cao spoke.')]
        assert found == ['Cao', 'Cao Cao']

    def test_three_level_prefix_chain(self):
        pat = build_needle_pattern(['Liu', 'Liu Bei', 'Liu Bei Xuande'])
        assert pat.search('Liu Bei Xuande arrived.').group(0) == 'Liu Bei Xuande'


class TestWhitespaceBetweenTokens:
    """Bug 9233c4d: multi-word needles compile with \\s+ between tokens
    so names spanning line breaks still match."""

    def test_matches_across_newline(self):
        pat = build_needle_pattern(['Wang Yun'])
        m = pat.search('They sought Wang\nYun at once.')
        assert m is not None
        assert 'Wang' in m.group(0) and 'Yun' in m.group(0)

    def test_matches_across_multiple_spaces(self):
        pat = build_needle_pattern(['Wang Yun'])
        assert pat.search('Wang   Yun spoke.') is not None

    def test_matches_across_crlf(self):
        pat = build_needle_pattern(['Wang Yun'])
        assert pat.search('Wang\r\nYun spoke.') is not None

    def test_matched_text_needs_collapse_before_lookup(self):
        # Callers must whitespace-collapse group(0) before dict lookup —
        # this documents that the raw match preserves source whitespace.
        pat = build_needle_pattern(['Wang Yun'])
        m = pat.search('Wang\nYun spoke.')
        assert m.group(0) == 'Wang\nYun'
        assert re.sub(r'\s+', ' ', m.group(0)) == 'Wang Yun'


class TestTrailingContext:
    """Bug 9233c4d (same commit): trailing (?=\\W|$) instead of a
    hand-rolled punctuation allowlist."""

    @pytest.mark.parametrize('suffix', [':', ')', ']', '}', ',', '.', ';',
                                        '!', '?', '"', "'", '—', '-', ' '])
    def test_matches_before_punctuation(self, suffix):
        pat = build_needle_pattern(['Wang Yun'])
        assert pat.search(f'Wang Yun{suffix} said') is not None

    def test_matches_at_end_of_string(self):
        pat = build_needle_pattern(['Wang Yun'])
        assert pat.search('It was Wang Yun') is not None

    def test_no_match_when_glued_to_word_chars(self):
        pat = build_needle_pattern(['Cao'])
        assert pat.search('Caozhen spoke.') is None


class TestLeadingBoundary:
    def test_no_match_mid_word(self):
        pat = build_needle_pattern(['Yun'])
        assert pat.search('Xiayun spoke.') is None

    def test_match_at_start_of_string(self):
        pat = build_needle_pattern(['Cao Cao'])
        assert pat.search('Cao Cao opened the gates.') is not None


class TestNeedleEscaping:
    def test_regex_special_chars_escaped(self):
        # A needle containing regex metacharacters must match literally.
        pat = build_needle_pattern(['Lord (the Elder)'])
        assert pat.search('It was Lord (the Elder), truly.') is not None

    def test_dot_is_literal(self):
        pat = build_needle_pattern(['A.B'])
        assert pat.search('Then AxB happened') is None

    def test_empty_needle_list_matches_nothing(self):
        pat = build_needle_pattern([])
        assert pat.search('anything at all') is None

    def test_whitespace_only_needles_match_nothing(self):
        pat = build_needle_pattern(['   ', '\n'])
        assert pat.search('anything at all') is None


class TestStripHtmlTags:
    def test_tags_become_spaces(self):
        assert strip_html_tags('<p>Hello</p>') == ' Hello '

    def test_adjacent_words_not_glued(self):
        out = strip_html_tags('foo<span>bar</span>')
        assert 'foobar' not in out
        assert 'foo' in out and 'bar' in out

    def test_empty_and_none(self):
        assert strip_html_tags('') == ''
        assert strip_html_tags(None) == ''

    def test_attributes_stripped(self):
        out = strip_html_tags("<span class='x' data-y='1'>Cao</span>")
        assert out.strip() == 'Cao'


class TestNormalizeSnippet:
    """The MatchExclusion fingerprint normaliser — bug: form-round-
    tripped \\r\\n vs raw \\n made stored fingerprints never match."""

    def test_crlf_equals_lf(self):
        assert normalize_snippet('a\r\nb') == normalize_snippet('a\nb')

    def test_multispace_collapses(self):
        assert normalize_snippet('a   b') == 'a b'

    def test_strips_ends(self):
        assert normalize_snippet('  a b  ') == 'a b'

    def test_idempotent(self):
        once = normalize_snippet(' a\r\n b ')
        assert normalize_snippet(once) == once

    def test_empty_and_none(self):
        assert normalize_snippet('') == ''
        assert normalize_snippet(None) == ''


class TestSplitKeywordsCsv:
    def test_basic_split(self):
        assert split_keywords_csv('a,b,c') == ['a', 'b', 'c']

    def test_strips_whitespace(self):
        assert split_keywords_csv(' a , b ,c ') == ['a', 'b', 'c']

    def test_dedupes_preserving_order(self):
        assert split_keywords_csv('b,a,b,a') == ['b', 'a']

    def test_drops_empties(self):
        assert split_keywords_csv('a,,b,') == ['a', 'b']

    def test_empty_and_none(self):
        assert split_keywords_csv('') == []
        assert split_keywords_csv(None) == []


class TestNormalizeCsvViewHelper:
    """main.views._normalize_csv — 'A, B' stored as 'A,B'."""

    def test_space_after_comma_removed(self):
        from app.blueprints.main.views import _normalize_csv
        assert _normalize_csv('A, B') == 'A,B'

    def test_empties_dropped(self):
        from app.blueprints.main.views import _normalize_csv
        assert _normalize_csv('A,,B, ') == 'A,B'

    def test_none_is_empty(self):
        from app.blueprints.main.views import _normalize_csv
        assert _normalize_csv(None) == ''
