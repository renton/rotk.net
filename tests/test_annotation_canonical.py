"""T3 — annotation section fingerprints + icon injection.

The canonical form exists because the browser's textContent and the
server's strip_html_tags NEVER agree on tag-boundary whitespace
(bug c156429): textContent inserts nothing at tag boundaries, strip
inserts a space. Removing ALL whitespace is the only reconciliation.
"""
import pytest

from tools.book_parser import (
    annotation_section_canonical,
    annotation_section_hash,
    inject_annotation_icons,
    normalize_paragraph_text,
)


class FakeAnnotation:
    def __init__(self, is_public):
        self.is_public = is_public


PUB = FakeAnnotation(is_public=True)
PRIV = FakeAnnotation(is_public=False)


class TestCanonicalForm:
    def test_br_boundary_matches_browser_textcontent(self):
        # Browser: 'Wang<br>Yun'.textContent == 'WangYun'
        # Server: strip_html_tags → 'Wang Yun'
        # Canonical (whitespace removed) reconciles both to 'WangYun'.
        server_side = annotation_section_canonical('Wang<br>Yun')
        browser_side = annotation_section_canonical('WangYun')
        assert server_side == browser_side == 'WangYun'

    def test_entity_decoding_amp(self):
        assert annotation_section_canonical('Salt &amp; iron') == \
            annotation_section_canonical('Salt & iron')

    def test_entity_decoding_nbsp(self):
        # &nbsp; decodes to \xa0 which is whitespace — removed entirely.
        assert annotation_section_canonical('a&nbsp;tax') == \
            annotation_section_canonical('a tax')

    def test_all_whitespace_removed(self):
        assert annotation_section_canonical(' a \n b\tc ') == 'abc'

    def test_tags_stripped(self):
        canon = annotation_section_canonical(
            "<span class='x'>Cao Cao</span> rose")
        assert canon == 'CaoCaorose'

    def test_empty_and_none(self):
        assert annotation_section_canonical('') == ''
        assert annotation_section_canonical(None) == ''

    def test_idempotent(self):
        once = annotation_section_canonical('<p>a &amp; b</p>')
        assert annotation_section_canonical(once) == once


class TestSectionHash:
    def test_hash_converges_raw_html_vs_stripped_text(self):
        raw = "It was <span class='pill'>Cao Cao</span> who spoke."
        stripped = 'It was Cao Cao who spoke.'
        assert annotation_section_hash(raw) == annotation_section_hash(stripped)

    def test_hash_converges_browser_style_text(self):
        # No space at tag boundary — as textContent would give it.
        raw = 'Wang<br>Yun alone.'
        browser = 'WangYun alone.'
        assert annotation_section_hash(raw) == annotation_section_hash(browser)

    def test_hash_is_16_hex_chars(self):
        h = annotation_section_hash('some paragraph')
        assert len(h) == 16
        int(h, 16)  # raises if not hex

    def test_different_text_different_hash(self):
        assert annotation_section_hash('paragraph one') != \
            annotation_section_hash('paragraph two')


class TestNormalizeParagraphText:
    def test_collapses_whitespace_keeps_spaces(self):
        assert normalize_paragraph_text('a  b\nc') == 'a b c'

    def test_decodes_entities(self):
        assert normalize_paragraph_text('a &amp; b') == 'a & b'


