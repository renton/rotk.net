"""Public character detail page (/characters/<id>) + the pill links
that lead to it from across the site."""
from sqlalchemy import text

from app.models import YearMap
from tests import factories


class TestCharacterViewPage:
    def _seed(self, db_session):
        wei = factories.make_faction(name='View Wei')
        shu = factories.make_faction(name='View Shu')
        role = factories.make_role(name='view marshal')
        c = factories.make_character(name='View Guy', chinese_name='觀者',
                                     courtesty_name='Shiyou',
                                     birth_date='155', death_date='220',
                                     ancestral_home='Qiao',
                                     book_mention_count=7)
        c.set_primary_faction(wei)
        c.factions.append(shu)
        c.roles.append(role)
        other = factories.make_character(name='View Kid', sex='female')
        t = factories.make_relationship_type(
            side1_label='Father', side2_label='Son',
            side2_label_female='Daughter')
        factories.make_relationship(c, other, t)
        factories.make_portrait(character=c, is_hidden=False,
                                filename='view_guy.png',
                                source_site='View Source')
        factories.make_url(target_type='character', target_id=c.id,
                           name='View Wiki')
        ch = factories.make_chapter(content='<p>View Guy strides.</p>')
        factories.associate_character(ch, c, keywords='View Guy')
        db_session.execute(
            text('UPDATE chapter_character SET summary = :s '
                 'WHERE chapter_id = :c AND character_id = :h'),
            {'s': 'He strides.', 'c': ch.id, 'h': c.id})
        db_session.flush()
        return c, other, ch, wei

    def test_renders_everything(self, client, db_session):
        c, other, ch, wei = self._seed(db_session)
        resp = client.get(f'/characters/{c.id}')
        assert resp.status_code == 200
        assert b'View Guy' in resp.data
        assert '觀者'.encode() in resp.data
        assert b'Shiyou' in resp.data
        assert b'155' in resp.data and b'220' in resp.data
        assert b'view marshal' in resp.data
        assert b'View Wei' in resp.data and b'(primary)' in resp.data
        assert b'view_guy.png' in resp.data
        assert b'View Source' in resp.data
        assert b'View Wiki' in resp.data
        # Relationship pill: label resolved for the OTHER end's sex,
        # linking to her page in a new tab.
        assert b'Daughter' in resp.data
        assert f'/characters/{other.id}'.encode() in resp.data
        # Chapter appearance + summary.
        assert f'Chapter {ch.chapter_num}'.encode() in resp.data
        assert b'He strides.' in resp.data

    def test_faction_pill_links_to_filtered_list_new_tab(self, client,
                                                         db_session):
        c, other, ch, wei = self._seed(db_session)
        resp = client.get(f'/characters/{c.id}')
        assert f'/characters?any_faction={wei.id}'.encode() in resp.data
        assert b'target="_blank"' in resp.data

    def test_missing_and_deleted_404(self, client, db_session):
        ghost = factories.make_character(is_deleted=True)
        db_session.flush()
        assert client.get('/characters/424242').status_code == 404
        assert client.get(f'/characters/{ghost.id}').status_code == 404

    def test_admin_sees_edit_button(self, admin_client, client, db_session):
        c, *_ = self._seed(db_session)
        aclient, _ = admin_client
        assert b'Edit' in aclient.get(f'/characters/{c.id}').data
        edit_href = f'/characters/edit/{c.id}'.encode()
        assert edit_href in aclient.get(f'/characters/{c.id}').data
        assert edit_href not in client.get(f'/characters/{c.id}').data


class TestLinkSources:
    def test_characters_list_links(self, client, db_session):
        t = factories.make_relationship_type(side1_label='Father',
                                             side2_label='Son')
        dad = factories.make_character(name='Link Dad')
        kid = factories.make_character(name='Link Kid')
        factories.make_relationship(dad, kid, t)
        db_session.flush()
        resp = client.get('/characters')
        # Public name links to the view page...
        assert f'href="/characters/{dad.id}"'.encode() in resp.data
        # ...and the relationship pill links to the OTHER character.
        assert f'href="/characters/{kid.id}"'.encode() in resp.data

    def test_factions_list_leader_pill_links(self, client, db_session):
        f = factories.make_faction()
        leader = factories.make_character(name='Link Leader')
        f.leaders.append(leader)
        db_session.flush()
        resp = client.get('/factions')
        assert f'href="/characters/{leader.id}"'.encode() in resp.data

    def test_chapter_sidebar_links(self, client, db_session):
        t = factories.make_relationship_type(side1_label='Father',
                                             side2_label='Son')
        c = factories.make_character(name='Sidebar Linked')
        kin = factories.make_character(name='Sidebar Kin')
        factories.make_relationship(c, kin, t)
        ch = factories.make_chapter(content='<p>Sidebar Linked waits.</p>')
        factories.associate_character(ch, c, keywords='Sidebar Linked')
        db_session.flush()
        resp = client.get(f'/chapter/{ch.chapter_num}')
        # Panel heading links to the character page.
        assert f'href="/characters/{c.id}"'.encode() in resp.data
        # Relationship pill links to the kin's page.
        assert f'href="/characters/{kin.id}"'.encode() in resp.data

    def test_yearmap_leader_links(self, client, db_session):
        f = factories.make_faction()
        leader = factories.make_character(name='Map Linked Leader')
        f.leaders.append(leader)
        ch = factories.make_chapter(date='208')
        m = YearMap(year=208, filename='208.png')
        m.factions = [f]
        db_session.add(m)
        db_session.flush()
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert f'href="/characters/{leader.id}"'.encode() in resp.data
        assert b'Map Linked Leader' in resp.data


class TestViewPagePolish:
    def test_sex_symbols(self, client, db_session):
        him = factories.make_character(name='Symbol Him', sex='male')
        her = factories.make_character(name='Symbol Her', sex='female')
        db_session.flush()
        assert b'fa-mars' in client.get(f'/characters/{him.id}').data
        assert b'fa-venus' in client.get(f'/characters/{her.id}').data

    def test_aliases_render_as_pills(self, client, db_session):
        c = factories.make_character(name='Alias Shower',
                                     aliases='Mengde, Lord Big')
        db_session.flush()
        resp = client.get(f'/characters/{c.id}')
        assert b'Also known as' in resp.data
        assert b'>Mengde</span>' in resp.data
        assert b'>Lord Big</span>' in resp.data

    def test_sidebar_faction_pills_link_filtered_list(self, client,
                                                      db_session):
        wei = factories.make_faction(name='Sidebar Wei')
        old = factories.make_faction(name='Sidebar Old Banner')
        c = factories.make_character(name='Sidebar Faction Guy')
        c.set_primary_faction(wei)
        c.factions.append(old)
        ch = factories.make_chapter(
            content='<p>Sidebar Faction Guy passes.</p>')
        factories.associate_character(ch, c, keywords='Sidebar Faction Guy')
        db_session.flush()
        resp = client.get(f'/chapter/{ch.chapter_num}')
        assert f'/characters?any_faction={wei.id}'.encode() in resp.data
        assert f'/characters?any_faction={old.id}'.encode() in resp.data
