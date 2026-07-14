"""Chapter sidebar province-map panel.

Covers the `_chapter_province_maps` payload builder (unit) and the
rendered chapter page (integration): province tabs, the per-location
"click to show on map" gate, and the empty state.
"""
from app.blueprints.main.views import _chapter_province_maps
from tests import factories


def _province_chain(chapter, *, place=True, label='', prov_name='Sili',
                    county_name='Luoyang'):
    """Province → County under a chapter; optionally place the county on
    the province's map. Returns (province, county, province_map)."""
    prov_type = factories.make_location_type(name='Province')
    county_type = factories.make_location_type(name='County')
    prov = factories.make_location(name=prov_name,
                                   location_type_id=prov_type.id)
    county = factories.make_location(name=county_name, parent_id=prov.id,
                                     location_type_id=county_type.id)
    pm = factories.make_province_map(location=prov, label=label)
    if place:
        factories.make_province_map_placement(
            province_map=pm, location=county, kind='point', geometry=[12, 34])
    factories.associate_location(chapter, county)
    return prov, county, pm


class TestChapterProvinceMapsBuilder:
    def test_payload_shape_and_mapped_ids(self, app, db_session):
        with app.test_request_context():
            ch = factories.make_chapter()
            prov, county, pm = _province_chain(ch)
            ancestry = {county.id: [prov]}
            payload, mapped = _chapter_province_maps([county], ancestry)

            assert mapped == {county.id}
            assert len(payload) == 1
            prov_out = payload[0]
            assert prov_out['province_id'] == prov.id
            assert prov_out['province_name'] == 'Sili'
            assert len(prov_out['maps']) == 1
            m = prov_out['maps'][0]
            assert m['map_id'] == pm.id
            assert len(m['placements']) == 1
            pl = m['placements'][0]
            assert pl['location_id'] == county.id
            assert pl['kind'] == 'point'
            assert pl['geometry'] == [12, 34]

    def test_tab_per_province(self, app, db_session):
        with app.test_request_context():
            ch = factories.make_chapter()
            p1, c1, _ = _province_chain(ch, prov_name='Sili',
                                        county_name='Luoyang')
            p2, c2, _ = _province_chain(ch, prov_name='Ji',
                                        county_name='Ye')
            ancestry = {c1.id: [p1], c2.id: [p2]}
            payload, mapped = _chapter_province_maps([c1, c2], ancestry)
            assert {d['province_name'] for d in payload} == {'Sili', 'Ji'}
            assert mapped == {c1.id, c2.id}
            # sorted by province name
            assert [d['province_name'] for d in payload] == ['Ji', 'Sili']

    def test_multiple_maps_one_province(self, app, db_session):
        with app.test_request_context():
            ch = factories.make_chapter()
            prov, county, pm_north = _province_chain(
                ch, label='North', prov_name='Yong')
            pm_south = factories.make_province_map(location=prov,
                                                   label='South')
            payload, _ = _chapter_province_maps(
                [county], {county.id: [prov]})
            assert len(payload) == 1
            labels = {m['label'] for m in payload[0]['maps']}
            assert labels == {'North', 'South'}

    def test_province_with_map_but_no_placement_still_tabbed(self, app,
                                                             db_session):
        # Answer locked with user: every mentioned province with a map
        # gets a tab even with no placed locations this chapter.
        with app.test_request_context():
            ch = factories.make_chapter()
            prov, county, pm = _province_chain(ch, place=False)
            payload, mapped = _chapter_province_maps(
                [county], {county.id: [prov]})
            assert len(payload) == 1
            assert payload[0]['maps'][0]['placements'] == []
            assert mapped == set()

    def test_no_maps_returns_empty(self, app, db_session):
        with app.test_request_context():
            ch = factories.make_chapter()
            county_type = factories.make_location_type(name='County')
            county = factories.make_location(name='Nowhere',
                                             location_type_id=county_type.id)
            factories.associate_location(ch, county)
            payload, mapped = _chapter_province_maps([county], {county.id: []})
            assert payload == []
            assert mapped == set()


class TestChapterPageRender:
    def test_placed_location_renders_tab_and_gate(self, client, db_session):
        ch = factories.make_chapter()
        prov, county, pm = _province_chain(ch)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert f'pm-tab-{prov.id}' in html
        assert f'data-pm-map-id="{pm.id}"' in html
        assert f'data-on-province-map="{county.id}"' in html

    def test_unplaced_location_no_gate_empty_map(self, client, db_session):
        ch = factories.make_chapter()
        county_type = factories.make_location_type(name='County')
        county = factories.make_location(name='Unplaced',
                                         location_type_id=county_type.id)
        factories.associate_location(ch, county)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'data-on-province-map' not in html
        assert "No province maps for this chapter's locations yet." in html
