"""B2-3 — list filters, timeline + date parser, remaining auth flows."""
from app.models import User
from tests import factories
from tools.date_parser import parse_date_range


class TestCharactersFilters:
    def test_letter_filter(self, client, db_session):
        factories.make_character(name='Cao Cao')
        factories.make_character(name='Zhang Fei')
        resp = client.get('/characters?letter=C')
        assert resp.status_code == 200
        assert b'Cao Cao' in resp.data
        assert b'Zhang Fei' not in resp.data

    def test_no_filter_lists_all(self, client, db_session):
        factories.make_character(name='Cao Cao')
        factories.make_character(name='Zhang Fei')
        resp = client.get('/characters')
        assert b'Cao Cao' in resp.data
        assert b'Zhang Fei' in resp.data


class TestEventsFilters:
    def test_search_q_matches_name_and_aliases(self, client, db_session):
        factories.make_event(name='Battle of Red Cliffs', aliases='Chibi')
        factories.make_event(name='Yellow Turban Rising')
        resp = client.get('/events?q=Chibi')
        assert b'Battle of Red Cliffs' in resp.data
        assert b'Yellow Turban Rising' not in resp.data

    def test_location_filter(self, client, db_session):
        loc = factories.make_location(name='Chibi')
        factories.make_event(name='Fire Attack', location_id=loc.id)
        factories.make_event(name='Unrelated March')
        resp = client.get(f'/events?location_id={loc.id}')
        assert b'Fire Attack' in resp.data
        assert b'Unrelated March' not in resp.data


class TestTimeline:
    def test_timeline_renders(self, client, db_session):
        factories.make_chapter(date='208 AD')
        assert client.get('/timeline').status_code == 200


class TestParseDateRange:
    def test_single_year_ad(self):
        span = parse_date_range('208 AD')
        assert span is not None
        lo, hi = span
        assert lo < hi
        assert 207 <= lo <= 208
        assert 208 <= hi <= 209

    def test_bc_year_negative(self):
        span = parse_date_range('208 BC')
        assert span is not None
        assert span[0] < 0

    def test_range_wider_than_single(self):
        single = parse_date_range('208 AD')
        ranged = parse_date_range('208-210 AD')
        assert ranged is not None
        assert (ranged[1] - ranged[0]) > (single[1] - single[0])

    def test_bc_earlier_than_ad(self):
        bc = parse_date_range('100 BC')
        ad = parse_date_range('100 AD')
        assert bc[0] < ad[0]

    def test_garbage_none(self):
        assert parse_date_range('not a date at all ???') is None

    def test_empty_and_none(self):
        assert parse_date_range('') is None
        assert parse_date_range(None) is None
        assert parse_date_range('   ') is None

    def test_span_always_positive_width(self):
        for s in ('208 AD', '208-209 AD', '100 BC'):
            span = parse_date_range(s)
            if span is not None:
                assert span[1] > span[0], s


class TestRemainingAuthFlows:
    def test_confirm_route_confirms(self, app, db_session):
        u = factories.make_user(confirmed=False)
        with app.test_request_context():
            token = u.generate_confirmation_token()
        client = app.test_client()
        client.post('/auth/login', data={
            'email': u.email, 'password': factories.DEFAULT_PASSWORD})
        resp = client.get(f'/auth/confirm/{token}', follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        assert User.query.get(u.id).confirmed is True

    def test_confirm_bad_token_does_not_confirm(self, app, db_session):
        u = factories.make_user(confirmed=False)
        client = app.test_client()
        client.post('/auth/login', data={
            'email': u.email, 'password': factories.DEFAULT_PASSWORD})
        client.get('/auth/confirm/garbage-token', follow_redirects=True)
        db_session.expire_all()
        assert User.query.get(u.id).confirmed is False

    def test_resend_confirmation_requires_login(self, client):
        resp = client.get('/auth/resend-confirmation')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_resend_confirmation_logged_in(self, app, db_session):
        u = factories.make_user(confirmed=False)
        client = app.test_client()
        client.post('/auth/login', data={
            'email': u.email, 'password': factories.DEFAULT_PASSWORD})
        resp = client.get('/auth/resend-confirmation',
                          follow_redirects=True)
        assert resp.status_code == 200   # mail suppressed, no crash

    def test_change_email_requires_login(self, client):
        resp = client.get('/auth/change-email')
        assert resp.status_code == 302

    def test_change_email_request_page(self, user_client):
        client, _ = user_client
        assert client.get('/auth/change-email').status_code == 200

    def test_forgot_password_post_unknown_email_no_crash(self, client,
                                                         db_session):
        resp = client.post('/auth/forgot-password', data={
            'email': 'nobody@test.example',
        }, follow_redirects=True)
        assert resp.status_code == 200


class TestCharactersMentionSort:
    def test_sort_desc_puts_most_mentioned_first(self, client, db_session):
        factories.make_character(name='Quiet Fellow', book_mention_count=2)
        factories.make_character(name='Famous Fellow', book_mention_count=900)
        resp = client.get('/characters?sort=mentions&dir=desc')
        assert resp.status_code == 200
        assert resp.data.find(b'Famous Fellow') < resp.data.find(b'Quiet Fellow')

    def test_sort_asc_reverses(self, client, db_session):
        factories.make_character(name='Quiet Fellow', book_mention_count=2)
        factories.make_character(name='Famous Fellow', book_mention_count=900)
        resp = client.get('/characters?sort=mentions&dir=asc')
        assert resp.data.find(b'Quiet Fellow') < resp.data.find(b'Famous Fellow')

    def test_default_stays_alphabetical(self, client, db_session):
        factories.make_character(name='Aardvark Man', book_mention_count=1)
        factories.make_character(name='Zebra Man', book_mention_count=999)
        resp = client.get('/characters')
        assert resp.data.find(b'Aardvark Man') < resp.data.find(b'Zebra Man')

    def test_header_link_and_count_cell(self, client, db_session):
        factories.make_character(name='Counted Guy', book_mention_count=37)
        resp = client.get('/characters?sort=mentions&dir=desc')
        assert b'sort=mentions' in resp.data
        assert b'>37<' in resp.data.replace(b'\n', b'').replace(b' ', b'')


class TestListingMobileCards:
    """Each public listing renders twice: mobile cards (d-md-none) and
    the desktop table (d-none d-md-block) — same rows in both."""

    def test_characters_page_has_card_and_table(self, client, db_session):
        factories.make_character(name='Card Table Guy', book_mention_count=5)
        resp = client.get('/characters')
        assert b'd-md-none' in resp.data
        assert b'table-responsive d-none d-md-block' in resp.data
        assert resp.data.count(b'Card Table Guy') >= 2   # card + table row
        assert b'5 mentions' in resp.data                # card summary line

    def test_events_page_has_card_and_table(self, client, db_session):
        factories.make_event(name='Cardable Battle')
        resp = client.get('/events')
        assert b'd-md-none' in resp.data
        assert b'table-responsive d-none d-md-block' in resp.data
        assert resp.data.count(b'Cardable Battle') >= 2

    def test_locations_page_has_card_and_table(self, client, db_session):
        parent = factories.make_location(name='Cardland Province')
        factories.make_location(name='Cardville', parent_id=parent.id)
        resp = client.get('/locations')
        assert b'd-md-none' in resp.data
        assert b'table-responsive d-none d-md-block' in resp.data
        assert resp.data.count(b'Cardville') >= 2
