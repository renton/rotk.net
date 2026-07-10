"""B3 — scraper parsing logic with mocked HTTP.

No network: requests.get is monkeypatched with a canned threekingdoms.com
page skeleton. The td-class mapping (1=prose, 2=quote, 3b=poem) is the
site's actual markup — class="2" blocks were silently dropped for months
(bug f7a1ab5), so that mapping gets pinned hard here.
"""
import pytest

from tools import scraper as scraper_mod
from tools.scraper import (
    build_chapter_url,
    clean_text,
    remove_html_tags,
    scrape_chapter,
)

# Faithful to the live threekingdoms.com markup (captured 2026-07-10):
# unquoted class attrs, a t12b title block whose "Chapter NN" text lives
# inside nested nav links + per-letter <font color=...> tags (ALL nested
# tags get decomposed by the scraper — only the <br>-separated plain
# title lines survive), note-anchor <sup> prefixes on prose cells, and
# <td class=n><textarea class=n> note cells between content cells.
PAGE = """
<html><body>
<font class=t12b>
  <a href="chapter.aspx?c=28"><font color=deeppink>&lt;</font></a><u> <font color=red>C</font><font color=green>h</font>apter 29 </u><a href="chapter.aspx?c=30"><font color=hotpink>&gt;</font></a>
  <br>The Little Chief Of The South Slays Yu Ji;<br>The Green Eyed Boy Lays Hold On The South Land.
  <br>
</font>
<table id=txt_content>
<tr><td class=1><a class="1" name="1" href="note.aspx?p=1"><sup>1</sup></a> Plain prose paragraph one.</td>
<td class=n><textarea class=n></textarea></td></tr>
<tr><td class=2><a class="2" name="2" href="note.aspx?p=2"><sup>2</sup></a> "A quoted letter to the throne."</td>
<td class=n><textarea class=n onclick=alert(this.value)>Explainer text</textarea></td></tr>
<tr><td class=3b>Two kingdoms rise;<br>one falls.</td>
<td class=n><textarea class=n></textarea></td></tr>
<tr><td class=1>Second prose paragraph.</td>
<td class=n><textarea class=n></textarea></td></tr>
</table>
</body></html>
"""


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


@pytest.fixture()
def mock_get(monkeypatch):
    calls = []

    def fake_get(url, headers=None, **kw):
        calls.append(url)
        return FakeResponse(PAGE)

    monkeypatch.setattr(scraper_mod.requests, 'get', fake_get)
    return calls


class TestHelpers:
    def test_build_chapter_url_zero_pads(self):
        assert build_chapter_url(7).endswith('/007.htm')
        assert build_chapter_url(120).endswith('/120.htm')

    def test_clean_text_collapses(self):
        assert clean_text('  a\r\n b\tc  ') == 'a b c'

    def test_clean_text_none(self):
        assert clean_text(None) == ''

    def test_remove_html_tags(self):
        assert remove_html_tags('<b>x</b> y') == 'x y'


class TestScrapeChapter:
    def test_fetches_right_url(self, mock_get):
        scrape_chapter(29)
        assert mock_get[0].endswith('/029.htm')

    def test_title_is_plain_br_lines_nested_tags_decomposed(self, mock_get):
        # Real-site behaviour: the rainbow "Chapter 29" letters live in
        # nested <font>/<a>/<u> tags which the scraper decomposes; only
        # the plain-text <br> title lines survive.
        title, _ = scrape_chapter(29)
        assert 'The Little Chief Of The South Slays Yu Ji' in title
        assert 'chapter.aspx' not in title       # nav links gone
        assert 'deeppink' not in title           # colour spam gone

    def test_title_semicolon_gets_br(self, mock_get):
        # scrape_chapter post-processes: ";" → "; <br>" for two-line
        # display of the traditional couplet titles.
        title, _ = scrape_chapter(29)
        assert '; <br>' in title

    def test_prose_paragraphs_become_plain_p(self, mock_get):
        _, content = scrape_chapter(29)
        assert 'Plain prose paragraph one.' in content
        assert 'Second prose paragraph.' in content

    def test_class_2_quote_blocks_captured(self, mock_get):
        # Regression f7a1ab5: class="2" commentary blocks were dropped.
        _, content = scrape_chapter(29)
        assert 'A quoted letter to the throne.' in content
        assert 'class="quote"' in content

    def test_class_3b_poems_captured(self, mock_get):
        _, content = scrape_chapter(29)
        assert 'Two kingdoms rise;' in content
        assert 'class="poem"' in content

    def test_note_anchors_stripped(self, mock_get):
        _, content = scrape_chapter(29)
        assert 'note.aspx' not in content

    def test_notes_textareas_not_included(self, mock_get):
        _, content = scrape_chapter(29)
        assert 'textarea' not in content

    def test_output_is_p_tags(self, mock_get):
        _, content = scrape_chapter(29)
        assert content.count('<p') == 4
        assert '<td' not in content

    def test_http_error_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            scraper_mod.requests, 'get',
            lambda url, headers=None, **kw: FakeResponse('', status_code=404))
        assert scrape_chapter(29) == ''
