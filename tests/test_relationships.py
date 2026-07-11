"""Character relationships — RelationshipType (two-ended labels),
the Relationship model's two-way semantics, the character-edit
add/remove endpoints, and the listing + chapter-sidebar rendering."""
import pytest

from app.models import Relationship, RelationshipType
from tests import factories


class TestModel:
    def test_describe_for_both_ends(self, db_session):
        t = factories.make_relationship_type(side1_label='Father',
                                             side2_label='Son')
        dad = factories.make_character(name='Dad Guy')
        kid = factories.make_character(name='Kid Guy')
        r = factories.make_relationship(dad, kid, t)
        # From the father's side, the OTHER character is the Son.
        other, label = r.describe_for(dad.id)
        assert other is kid and label == 'Son'
        other, label = r.describe_for(kid.id)
        assert other is dad and label == 'Father'

    def test_symmetric_uses_side1_label_both_ways(self, db_session):
        t = factories.make_relationship_type(name='Brothers',
                                             side1_label='Brother',
                                             side2_label='')
        a = factories.make_character()
        b = factories.make_character()
        r = factories.make_relationship(a, b, t)
        assert r.describe_for(a.id)[1] == 'Brother'
        assert r.describe_for(b.id)[1] == 'Brother'
        assert t.is_symmetric

    def test_label_falls_back_to_type_name(self, db_session):
        t = factories.make_relationship_type(name='Sworn Siblings',
                                             side1_label='', side2_label='')
        a = factories.make_character()
        b = factories.make_character()
        r = factories.make_relationship(a, b, t)
        assert r.describe_for(a.id)[1] == 'Sworn Siblings'

    def test_unique_pair_type(self, db_session):
        from sqlalchemy.exc import IntegrityError
        t = factories.make_relationship_type()
        a = factories.make_character()
        b = factories.make_character()
        factories.make_relationship(a, b, t)
        with pytest.raises(IntegrityError):
            factories.make_relationship(a, b, t)
        db_session.rollback()


class TestTypeAdmin:
    def test_list_page(self, admin_client, db_session):
        client, _ = admin_client
        factories.make_relationship_type(name='Listed Tie',
                                         side1_label='Uncle',
                                         side2_label='Nephew')
        factories.make_relationship_type(name='Symmetric Tie',
                                         side1_label='Cousin',
                                         side2_label='')
        resp = client.get('/admin/relationship-types')
        assert resp.status_code == 200
        assert b'Listed Tie' in resp.data
        assert b'Uncle' in resp.data
        assert b'symmetric' in resp.data   # blank side-2 marker

    def test_create_edit(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/admin/relationship-types/new', data={
            'name': 'Husband/Wife', 'side1_label': 'Husband',
            'side2_label': 'Wife',
        }, follow_redirects=True)
        assert resp.status_code == 200
        t = RelationshipType.query.filter_by(name='Husband/Wife').first()
        assert t is not None and t.side2_label == 'Wife'
        client.post(f'/admin/relationship-types/{t.id}/edit', data={
            'name': 'Husband/Wife', 'side1_label': 'Husband',
            'side2_label': 'Spouse',
        }, follow_redirects=True)
        db_session.expire_all()
        assert t.side2_label == 'Spouse'

    def test_delete_guard_when_in_use(self, admin_client, db_session):
        client, _ = admin_client
        t = factories.make_relationship_type()
        a = factories.make_character()
        b = factories.make_character()
        factories.make_relationship(a, b, t)
        db_session.commit()
        resp = client.post(f'/admin/relationship-types/{t.id}/delete',
                           follow_redirects=True)
        assert b"Can't delete" in resp.data
        assert RelationshipType.query.get(t.id) is not None
        # Remove the tie → delete goes through.
        Relationship.query.delete()
        db_session.commit()
        client.post(f'/admin/relationship-types/{t.id}/delete',
                    follow_redirects=True)
        assert RelationshipType.query.get(t.id) is None

    def test_non_admin_forbidden(self, user_client, db_session):
        client, _ = user_client
        assert client.get('/admin/relationship-types').status_code == 403


