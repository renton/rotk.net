"""B3 — colour palette invariants, validators, CSP header, small model
helpers, location-type hierarchy."""
import random

import pytest
from wtforms import ValidationError

from app.models.location import (
    LOCATION_TYPE_PARENT_HIERARCHY, expected_parent_type_name,
)
from tests import factories
from tools.colours import (
    _relative_luminance,
    derive_border_colour,
    random_bg_colour,
    randomize_palette,
    readable_font_colour,
)


HEX_RE = r'^#[0-9a-fA-F]{6}$'


class TestPalette:
    def test_shapes_are_hex(self):
        import re
        rng = random.Random(42)
        for _ in range(20):
            bg, font, border = randomize_palette(rng=rng)
            for colour in (bg, font, border):
                assert re.match(HEX_RE, colour), colour

    def test_font_is_wcag_readable_pick(self):
        # The generator's core promise: black text on light backgrounds,
        # white on dark, decided by relative luminance.
        rng = random.Random(7)
        for _ in range(50):
            bg = random_bg_colour(rng=rng)
            font = readable_font_colour(bg)
            if _relative_luminance(bg) > 0.5:
                assert font == '#000000'
            else:
                assert font == '#ffffff'

    def test_border_differs_from_bg(self):
        rng = random.Random(99)
        for _ in range(20):
            bg = random_bg_colour(rng=rng)
            border = derive_border_colour(bg, rng=rng)
            assert border != bg

    def test_deterministic_with_seed(self):
        assert randomize_palette(rng=random.Random(5)) == \
            randomize_palette(rng=random.Random(5))

    def test_luminance_bounds(self):
        assert _relative_luminance('#000000') == pytest.approx(0.0)
        assert _relative_luminance('#ffffff') == pytest.approx(1.0)


class TestColourValidator:
    class FakeField:
        def __init__(self, data):
            self.data = data

    def _validate(self, value):
        from tools.validators import validate_colour
        validate_colour(None, self.FakeField(value))

    def test_six_digit_hex_ok(self):
        self._validate('#123abc')

    def test_three_digit_hex_ok(self):
        self._validate('#abc')

    @pytest.mark.parametrize('bad', ['red', '123456', '#12345', '#gggggg',
                                     '', '#1234567'])
    def test_bad_values_rejected(self, bad):
        with pytest.raises(ValidationError):
            self._validate(bad)


class TestCspHeader:
    def test_csp_header_present_with_nonce(self, client, db_session):
        resp = client.get('/')
        csp = resp.headers.get('Content-Security-Policy', '')
        assert csp, 'CSP header missing'
        assert "'nonce-" in csp

    def test_nonce_changes_per_request(self, client, db_session):
        def nonce_of(resp):
            csp = resp.headers.get('Content-Security-Policy', '')
            start = csp.index("'nonce-") + len("'nonce-")
            return csp[start:csp.index("'", start)]
        n1 = nonce_of(client.get('/'))
        n2 = nonce_of(client.get('/'))
        assert n1 != n2


class TestSetPrimaryFaction:
    def test_sets_fk_and_m2m(self, db_session):
        c = factories.make_character()
        f = factories.make_faction()
        c.set_primary_faction(f)
        db_session.flush()
        assert c.primary_faction_id == f.id
        assert f in c.factions.all()

    def test_none_clears(self, db_session):
        f = factories.make_faction()
        c = factories.make_character(primary_faction_id=f.id)
        c.set_primary_faction(None)
        db_session.flush()
        assert c.primary_faction_id is None

    def test_no_duplicate_m2m_row(self, db_session):
        c = factories.make_character()
        f = factories.make_faction()
        c.factions.append(f)
        db_session.flush()
        c.set_primary_faction(f)
        db_session.flush()
        assert c.factions.count() == 1


class TestLocationTypeHierarchy:
    def test_county_parents_to_commandery(self):
        assert expected_parent_type_name('County') == 'Commandery'

    def test_commandery_parents_to_province(self):
        assert expected_parent_type_name('Commandery') == 'Province'

    def test_province_is_top(self):
        assert expected_parent_type_name('Province') is None

    def test_non_hierarchical_types_unconstrained(self):
        for t in ('Mountain', 'River', 'Battlefield'):
            assert expected_parent_type_name(t) is None

    def test_hierarchy_map_is_acyclic(self):
        # Walking parents from any key must terminate.
        for start in LOCATION_TYPE_PARENT_HIERARCHY:
            seen = set()
            cur = start
            while cur is not None:
                assert cur not in seen, f'cycle at {cur}'
                seen.add(cur)
                cur = LOCATION_TYPE_PARENT_HIERARCHY.get(cur)