class TestIconInjection:
    P1 = 'The first paragraph of prose.'
    P2 = 'The second paragraph entirely.'
    HTML = f'<p>{P1}</p>\n<p>{P2}</p>'

    def _by_section(self, mapping):
        # keys must be canonical forms
        return {
            annotation_section_canonical(text): anns
            for text, anns in mapping.items()
        }

    # --- public reader ---

    def test_public_no_annotations_no_icon(self):
        out = inject_annotation_icons(self.HTML, {}, is_admin=False)
        assert 'annotation-icon' not in out

    def test_public_private_only_no_icon(self):
        by = self._by_section({self.P1: [PRIV]})
        out = inject_annotation_icons(self.HTML, by, is_admin=False)
        assert 'annotation-icon' not in out

    def test_public_sees_black_icon_for_public_annotation(self):
        by = self._by_section({self.P1: [PUB]})
        out = inject_annotation_icons(self.HTML, by, is_admin=False)
        assert 'annotation-icon-black' in out
        assert 'annotation-icon-red' not in out
        assert 'annotation-icon-blue' not in out

    def test_public_icon_only_on_annotated_paragraph(self):
        by = self._by_section({self.P1: [PUB]})
        out = inject_annotation_icons(self.HTML, by, is_admin=False)
        p1_part, p2_part = out.split('</p>', 1)
        assert 'annotation-icon' in p1_part
        assert 'annotation-icon' not in p2_part

    # --- admin ---

    def test_admin_gets_blue_add_icon_on_clean_paragraph(self):
        out = inject_annotation_icons(self.HTML, {}, is_admin=True)
        assert out.count('annotation-icon-blue') == 2
        assert 'annotation-icon-add' in out

    def test_admin_public_only_black(self):
        by = self._by_section({self.P1: [PUB]})
        out = inject_annotation_icons(self.HTML, by, is_admin=True)
        p1_part = out.split('</p>', 1)[0]
        assert 'annotation-icon-black' in p1_part
        assert 'annotation-icon-red' not in p1_part

    def test_admin_private_wins_red(self):
        by = self._by_section({self.P1: [PUB, PRIV]})
        out = inject_annotation_icons(self.HTML, by, is_admin=True)
        p1_part = out.split('</p>', 1)[0]
        assert 'annotation-icon-red' in p1_part
        assert 'fa-circle-exclamation' in p1_part

    def test_red_exclamation_precedes_notepad(self):
        # The exclamation sits BEFORE the note-sticky so it grows into
        # the gutter, not over the text (user-requested fix).
        by = self._by_section({self.P1: [PRIV]})
        out = inject_annotation_icons(self.HTML, by, is_admin=True)
        assert out.index('fa-circle-exclamation') < out.index('fa-note-sticky')

    # --- anchors + keys ---

    def test_anchor_id_present_and_hash_derived(self):
        by = self._by_section({self.P1: [PUB]})
        out = inject_annotation_icons(self.HTML, by, is_admin=False)
        expected = annotation_section_hash(self.P1)
        assert f'id="annotation-{expected}"' in out

    def test_data_section_key_set_when_annotated(self):
        by = self._by_section({self.P1: [PUB]})
        out = inject_annotation_icons(self.HTML, by, is_admin=False)
        expected = annotation_section_hash(self.P1)
        assert f'data-section-key="{expected}"' in out

    def test_data_section_key_empty_for_blue_add_icon(self):
        out = inject_annotation_icons(self.HTML, {}, is_admin=True)
        assert 'data-section-key=""' in out

    def test_no_trailing_space_after_icon(self):
        # A trailing space after </a> pushed the first prose word right
        # (indent regression). The icon anchor must abut the text.
        by = self._by_section({self.P1: [PUB]})
        out = inject_annotation_icons(self.HTML, by, is_admin=False)
        assert '</a> The first' not in out
        assert '</a>The first' in out

    def test_annotated_paragraph_with_inline_pills_still_matches(self):
        # Render-time paragraphs contain pill spans; the canonical
        # lookup must still find the stored (plain-text) section.
        pilled = ("<p>It was <span class='text-ref'>Cao Cao</span> "
                  "who spoke.</p>")
        by = self._by_section({'It was Cao Cao who spoke.': [PUB]})
        out = inject_annotation_icons(pilled, by, is_admin=False)
        assert 'annotation-icon-black' in out

    def test_empty_html_passthrough(self):
        assert inject_annotation_icons('', {}, is_admin=True) == ''