class TestAddRemove:
    def _add(self, client, character, option, other=None, search=''):
        return client.post(
            f'/characters/{character.id}/relationships/add',
            data={'relationship_option': option,
                  'character_id': str(other.id) if other else '',
                  'character_search': search},
            follow_redirects=True)

    def test_add_as_side1(self, admin_client, db_session):
        client, _ = admin_client
        t = factories.make_relationship_type()   # Father/Son
        dad = factories.make_character()
        kid = factories.make_character()
        resp = self._add(client, dad, f'{t.id}:1', other=kid)
        assert resp.status_code == 200
        r = Relationship.query.one()
        assert (r.character1_id, r.character2_id) == (dad.id, kid.id)

    def test_add_as_side2_stores_reversed(self, admin_client, db_session):
        client, _ = admin_client
        t = factories.make_relationship_type()   # Father/Son
        dad = factories.make_character()
        kid = factories.make_character()
        # "kid is the Son of dad" → stored as (dad, kid).
        self._add(client, kid, f'{t.id}:2', other=dad)
        r = Relationship.query.one()
        assert (r.character1_id, r.character2_id) == (dad.id, kid.id)

    def test_two_way_visibility_on_both_edit_pages(self, admin_client,
                                                   db_session):
        client, _ = admin_client
        t = factories.make_relationship_type(side1_label='Father',
                                             side2_label='Son')
        dad = factories.make_character(name='Recip Dad')
        kid = factories.make_character(name='Recip Kid')
        self._add(client, dad, f'{t.id}:1', other=kid)
        resp = client.get(f'/characters/edit/{dad.id}')
        assert b'Recip Kid' in resp.data
        assert b'Son' in resp.data
        resp = client.get(f'/characters/edit/{kid.id}')
        assert b'Recip Dad' in resp.data
        assert b'Father' in resp.data

    def test_self_relationship_blocked(self, admin_client, db_session):
        client, _ = admin_client
        t = factories.make_relationship_type()
        a = factories.make_character()
        resp = self._add(client, a, f'{t.id}:1', other=a)
        assert b"can't have a relationship with themselves" in resp.data
        assert Relationship.query.count() == 0

    def test_duplicate_blocked(self, admin_client, db_session):
        client, _ = admin_client
        t = factories.make_relationship_type()
        a = factories.make_character()
        b = factories.make_character()
        self._add(client, a, f'{t.id}:1', other=b)
        resp = self._add(client, a, f'{t.id}:1', other=b)
        assert b'already exists' in resp.data
        assert Relationship.query.count() == 1

    def test_symmetric_reversed_duplicate_blocked(self, admin_client,
                                                  db_session):
        client, _ = admin_client
        t = factories.make_relationship_type(side1_label='Brother',
                                             side2_label='')
        a = factories.make_character()
        b = factories.make_character()
        self._add(client, a, f'{t.id}:1', other=b)
        # Same tie added from the other character.
        resp = self._add(client, b, f'{t.id}:1', other=a)
        assert b'already exists' in resp.data
        assert Relationship.query.count() == 1

    def test_bad_option_flashes(self, admin_client, db_session):
        client, _ = admin_client
        a = factories.make_character()
        b = factories.make_character()
        resp = self._add(client, a, 'garbage', other=b)
        assert b'Pick a relationship type.' in resp.data

    def test_remove_from_either_end(self, admin_client, db_session):
        client, _ = admin_client
        t = factories.make_relationship_type()
        dad = factories.make_character()
        kid = factories.make_character()
        self._add(client, dad, f'{t.id}:1', other=kid)
        r = Relationship.query.one()
        # Remove from the OTHER end's page.
        resp = client.post(
            f'/characters/{kid.id}/relationships/remove/{r.id}',
            follow_redirects=True)
        assert b'Removed relationship' in resp.data
        assert Relationship.query.count() == 0

    def test_remove_foreign_relationship_404(self, admin_client, db_session):
        client, _ = admin_client
        t = factories.make_relationship_type()
        a = factories.make_character()
        b = factories.make_character()
        outsider = factories.make_character()
        r = factories.make_relationship(a, b, t)
        db_session.commit()
        resp = client.post(
            f'/characters/{outsider.id}/relationships/remove/{r.id}')
        assert resp.status_code == 404
        assert Relationship.query.count() == 1

    def test_non_admin_forbidden(self, user_client, db_session):
        client, _ = user_client
        t = factories.make_relationship_type()
        a = factories.make_character()
        b = factories.make_character()
        assert client.post(f'/characters/{a.id}/relationships/add', data={
            'relationship_option': f'{t.id}:1',
            'character_id': str(b.id), 'character_search': '',
        }).status_code == 403


class TestListingAndSidebar:
    def test_characters_list_relationships_column(self, client, db_session):
        t = factories.make_relationship_type(side1_label='Father',
                                             side2_label='Son')
        dad = factories.make_character(name='Column Dad')
        kid = factories.make_character(name='Column Kid')
        factories.make_relationship(dad, kid, t)
        resp = client.get('/characters')
        assert resp.status_code == 200
        assert b'Relationships' in resp.data
        # Dad's row shows the kid pill labelled Son; kid's row the
        # reverse.
        assert b'Column Kid' in resp.data
        assert b'>Son</span>' in resp.data.replace(b'\n', b'')
        assert b'>Father</span>' in resp.data.replace(b'\n', b'')

    def test_chapter_sidebar_relationships_section(self, client, db_session):
        t = factories.make_relationship_type(side1_label='Husband',
                                             side2_label='Wife')
        h = factories.make_character(name='Sidebar Husband')
        w = factories.make_character(name='Sidebar Wife')
        factories.make_relationship(h, w, t)
        ch = factories.make_chapter(
            content='<p>Sidebar Husband met Sidebar Wife.</p>')
        factories.associate_character(ch, h, keywords=h.name)
        factories.associate_character(ch, w, keywords=w.name)
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert resp.status_code == 200
        assert b'Relationships:' in resp.data
        assert b'Wife' in resp.data
        assert b'Husband' in resp.data


class TestDropdownDisambiguation:
    def test_colliding_labels_get_type_name(self, admin_client, db_session):
        client, _ = admin_client
        factories.make_relationship_type(name='Father/Son',
                                         side1_label='Father',
                                         side2_label='Son')
        factories.make_relationship_type(name='Father/Daughter',
                                         side1_label='Father',
                                         side2_label='Daughter')
        c = factories.make_character()
        resp = client.get(f'/characters/edit/{c.id}')
        # The two "Father of" options are disambiguated by type name...
        assert b'Father of (Father/Son)' in resp.data
        assert b'Father of (Father/Daughter)' in resp.data
        # ...while unique labels stay clean.
        assert b'>Son of<' in resp.data
        assert b'>Daughter of<' in resp.data

    def test_unique_labels_stay_clean(self, admin_client, db_session):
        client, _ = admin_client
        factories.make_relationship_type(name='Husband/Wife',
                                         side1_label='Husband',
                                         side2_label='Wife')
        c = factories.make_character()
        resp = client.get(f'/characters/edit/{c.id}')
        assert b'>Husband of<' in resp.data
        assert b'Husband of (' not in resp.data
