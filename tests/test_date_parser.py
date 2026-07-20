"""tools.date_parser — pure-function suite (no DB).

Pins every date-string shape found in the production DB as of the
2026-07 sweep of event.date + character.birth_date/death_date (297
distinct strings), especially the range/partial-endpoint shapes added
for them. Approximate float positions use pytest.approx.
"""
import pytest

from tools.date_parser import parse_date_range, parse_date_range_detailed


approx = lambda pair: pytest.approx(pair, abs=0.01)


class TestSinglePoints:
    def test_bare_year(self):
        assert parse_date_range('208') == (208.0, 209.0)

    def test_era_variants(self):
        assert parse_date_range('208 AD') == (208.0, 209.0)
        assert parse_date_range('AD 208') == (208.0, 209.0)
        assert parse_date_range('208 CE') == (208.0, 209.0)
        # BC 1 == astronomical 0
        assert parse_date_range('208 BC') == (-207.0, -206.0)
        assert parse_date_range('1046 BCE') == (-1045.0, -1044.0)

    def test_month_year(self):
        lo, hi = parse_date_range('October 184')
        assert 184.7 < lo < hi < 184.9

    def test_month_day_year_with_comma(self):
        lo, hi = parse_date_range('February 3, 168')
        assert 168.08 < lo < hi < 168.1

    def test_day_month_year(self):
        lo, hi = parse_date_range('11 December 220')
        assert 220.9 < lo < hi < 221.0

    def test_day_month_comma_era(self):
        # "15 January, 5 CE" — comma in day-month order (db shape)
        lo, hi = parse_date_range('15 January, 5 CE')
        assert 5.0 < lo < hi < 5.1

    def test_era_between_month_and_year(self):
        # "6 October AD 23 " — era token before the year, trailing space
        lo, hi = parse_date_range('6 October AD 23 ')
        assert 23.7 < lo < hi < 23.8

    def test_season(self):
        lo, hi = parse_date_range('Winter 208')
        assert lo > 208.9 and hi == 209.0

    def test_bc_day_precision(self):
        lo, hi = parse_date_range('1 June 195 BC')
        assert -193.7 < lo < hi < -193.5


class TestQualifiers:
    def test_circa_keeps_literal_span(self):
        # Circa no longer pads the span — the literal dates stand and
        # the fuzziness travels as the `uncertain` flag instead
        # (renderers fade the edge rather than inventing years).
        assert parse_date_range('c. 211') == (211.0, 212.0)
        assert parse_date_range('c.208') == (208.0, 209.0)

    def test_circa_sets_uncertain_flag(self):
        assert parse_date_range_detailed('c. 211') == (211.0, 212.0, True)
        assert parse_date_range_detailed('approx 168') == (168.0, 169.0, True)
        assert parse_date_range_detailed('208') == (208.0, 209.0, False)

    def test_early_late(self):
        # early/mid/late still TIGHTEN the span (position, not
        # uncertainty) and don't set the flag.
        lo, hi = parse_date_range('early 190')
        assert lo == 190.0 and hi == approx(190.0 + 1 / 3.0)
        assert parse_date_range_detailed('early 190')[2] is False

    def test_trailing_question_mark_is_uncertain(self):
        # "220?" — literal year, uncertain flag (db shape)
        assert parse_date_range('220?') == (220.0, 221.0)
        assert parse_date_range_detailed('220?')[2] is True

    def test_bare_question_mark_unparseable(self):
        # "?" placeholder must stay None
        assert parse_date_range('?') is None
        assert parse_date_range_detailed('?') is None


class TestDecades:
    def test_bare_decade(self):
        # "90s" (db shape)
        assert parse_date_range('90s') == (90.0, 100.0)

    def test_decade_with_era(self):
        assert parse_date_range('190s') == (190.0, 200.0)


class TestRanges:
    def test_year_to_year(self):
        assert parse_date_range('168-172') == (168.0, 173.0)
        assert parse_date_range('168 to 172') == (168.0, 173.0)
        assert parse_date_range('168/172') == (168.0, 173.0)

    def test_trailing_era_applies_to_both_years(self):
        # "500-401 BCE" misparsed to (-400.0, 501.0) before the 2026-07
        # rewrite: the era only bound to the second year, so the first
        # stayed AD. Both ends must be BCE.
        assert parse_date_range('500-401 BCE') == (-499.0, -399.0)

    def test_both_eras_explicit(self):
        assert parse_date_range('256 BC - 247 BC') == (-255.0, -245.0)

    def test_month_year_to_month_year(self):
        # en dash (db shape: "December 215 – April 216")
        lo, hi = parse_date_range('December 215 – April 216')
        assert 215.9 < lo < 216.0 and 216.3 < hi < 216.4

    def test_month_to_month_same_year_shared(self):
        # "c. August – December 219" — left borrows the year; circa
        # keeps the literal span but flags it uncertain
        lo, hi, uncertain = parse_date_range_detailed(
            'c. August – December 219')
        assert lo == approx(219.0 + 212 / 365.0)
        assert hi == approx(220.0)
        assert uncertain is True

    def test_year_to_day(self):
        lo, hi = parse_date_range('198 - 7 February 199')
        assert lo == 198.0 and 199.09 < hi < 199.12

    def test_month_to_bare_year(self):
        lo, hi = parse_date_range('February 190 - 191')
        assert 190.0 < lo < 190.1 and hi == 192.0

    def test_day_month_borrow_year_from_right(self):
        # "3 February - 2 March 200" — left endpoint has no year
        lo, hi = parse_date_range('3 February - 2 March 200')
        assert 200.08 < lo < 200.1 and 200.16 < hi < 200.18

    def test_month_to_day_same_year(self):
        lo, hi = parse_date_range('March 204 - 13 September 204')
        assert 204.1 < lo < 204.2 and 204.69 < hi < 204.71

    def test_or_alternative_endpoint(self):
        # "January or February 213 – July 214" — left side is a union
        lo, hi = parse_date_range('January or February 213 – July 214')
        assert lo == 213.0 and 214.5 < hi < 214.6

    def test_multi_year_month_range(self):
        lo, hi = parse_date_range('July 270 - February 280')
        assert 270.4 < lo < 270.6 and 280.1 < hi < 280.2


class TestUnparseable:
    def test_junk(self):
        assert parse_date_range('bk') is None
        assert parse_date_range('not a date at all ???') is None

    def test_empty(self):
        assert parse_date_range('') is None
        assert parse_date_range('   ') is None
        assert parse_date_range(None) is None
