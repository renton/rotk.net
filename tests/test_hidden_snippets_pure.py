"""T4 — Chapter Edit hide-snippet machinery (pure functions).

apply_hidden_snippets removes admin-hidden prose from the public
render (admin=False) or wraps it in a clickable <s> (admin=True).
Fingerprints are content-addressed; rows whose fingerprint no longer
matches are silently skipped (orphaned, recoverable via admin UI).
"""
from tools.book_parser import (
    _hidden_snippet_context,
    apply_hidden_snippets,
    strip_and_normalize_with_html_map,
)


class FakeRow:
    _next = iter(range(1, 10_000))

    def __init__(self, match_text, before='', after='', id=None):
        self.id = id if id is not None else next(self._next)
        self.match_text = match_text
        self.before_snippet = before
        self.after_snippet = after


def make_row_for(html, target):
    """Build a FakeRow whose fingerprint matches `target`'s first
    occurrence in html — exactly the way chapter_edit_hide stores it."""
    normalized, _ = strip_and_normalize_with_html_map(html)
    idx = normalized.find(target)
    assert idx >= 0, f'{target!r} not in normalized content'
    before, after = _hidden_snippet_context(normalized, idx, len(target))
    return FakeRow(target, before=before, after=after)


class TestStripAndNormalizeWithHtmlMap:
    def test_positions_map_back_to_html(self):
        html = '<p>Hello world</p>'
        normalized, positions = strip_and_normalize_with_html_map(html)
        assert normalized == 'Hello world'
        # Every mapped character must be the same char in the html.
        for i, ch in enumerate(normalized):
            if ch != ' ':
                assert html[positions[i]] == ch

    def test_tags_collapse_to_single_space(self):
        html = 'foo<span>bar</span>baz'
        normalized, _ = strip_and_normalize_with_html_map(html)
        assert normalized == 'foo bar baz'

    def test_whitespace_runs_collapse(self):
        normalized, _ = strip_and_normalize_with_html_map('a   b\n\nc')
        assert normalized == 'a b c'

    def test_leading_trailing_trimmed(self):
        normalized, positions = strip_and_normalize_with_html_map('  <p> a </p>  ')
        assert normalized == 'a'
        assert len(positions) == 1

    def test_empty(self):
        assert strip_and_normalize_with_html_map('') == ('', [])
        assert strip_and_normalize_with_html_map(None) == ('', [])

    def test_positions_align_after_tags(self):
        html = '<p>abc</p><p>def</p>'
        normalized, positions = strip_and_normalize_with_html_map(html)
        assert normalized == 'abc def'
        d_norm_idx = normalized.index('d')
        assert html[positions[d_norm_idx]] == 'd'


class TestHiddenSnippetContext:
    def test_short_content_no_ellipsis(self):
        normalized = 'Hello hidden world'
        idx = normalized.find('hidden')
        before, after = _hidden_snippet_context(normalized, idx, len('hidden'))
        assert '…' not in before and '…' not in after

    def test_long_before_gets_ellipsis_and_word_trim(self):
        normalized = ('word ' * 30).strip() + ' TARGET tail'
        idx = normalized.find('TARGET')
        before, after = _hidden_snippet_context(normalized, idx, len('TARGET'))
        assert before.startswith('…')
        assert len(before) <= 62  # 60 + ellipsis wiggle

    def test_long_after_gets_ellipsis(self):
        normalized = 'head TARGET ' + ('word ' * 30).strip()
        idx = normalized.find('TARGET')
        before, after = _hidden_snippet_context(normalized, idx, len('TARGET'))
        assert after.endswith('…')


class TestApplyHiddenSnippetsPublic:
    HTML = '<p>Alpha beta gamma delta.</p><p>Second paragraph here.</p>'

    def test_matching_snippet_removed(self):
        row = make_row_for(self.HTML, 'beta gamma')
        out = apply_hidden_snippets(self.HTML, [row], admin=False)
        assert 'beta gamma' not in out
        assert 'Alpha' in out and 'delta' in out

    def test_structure_preserved_around_removal(self):
        row = make_row_for(self.HTML, 'beta gamma')
        out = apply_hidden_snippets(self.HTML, [row], admin=False)
        assert out.count('<p>') == 2 and out.count('</p>') == 2

    def test_orphaned_fingerprint_skipped_silently(self):
        row = FakeRow('beta gamma', before='stale context',
                      after='also stale')
        out = apply_hidden_snippets(self.HTML, [row], admin=False)
        assert out == self.HTML  # untouched

    def test_unmatched_text_skipped(self):
        row = FakeRow('nonexistent phrase', before='', after='')
        out = apply_hidden_snippets(self.HTML, [row], admin=False)
        assert out == self.HTML

    def test_multiple_rows_removed_in_order(self):
        r1 = make_row_for(self.HTML, 'beta gamma')
        r2 = make_row_for(self.HTML, 'Second paragraph')
        out = apply_hidden_snippets(self.HTML, [r2, r1], admin=False)
        assert 'beta gamma' not in out
        assert 'Second paragraph' not in out
        assert 'Alpha' in out and 'here' in out

    def test_empty_rows_no_op(self):
        assert apply_hidden_snippets(self.HTML, [], admin=False) == self.HTML

    def test_empty_html_no_op(self):
        assert apply_hidden_snippets('', [FakeRow('x')], admin=False) == ''

    def test_whitespace_variant_in_stored_match_still_hides(self):
        # match_text normalised before lookup — a stored "beta  gamma"
        # (double space) still finds the single-space occurrence.
        good = make_row_for(self.HTML, 'beta gamma')
        row = FakeRow('beta  gamma', before=good.before_snippet,
                      after=good.after_snippet)
        out = apply_hidden_snippets(self.HTML, [row], admin=False)
        assert 'beta gamma' not in out


class TestApplyHiddenSnippetsAdmin:
    HTML = '<p>Alpha beta gamma delta.</p>'

    def test_admin_wraps_in_strikethrough(self):
        row = make_row_for(self.HTML, 'beta gamma')
        out = apply_hidden_snippets(self.HTML, [row], admin=True)
        assert 'beta gamma' in out  # text still present
        assert '<s class="hidden-snippet"' in out
        assert f'data-hidden-id="{row.id}"' in out
        assert '</s>' in out

    def test_admin_wrap_encloses_exactly_the_match(self):
        row = make_row_for(self.HTML, 'beta gamma')
        out = apply_hidden_snippets(self.HTML, [row], admin=True)
        start = out.index('<s ')
        end = out.index('</s>')
        wrapped = out[start:end]
        assert 'beta gamma' in wrapped
        assert 'Alpha' not in wrapped and 'delta' not in wrapped

    def test_overlapping_ranges_second_skipped(self):
        # Two rows that would overlap: only the first (by position)
        # is applied; the overlapping one is skipped, not mangled.
        html = '<p>one two three four five</p>'
        r1 = make_row_for(html, 'two three')
        r2 = make_row_for(html, 'three four')
        out = apply_hidden_snippets(html, [r1, r2], admin=False)
        assert 'two three' not in out
        # 'four' survives because the overlapping range was skipped
        assert 'four' in out

    def test_hidden_inside_inline_tags(self):
        html = "<p>It was <span class='x'>Cao Cao</span> who spoke.</p>"
        # Hide across the span boundary — normalized text sees
        # 'It was Cao Cao who spoke.'
        row = make_row_for(html, 'Cao Cao')
        out = apply_hidden_snippets(html, [row], admin=False)
        assert 'Cao Cao' not in out
